"""Read-only access to the PM2.5 warehouse.

Opens the SQLite database that ``server/ingest.py`` writes, using ``mode=ro`` (live
WAL database) or ``immutable=1`` (static snapshot), and additionally sets
``PRAGMA query_only`` so this process can never write. Schema is the multi-sensor
warehouse: ``readings_raw(sensor_id, ts, ...)`` plus ``devices``.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

SENSOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Prefer the humidity-corrected PM2.5 (from the GY-SHT31 RH), fall back to raw.
PM25 = "COALESCE(pm2_5_corr, pm2_5)"


def valid_sensor_id(sensor_id: str) -> bool:
    return bool(SENSOR_ID_RE.fullmatch(sensor_id))


def connect(db_path: str, immutable: bool = False) -> sqlite3.Connection:
    """Open the warehouse read-only. Raises ``sqlite3.OperationalError`` if missing."""
    abspath = Path(db_path).resolve()
    query = "immutable=1" if immutable else "mode=ro"
    conn = sqlite3.connect(f"file:{abspath}?{query}", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def distinct_sensors(conn: sqlite3.Connection) -> list[str]:
    """Known sensor IDs, from ``devices`` when present else derived from readings."""
    if table_exists(conn, "devices"):
        rows = conn.execute("SELECT sensor_id FROM devices ORDER BY sensor_id").fetchall()
        if rows:
            return [r[0] for r in rows]
    rows = conn.execute(
        "SELECT DISTINCT sensor_id FROM readings_raw ORDER BY sensor_id"
    ).fetchall()
    return [r[0] for r in rows]


def most_recent_sensor(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sensor_id FROM readings_raw GROUP BY sensor_id ORDER BY max(ts) DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def latest_reading(conn: sqlite3.Connection, sensor_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM readings_raw WHERE sensor_id=? ORDER BY ts DESC LIMIT 1",
        (sensor_id,),
    ).fetchone()


def device_row(conn: sqlite3.Connection, sensor_id: str) -> sqlite3.Row | None:
    if not table_exists(conn, "devices"):
        return None
    return conn.execute(
        "SELECT * FROM devices WHERE sensor_id=?", (sensor_id,)
    ).fetchone()


def hourly_pm(conn: sqlite3.Connection, sensor_id: str, since: int) -> list[sqlite3.Row]:
    """Hourly means (oldest first) for NowCast: pm2_5 (corrected) and pm10."""
    return conn.execute(
        f"SELECT avg({PM25}) AS pm2_5, avg(pm10) AS pm10 "
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY ts/3600 ORDER BY ts/3600",
        (sensor_id, since),
    ).fetchall()


def count_since(conn: sqlite3.Connection, sensor_id: str, since: int) -> int:
    return conn.execute(
        "SELECT count(*) FROM readings_raw WHERE sensor_id=? AND ts>=?",
        (sensor_id, since),
    ).fetchone()[0]
