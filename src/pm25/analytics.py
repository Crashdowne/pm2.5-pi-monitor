"""Rich dashboard analytics — Python port of the aqi-worker ``analytics.ts``, adapted to
the Pi's single-sensor SQLite schema (no ``sensor_id`` column). Read-only.

Recent/fine-grained views read ``readings_raw``; long-range and aggregate views read the
hourly/daily rollups. AQI/NowCast come from :mod:`pm25.aqi` so the EPA math has one source
of truth. Time-of-day bucketing applies the configured timezone offset, matching the Worker.
"""
from __future__ import annotations

import sqlite3
import time

from . import aqi as aqilib
from . import mask as masklib
from .config import Config

# PM2.5 source: prefer the humidity-corrected value, fall back to raw.
PM25 = "COALESCE(pm2_5_corr, pm2_5)"

# range key -> (default_bucket_seconds, span_seconds)
RANGES: dict[str, tuple[int, int]] = {
    "6h": (300, 6 * 3600),
    "24h": (900, 24 * 3600),
    "7d": (3600, 7 * 86400),
    "30d": (10800, 30 * 86400),
    "90d": (86400, 90 * 86400),
    "1y": (86400, 365 * 86400),
}

# (upper_aqi_inclusive, label, color) mirroring the EPA categories.
BANDS: list[tuple[int, str, str]] = [
    (50, "Good", "#00e400"),
    (100, "Moderate", "#ffff00"),
    (150, "Unhealthy for Sensitive Groups", "#ff7e00"),
    (200, "Unhealthy", "#ff0000"),
    (300, "Very Unhealthy", "#8f3f97"),
    (10**9, "Hazardous", "#7e0023"),
]

CIGARETTE_UGM3_DAY = 22.0  # Berkeley Earth: ~22 µg/m³·day of PM2.5 ≈ one cigarette
STALE_FLOOR_S = 900
STALE_PERIODS = 3
HOURLY_SPAN_MIN = 7 * 86400  # reads switch raw -> hourly rollup at/above 7 d


def _now() -> int:
    return int(time.time())


def _round1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _aqi_of(pm2_5: float | None, pm10: float | None) -> tuple[int, str]:
    """Overall AQI and dominant pollutant for a bucket's mean concentrations."""
    a25 = aqilib.aqi("pm2_5", pm2_5) or 0
    a10 = aqilib.aqi("pm10", pm10) or 0
    return (a25, "pm2_5") if a25 >= a10 else (a10, "pm10")


def _band_index(aqi_value: int) -> int:
    for i, (upper, _label, _color) in enumerate(BANDS):
        if aqi_value <= upper:
            return i
    return len(BANDS) - 1


def _sample_period_s(cfg: Config) -> int:
    return max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else cfg.sensor.sample_interval_s)


def _offset_s(cfg: Config) -> int:
    return round(cfg.dashboard.tz_offset_hours * 3600)


def _thresholds(cfg: Config) -> tuple[int, int, int, int]:
    d = cfg.dashboard
    return masklib.resolve_thresholds(
        d.mask_sensitivity,
        (d.mask_carry_aqi, d.mask_recommended_aqi, d.mask_strong_aqi, d.mask_indoors_aqi),
    )


