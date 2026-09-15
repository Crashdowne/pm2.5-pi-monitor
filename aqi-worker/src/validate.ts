// Ingest record validation — mirrors server/ingest.py (_validated_record + VALUE_RANGES,
// SENSOR_ID_RE, ts window). Rejected records cause the whole batch to 400, exactly as
// the current server does, so the Pi's sync ack check behaves identically.
import { RAW_COLS, type RawRow } from "./lib/ingest.ts";

export const SENSOR_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
export const MAX_BODY = 5 * 1024 * 1024;
// Cap rows per POST so one ingest invocation stays under the free-tier D1 query cap
// (<=50): ceil(rows/7 raw upserts) + 2 rollups + 1 device <= 50 -> rows <= 329.
export const MAX_INGEST_ROWS = 329;
export const TS_MIN = 1577836800; // 2020-01-01T00:00:00Z

export const VALUE_RANGES: Record<(typeof RAW_COLS)[number], [number, number]> = {
  pm1_0: [0, 5000],
  pm2_5: [0, 5000],
  pm10: [0, 5000],
  pm2_5_corr: [0, 5000],
  n0_3: [0, 65535],
  n0_5: [0, 65535],
  n1_0: [0, 65535],
  n2_5: [0, 65535],
  n5_0: [0, 65535],
  n10: [0, 65535],
  rh: [0, 100],
  temp: [-80, 100],
};

export type CleanRecord = RawRow;

export function validateSensorId(id: string): boolean {
  return SENSOR_ID_RE.test(id);
}

// Returns a cleaned record, or null if invalid (caller responds 400).
export function validateRecord(record: unknown, now: number): CleanRecord | null {
  if (typeof record !== "object" || record === null || Array.isArray(record)) return null;
  const rec = record as Record<string, unknown>;
  const ts = rec.ts;
  if (typeof ts !== "number" || !Number.isInteger(ts)) return null;
  if (ts < TS_MIN || ts > now + 86400) return null;
  const clean = { ts } as CleanRecord;
  for (const col of RAW_COLS) {
    const v = rec[col];
    if (v === null || v === undefined) {
      clean[col] = null;
    } else if (typeof v !== "number" || !Number.isFinite(v)) {
      return null;
    } else {
      const [low, high] = VALUE_RANGES[col];
      if (v < low || v > high) return null;
      clean[col] = v;
    }
  }
  return clean;
}
