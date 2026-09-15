// Read helpers over the D1 warehouse (raw + hourly/daily rollups). Analytics prefer the
// humidity-corrected PM2.5 via COALESCE. The D1Database interface is satisfied in tests
// by the node:sqlite shim in test/d1-adapter.ts.

// Prefer the humidity-corrected PM2.5 (from the GY-SHT31 RH), fall back to raw. Valid on
// readings_raw and the rollup tables (all carry pm2_5 + pm2_5_corr columns).
export const PM25 = "COALESCE(pm2_5_corr, pm2_5)";

export interface ReadingRow {
  sensor_id: string;
  ts: number;
  pm1_0: number | null;
  pm2_5: number | null;
  pm10: number | null;
  pm2_5_corr: number | null;
  n0_3: number | null;
  n0_5: number | null;
  n1_0: number | null;
  n2_5: number | null;
  n5_0: number | null;
  n10: number | null;
  rh: number | null;
  temp: number | null;
}

export interface DeviceRow {
  sensor_id: string;
  sample_period_s: number;
  last_ingest_ts: number;
  last_reading_ts: number;
}

export async function distinctSensors(db: D1Database): Promise<string[]> {
  const devices = await db
    .prepare("SELECT sensor_id FROM devices ORDER BY sensor_id")
    .all<{ sensor_id: string }>();
  if (devices.results.length) return devices.results.map((r) => r.sensor_id);
  const rows = await db
    .prepare("SELECT DISTINCT sensor_id FROM readings_raw ORDER BY sensor_id")
    .all<{ sensor_id: string }>();
  return rows.results.map((r) => r.sensor_id);
}

export async function mostRecentSensor(db: D1Database): Promise<string | null> {
  const row = await db
    .prepare("SELECT sensor_id FROM readings_raw GROUP BY sensor_id ORDER BY max(ts) DESC LIMIT 1")
    .first<{ sensor_id: string }>();
  return row ? row.sensor_id : null;
}

export async function latestReading(db: D1Database, sensorId: string): Promise<ReadingRow | null> {
  return db
    .prepare("SELECT * FROM readings_raw WHERE sensor_id=? ORDER BY ts DESC LIMIT 1")
    .bind(sensorId)
    .first<ReadingRow>();
}

export async function deviceRow(db: D1Database, sensorId: string): Promise<DeviceRow | null> {
  return db.prepare("SELECT * FROM devices WHERE sensor_id=?").bind(sensorId).first<DeviceRow>();
}

// Hourly means (oldest first) from the hourly rollup, for NowCast + trend.
export async function hourlySince(
  db: D1Database,
  sensorId: string,
  since: number,
): Promise<{ ts_hour: number; pm2_5: number | null; pm10: number | null }[]> {
  const rows = await db
    .prepare(
      `SELECT ts_hour, ${PM25} AS pm2_5, pm10 ` +
        "FROM readings_hourly WHERE sensor_id=? AND ts_hour>=? ORDER BY ts_hour",
    )
    .bind(sensorId, since)
    .all<{ ts_hour: number; pm2_5: number | null; pm10: number | null }>();
  return rows.results;
}

export async function countSince(db: D1Database, sensorId: string, since: number): Promise<number> {
  const row = await db
    .prepare("SELECT count(*) AS n FROM readings_raw WHERE sensor_id=? AND ts>=?")
    .bind(sensorId, since)
    .first<{ n: number }>();
  return row ? row.n : 0;
}
