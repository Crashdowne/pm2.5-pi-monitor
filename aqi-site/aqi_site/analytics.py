"""Analytics computed on the fly from the raw warehouse table.

All aggregation buckets straight from ``readings_raw`` (the warehouse has no rollup
tables), preferring the humidity-corrected PM2.5. AQI/NowCast come from ``pm25.aqi``
so the EPA math has a single source of truth.
"""
from __future__ import annotations

import sqlite3
import time

from pm25 import aqi

from . import db, mask
from .config import MaskConfig

# range key -> (bucket_seconds, span_seconds)
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

# Berkeley Earth rule of thumb: ~22 ug/m3 of PM2.5 for a day ≈ one cigarette.
CIGARETTE_UGM3_DAY = 22.0


def _aqi_of(pm2_5: float | None, pm10: float | None) -> tuple[int, str]:
    """Overall AQI and dominant pollutant for a bucket's mean concentrations."""
    a25 = aqi.aqi("pm2_5", pm2_5) or 0
    a10 = aqi.aqi("pm10", pm10) or 0
    if a25 >= a10:
        return a25, "pm2_5"
    return a10, "pm10"


def _band_index(aqi_value: int) -> int:
    for i, (upper, _label, _color) in enumerate(BANDS):
        if aqi_value <= upper:
            return i
    return len(BANDS) - 1


def _offset_seconds(tz_offset_hours: float) -> int:
    return int(round(tz_offset_hours * 3600))


def _mean_pm(conn: sqlite3.Connection, sensor_id: str, since: int, until: int) -> float | None:
    row = conn.execute(
        f"SELECT avg({db.PM25}) FROM readings_raw WHERE sensor_id=? AND ts>=? AND ts<?",
        (sensor_id, since, until),
    ).fetchone()
    return row[0]


def _trend(conn: sqlite3.Connection, sensor_id: str, now: int) -> str:
    """Compare the most recent hour to the previous three to label the direction."""
    rows = conn.execute(
        f"SELECT ts/3600 AS h, avg({db.PM25}) AS pm2_5 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY h ORDER BY h",
        (sensor_id, now - 4 * 3600),
    ).fetchall()
    values = [r["pm2_5"] for r in rows if r["pm2_5"] is not None]
    if len(values) < 2:
        return "steady"
    recent = values[-1]
    base = sum(values[:-1]) / len(values[:-1])
    delta = (aqi.aqi("pm2_5", recent) or 0) - (aqi.aqi("pm2_5", base) or 0)
    if delta >= 8:
        return "worsening"
    if delta <= -8:
        return "improving"
    return "steady"


def _good_window(conn: sqlite3.Connection, sensor_id: str, offset: int) -> dict | None:
    """Local hour-of-day with the lowest typical PM2.5 over the last two weeks."""
    now = int(time.time())
    rows = conn.execute(
        f"SELECT CAST(strftime('%H', ts + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({db.PM25}) AS pm2_5 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY hour",
        (offset, sensor_id, now - 14 * 86400),
    ).fetchall()
    hours = [(r["hour"], r["pm2_5"]) for r in rows if r["pm2_5"] is not None]
    if len(hours) < 4:
        return None
    hour, pm = min(hours, key=lambda x: x[1])
    return {"hour": hour, "aqi": aqi.aqi("pm2_5", pm) or 0}


