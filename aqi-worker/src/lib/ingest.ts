// D1 write helpers for ingest: chunked multi-row upserts plus set-based rollup
// recompute. Engineered around free-tier D1 caps: <=100 bound params per query and
// <=50 queries per Worker invocation.

export const RAW_COLS = [
  "pm1_0", "pm2_5", "pm10", "pm2_5_corr",
  "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10",
  "rh", "temp",
] as const;

export const COLS_PER_ROW = 2 + RAW_COLS.length; // sensor_id, ts, + raw cols = 14
export const MAX_PARAMS = 100;
export const ROWS_PER_STMT = Math.floor(MAX_PARAMS / COLS_PER_ROW); // 7

export type Scalar = number | string | null;
export interface RawRow {
  ts: number;
  [col: string]: number | null;
}
export interface Stmt {
  sql: string;
  params: Scalar[];
}

// Build chunked multi-row upserts into readings_raw, each within MAX_PARAMS.
export function buildRawUpserts(
  sensorId: string,
  rows: RawRow[],
  rowsPerStmt: number = ROWS_PER_STMT,
): Stmt[] {
  const cols = ["sensor_id", "ts", ...RAW_COLS];
  const setClause = RAW_COLS.map((c) => `${c}=excluded.${c}`).join(", ");
  const stmts: Stmt[] = [];
  for (let i = 0; i < rows.length; i += rowsPerStmt) {
    const chunk = rows.slice(i, i + rowsPerStmt);
    const tuples: string[] = [];
    const params: Scalar[] = [];
    for (const r of chunk) {
      tuples.push(`(${cols.map(() => "?").join(",")})`);
      params.push(sensorId, r.ts, ...RAW_COLS.map((c) => (r[c] ?? null)));
    }
    stmts.push({
      sql:
        `INSERT INTO readings_raw (${cols.join(",")}) VALUES ${tuples.join(",")} ` +
        `ON CONFLICT(sensor_id, ts) DO UPDATE SET ${setClause}`,
      params,
    });
  }
  return stmts;
}

// Recompute hourly + daily rollups for every bucket the batch touched, in exactly two
// set-based upserts (independent of how many buckets/rows are involved).
export function buildRollupUpserts(sensorId: string, minTs: number, maxTs: number): Stmt[] {
  const hourStart = Math.floor(minTs / 3600) * 3600;
  const dayStart = Math.floor(minTs / 86400) * 86400;
  const endExcl = maxTs + 1;
  const roll = (table: string, key: string, bucket: number, start: number): Stmt => ({
    sql:
      `INSERT INTO ${table} (sensor_id, ${key}, pm2_5, pm10, pm2_5_corr, rh, temp, samples) ` +
      `SELECT sensor_id, (ts/${bucket})*${bucket} AS ${key}, ` +
      `avg(pm2_5), avg(pm10), avg(pm2_5_corr), avg(rh), avg(temp), count(*) ` +
      `FROM readings_raw WHERE sensor_id=? AND ts>=? AND ts<? GROUP BY sensor_id, ${key} ` +
      `ON CONFLICT(sensor_id, ${key}) DO UPDATE SET pm2_5=excluded.pm2_5, pm10=excluded.pm10, ` +
      `pm2_5_corr=excluded.pm2_5_corr, rh=excluded.rh, temp=excluded.temp, samples=excluded.samples`,
    params: [sensorId, start, endExcl],
  });
  return [
    roll("readings_hourly", "ts_hour", 3600, hourStart),
    roll("readings_daily", "ts_day", 86400, dayStart),
  ];
}

// Total D1 statements a single ingest invocation will issue (raw chunks + 2 rollups +
// 1 devices upsert). Used by probes/ingest_caps.ts to prove we stay under the free cap.
export function ingestStatementCount(rowCount: number, rowsPerStmt: number = ROWS_PER_STMT): number {
  return Math.ceil(rowCount / rowsPerStmt) + 2 + 1;
}
