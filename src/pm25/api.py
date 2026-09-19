"""Flask JSON API + static PWA serving."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import NotFound

from . import analytics, aqi, db, events, forecast, mask
from .config import Config

_ROOT = Path(__file__).resolve().parents[2]
LEGACY_WEB_DIR = _ROOT / "web"
REACT_DIST_DIR = _ROOT / "aqi-worker" / "web" / "dist"


def _web_root() -> Path:
    """Serve the built React dashboard when present, else the no-build legacy PWA."""
    return REACT_DIST_DIR if (REACT_DIST_DIR / "index.html").exists() else LEGACY_WEB_DIR


# range -> (bucket_seconds, count, bucket_kind) for the legacy /api/history endpoint.
_RANGES = {
    "24h": (3600, 24, "hour"),
    "48h": (3600, 48, "hour"),
    "7d": (86400, 7, "day"),
    "30d": (86400, 30, "day"),
    "12w": (604800, 12, "week"),
}


def config_payload(cfg: Config) -> dict:
    """`/api/config` — presentation + mask config the React dashboard reads on load."""
    d = cfg.dashboard
    carry, recommended, strong, indoors = mask.resolve_thresholds(
        d.mask_sensitivity,
        (d.mask_carry_aqi, d.mask_recommended_aqi, d.mask_strong_aqi, d.mask_indoors_aqi),
    )
    presets = {
        name: {"carry": v[0], "recommended": v[1], "strong": v[2], "indoors": v[3]}
        for name, v in mask.PRESETS.items()
    }
    return {
        "site_title": d.site_title,
        "temp_unit": d.temp_unit,
        "tz_offset_hours": d.tz_offset_hours,
        "ranges": list(analytics.RANGES.keys()),
        "bands": [{"upper": upper, "label": label, "color": color} for upper, label, color in analytics.BANDS],
        "mask": {
            "sensitivity": d.mask_sensitivity,
            "thresholds": {"carry": carry, "recommended": recommended, "strong": strong, "indoors": indoors},
            "presets": presets,
            "levels": mask.all_levels(),
            "disclaimer": mask.DISCLAIMER,
        },
    }


def alerts_payload(cfg: Config, conn) -> dict:
    """`/api/alerts` — the Pi's webhook alert config mapped into the dashboard view shape."""
    snap = analytics.current(conn, cfg)
    sensors = (
        [{"sensor_id": cfg.sync.sensor_id, "last_level": snap["mask"]["level"], "last_fired_ts": 0}]
        if snap
        else []
    )
    return {
        "enabled": cfg.alerts.enabled,
        "notify_from": "recommended",
        "min_interval_s": cfg.alerts.cooldown_s,
        "quiet_start_hour": -1,
        "quiet_end_hour": -1,
        "ntfy_configured": False,
        "webhook_configured": bool(cfg.alerts.webhook_url),
        "levels": list(mask.LEVELS),
        "sensors": sensors,
    }


def _sse_pack(data: object) -> str:
    return f"data: {json.dumps(data)}\n\n"