def current(conn: sqlite3.Connection, sensor_id: str, mask_cfg: MaskConfig, offset: int = 0) -> dict | None:
    latest = db.latest_reading(conn, sensor_id)
    if latest is None:
        return None
    latest_ts = latest["ts"]
    now = int(time.time())
    hourly = db.hourly_pm(conn, sensor_id, latest_ts - 12 * 3600)
    corr_latest = latest["pm2_5_corr"] if latest["pm2_5_corr"] is not None else latest["pm2_5"]
    nc25 = aqi.nowcast([r["pm2_5"] for r in hourly])
    nc10 = aqi.nowcast([r["pm10"] for r in hourly])
    nc25 = nc25 if nc25 is not None else corr_latest
    nc10 = nc10 if nc10 is not None else latest["pm10"]
    overall, dominant = _aqi_of(nc25, nc10)
    category = aqi.category(overall)
    trend = _trend(conn, sensor_id, latest_ts)
    reco = mask.recommend(overall, mask_cfg.thresholds, dominant=dominant, trend=trend)
    return {
        "sensor_id": sensor_id,
        "ts": latest_ts,
        "age_s": max(0, now - latest_ts),
        "pm2_5": corr_latest,
        "pm2_5_raw": latest["pm2_5"],
        "pm10": latest["pm10"],
        "rh": latest["rh"],
        "temp": latest["temp"],
        "nowcast_aqi": overall,
        "category": category["label"],
        "color": category["color"],
        "dominant": dominant,
        "trend": trend,
        "mask": reco,
        "good_window": _good_window(conn, sensor_id, offset),
    }


def history(conn: sqlite3.Connection, sensor_id: str, range_key: str, bucket: int | None = None) -> list[dict]:
    default_bucket, span = RANGES[range_key]
    if bucket is None:
        bucket = default_bucket
    bucket = max(60, min(86400, int(bucket)))
    now = int(time.time())
    since = now - span
    rows = conn.execute(
        f"SELECT (ts/?)*? AS t, avg({db.PM25}) AS pm2_5, avg(pm10) AS pm10, "
        "avg(temp) AS temp, avg(rh) AS rh "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY t ORDER BY t",
        (bucket, bucket, sensor_id, since),
    ).fetchall()
    out = []
    for r in rows:
        value, _dominant = _aqi_of(r["pm2_5"], r["pm10"])
        out.append(
            {
                "t": r["t"],
                "pm2_5": _round(r["pm2_5"]),
                "pm10": _round(r["pm10"]),
                "temp": _round(r["temp"]),
                "rh": _round(r["rh"]),
                "aqi": value,
            }
        )
    return out


def calendar(conn: sqlite3.Connection, sensor_id: str, year: int, offset: int = 0) -> list[dict]:
    day = 86400
    rows = conn.execute(
        f"SELECT (ts + ?)/? AS d, avg({db.PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_raw WHERE sensor_id=? "
        "AND strftime('%Y', ts + ?, 'unixepoch')=? GROUP BY d ORDER BY d",
        (offset, day, sensor_id, offset, f"{year:04d}"),
    ).fetchall()
    out = []
    for r in rows:
        value, _dominant = _aqi_of(r["pm2_5"], r["pm10"])
        date = time.strftime("%Y-%m-%d", time.gmtime(r["d"] * day))
        out.append({"date": date, "aqi": value, "pm2_5": _round(r["pm2_5"])})
    return out


def heatmap(conn: sqlite3.Connection, sensor_id: str, range_key: str, offset: int = 0) -> list[list[int]]:
    _bucket, span = RANGES[range_key]
    since = int(time.time()) - span
    rows = conn.execute(
        f"SELECT CAST(strftime('%w', ts + ?, 'unixepoch') AS INTEGER) AS dow, "
        f"CAST(strftime('%H', ts + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({db.PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY dow, hour",
        (offset, offset, sensor_id, since),
    ).fetchall()
    out = []
    for r in rows:
        value, _dominant = _aqi_of(r["pm2_5"], r["pm10"])
        out.append([r["hour"], r["dow"], value])
    return out


