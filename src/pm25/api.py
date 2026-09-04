"""Flask JSON API + static PWA serving."""
from __future__ import annotations

import os
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from . import aqi, db
from .config import Config

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

# range -> (bucket_seconds, count, bucket_kind)
_RANGES = {
    "24h": (3600, 24, "hour"),
    "48h": (3600, 48, "hour"),
    "7d": (86400, 7, "day"),
    "30d": (86400, 30, "day"),
    "12w": (604800, 12, "week"),
}


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    _c = db.connect(cfg.storage.db_path)
    db.init_db(_c)  # ensure schema + pm2_5_corr migration before serving
    _c.close()

    def get_conn():
        return db.connect(cfg.storage.db_path)

    def health_payload(conn, last_ts: int | None) -> dict:
        now = int(time.time())
        period = max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else 60)
        expected_24h = max(1, round(86400 / period))
        received_24h = conn.execute(
            "SELECT COALESCE(sum(samples), 0) FROM readings_hourly WHERE ts_hour >= ?",
            (now - 86400,),
        ).fetchone()[0]
        reader = conn.execute("SELECT * FROM reader_status WHERE id = 1").fetchone()
        sync = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        age = now - last_ts if last_ts else None
        if age is None:
            freshness = "none"
        elif age <= period + 30:
            freshness = "fresh"
        elif age <= period * 3:
            freshness = "delayed"
        else:
            freshness = "stale"

        failures = reader["consecutive_failures"] if reader else 0
        if freshness == "stale":
            pm_state = "unavailable"
        elif failures:
            pm_state = "recovering"
        elif last_ts is None:
            pm_state = "warming_up"
        else:
            pm_state = "ok"

        if not cfg.sync.enabled:
            sync_state = "off"
        elif sync and sync["last_error"]:
            sync_state = "error"
        elif sync and sync["backlog_rows"]:
            sync_state = "scheduled"
        else:
            sync_state = "current"

        return {
            "sample_period_s": period,
            "last_reading_ts": last_ts,
            "next_reading_ts": (last_ts + period) if last_ts else None,
            "age_s": age,
            "freshness": freshness,
            "coverage_24h": {
                "received": received_24h,
                "expected": expected_24h,
                "pct": min(100, round(received_24h * 100 / expected_24h)),
            },
            "sensors": {
                "pm": pm_state,
                "humidity": (
                    "off"
                    if not cfg.sensor.sht31.enabled
                    else "ok"
                    if reader and reader["sht31_ok"] == 1
                    else "unavailable"
                    if reader and reader["sht31_ok"] == 0
                    else "warming_up"
                ),
            },
            "reader": {
                "consecutive_failures": failures,
                "valid_frames_total": reader["valid_frames_total"] if reader else 0,
                "checksum_errors_total": reader["checksum_errors_total"] if reader else 0,
                "transport_errors_total": reader["transport_errors_total"] if reader else 0,
                "timeout_reads_total": reader["timeout_reads_total"] if reader else 0,
                "sensor_resets_total": reader["sensor_resets_total"] if reader else 0,
                "serial_reopens_total": reader["serial_reopens_total"] if reader else 0,
                "sht31_failures_total": reader["sht31_failures_total"] if reader else 0,
                "last_error": reader["last_error"] if reader else "",
            },
            "sync": {
                "state": sync_state,
                "pending": sync["backlog_rows"] if sync else 0,
                "last_attempt_ts": sync["last_attempt_ts"] if sync else 0,
                "last_success_ts": sync["last_success_ts"] if sync else 0,
                "last_error": sync["last_error"] if sync else "",
            },
        }

    @app.get("/api/current")
    def current():
        conn = get_conn()
        row = conn.execute("SELECT * FROM readings_raw ORDER BY ts DESC LIMIT 1").fetchone()
        hourly = conn.execute(
            "SELECT pm2_5, pm10, pm2_5_corr FROM readings_hourly ORDER BY ts_hour DESC LIMIT 12"
        ).fetchall()
        if row is None:
            health = health_payload(conn, None)
            conn.close()
            return jsonify({"ts": None, "health": health})

        # Prefer the humidity-corrected PM2.5 wherever it is available.
        pm25_now = row["pm2_5_corr"] if row["pm2_5_corr"] is not None else row["pm2_5"]
        pm25_hours = list(reversed([(h["pm2_5_corr"] if h["pm2_5_corr"] is not None else h["pm2_5"]) for h in hourly]))
        pm10_hours = list(reversed([h["pm10"] for h in hourly]))
        nc25 = aqi.nowcast(pm25_hours)
        nc10 = aqi.nowcast(pm10_hours)
        a25 = aqi.aqi("pm2_5", nc25 if nc25 is not None else pm25_now)
        a10 = aqi.aqi("pm10", nc10 if nc10 is not None else row["pm10"])
        dominant = "pm2_5" if (a25 or 0) >= (a10 or 0) else "pm10"
        overall = max(a25 or 0, a10 or 0)
        cat = aqi.category(overall)
        health = health_payload(conn, row["ts"])
        conn.close()
        response = jsonify(
            {
                "ts": row["ts"],
                "pm1_0": row["pm1_0"], "pm2_5": pm25_now, "pm10": row["pm10"],
                "pm2_5_raw": row["pm2_5"], "pm2_5_corr": row["pm2_5_corr"],
                "rh": row["rh"], "temp": row["temp"],
                "aqi": {"value": overall, "category": cat["label"], "color": cat["color"], "dominant": dominant},
                "aqi_pm2_5": a25, "aqi_pm10": a10,
                "health": health,
            }
        )
        sync = health["sync"]
        response.set_etag(f'{row["ts"]}-{health["reader"]["consecutive_failures"]}-{sync["last_attempt_ts"]}')
        return response.make_conditional(request)

    @app.get("/api/history")
    def history():
        metric = request.args.get("metric", "pm25")
        rng = request.args.get("range", "24h")
        if metric not in ("pm25", "pm10") or rng not in _RANGES:
            abort(400)
        col = "COALESCE(pm2_5_corr, pm2_5)" if metric == "pm25" else "pm10"
        step, count, bucket = _RANGES[rng]
        since = int(time.time()) - step * count

        conn = get_conn()
        if bucket == "hour":
            rows = conn.execute(
                f"SELECT ts_hour AS t, {col} AS v FROM readings_hourly WHERE ts_hour >= ? ORDER BY ts_hour",
                (since,),
            ).fetchall()
            out = [{"t": r["t"], "v": r["v"]} for r in rows]
        else:
            rows = conn.execute(
                f"SELECT ts_day AS t, {col} AS v FROM readings_daily WHERE ts_day >= ? ORDER BY ts_day",
                (since,),
            ).fetchall()
            if bucket == "day":
                out = [{"t": r["t"], "v": r["v"]} for r in rows]
            else:  # week
                weeks: dict[int, list[float]] = {}
                for r in rows:
                    weeks.setdefault(r["t"] - r["t"] % 604800, []).append(r["v"])
                out = [{"t": k, "v": sum(v) / len(v)} for k, v in sorted(weeks.items())]
        conn.close()
        return jsonify(out)

    @app.get("/api/averages")
    def averages():
        now = int(time.time())
        period = max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else 60)
        expected_hour = max(1, round(3600 / period))
        expected_day = max(1, round(86400 / period))
        conn = get_conn()
        hourly = conn.execute(
            "SELECT ts_hour AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, samples FROM readings_hourly WHERE ts_hour >= ? ORDER BY ts_hour",
            (now - 24 * 3600,),
        ).fetchall()
        daily = conn.execute(
            "SELECT ts_day AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, samples FROM readings_daily WHERE ts_day >= ? ORDER BY ts_day",
            (now - 30 * 86400,),
        ).fetchall()
        for_weeks = conn.execute(
            "SELECT ts_day AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, samples FROM readings_daily WHERE ts_day >= ? ORDER BY ts_day",
            (now - 12 * 604800,),
        ).fetchall()
        conn.close()

        wk: dict[int, dict[str, list[float] | int]] = {}
        for r in for_weeks:
            k = r["t"] - r["t"] % 604800
            b = wk.setdefault(k, {"pm2_5": [], "pm10": [], "samples": 0})
            b["pm2_5"].append(r["pm2_5"])
            b["pm10"].append(r["pm10"])
            b["samples"] += r["samples"]
        weekly = [
            {
                "t": k,
                "pm2_5": sum(v["pm2_5"]) / len(v["pm2_5"]),
                "pm10": sum(v["pm10"]) / len(v["pm10"]),
                "samples": v["samples"],
                "coverage": min(1, v["samples"] / (expected_day * 7)),
            }
            for k, v in sorted(wk.items())
        ]
        return jsonify(
            {
                "hourly": [{"t": r["t"], "pm2_5": r["pm2_5"], "pm10": r["pm10"], "samples": r["samples"], "coverage": min(1, r["samples"] / expected_hour)} for r in hourly],
                "daily": [{"t": r["t"], "pm2_5": r["pm2_5"], "pm10": r["pm10"], "samples": r["samples"], "coverage": min(1, r["samples"] / expected_day)} for r in daily],
                "weekly": weekly,
            }
        )

    @app.get("/api/health")
    def health():
        conn = get_conn()
        last = conn.execute("SELECT max(ts) AS ts FROM readings_raw").fetchone()["ts"]
        raw_rows = conn.execute("SELECT count(*) AS n FROM readings_raw").fetchone()["n"]
        payload = health_payload(conn, last)
        conn.close()
        payload.update({"ok": payload["freshness"] in ("fresh", "delayed"), "raw_rows": raw_rows, "db_bytes": db.database_bytes(cfg.storage.db_path)})
        return jsonify(payload)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:fname>")
    def static_files(fname: str):
        return send_from_directory(WEB_DIR, fname)

    return app