def sse_current_stream(get_conn, cfg: Config, interval_s: int, max_events: int | None = None):
    """Yield the current snapshot as SSE events, refreshing every ``interval_s`` seconds."""
    count = 0
    while True:
        conn = get_conn()
        try:
            data = analytics.current(conn, cfg)
        finally:
            conn.close()
        yield _sse_pack(data)
        count += 1
        if max_events is not None and count >= max_events:
            return
        if interval_s > 0:
            time.sleep(interval_s)


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    _c = db.connect(cfg.storage.db_path)
    db.init_db(_c)  # ensure schema + pm2_5_corr migration before serving
    _c.close()

    def get_conn():
        return db.connect(cfg.storage.db_path)

    @app.after_request
    def set_response_headers(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; "
            "img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; manifest-src 'self'",
        )
        return response

    def health_payload(conn, last_ts: int | None) -> dict:
        now = int(time.time())
        period = max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else cfg.sensor.sample_interval_s)
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
        response.set_etag(
            f'{row["ts"]}-{health["sample_period_s"]}-'
            f'{health["reader"]["consecutive_failures"]}-{sync["last_attempt_ts"]}'
        )
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
        period = max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else cfg.sensor.sample_interval_s)
        expected_hour = max(1, round(3600 / period))
        expected_day = max(1, round(86400 / period))
        conn = get_conn()
        hourly = conn.execute(
            "SELECT ts_hour AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, rh, temp, samples "
            "FROM readings_hourly WHERE ts_hour >= ? ORDER BY ts_hour",
            (now - 24 * 3600,),
        ).fetchall()
        daily = conn.execute(
            "SELECT ts_day AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, rh, temp, samples "
            "FROM readings_daily WHERE ts_day >= ? ORDER BY ts_day",
            (now - 30 * 86400,),
        ).fetchall()
        for_weeks = conn.execute(
            "SELECT ts_day AS t, COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10, rh, temp, samples "
            "FROM readings_daily WHERE ts_day >= ? ORDER BY ts_day",
            (now - 12 * 604800,),
        ).fetchall()
        conn.close()

        wk: dict[int, dict[str, list[float] | int]] = {}
        for r in for_weeks:
            k = r["t"] - r["t"] % 604800
            b = wk.setdefault(k, {"pm2_5": [], "pm10": [], "rh": [], "temp": [], "samples": 0})
            b["pm2_5"].append(r["pm2_5"])
            b["pm10"].append(r["pm10"])
            if r["rh"] is not None:
                b["rh"].append(r["rh"])
            if r["temp"] is not None:
                b["temp"].append(r["temp"])
            b["samples"] += r["samples"]
        weekly = [
            {
                "t": k,
                "pm2_5": sum(v["pm2_5"]) / len(v["pm2_5"]),
                "pm10": sum(v["pm10"]) / len(v["pm10"]),
                "rh": sum(v["rh"]) / len(v["rh"]) if v["rh"] else None,
                "temp": sum(v["temp"]) / len(v["temp"]) if v["temp"] else None,
                "samples": v["samples"],
                "coverage": min(1, v["samples"] / (expected_day * 7)),
            }
            for k, v in sorted(wk.items())
        ]
        return jsonify(
            {
                "hourly": [{"t": r["t"], "pm2_5": r["pm2_5"], "pm10": r["pm10"], "rh": r["rh"], "temp": r["temp"], "samples": r["samples"], "coverage": min(1, r["samples"] / expected_hour)} for r in hourly],
                "daily": [{"t": r["t"], "pm2_5": r["pm2_5"], "pm10": r["pm10"], "rh": r["rh"], "temp": r["temp"], "samples": r["samples"], "coverage": min(1, r["samples"] / expected_day)} for r in daily],
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

    @app.get("/api/config")
    def api_config():
        return jsonify(config_payload(cfg))

    @app.get("/api/sensors")
    def api_sensors():
        conn = get_conn()
        try:
            data = analytics.sensors_overview(conn, cfg)
        finally:
            conn.close()
        max_ts = max((s["ts"] for s in data), default=0)
        response = jsonify(data)
        response.set_etag(f"{max_ts}-{len(data)}")
        return response.make_conditional(request)

    @app.get("/api/sensors/<sid>/<action>")
    def api_sensor_action(sid: str, action: str):
        if sid != cfg.sync.sensor_id:
            abort(404)
        range_key = request.args.get("range", "24h")
        conn = get_conn()
        try:
            if action == "current":
                data = analytics.current(conn, cfg)
                if data is None:
                    abort(404)
                return jsonify(data)
            if action == "history":
                if range_key not in analytics.RANGES:
                    abort(400)
                bucket_raw = request.args.get("bucket")
                bucket = int(bucket_raw) if bucket_raw and bucket_raw.lstrip("-").isdigit() else None
                return jsonify(analytics.history(conn, cfg, range_key, bucket))
            if action == "calendar":
                year_raw = request.args.get("year")
                year = int(year_raw) if year_raw and year_raw.isdigit() else time.gmtime().tm_year
                if not 1970 <= year <= 3000:
                    abort(400)
                return jsonify(analytics.calendar(conn, cfg, year))
            if action == "heatmap":
                if range_key not in analytics.RANGES:
                    abort(400)
                return jsonify(analytics.heatmap(conn, cfg, range_key))
            if action == "distribution":
                if range_key not in analytics.RANGES:
                    abort(400)
                return jsonify(analytics.distribution(conn, cfg, range_key))
            if action == "diurnal":
                if range_key not in analytics.RANGES:
                    abort(400)
                return jsonify(analytics.diurnal(conn, cfg, range_key))
            if action == "summary":
                return jsonify(analytics.summary(conn, cfg))
            if action == "status":
                data = analytics.status(conn, cfg)
                if data is None:
                    abort(404)
                return jsonify(data)
            if action == "mask":
                data = analytics.current(conn, cfg)
                if data is None:
                    abort(404)
                return jsonify(
                    {
                        "sensor_id": cfg.sync.sensor_id,
                        "aqi": data["nowcast_aqi"],
                        "mask": data["mask"],
                        "trend": data["trend"],
                        "good_window": data["good_window"],
                    }
                )
            if action == "export":
                if range_key not in analytics.RANGES:
                    abort(400)
                fmt = request.args.get("format", "csv")
                if fmt not in ("csv", "json"):
                    abort(400)
                rows = analytics.export_rows(conn, cfg, range_key)
                if fmt == "json":
                    return jsonify(rows)
                lines = ["ts,iso_utc,pm2_5,pm10,temp,rh,aqi"]
                for r in rows:
                    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r["t"])) + "Z"
                    cells = [r["pm2_5"], r["pm10"], r["temp"], r["rh"]]
                    lines.append(
                        ",".join([str(r["t"]), iso, *["" if v is None else str(v) for v in cells], str(r["aqi"])])
                    )
                body = "\r\n".join(lines) + "\r\n"
                return app.response_class(
                    body,
                    mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{sid}-{range_key}.csv"'},
                )
            if action == "forecast":
                hours_raw = request.args.get("hours")
                hours = int(hours_raw) if hours_raw and hours_raw.isdigit() else 6
                return jsonify(forecast.forecast(conn, cfg, max(1, min(24, hours))))
            if action == "events":
                if range_key not in analytics.RANGES:
                    abort(400)
                _bucket, span = analytics.RANGES[range_key]
                return jsonify(events.classify_events(conn, cfg, hours=max(1, span // 3600)))
            abort(404)
        finally:
            conn.close()

    @app.get("/api/sensors/<sid>/stream")
    def api_sensor_stream(sid: str):
        if sid != cfg.sync.sensor_id:
            abort(404)
        once = request.args.get("once") == "1"
        interval = max(1, cfg.dashboard.live_interval_s)
        gen = sse_current_stream(get_conn, cfg, interval, max_events=1 if once else None)
        return app.response_class(
            stream_with_context(gen),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/alerts")
    def api_alerts():
        conn = get_conn()
        try:
            return jsonify(alerts_payload(cfg, conn))
        finally:
            conn.close()

    @app.post("/api/alerts")
    def api_alerts_post():
        # Alerts on the Pi are configured in config.toml; the dashboard cannot override them.
        abort(403, description="Alerts are configured in /etc/pm25/config.toml on this device.")

    @app.get("/")
    def index():
        return send_from_directory(_web_root(), "index.html")

    @app.get("/<path:fname>")
    def static_files(fname: str):
        root = _web_root()
        try:
            return send_from_directory(root, fname)
        except NotFound:
            # SPA fallback: extension-less client routes resolve to index.html.
            if "." in fname.rsplit("/", 1)[-1]:
                raise
            return send_from_directory(root, "index.html")

    return app
