"""Tailscale-side warehouse: authenticated ingest of raw readings into SQLite.

Bind this to the Tailscale interface and restrict access with a tailnet ACL so only the
Pi's tag can reach it. A bearer token is required in addition to network isolation.
"""
from __future__ import annotations

import argparse
import gzip
import hmac
import io
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from pm25 import aqi

RAW_COLS = ["pm1_0", "pm2_5", "pm10", "pm2_5_corr", "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10", "rh", "temp"]
MAX_BODY = 5 * 1024 * 1024

READINGS_SCHEMA = """
CREATE TABLE {table} (
    sensor_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    pm1_0 REAL, pm2_5 REAL, pm10 REAL, pm2_5_corr REAL,
    n0_3 INTEGER, n0_5 INTEGER, n1_0 INTEGER,
    n2_5 INTEGER, n5_0 INTEGER, n10 INTEGER,
    rh REAL, temp REAL,
    PRIMARY KEY (sensor_id, ts)
)
"""
SUPPORT_SCHEMA = (
    "CREATE INDEX IF NOT EXISTS idx_readings_raw_ts ON readings_raw(ts)",
    "CREATE TABLE IF NOT EXISTS devices ("
    "sensor_id TEXT PRIMARY KEY, sample_period_s INTEGER NOT NULL DEFAULT 120, "
    "last_ingest_ts INTEGER NOT NULL DEFAULT 0, last_reading_ts INTEGER NOT NULL DEFAULT 0)",
)

