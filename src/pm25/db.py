"""SQLite storage: raw 1-sample rows plus hourly/daily rollups.

Timestamps are unix seconds in UTC. Rollups are recomputed only for the current
hour/day on each insert, so pruning old raw rows never corrupts historical rollups.
"""
from __future__ import annotations

import sqlite3
import os
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings_raw (
    ts     INTEGER PRIMARY KEY,   -- unix seconds, UTC
    pm1_0  REAL, pm2_5 REAL, pm10 REAL,
    pm2_5_corr REAL,               -- EPA/Barkjohn humidity-corrected PM2.5 (nullable; needs RH)
    n0_3 INTEGER, n0_5 INTEGER, n1_0 INTEGER,
    n2_5 INTEGER, n5_0 INTEGER, n10 INTEGER,
    rh REAL, temp REAL,            -- nullable; populated only when the SHT31 is enabled
    synced INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS readings_hourly (
    ts_hour INTEGER PRIMARY KEY,
    pm2_5 REAL, pm10 REAL, pm2_5_corr REAL,
    rh REAL, temp REAL, samples INTEGER
);

CREATE TABLE IF NOT EXISTS readings_daily (
    ts_day INTEGER PRIMARY KEY,
    pm2_5 REAL, pm10 REAL, pm2_5_corr REAL,
    rh REAL, temp REAL, samples INTEGER
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_pushed_ts INTEGER NOT NULL DEFAULT 0,
    server_max_ts  INTEGER NOT NULL DEFAULT 0,
    last_attempt_ts INTEGER NOT NULL DEFAULT 0,
    last_success_ts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    backlog_rows INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reader_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_cycle_ts INTEGER,
    last_success_ts INTEGER,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    valid_frames_total INTEGER NOT NULL DEFAULT 0,
    checksum_errors_total INTEGER NOT NULL DEFAULT 0,
    timeout_reads_total INTEGER NOT NULL DEFAULT 0,
    transport_errors_total INTEGER NOT NULL DEFAULT 0,
    sensor_resets_total INTEGER NOT NULL DEFAULT 0,
    serial_reopens_total INTEGER NOT NULL DEFAULT 0,
    sht31_failures_total INTEGER NOT NULL DEFAULT 0,
    sht31_ok INTEGER,
    last_error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alert_state (
    kind TEXT PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    breach_count INTEGER NOT NULL DEFAULT 0,
    last_sent_ts INTEGER NOT NULL DEFAULT 0,
    last_value REAL,
    last_error TEXT NOT NULL DEFAULT ''
);
"""

RAW_COLS = ["pm1_0", "pm2_5", "pm10", "pm2_5_corr", "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10", "rh", "temp"]


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    if conn.execute("PRAGMA page_count").fetchone()[0] == 0:
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")  # keep temp b-trees in RAM, off the SD card
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in ("readings_raw", "readings_hourly", "readings_daily"):
        _ensure_column(conn, table, "pm2_5_corr", "REAL")  # migrate pre-correction databases
    _ensure_column(conn, "readings_raw", "synced", "INTEGER NOT NULL DEFAULT 0")
    for column, decl in (
        ("last_attempt_ts", "INTEGER NOT NULL DEFAULT 0"),
        ("last_success_ts", "INTEGER NOT NULL DEFAULT 0"),
        ("last_error", "TEXT NOT NULL DEFAULT ''"),
        ("backlog_rows", "INTEGER NOT NULL DEFAULT 0"),
    ):
        _ensure_column(conn, "sync_state", column, decl)
    _ensure_column(conn, "reader_status", "transport_errors_total", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("INSERT OR IGNORE INTO sync_state (id) VALUES (1)")
    conn.execute("INSERT OR IGNORE INTO reader_status (id) VALUES (1)")
    conn.commit()


def insert_raw(conn: sqlite3.Connection, ts: int, values: dict) -> None:
    cols = ",".join(["ts", *RAW_COLS])
    placeholders = ",".join(["?"] * (1 + len(RAW_COLS)))
    row = [ts, *[values.get(c) for c in RAW_COLS]]
    updates = ",".join(f"{column}=excluded.{column}" for column in RAW_COLS)
    changed = " OR ".join(f"readings_raw.{column} IS NOT excluded.{column}" for column in RAW_COLS)
    conn.execute(
        f"INSERT INTO readings_raw ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(ts) DO UPDATE SET {updates}, "
        f"synced=CASE WHEN {changed} THEN 0 ELSE readings_raw.synced END",
        row,
    )


def update_rollups(conn: sqlite3.Connection, ts: int) -> None:
    hour = ts - ts % 3600
    day = ts - ts % 86400

    h = conn.execute(
        "SELECT avg(pm2_5), avg(pm10), avg(pm2_5_corr), avg(rh), avg(temp), count(*) "
        "FROM readings_raw WHERE ts >= ? AND ts < ?",
        (hour, hour + 3600),
    ).fetchone()
    conn.execute(
        "INSERT INTO readings_hourly (ts_hour, pm2_5, pm10, pm2_5_corr, rh, temp, samples) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ts_hour) DO UPDATE SET pm2_5=excluded.pm2_5, pm10=excluded.pm10, "
        "pm2_5_corr=excluded.pm2_5_corr, rh=excluded.rh, temp=excluded.temp, samples=excluded.samples",
        (hour, h[0], h[1], h[2], h[3], h[4], h[5]),
    )

    d = conn.execute(
        "SELECT avg(pm2_5), avg(pm10), avg(pm2_5_corr), avg(rh), avg(temp), count(*) "
        "FROM readings_raw WHERE ts >= ? AND ts < ?",
        (day, day + 86400),
    ).fetchone()
    conn.execute(
        "INSERT INTO readings_daily (ts_day, pm2_5, pm10, pm2_5_corr, rh, temp, samples) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ts_day) DO UPDATE SET pm2_5=excluded.pm2_5, pm10=excluded.pm10, "
        "pm2_5_corr=excluded.pm2_5_corr, rh=excluded.rh, temp=excluded.temp, samples=excluded.samples",
        (day, d[0], d[1], d[2], d[3], d[4], d[5]),
    )


def record_reader_cycle(
    conn: sqlite3.Connection,
    ts: int,
    *,
    success: bool,
    valid_frames: int,
    checksum_errors: int,
    timeout_reads: int,
    transport_errors: int = 0,
    sht31_ok: bool | None,
    recovery: str | None = None,
) -> None:
    error = "" if success else "no valid PMS5003 frames"
    conn.execute(
        "UPDATE reader_status SET last_cycle_ts = ?, "
        "last_success_ts = CASE WHEN ? THEN ? ELSE last_success_ts END, "
        "consecutive_failures = CASE WHEN ? THEN 0 ELSE consecutive_failures + 1 END, "
        "valid_frames_total = valid_frames_total + ?, "
        "checksum_errors_total = checksum_errors_total + ?, "
        "timeout_reads_total = timeout_reads_total + ?, "
        "transport_errors_total = transport_errors_total + ?, "
        "sensor_resets_total = sensor_resets_total + ?, "
        "serial_reopens_total = serial_reopens_total + ?, "
        "sht31_failures_total = sht31_failures_total + ?, "
        "sht31_ok = COALESCE(?, sht31_ok), last_error = ? WHERE id = 1",
        (
            ts,
            success,
            ts,
            success,
            valid_frames,
            checksum_errors,
            timeout_reads,
            transport_errors,
            recovery in ("reset", "reopen"),
            recovery == "reopen",
            sht31_ok is False,
            None if sht31_ok is None else int(sht31_ok),
            error,
        ),
    )


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def database_bytes(path: str) -> int:
    return sum(os.path.getsize(candidate) for candidate in (path, f"{path}-wal", f"{path}-shm") if os.path.exists(candidate))


def maintain(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA optimize")
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
        conn.execute("PRAGMA incremental_vacuum(1000)")
