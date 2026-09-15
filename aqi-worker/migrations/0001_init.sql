-- aqi-worker D1 schema (multi-sensor). Mirrors server/ingest.py + src/pm25/db.py,
-- with sensor_id added to the rollup keys. `synced` is Pi-local only and omitted here.

CREATE TABLE readings_raw (
  sensor_id  TEXT    NOT NULL,
  ts         INTEGER NOT NULL,            -- unix seconds, UTC
  pm1_0 REAL, pm2_5 REAL, pm10 REAL, pm2_5_corr REAL,
  n0_3 INTEGER, n0_5 INTEGER, n1_0 INTEGER, n2_5 INTEGER, n5_0 INTEGER, n10 INTEGER,
  rh REAL, temp REAL,
  PRIMARY KEY (sensor_id, ts)
);

CREATE TABLE readings_hourly (
  sensor_id  TEXT    NOT NULL,
  ts_hour    INTEGER NOT NULL,
  pm2_5 REAL, pm10 REAL, pm2_5_corr REAL, rh REAL, temp REAL, samples INTEGER,
  PRIMARY KEY (sensor_id, ts_hour)
);

CREATE TABLE readings_daily (
  sensor_id  TEXT    NOT NULL,
  ts_day     INTEGER NOT NULL,
  pm2_5 REAL, pm10 REAL, pm2_5_corr REAL, rh REAL, temp REAL, samples INTEGER,
  PRIMARY KEY (sensor_id, ts_day)
);

CREATE TABLE devices (
  sensor_id       TEXT PRIMARY KEY,
  sample_period_s INTEGER NOT NULL DEFAULT 180,
  last_ingest_ts  INTEGER NOT NULL DEFAULT 0,
  last_reading_ts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE alert_state (
  sensor_id     TEXT PRIMARY KEY,
  last_level    TEXT    NOT NULL DEFAULT 'none',
  last_fired_ts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE alert_overrides (
  id   INTEGER PRIMARY KEY CHECK (id = 1),
  data TEXT NOT NULL
);