def distribution(conn: sqlite3.Connection, sensor_id: str, range_key: str) -> list[dict]:
    _bucket, span = RANGES[range_key]
    since = int(time.time()) - span
    rows = conn.execute(
        f"SELECT avg({db.PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY ts/3600",
        (sensor_id, since),
    ).fetchall()
    counts = [0] * len(BANDS)
    for r in rows:
        if r["pm2_5"] is None and r["pm10"] is None:
            continue
        value, _dominant = _aqi_of(r["pm2_5"], r["pm10"])
        counts[_band_index(value)] += 1
    total = sum(counts)
    out = []
    for i, (_upper, label, color) in enumerate(BANDS):
        pct = round(counts[i] * 100 / total, 1) if total else 0.0
        out.append({"band": i, "label": label, "color": color, "hours": counts[i], "pct": pct})
    return out


def diurnal(conn: sqlite3.Connection, sensor_id: str, range_key: str, offset: int = 0) -> list[dict]:
    _bucket, span = RANGES[range_key]
    since = int(time.time()) - span
    rows = conn.execute(
        f"SELECT CAST(strftime('%H', ts + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({db.PM25}) AS avg_pm, min({db.PM25}) AS min_pm, max({db.PM25}) AS max_pm "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY hour ORDER BY hour",
        (offset, sensor_id, since),
    ).fetchall()
    by_hour = {r["hour"]: r for r in rows}
    out = []
    for hour in range(24):
        r = by_hour.get(hour)
        if r is None or r["avg_pm"] is None:
            out.append({"hour": hour, "avg": None, "min": None, "max": None, "aqi": None})
            continue
        out.append(
            {
                "hour": hour,
                "avg": _round(r["avg_pm"]),
                "min": _round(r["min_pm"]),
                "max": _round(r["max_pm"]),
                "aqi": aqi.aqi("pm2_5", r["avg_pm"]) or 0,
            }
        )
    return out


def summary(conn: sqlite3.Connection, sensor_id: str) -> dict:
    now = int(time.time())
    windows = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
    out: dict = {}
    for key, span in windows.items():
        mean = _mean_pm(conn, sensor_id, now - span, now)
        out[f"pm25_{key}"] = _round(mean)
        out[f"aqi_{key}"] = aqi.aqi("pm2_5", mean) if mean is not None else None
        days = span / 86400
        out[f"cigarettes_{key}"] = (
            round(mean * days / CIGARETTE_UGM3_DAY, 1) if mean is not None else None
        )
    peak = conn.execute(
        f"SELECT max(h.pm2_5) FROM (SELECT avg({db.PM25}) AS pm2_5 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY ts/3600) h",
        (sensor_id, now - 7 * 86400),
    ).fetchone()[0]
    out["peak_aqi_7d"] = aqi.aqi("pm2_5", peak) if peak is not None else None
    exceed_rows = conn.execute(
        f"SELECT avg({db.PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY ts/3600",
        (sensor_id, now - 30 * 86400),
    ).fetchall()
    out["exceedance_hours_30d"] = sum(
        1 for r in exceed_rows if _aqi_of(r["pm2_5"], r["pm10"])[0] > 100
    )
    return out


def export_rows(conn: sqlite3.Connection, sensor_id: str, range_key: str) -> list[dict]:
    return history(conn, sensor_id, range_key)


def sensors_overview(conn: sqlite3.Connection, mask_cfg: MaskConfig, offset: int = 0) -> list[dict]:
    """Fleet snapshot: latest AQI, mask level, and 24h coverage per device."""
    now = int(time.time())
    out = []
    for sensor_id in db.distinct_sensors(conn):
        snap = current(conn, sensor_id, mask_cfg, offset)
        if snap is None:
            continue
        device = db.device_row(conn, sensor_id)
        period = device["sample_period_s"] if device else 120
        expected = max(1, round(86400 / period))
        count_24h = db.count_since(conn, sensor_id, now - 86400)
        out.append(
            {
                "sensor_id": sensor_id,
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
                "coverage_24h": min(100, round(count_24h * 100 / expected)),
            }
        )
    return out


def _round(value: float | None, ndigits: int = 1) -> float | None:
    return round(value, ndigits) if value is not None else None