SERVER_DIR = Path(__file__).resolve().parent
WEB_DIR = SERVER_DIR.parent / "web"
SENSOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VALUE_RANGES = {
    "pm1_0": (0, 5000), "pm2_5": (0, 5000), "pm10": (0, 5000), "pm2_5_corr": (0, 5000),
    "n0_3": (0, 65535), "n0_5": (0, 65535), "n1_0": (0, 65535),
    "n2_5": (0, 65535), "n5_0": (0, 65535), "n10": (0, 65535),
    "rh": (0, 100), "temp": (-80, 100),
}


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_path)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            if _table_exists(conn, "readings_raw_legacy"):
                if _table_exists(conn, "readings_raw"):
                    live_count = conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0]
                    if live_count:
                        raise RuntimeError("both live and legacy warehouse tables contain data; refusing migration")
                    conn.execute("DROP TABLE readings_raw")
                conn.execute("ALTER TABLE readings_raw_legacy RENAME TO readings_raw")

            if not _table_exists(conn, "readings_raw"):
                conn.execute(READINGS_SCHEMA.format(table="readings_raw"))
            else:
                old_columns = {row[1] for row in conn.execute("PRAGMA table_info(readings_raw)")}
                if "sensor_id" not in old_columns:
                    if "ts" not in old_columns:
                        raise RuntimeError("legacy warehouse table has no timestamp column")
                    conn.execute(READINGS_SCHEMA.format(table="readings_raw_new"))
                    copy_columns = ["ts", *RAW_COLS]
                    select_values = [column if column in old_columns else "NULL" for column in copy_columns]
                    conn.execute(
                        f"INSERT INTO readings_raw_new (sensor_id, {','.join(copy_columns)}) "
                        f"SELECT 'default', {','.join(select_values)} FROM readings_raw"
                    )
                    old_count = conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0]
                    new_count = conn.execute("SELECT count(*) FROM readings_raw_new").fetchone()[0]
                    if old_count != new_count:
                        raise RuntimeError("warehouse migration row-count verification failed")
                    conn.execute("DROP TABLE readings_raw")
                    conn.execute("ALTER TABLE readings_raw_new RENAME TO readings_raw")

            for statement in SUPPORT_SCHEMA:
                conn.execute(statement)
            latest = conn.execute(
                "SELECT COALESCE(max(ts), 0) FROM readings_raw WHERE sensor_id = 'default'"
            ).fetchone()[0]
            if latest:
                conn.execute(
                    "INSERT OR IGNORE INTO devices (sensor_id, last_reading_ts) VALUES ('default', ?)",
                    (latest,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _validated_record(record: object, now: int) -> dict:
    if not isinstance(record, dict):
        abort(400)
    ts = record.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int) or not 1577836800 <= ts <= now + 86400:
        abort(400)
    clean = {"ts": ts}
    for column, (low, high) in VALUE_RANGES.items():
        value = record.get(column)
        if value is None:
            clean[column] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            abort(400)
        elif not low <= value <= high:
            abort(400)
        else:
            clean[column] = value
    return clean


def _request_body() -> bytes:
    compressed = request.get_data(cache=False)
    if len(compressed) > MAX_BODY:
        abort(413)
    if request.headers.get("Content-Encoding", "").lower() != "gzip":
        return compressed
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
            raw = source.read(MAX_BODY + 1)
    except (OSError, EOFError):
        abort(400)
    if len(raw) > MAX_BODY:
        abort(413)
    return raw


def create_app(db_path: str, token: str, device_tokens: dict[str, str] | None = None) -> Flask:
    app = Flask(__name__)
    _init_db(db_path)
    tokens = device_tokens or {}

    def require_auth() -> str:
        sensor_id = request.headers.get("X-PM25-Sensor-ID", "default")
        if not SENSOR_ID_RE.fullmatch(sensor_id):
            abort(400)
        expected = tokens.get(sensor_id, token if not tokens else "")
        provided = request.headers.get("Authorization", "")
        if not expected or not hmac.compare_digest(provided, f"Bearer {expected}"):
            abort(401)
        return sensor_id

    @app.post("/ingest")
    def ingest():
        sensor_id = require_auth()
        raw = _request_body()

        cols = ",".join(["sensor_id", "ts", *RAW_COLS])
        placeholders = ",".join(["?"] * (2 + len(RAW_COLS)))
        received = 0
        max_ts = 0
        records = []
        now = int(time.time())
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            abort(400)
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(_validated_record(json.loads(line), now))
            except json.JSONDecodeError:
                abort(400)
        if not records:
            abort(400)

        conn = _connect(db_path)
        try:
            updates = ",".join(f"{column}=excluded.{column}" for column in RAW_COLS)
            for rec in records:
                ts = rec["ts"]
                values = [sensor_id, ts, *[rec[c] for c in RAW_COLS]]
                conn.execute(
                    f"INSERT INTO readings_raw ({cols}) VALUES ({placeholders}) "
                    f"ON CONFLICT(sensor_id, ts) DO UPDATE SET {updates}",
                    values,
                )
                received += 1
                max_ts = max(max_ts, ts)
            try:
                sample_period = max(1, min(3600, int(request.headers.get("X-PM25-Sample-Period", "120"))))
            except ValueError:
                abort(400)
            conn.execute(
                "INSERT INTO devices (sensor_id, sample_period_s, last_ingest_ts, last_reading_ts) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(sensor_id) DO UPDATE SET sample_period_s=excluded.sample_period_s, "
                "last_ingest_ts=excluded.last_ingest_ts, last_reading_ts=max(devices.last_reading_ts, excluded.last_reading_ts)",
                (sensor_id, sample_period, int(time.time()), max_ts),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"received": received, "max_ts": max_ts})

    @app.get("/max_ts")
    def max_ts():
        sensor_id = require_auth()
        with closing(_connect(db_path)) as conn:
            row = conn.execute("SELECT max(ts) FROM readings_raw WHERE sensor_id = ?", (sensor_id,)).fetchone()
        return jsonify({"max_ts": row[0] or 0})

    @app.get("/api/fleet")
    def fleet():
        now = int(time.time())
        out = []
        with closing(_connect(db_path)) as conn:
            devices = conn.execute("SELECT * FROM devices ORDER BY sensor_id").fetchall()
            for device in devices:
                sensor_id = device["sensor_id"]
                latest = conn.execute(
                    "SELECT * FROM readings_raw WHERE sensor_id = ? ORDER BY ts DESC LIMIT 1",
                    (sensor_id,),
                ).fetchone()
                if latest is None:
                    continue
                hourly = conn.execute(
                    "SELECT avg(COALESCE(pm2_5_corr, pm2_5)) AS pm2_5, avg(pm10) AS pm10 "
                    "FROM readings_raw WHERE sensor_id = ? AND ts >= ? GROUP BY ts / 3600 ORDER BY ts / 3600",
                    (sensor_id, now - 12 * 3600),
                ).fetchall()
                pm25_now = latest["pm2_5_corr"] if latest["pm2_5_corr"] is not None else latest["pm2_5"]
                nc25 = aqi.nowcast([row["pm2_5"] for row in hourly]) or pm25_now
                nc10 = aqi.nowcast([row["pm10"] for row in hourly]) or latest["pm10"]
                overall = max(aqi.aqi("pm2_5", nc25) or 0, aqi.aqi("pm10", nc10) or 0)
                count_24h = conn.execute(
                    "SELECT count(*) FROM readings_raw WHERE sensor_id = ? AND ts >= ?",
                    (sensor_id, now - 86400),
                ).fetchone()[0]
                expected = max(1, round(86400 / device["sample_period_s"]))
                category = aqi.category(overall)
                out.append(
                    {
                        "sensor_id": sensor_id,
                        "ts": latest["ts"],
                        "pm2_5": pm25_now,
                        "pm10": latest["pm10"],
                        "rh": latest["rh"],
                        "temp": latest["temp"],
                        "aqi": {"value": overall, "category": category["label"], "color": category["color"]},
                        "coverage_24h": min(100, round(count_24h * 100 / expected)),
                        "last_ingest_ts": device["last_ingest_ts"],
                    }
                )
        response = jsonify(out)
        response.set_etag(f'{max([row["last_ingest_ts"] for row in out], default=0)}-{len(out)}')
        return response.make_conditional(request)

    @app.get("/api/sensors/<sensor_id>/history")
    def sensor_history(sensor_id: str):
        if not SENSOR_ID_RE.fullmatch(sensor_id):
            abort(400)
        ranges = {"24h": (3600, 24), "7d": (21600, 28), "30d": (86400, 30)}
        requested_range = request.args.get("range", "24h")
        if requested_range not in ranges:
            abort(400)
        bucket, count = ranges[requested_range]
        since = int(time.time()) - bucket * count
        with closing(_connect(db_path)) as conn:
            rows = conn.execute(
                "SELECT (ts / ?) * ? AS t, avg(COALESCE(pm2_5_corr, pm2_5)) AS pm2_5, avg(pm10) AS pm10 "
                "FROM readings_raw WHERE sensor_id = ? AND ts >= ? GROUP BY t ORDER BY t",
                (bucket, bucket, sensor_id, since),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/")
    def fleet_index():
        return send_from_directory(SERVER_DIR, "fleet.html")

    @app.get("/fleet.js")
    def fleet_js():
        return send_from_directory(SERVER_DIR, "fleet.js")

    @app.get("/charts.js")
    def charts_js():
        return send_from_directory(WEB_DIR, "charts.js")

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="PM2.5 ingest server")
    ap.add_argument("--db", default=os.environ.get("PM25_SERVER_DB", "/var/lib/pm25-server/pm25.db"))
    ap.add_argument("--host", default=os.environ.get("PM25_SERVER_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PM25_SERVER_PORT", "9000")))
    args = ap.parse_args()

    token = os.environ.get("PM25_INGEST_TOKEN", "")
    try:
        device_tokens = json.loads(os.environ.get("PM25_INGEST_TOKENS", "{}"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"PM25_INGEST_TOKENS must be a JSON object: {exc}") from exc
    if not isinstance(device_tokens, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in device_tokens.items()):
        raise SystemExit("PM25_INGEST_TOKENS must be a JSON object of sensor IDs to tokens")
    if not token and not device_tokens:
        raise SystemExit("Set PM25_INGEST_TOKEN or PM25_INGEST_TOKENS in the environment")

    from waitress import serve

    serve(create_app(args.db, token, device_tokens), host=args.host, port=args.port, threads=4)


if __name__ == "__main__":
    main()
