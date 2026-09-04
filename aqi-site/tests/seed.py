"""Build a seeded warehouse-schema SQLite DB matching ``server/ingest.py``."""
from __future__ import annotations

import math
import sqlite3
import time

_READINGS_SCHEMA = """
CREATE TABLE readings_raw (
    sensor_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    pm1_0 REAL, pm2_5 REAL, pm10 REAL, pm2_5_corr REAL,
    n0_3 INTEGER, n0_5 INTEGER, n1_0 INTEGER,
    n2_5 INTEGER, n5_0 INTEGER, n10 INTEGER,
    rh REAL, temp REAL,
    PRIMARY KEY (sensor_id, ts)
)
"""
_DEVICES_SCHEMA = (
    "CREATE TABLE devices ("
    "sensor_id TEXT PRIMARY KEY, sample_period_s INTEGER NOT NULL DEFAULT 120, "
    "last_ingest_ts INTEGER NOT NULL DEFAULT 0, last_reading_ts INTEGER NOT NULL DEFAULT 0)"
)

_COLS = [
    "sensor_id", "ts", "pm1_0", "pm2_5", "pm10", "pm2_5_corr",
    "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10", "rh", "temp",
]


def _row(sensor_id, ts, pm2_5, *, corr=True, env=True):
    pm10 = round(pm2_5 * 1.4, 1)
    rh = 55.0 if env else None
    temp = 20.0 if env else None
    pm2_5_corr = round(max(0.0, 0.524 * pm2_5 - 0.0862 * (rh or 0) + 5.75), 1) if corr else None
    return {
        "sensor_id": sensor_id, "ts": ts, "pm1_0": round(pm2_5 * 0.8, 1),
        "pm2_5": round(pm2_5, 1), "pm10": pm10, "pm2_5_corr": pm2_5_corr,
        "n0_3": 100, "n0_5": 50, "n1_0": 20, "n2_5": 5, "n5_0": 2, "n10": 1,
        "rh": rh, "temp": temp,
    }


def make_warehouse(path: str, now: int | None = None) -> int:
    """Create and seed a warehouse DB. Returns the ``now`` timestamp used."""
    now = now or int(time.time())
    conn = sqlite3.connect(path)
    conn.execute(_READINGS_SCHEMA)
    conn.execute("CREATE INDEX idx_readings_raw_ts ON readings_raw(ts)")
    conn.execute(_DEVICES_SCHEMA)

    rows: list[dict] = []
    # backyard: 48h @ 15 min, moderate diurnal swing, full env + correction.
    for i in range(192):
        ts = now - i * 900
        pm = 25 + 20 * math.sin(i / 8.0) + 10 * math.sin(i / 40.0)
        rows.append(_row("backyard", ts, max(2.0, pm)))
    # rooftop: 30 days @ hourly, low values, NO env/correction (SHT31 disabled).
    for i in range(720):
        ts = now - i * 3600
        pm = 12 + 8 * math.sin(i / 12.0)
        rows.append(_row("rooftop", ts, max(2.0, pm), corr=False, env=False))
    # smoky: 12h @ 15 min, very high (wildfire-like). Raw is high enough that the
    # Barkjohn humidity correction still lands in the top AQI bands.
    for i in range(48):
        ts = now - i * 900
        rows.append(_row("smoky", ts, 260.0))

    placeholders = ",".join(["?"] * len(_COLS))
    conn.executemany(
        f"INSERT INTO readings_raw ({','.join(_COLS)}) VALUES ({placeholders})",
        [tuple(r[c] for c in _COLS) for r in rows],
    )
    for sensor_id, period in (("backyard", 900), ("rooftop", 3600), ("smoky", 900)):
        last = conn.execute(
            "SELECT max(ts) FROM readings_raw WHERE sensor_id=?", (sensor_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO devices (sensor_id, sample_period_s, last_ingest_ts, last_reading_ts) "
            "VALUES (?, ?, ?, ?)",
            (sensor_id, period, now, last),
        )
    conn.commit()
    conn.close()
    return now
