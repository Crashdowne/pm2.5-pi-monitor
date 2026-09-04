"""Flask application: read-only JSON API plus the built single-page dashboard.

Every data route buckets from the warehouse on demand. No route ever writes to the
warehouse; only the alert-override endpoint touches the sidecar's own state store.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import alerts, analytics, db, mask
from .config import MASK_PRESETS, Config

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _web_dist(config: Config) -> Path:
    if config.web_dist:
        return Path(config.web_dist)
    return _PACKAGE_ROOT / "web" / "dist"


def create_app(config: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    offset = int(round(config.display.tz_offset_hours * 3600))
    web_dist = _web_dist(config)

    def open_ro() -> sqlite3.Connection:
        return db.connect(config.db_path, config.db_immutable)

    def pick_sensor(conn: sqlite3.Connection, requested: str | None) -> str:
        sensors = db.distinct_sensors(conn)
        if not sensors:
            abort(404, "no sensors in warehouse")
        if requested:
            if requested not in sensors:
                abort(404, "unknown sensor")
            return requested
        if config.default_sensor and config.default_sensor in sensors:
            return config.default_sensor
        return db.most_recent_sensor(conn) or sensors[0]

    def valid_sensor(sensor_id: str) -> str:
        if not db.valid_sensor_id(sensor_id):
            abort(400, "invalid sensor id")
        return sensor_id

    def valid_range() -> str:
        key = request.args.get("range", "24h")
        if key not in analytics.RANGES:
            abort(400, "invalid range")
        return key

    # ------------------------------------------------------------------ health
    @app.get("/healthz")
    def healthz():
        try:
            conn = open_ro()
        except sqlite3.OperationalError:
            return jsonify({"ok": False, "error": "warehouse unavailable"}), 503
        try:
            sensors = db.distinct_sensors(conn)
            latest = 0
            for sensor_id in sensors:
                row = db.latest_reading(conn, sensor_id)
                if row is not None:
                    latest = max(latest, row["ts"])
        finally:
            conn.close()
        age = max(0, int(time.time()) - latest) if latest else None
        return jsonify({"ok": True, "sensors": len(sensors), "last_reading_age_s": age})

    # ------------------------------------------------------------------ config
    @app.get("/api/config")
    def site_config():
        m = config.mask
        return jsonify(
            {
                "site_title": config.display.site_title,
                "temp_unit": config.display.temp_unit,
                "tz_offset_hours": config.display.tz_offset_hours,
                "ranges": list(analytics.RANGES.keys()),
                "bands": [
                    {"upper": upper, "label": label, "color": color}
                    for upper, label, color in analytics.BANDS
                ],
                "mask": {
                    "sensitivity": m.sensitivity,
                    "thresholds": {
                        "carry": m.carry_aqi,
                        "recommended": m.recommended_aqi,
                        "strong": m.strong_aqi,
                        "indoors": m.indoors_aqi,
                    },
                    "presets": {
                        name: {
                            "carry": vals[0],
                            "recommended": vals[1],
                            "strong": vals[2],
                            "indoors": vals[3],
                        }
                        for name, vals in MASK_PRESETS.items()
                    },
                    "levels": mask.all_levels(),
                    "disclaimer": mask.DISCLAIMER,
                },
            }
        )

    # ------------------------------------------------------------------ sensors
    @app.get("/api/sensors")
    def sensors():
        try:
            conn = open_ro()
        except sqlite3.OperationalError:
            return jsonify({"error": "warehouse unavailable"}), 503
        try:
            data = analytics.sensors_overview(conn, config.mask, offset)
        finally:
            conn.close()
        response = jsonify(data)
        response.set_etag(f'{max((d["ts"] for d in data), default=0)}-{len(data)}')
        return response.make_conditional(request)

    @app.get("/api/sensors/<sensor_id>/current")
    def sensor_current(sensor_id: str):
        valid_sensor(sensor_id)
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.current(conn, sid, config.mask, offset)
        if data is None:
            abort(404, "no readings")
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/history")
    def sensor_history(sensor_id: str):
        valid_sensor(sensor_id)
        range_key = valid_range()
        bucket = request.args.get("bucket", type=int)
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.history(conn, sid, range_key, bucket)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/calendar")
    def sensor_calendar(sensor_id: str):
        valid_sensor(sensor_id)
        year = request.args.get("year", default=time.gmtime().tm_year, type=int)
        if year is None or not 1970 <= year <= 3000:
            abort(400, "invalid year")
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.calendar(conn, sid, year, offset)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/heatmap")
    def sensor_heatmap(sensor_id: str):
        valid_sensor(sensor_id)
        range_key = valid_range()
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.heatmap(conn, sid, range_key, offset)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/distribution")
    def sensor_distribution(sensor_id: str):
        valid_sensor(sensor_id)
        range_key = valid_range()
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.distribution(conn, sid, range_key)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/diurnal")
    def sensor_diurnal(sensor_id: str):
        valid_sensor(sensor_id)
        range_key = valid_range()
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.diurnal(conn, sid, range_key, offset)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/summary")
    def sensor_summary(sensor_id: str):
        valid_sensor(sensor_id)
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.summary(conn, sid)
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/status")
    def sensor_status(sensor_id: str):
        valid_sensor(sensor_id)
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.status(conn, sid)
        if data is None:
            abort(404, "no device")
        return jsonify(data)

    @app.get("/api/sensors/<sensor_id>/mask")
    def sensor_mask(sensor_id: str):
        valid_sensor(sensor_id)
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            data = analytics.current(conn, sid, config.mask, offset)
        if data is None:
            abort(404, "no readings")
        return jsonify(
            {
                "sensor_id": sid,
                "aqi": data["nowcast_aqi"],
                "mask": data["mask"],
                "trend": data["trend"],
                "good_window": data["good_window"],
            }
        )

    @app.get("/api/sensors/<sensor_id>/export")
    def sensor_export(sensor_id: str):
        valid_sensor(sensor_id)
        range_key = valid_range()
        fmt = request.args.get("format", "csv")
        if fmt not in ("csv", "json"):
            abort(400, "invalid format")
        with _conn_or_503(open_ro) as conn:
            sid = pick_sensor(conn, sensor_id)
            rows = analytics.export_rows(conn, sid, range_key)
        if fmt == "json":
            return jsonify(rows)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["ts", "iso_utc", "pm2_5", "pm10", "temp", "rh", "aqi"])
        for r in rows:
            writer.writerow(
                [
                    r["t"],
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["t"])),
                    r["pm2_5"],
                    r["pm10"],
                    r["temp"],
                    r["rh"],
                    r["aqi"],
                ]
            )
        filename = f"{sid}-{range_key}.csv"
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------------ alerts
    @app.get("/api/alerts")
    def alerts_get():
        state = alerts.open_state(config.state_db_path)
        try:
            cfg = alerts.effective_alerts(config.alerts, alerts.load_overrides(state))
            sensor_rows = state.execute(
                "SELECT sensor_id, last_level, last_fired_ts FROM alert_state ORDER BY sensor_id"
            ).fetchall()
        finally:
            state.close()
        return jsonify(_alerts_view(cfg, sensor_rows))

    @app.post("/api/alerts")
    def alerts_post():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400, "expected a JSON object")
        if "notify_from" in body and body["notify_from"] not in mask.LEVELS:
            abort(400, "invalid notify_from level")
        state = alerts.open_state(config.state_db_path)
        try:
            alerts.save_overrides(state, body)
            cfg = alerts.effective_alerts(config.alerts, alerts.load_overrides(state))
            sensor_rows = state.execute(
                "SELECT sensor_id, last_level, last_fired_ts FROM alert_state ORDER BY sensor_id"
            ).fetchall()
        finally:
            state.close()
        return jsonify(_alerts_view(cfg, sensor_rows))

    # ------------------------------------------------------------------ static
    @app.get("/")
    def index():
        return _serve_spa(web_dist, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        if filename.startswith("api/"):
            abort(404)
        candidate = (web_dist / filename).resolve()
        try:
            candidate.relative_to(web_dist.resolve())
        except ValueError:
            abort(404)
        if candidate.is_file():
            return send_from_directory(web_dist, filename)
        return _serve_spa(web_dist, "index.html")

    return app


def _alerts_view(cfg, sensor_rows) -> dict:
    return {
        "enabled": cfg.enabled,
        "notify_from": cfg.notify_from,
        "min_interval_s": cfg.min_interval_s,
        "quiet_start_hour": cfg.quiet_start_hour,
        "quiet_end_hour": cfg.quiet_end_hour,
        "ntfy_configured": bool(cfg.ntfy_url and cfg.ntfy_topic),
        "webhook_configured": bool(cfg.webhook_url),
        "levels": mask.LEVELS,
        "sensors": [
            {
                "sensor_id": r["sensor_id"],
                "last_level": r["last_level"],
                "last_fired_ts": r["last_fired_ts"],
            }
            for r in sensor_rows
        ],
    }


def _serve_spa(web_dist: Path, filename: str):
    index = web_dist / filename
    if not index.is_file():
        return (
            "Dashboard not built. Run the web build (npm ci && npm run build) "
            "or use the Docker image.",
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
        )
    return send_from_directory(web_dist, filename)


class _conn_or_503:
    """Context manager that opens a read-only connection or aborts with 503."""

    def __init__(self, opener):
        self._opener = opener
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._conn = self._opener()
        except sqlite3.OperationalError:
            abort(503, "warehouse unavailable")
        return self._conn

    def __exit__(self, *exc) -> None:
        if self._conn is not None:
            self._conn.close()