def _last_ingest_ts(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_success_ts FROM sync_state WHERE id = 1").fetchone()
    return row["last_success_ts"] if row else 0


def _coalesced(row: sqlite3.Row) -> float | None:
    return row["pm2_5_corr"] if row["pm2_5_corr"] is not None else row["pm2_5"]


def _trend(conn: sqlite3.Connection, now_ts: int) -> str:
    rows = conn.execute(
        "SELECT pm2_5, pm2_5_corr FROM readings_hourly WHERE ts_hour >= ? ORDER BY ts_hour",
        (now_ts - 4 * 3600,),
    ).fetchall()
    values = [v for v in (_coalesced(r) for r in rows) if v is not None]
    if len(values) < 2:
        return "steady"
    recent = values[-1]
    rest = values[:-1]
    base = sum(rest) / len(rest)
    delta = (aqilib.aqi("pm2_5", recent) or 0) - (aqilib.aqi("pm2_5", base) or 0)
    if delta >= 8:
        return "worsening"
    if delta <= -8:
        return "improving"
    return "steady"


def _good_window(conn: sqlite3.Connection, cfg: Config) -> dict | None:
    offset = _offset_s(cfg)
    rows = conn.execute(
        "SELECT CAST(strftime('%H', ts_hour + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({PM25}) AS pm2_5 FROM readings_hourly WHERE ts_hour >= ? GROUP BY hour",
        (offset, _now() - 14 * 86400),
    ).fetchall()
    hours = [(r["hour"], r["pm2_5"]) for r in rows if r["pm2_5"] is not None]
    if len(hours) < 4:
        return None
    hour, pm = min(hours, key=lambda x: x[1])
    return {"hour": hour, "aqi": aqilib.aqi("pm2_5", pm) or 0}


def current(conn: sqlite3.Connection, cfg: Config) -> dict | None:
    row = conn.execute("SELECT * FROM readings_raw ORDER BY ts DESC LIMIT 1").fetchone()
    if row is None:
        return None
    latest_ts = row["ts"]
    now_ts = _now()
    hourly = conn.execute(
        "SELECT pm2_5, pm10, pm2_5_corr FROM readings_hourly WHERE ts_hour >= ? ORDER BY ts_hour",
        (latest_ts - 12 * 3600,),
    ).fetchall()
    corr_latest = _coalesced(row)
    nc25 = aqilib.nowcast([_coalesced(h) for h in hourly])
    nc10 = aqilib.nowcast([h["pm10"] for h in hourly])
    nc25 = nc25 if nc25 is not None else corr_latest
    nc10 = nc10 if nc10 is not None else row["pm10"]
    overall, dominant = _aqi_of(nc25, nc10)
    cat = aqilib.category(overall)
    direction = _trend(conn, latest_ts)
    reco = masklib.recommend(overall, _thresholds(cfg), dominant=dominant, trend=direction)
    period = _sample_period_s(cfg)
    last_ingest_ts = _last_ingest_ts(conn)
    age = max(0, now_ts - latest_ts)
    stale = age > max(STALE_FLOOR_S, STALE_PERIODS * period)
    return {
        "sensor_id": cfg.sync.sensor_id,
        "ts": latest_ts,
        "age_s": age,
        "online": not stale,
        "stale": stale,
        "last_ingest_ts": last_ingest_ts or None,
        "last_ingest_age_s": (max(0, now_ts - last_ingest_ts) if last_ingest_ts else None),
        "sample_period_s": period,
        "pm2_5": corr_latest,
        "pm2_5_raw": row["pm2_5"],
        "pm10": row["pm10"],
        "rh": row["rh"],
        "temp": row["temp"],
        "nowcast_aqi": overall,
        "category": cat["label"],
        "color": cat["color"],
        "dominant": dominant,
        "trend": direction,
        "mask": reco,
        "good_window": _good_window(conn, cfg),
    }


def history(
    conn: sqlite3.Connection, cfg: Config, range_key: str, bucket: int | None = None
) -> list[dict]:
    default_bucket, span = RANGES[range_key]
    b = default_bucket if bucket is None else bucket
    b = max(60, min(86400, int(b)))
    since = _now() - span
    table = "readings_hourly" if span >= HOURLY_SPAN_MIN else "readings_raw"
    tcol = "ts_hour" if span >= HOURLY_SPAN_MIN else "ts"
    rows = conn.execute(
        f"SELECT ({tcol}/?)*? AS t, avg({PM25}) AS pm2_5, avg(pm10) AS pm10, "
        f"avg(temp) AS temp, avg(rh) AS rh FROM {table} "
        f"WHERE {tcol} >= ? GROUP BY t ORDER BY t",
        (b, b, since),
    ).fetchall()
    out = []
    for r in rows:
        value, _ = _aqi_of(r["pm2_5"], r["pm10"])
        out.append(
            {
                "t": r["t"],
                "pm2_5": _round1(r["pm2_5"]),
                "pm10": _round1(r["pm10"]),
                "temp": _round1(r["temp"]),
                "rh": _round1(r["rh"]),
                "aqi": value,
            }
        )
    return out


def calendar(conn: sqlite3.Connection, cfg: Config, year: int) -> list[dict]:
    offset = _offset_s(cfg)
    day = 86400
    rows = conn.execute(
        f"SELECT (ts_day + ?)/? AS dd, avg({PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_daily WHERE strftime('%Y', ts_day + ?, 'unixepoch') = ? GROUP BY dd ORDER BY dd",
        (offset, day, offset, f"{year:04d}"),
    ).fetchall()
    out = []
    for r in rows:
        value, _ = _aqi_of(r["pm2_5"], r["pm10"])
        date = time.strftime("%Y-%m-%d", time.gmtime(r["dd"] * day))
        out.append({"date": date, "aqi": value, "pm2_5": _round1(r["pm2_5"])})
    return out


def heatmap(conn: sqlite3.Connection, cfg: Config, range_key: str) -> list[list[int]]:
    offset = _offset_s(cfg)
    _bucket, span = RANGES[range_key]
    since = _now() - span
    rows = conn.execute(
        "SELECT CAST(strftime('%w', ts_hour + ?, 'unixepoch') AS INTEGER) AS dow, "
        "CAST(strftime('%H', ts_hour + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_hourly WHERE ts_hour >= ? GROUP BY dow, hour",
        (offset, offset, since),
    ).fetchall()
    out = []
    for r in rows:
        value, _ = _aqi_of(r["pm2_5"], r["pm10"])
        out.append([r["hour"], r["dow"], value])
    return out


def distribution(conn: sqlite3.Connection, cfg: Config, range_key: str) -> list[dict]:
    _bucket, span = RANGES[range_key]
    since = _now() - span
    rows = conn.execute(
        f"SELECT {PM25} AS pm2_5, pm10 FROM readings_hourly WHERE ts_hour >= ?",
        (since,),
    ).fetchall()
    counts = [0] * len(BANDS)
    for r in rows:
        if r["pm2_5"] is None and r["pm10"] is None:
            continue
        value, _ = _aqi_of(r["pm2_5"], r["pm10"])
        counts[_band_index(value)] += 1
    total = sum(counts)
    return [
        {
            "band": i,
            "label": label,
            "color": color,
            "hours": counts[i],
            "pct": round(counts[i] * 100 / total, 1) if total else 0.0,
        }
        for i, (_upper, label, color) in enumerate(BANDS)
    ]


def diurnal(conn: sqlite3.Connection, cfg: Config, range_key: str) -> list[dict]:
    offset = _offset_s(cfg)
    _bucket, span = RANGES[range_key]
    since = _now() - span
    rows = conn.execute(
        "SELECT CAST(strftime('%H', ts + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({PM25}) AS avg_pm, min({PM25}) AS min_pm, max({PM25}) AS max_pm "
        "FROM readings_raw WHERE ts >= ? GROUP BY hour ORDER BY hour",
        (offset, since),
    ).fetchall()
    by_hour = {r["hour"]: r for r in rows}
    out = []
    for hour in range(24):
        r = by_hour.get(hour)
        if r is None or r["avg_pm"] is None:
            out.append(
                {"hour": hour, "avg": None, "min": None, "max": None, "aqi": None, "aqi_min": None, "aqi_max": None}
            )
            continue
        out.append(
            {
                "hour": hour,
                "avg": _round1(r["avg_pm"]),
                "min": _round1(r["min_pm"]),
                "max": _round1(r["max_pm"]),
                "aqi": aqilib.aqi("pm2_5", r["avg_pm"]) or 0,
                "aqi_min": aqilib.aqi("pm2_5", r["min_pm"]) or 0,
                "aqi_max": aqilib.aqi("pm2_5", r["max_pm"]) or 0,
            }
        )
    return out


def _period_stats(conn: sqlite3.Connection, period: str, span: int) -> dict:
    now_ts = _now()
    rows = conn.execute(
        f"SELECT {PM25} AS pm2_5, pm10 FROM readings_hourly WHERE ts_hour >= ?",
        (now_ts - span,),
    ).fetchall()
    peak = 0
    unhealthy = 0
    total = 0.0
    n = 0
    for r in rows:
        value, _ = _aqi_of(r["pm2_5"], r["pm10"])
        peak = max(peak, value)
        if value > 100:
            unhealthy += 1
        if r["pm2_5"] is not None:
            total += r["pm2_5"]
            n += 1
    mean = total / n if n else None
    days = span / 86400
    return {
        "period": period,
        "avg_aqi": aqilib.aqi("pm2_5", mean) if mean is not None else None,
        "peak_aqi": peak if rows else None,
        "unhealthy_hours": unhealthy,
        "cigarettes": round(mean * days / CIGARETTE_UGM3_DAY, 1) if mean is not None else None,
        "pm25": _round1(mean),
    }


def summary(conn: sqlite3.Connection, cfg: Config) -> dict:
    periods = [("24h", 86400), ("7d", 7 * 86400), ("30d", 30 * 86400)]
    out: dict = {"by_period": []}
    stats = []
    for key, span in periods:
        s = _period_stats(conn, key, span)
        stats.append(s)
        out[f"pm25_{key}"] = s["pm25"]
        out[f"aqi_{key}"] = s["avg_aqi"]
        out[f"cigarettes_{key}"] = s["cigarettes"]
    out["peak_aqi_7d"] = stats[1]["peak_aqi"]
    out["exceedance_hours_30d"] = stats[2]["unhealthy_hours"]
    out["by_period"] = stats
    return out


def status(conn: sqlite3.Connection, cfg: Config) -> dict | None:
    row = conn.execute("SELECT * FROM readings_raw ORDER BY ts DESC LIMIT 1").fetchone()
    reader = conn.execute("SELECT * FROM reader_status WHERE id = 1").fetchone()
    if row is None and reader is None:
        return None
    now_ts = _now()
    period = _sample_period_s(cfg)
    last_reading_ts = row["ts"] if row is not None else 0
    last_ingest_ts = _last_ingest_ts(conn)
    age = max(0, now_ts - last_reading_ts) if last_reading_ts else None
    stale = age is None or age > max(STALE_FLOOR_S, STALE_PERIODS * period)

    def coverage(span: int) -> dict:
        count = conn.execute(
            "SELECT count(*) AS n FROM readings_raw WHERE ts >= ?", (now_ts - span,)
        ).fetchone()["n"]
        expected = max(1, round(span / period))
        return {"expected": expected, "actual": count, "pct": min(100, round(count * 100 / expected))}

    env = conn.execute(
        "SELECT count(*) AS total, count(temp) AS temp_n, count(rh) AS rh_n "
        "FROM readings_raw WHERE ts >= ?",
        (now_ts - 86400,),
    ).fetchone()
    env_total = env["total"] or 0
    sht31_ok = row is not None and row["temp"] is not None and row["rh"] is not None

    gap_threshold = max(2 * period, 600)
    ts_rows = conn.execute(
        "SELECT ts FROM readings_raw WHERE ts >= ? ORDER BY ts", (now_ts - 7 * 86400,)
    ).fetchall()
    gaps = []
    prev: int | None = None
    for tr in ts_rows:
        if prev is not None and tr["ts"] - prev > gap_threshold:
            gaps.append({"start": prev, "end": tr["ts"], "duration_s": tr["ts"] - prev, "ongoing": False})
        prev = tr["ts"]
    if prev is not None and now_ts - prev > gap_threshold:
        gaps.append({"start": prev, "end": now_ts, "duration_s": now_ts - prev, "ongoing": True})
    gaps.sort(key=lambda g: g["duration_s"], reverse=True)

    return {
        "sensor_id": cfg.sync.sensor_id,
        "online": not stale,
        "stale": stale,
        "last_reading_ts": last_reading_ts or None,
        "last_reading_age_s": age,
        "last_ingest_ts": last_ingest_ts or None,
        "last_ingest_age_s": (max(0, now_ts - last_ingest_ts) if last_ingest_ts else None),
        "sample_period_s": period,
        "coverage_24h": coverage(86400),
        "coverage_7d": coverage(7 * 86400),
        "sht31": {
            "ok": sht31_ok,
            "temp_pct_24h": round(env["temp_n"] * 100 / env_total) if env_total else 0,
            "rh_pct_24h": round(env["rh_n"] * 100 / env_total) if env_total else 0,
            "temp": row["temp"] if row is not None else None,
            "rh": row["rh"] if row is not None else None,
        },
        "gaps_7d": {"count": len(gaps), "items": gaps[:20]},
    }


def sensors_overview(conn: sqlite3.Connection, cfg: Config) -> list[dict]:
    """Single-sensor 'fleet': this Pi presented as one entry for the dashboard's sensor list."""
    snap = current(conn, cfg)
    if snap is None:
        return []
    now_ts = _now()
    period = _sample_period_s(cfg)
    expected = max(1, round(86400 / period))
    count24h = conn.execute(
        "SELECT count(*) AS n FROM readings_raw WHERE ts >= ?", (now_ts - 86400,)
    ).fetchone()["n"]
    return [
        {
            "sensor_id": cfg.sync.sensor_id,
            "ts": snap["ts"],
            "age_s": snap["age_s"],
            "pm2_5": snap["pm2_5"],
            "pm10": snap["pm10"],
            "rh": snap["rh"],
            "temp": snap["temp"],
            "aqi": snap["nowcast_aqi"],
            "category": snap["category"],
            "color": snap["color"],
            "mask_level": snap["mask"]["level"],
            "coverage_24h": min(100, round(count24h * 100 / expected)),
            "online": snap["online"],
            "stale": snap["stale"],
            "last_ingest_ts": snap["last_ingest_ts"],
            "last_ingest_age_s": snap["last_ingest_age_s"],
            "sample_period_s": snap["sample_period_s"],
            "sht31_ok": snap["temp"] is not None and snap["rh"] is not None,
        }
    ]


def export_rows(conn: sqlite3.Connection, cfg: Config, range_key: str) -> list[dict]:
    return history(conn, cfg, range_key)
