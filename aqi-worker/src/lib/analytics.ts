// Analytics over the D1 warehouse. Recent / fine-grained views read readings_raw;
// long-range and aggregate views read the hourly/daily rollups (maintained on ingest)
// to stay well within the free-tier D1 row-read budget. AQI/NowCast come from ./epa so
// the EPA math has a single source of truth.
import { aqi, category, nowcast, pyRound } from "./epa.ts";
import type { MaskConfig } from "./config.ts";
import * as db from "./db.ts";
import { PM25 } from "./db.ts";
import { recommend } from "./mask.ts";

// range key -> [bucket_seconds, span_seconds]
export const RANGES: Record<string, [number, number]> = {
  "6h": [300, 6 * 3600],
  "24h": [900, 24 * 3600],
  "7d": [3600, 7 * 86400],
  "30d": [10800, 30 * 86400],
  "90d": [86400, 90 * 86400],
  "1y": [86400, 365 * 86400],
};

// [upper_aqi_inclusive, label, color] mirroring the EPA categories.
export const BANDS: [number, string, string][] = [
  [50, "Good", "#00e400"],
  [100, "Moderate", "#ffff00"],
  [150, "Unhealthy for Sensitive Groups", "#ff7e00"],
  [200, "Unhealthy", "#ff0000"],
  [300, "Very Unhealthy", "#8f3f97"],
  [10 ** 9, "Hazardous", "#7e0023"],
];

// Berkeley Earth rule of thumb: ~22 ug/m3 of PM2.5 for a day == one cigarette.
const CIGARETTE_UGM3_DAY = 22.0;

// A sensor is stale/offline once its newest reading is older than this.
const STALE_FLOOR_S = 900;
const STALE_PERIODS = 3;

// Reads switch from raw to the hourly rollup at/above this span (7d and longer).
const HOURLY_SPAN_MIN = 7 * 86400;

const now = (): number => Math.floor(Date.now() / 1000);

function round1(value: number | null | undefined): number | null {
  return value === null || value === undefined ? null : pyRound(value, 1);
}

/** Overall AQI and dominant pollutant for a bucket's mean concentrations. */
function aqiOf(pm2_5: number | null, pm10: number | null): [number, string] {
  const a25 = aqi("pm2_5", pm2_5) ?? 0;
  const a10 = aqi("pm10", pm10) ?? 0;
  return a25 >= a10 ? [a25, "pm2_5"] : [a10, "pm10"];
}

function bandIndex(aqiValue: number): number {
  for (let i = 0; i < BANDS.length; i++) {
    if (aqiValue <= BANDS[i][0]) return i;
  }
  return BANDS.length - 1;
}

/** Compare the most recent hour to the previous few (hourly rollup) for direction. */
async function trend(d: D1Database, sensorId: string, nowTs: number): Promise<string> {
  const rows = await db.hourlySince(d, sensorId, nowTs - 4 * 3600);
  const values = rows
    .map((r) => r.pm2_5)
    .filter((v): v is number => v !== null && v !== undefined);
  if (values.length < 2) return "steady";
  const recent = values[values.length - 1];
  const rest = values.slice(0, -1);
  const base = rest.reduce((a, b) => a + b, 0) / rest.length;
  const delta = (aqi("pm2_5", recent) ?? 0) - (aqi("pm2_5", base) ?? 0);
  if (delta >= 8) return "worsening";
  if (delta <= -8) return "improving";
  return "steady";
}

/** Local hour-of-day with the lowest typical PM2.5 over the last two weeks (hourly). */
async function goodWindow(
  d: D1Database,
  sensorId: string,
  offset: number,
): Promise<{ hour: number; aqi: number } | null> {
  const res = await d
    .prepare(
      "SELECT CAST(strftime('%H', ts_hour + ?, 'unixepoch') AS INTEGER) AS hour, " +
        `avg(${PM25}) AS pm2_5 ` +
        "FROM readings_hourly WHERE sensor_id=? AND ts_hour>=? GROUP BY hour",
    )
    .bind(offset, sensorId, now() - 14 * 86400)
    .all<{ hour: number; pm2_5: number | null }>();
  const hours = res.results
    .filter((r) => r.pm2_5 !== null && r.pm2_5 !== undefined)
    .map((r) => [r.hour, r.pm2_5 as number] as [number, number]);
  if (hours.length < 4) return null;
  const [hour, pm] = hours.reduce((min, x) => (x[1] < min[1] ? x : min));
  return { hour, aqi: aqi("pm2_5", pm) ?? 0 };
}

export interface Current {
  sensor_id: string;
  ts: number;
  age_s: number;
  online: boolean;
  stale: boolean;
  last_ingest_ts: number | null;
  last_ingest_age_s: number | null;
  sample_period_s: number;
  pm2_5: number | null;
  pm2_5_raw: number | null;
  pm10: number | null;
  rh: number | null;
  temp: number | null;
  nowcast_aqi: number;
  category: string;
  color: string;
  dominant: string;
  trend: string;
  mask: ReturnType<typeof recommend>;
  good_window: { hour: number; aqi: number } | null;
}

export async function current(
  d: D1Database,
  sensorId: string,
  maskCfg: MaskConfig,
  offset = 0,
): Promise<Current | null> {
  const latest = await db.latestReading(d, sensorId);
  if (latest === null) return null;
  const latestTs = latest.ts;
  const nowTs = now();
  const hourly = await db.hourlySince(d, sensorId, latestTs - 12 * 3600);
  const corrLatest = latest.pm2_5_corr ?? latest.pm2_5;
  let nc25 = nowcast(hourly.map((r) => r.pm2_5));
  let nc10 = nowcast(hourly.map((r) => r.pm10));
  nc25 = nc25 ?? corrLatest;
  nc10 = nc10 ?? latest.pm10;
  const [overall, dominant] = aqiOf(nc25, nc10);
  const cat = category(overall);
  const dir = await trend(d, sensorId, latestTs);
  const reco = recommend(overall, maskCfg.thresholds, { dominant, trend: dir });
  const device = await db.deviceRow(d, sensorId);
  const samplePeriod = device ? device.sample_period_s : 120;
  const lastIngestTs = device ? device.last_ingest_ts : 0;
  const age = Math.max(0, nowTs - latestTs);
  const stale = age > Math.max(STALE_FLOOR_S, STALE_PERIODS * samplePeriod);
  return {
    sensor_id: sensorId,
    ts: latestTs,
    age_s: age,
    online: !stale,
    stale,
    last_ingest_ts: lastIngestTs || null,
    last_ingest_age_s: lastIngestTs ? Math.max(0, nowTs - lastIngestTs) : null,
    sample_period_s: samplePeriod,
    pm2_5: corrLatest,
    pm2_5_raw: latest.pm2_5,
    pm10: latest.pm10,
    rh: latest.rh,
    temp: latest.temp,
    nowcast_aqi: overall,
    category: cat.label,
    color: cat.color,
    dominant,
    trend: dir,
    mask: reco,
    good_window: await goodWindow(d, sensorId, offset),
  };
}

export interface HistoryPoint {
  t: number;
  pm2_5: number | null;
  pm10: number | null;
  temp: number | null;
  rh: number | null;
  aqi: number;
}

export async function history(
  d: D1Database,
  sensorId: string,
  rangeKey: string,
  bucket?: number | null,
): Promise<HistoryPoint[]> {
  const [defaultBucket, span] = RANGES[rangeKey];
  let b = bucket ?? defaultBucket;
  b = Math.max(60, Math.min(86400, Math.trunc(b)));
  const since = now() - span;
  const table = span >= HOURLY_SPAN_MIN ? "readings_hourly" : "readings_raw";
  const tcol = span >= HOURLY_SPAN_MIN ? "ts_hour" : "ts";
  const res = await d
    .prepare(
      `SELECT (${tcol}/?)*? AS t, avg(${PM25}) AS pm2_5, avg(pm10) AS pm10, ` +
        `avg(temp) AS temp, avg(rh) AS rh FROM ${table} ` +
        `WHERE sensor_id=? AND ${tcol}>=? GROUP BY t ORDER BY t`,
    )
    .bind(b, b, sensorId, since)
    .all<{ t: number; pm2_5: number | null; pm10: number | null; temp: number | null; rh: number | null }>();
  return res.results.map((r) => {
    const [value] = aqiOf(r.pm2_5, r.pm10);
    return {
      t: r.t,
      pm2_5: round1(r.pm2_5),
      pm10: round1(r.pm10),
      temp: round1(r.temp),
      rh: round1(r.rh),
      aqi: value,
    };
  });
}

export interface CalendarDay {
  date: string;
  aqi: number;
  pm2_5: number | null;
}

export async function calendar(
  d: D1Database,
  sensorId: string,
  year: number,
  offset = 0,
): Promise<CalendarDay[]> {
  const day = 86400;
  const res = await d
    .prepare(
      `SELECT (ts_day + ?)/? AS dd, avg(${PM25}) AS pm2_5, avg(pm10) AS pm10 ` +
        "FROM readings_daily WHERE sensor_id=? " +
        "AND strftime('%Y', ts_day + ?, 'unixepoch')=? GROUP BY dd ORDER BY dd",
    )
    .bind(offset, day, sensorId, offset, String(year).padStart(4, "0"))
    .all<{ dd: number; pm2_5: number | null; pm10: number | null }>();
  return res.results.map((r) => {
    const [value] = aqiOf(r.pm2_5, r.pm10);
    const date = new Date(r.dd * day * 1000).toISOString().slice(0, 10);
    return { date, aqi: value, pm2_5: round1(r.pm2_5) };
  });
}

export type HeatCell = [number, number, number]; // hour, weekday(0=Sun), aqi

export async function heatmap(
  d: D1Database,
  sensorId: string,
  rangeKey: string,
  offset = 0,
): Promise<HeatCell[]> {
  const [, span] = RANGES[rangeKey];
  const since = now() - span;
  const res = await d
    .prepare(
      "SELECT CAST(strftime('%w', ts_hour + ?, 'unixepoch') AS INTEGER) AS dow, " +
        "CAST(strftime('%H', ts_hour + ?, 'unixepoch') AS INTEGER) AS hour, " +
        `avg(${PM25}) AS pm2_5, avg(pm10) AS pm10 ` +
        "FROM readings_hourly WHERE sensor_id=? AND ts_hour>=? GROUP BY dow, hour",
    )
    .bind(offset, offset, sensorId, since)
    .all<{ dow: number; hour: number; pm2_5: number | null; pm10: number | null }>();
  return res.results.map((r) => {
    const [value] = aqiOf(r.pm2_5, r.pm10);
    return [r.hour, r.dow, value] as HeatCell;
  });
}

export interface DistBand {
  band: number;
  label: string;
  color: string;
  hours: number;
  pct: number;
}

export async function distribution(
  d: D1Database,
  sensorId: string,
  rangeKey: string,
): Promise<DistBand[]> {
  const [, span] = RANGES[rangeKey];
  const since = now() - span;
  const res = await d
    .prepare(`SELECT ${PM25} AS pm2_5, pm10 FROM readings_hourly WHERE sensor_id=? AND ts_hour>=?`)
    .bind(sensorId, since)
    .all<{ pm2_5: number | null; pm10: number | null }>();
  const counts = new Array(BANDS.length).fill(0);
  for (const r of res.results) {
    if (r.pm2_5 === null && r.pm10 === null) continue;
    const [value] = aqiOf(r.pm2_5, r.pm10);
    counts[bandIndex(value)] += 1;
  }
  const total = counts.reduce((a, b) => a + b, 0);
  return BANDS.map(([, label, color], i) => ({
    band: i,
    label,
    color,
    hours: counts[i],
    pct: total ? pyRound((counts[i] * 100) / total, 1) : 0.0,
  }));
}

export interface DiurnalHour {
  hour: number;
  avg: number | null;
  min: number | null;
  max: number | null;
  aqi: number | null;
  aqi_min: number | null;
  aqi_max: number | null;
}

export async function diurnal(
  d: D1Database,
  sensorId: string,
  rangeKey: string,
  offset = 0,
): Promise<DiurnalHour[]> {
  const [, span] = RANGES[rangeKey];
  const since = now() - span;
  const res = await d
    .prepare(
      "SELECT CAST(strftime('%H', ts + ?, 'unixepoch') AS INTEGER) AS hour, " +
        `avg(${PM25}) AS avg_pm, min(${PM25}) AS min_pm, max(${PM25}) AS max_pm ` +
        "FROM readings_raw WHERE sensor_id=? AND ts>=? GROUP BY hour ORDER BY hour",
    )
    .bind(offset, sensorId, since)
    .all<{ hour: number; avg_pm: number | null; min_pm: number | null; max_pm: number | null }>();
  const byHour = new Map(res.results.map((r) => [r.hour, r]));
  const out: DiurnalHour[] = [];
  for (let hour = 0; hour < 24; hour++) {
    const r = byHour.get(hour);
    if (!r || r.avg_pm === null) {
      out.push({ hour, avg: null, min: null, max: null, aqi: null, aqi_min: null, aqi_max: null });
      continue;
    }
    out.push({
      hour,
      avg: round1(r.avg_pm),
      min: round1(r.min_pm),
      max: round1(r.max_pm),
      aqi: aqi("pm2_5", r.avg_pm) ?? 0,
      aqi_min: aqi("pm2_5", r.min_pm) ?? 0,
      aqi_max: aqi("pm2_5", r.max_pm) ?? 0,
    });
  }
  return out;
}

interface PeriodStat {
  period: string;
  avg_aqi: number | null;
  peak_aqi: number | null;
  unhealthy_hours: number;
  cigarettes: number | null;
  pm25: number | null;
}

// One period's stats from the hourly rollup (means, peak, unhealthy hours, cigarettes).
async function periodStats(
  d: D1Database,
  sensorId: string,
  period: string,
  span: number,
): Promise<PeriodStat> {
  const nowTs = now();
  const rows = await d
    .prepare(`SELECT ${PM25} AS pm2_5, pm10 FROM readings_hourly WHERE sensor_id=? AND ts_hour>=?`)
    .bind(sensorId, nowTs - span)
    .all<{ pm2_5: number | null; pm10: number | null }>();
  let peak = 0;
  let unhealthy = 0;
  let sum = 0;
  let n = 0;
  for (const r of rows.results) {
    const [value] = aqiOf(r.pm2_5, r.pm10);
    peak = Math.max(peak, value);
    if (value > 100) unhealthy += 1;
    if (r.pm2_5 !== null) {
      sum += r.pm2_5;
      n += 1;
    }
  }
  const mean = n ? sum / n : null;
  const days = span / 86400;
  return {
    period,
    avg_aqi: mean !== null ? aqi("pm2_5", mean) : null,
    peak_aqi: rows.results.length ? peak : null,
    unhealthy_hours: unhealthy,
    cigarettes: mean !== null ? pyRound((mean * days) / CIGARETTE_UGM3_DAY, 1) : null,
    pm25: round1(mean),
  };
}

export interface Summary {
  by_period: PeriodStat[];
  [k: string]: unknown;
}

export async function summary(d: D1Database, sensorId: string): Promise<Summary> {
  const periods: [string, number][] = [
    ["24h", 86400],
    ["7d", 7 * 86400],
    ["30d", 30 * 86400],
  ];
  const out: Summary = { by_period: [] };
  const stats: PeriodStat[] = [];
  for (const [key, span] of periods) {
    const s = await periodStats(d, sensorId, key, span);
    stats.push(s);
    out[`pm25_${key}`] = s.pm25;
    out[`aqi_${key}`] = s.avg_aqi;
    out[`cigarettes_${key}`] = s.cigarettes;
  }
  out.peak_aqi_7d = stats[1].peak_aqi;
  out.exceedance_hours_30d = stats[2].unhealthy_hours;
  out.by_period = stats;
  return out;
}

export function exportRows(
  d: D1Database,
  sensorId: string,
  rangeKey: string,
): Promise<HistoryPoint[]> {
  return history(d, sensorId, rangeKey);
}

export interface SensorRow {
  sensor_id: string;
  ts: number;
  age_s: number;
  pm2_5: number | null;
  pm10: number | null;
  rh: number | null;
  temp: number | null;
  aqi: number;
  category: string;
  color: string;
  mask_level: string;
  coverage_24h: number;
  online: boolean;
  stale: boolean;
  last_ingest_ts: number | null;
  last_ingest_age_s: number | null;
  sample_period_s: number;
  sht31_ok: boolean;
}

/** Fleet snapshot: latest AQI, mask level, and 24h coverage per device. */
export async function sensorsOverview(
  d: D1Database,
  maskCfg: MaskConfig,
  offset = 0,
): Promise<SensorRow[]> {
  const nowTs = now();
  const out: SensorRow[] = [];
  for (const sensorId of await db.distinctSensors(d)) {
    const snap = await current(d, sensorId, maskCfg, offset);
    if (snap === null) continue;
    const device = await db.deviceRow(d, sensorId);
    const period = device ? device.sample_period_s : 120;
    const expected = Math.max(1, Math.round(86400 / period));
    const count24h = await db.countSince(d, sensorId, nowTs - 86400);
    out.push({
      sensor_id: sensorId,
      ts: snap.ts,
      age_s: snap.age_s,
      pm2_5: snap.pm2_5,
      pm10: snap.pm10,
      rh: snap.rh,
      temp: snap.temp,
      aqi: snap.nowcast_aqi,
      category: snap.category,
      color: snap.color,
      mask_level: snap.mask.level,
      coverage_24h: Math.min(100, Math.round((count24h * 100) / expected)),
      online: snap.online,
      stale: snap.stale,
      last_ingest_ts: snap.last_ingest_ts,
      last_ingest_age_s: snap.last_ingest_age_s,
      sample_period_s: snap.sample_period_s,
      sht31_ok: snap.temp !== null && snap.rh !== null,
    });
  }
  return out;
}

export interface Gap {
  start: number;
  end: number;
  duration_s: number;
  ongoing: boolean;
}

export interface Status {
  sensor_id: string;
  online: boolean;
  stale: boolean;
  last_reading_ts: number | null;
  last_reading_age_s: number | null;
  last_ingest_ts: number | null;
  last_ingest_age_s: number | null;
  sample_period_s: number;
  coverage_24h: { expected: number; actual: number; pct: number };
  coverage_7d: { expected: number; actual: number; pct: number };
  sht31: { ok: boolean; temp_pct_24h: number; rh_pct_24h: number; temp: number | null; rh: number | null };
  gaps_7d: { count: number; items: Gap[] };
}

/** Device-health view: online/stale, coverage, GY-SHT31 health, and recent gaps (raw). */
export async function status(d: D1Database, sensorId: string): Promise<Status | null> {
  const latest = await db.latestReading(d, sensorId);
  const device = await db.deviceRow(d, sensorId);
  if (latest === null && device === null) return null;
  const nowTs = now();
  const samplePeriod = device ? device.sample_period_s : 120;
  const lastReadingTs = latest !== null ? latest.ts : 0;
  const lastIngestTs = device ? device.last_ingest_ts : 0;
  const age = lastReadingTs ? Math.max(0, nowTs - lastReadingTs) : null;
  const stale = age === null || age > Math.max(STALE_FLOOR_S, STALE_PERIODS * samplePeriod);

  const coverage = async (span: number) => {
    const count = await db.countSince(d, sensorId, nowTs - span);
    const expected = Math.max(1, Math.round(span / samplePeriod));
    return { expected, actual: count, pct: Math.min(100, Math.round((count * 100) / expected)) };
  };

  const env = await d
    .prepare(
      "SELECT count(*) AS total, count(temp) AS temp_n, count(rh) AS rh_n " +
        "FROM readings_raw WHERE sensor_id=? AND ts>=?",
    )
    .bind(sensorId, nowTs - 86400)
    .first<{ total: number; temp_n: number; rh_n: number }>();
  const envTotal = env?.total ?? 0;
  const sht31Ok = latest !== null && latest.temp !== null && latest.rh !== null;

  const gapThreshold = Math.max(2 * samplePeriod, 600);
  const tsRows = await d
    .prepare("SELECT ts FROM readings_raw WHERE sensor_id=? AND ts>=? ORDER BY ts")
    .bind(sensorId, nowTs - 7 * 86400)
    .all<{ ts: number }>();
  const gaps: Gap[] = [];
  let prev: number | null = null;
  for (const row of tsRows.results) {
    if (prev !== null && row.ts - prev > gapThreshold) {
      gaps.push({ start: prev, end: row.ts, duration_s: row.ts - prev, ongoing: false });
    }
    prev = row.ts;
  }
  if (prev !== null && nowTs - prev > gapThreshold) {
    gaps.push({ start: prev, end: nowTs, duration_s: nowTs - prev, ongoing: true });
  }
  gaps.sort((a, b) => b.duration_s - a.duration_s);

  const cov24 = await coverage(86400);
  const cov7 = await coverage(7 * 86400);
  return {
    sensor_id: sensorId,
    online: !stale,
    stale,
    last_reading_ts: lastReadingTs || null,
    last_reading_age_s: age,
    last_ingest_ts: lastIngestTs || null,
    last_ingest_age_s: lastIngestTs ? Math.max(0, nowTs - lastIngestTs) : null,
    sample_period_s: samplePeriod,
    coverage_24h: cov24,
    coverage_7d: cov7,
    sht31: {
      ok: sht31Ok,
      temp_pct_24h: envTotal ? Math.round((env!.temp_n * 100) / envTotal) : 0,
      rh_pct_24h: envTotal ? Math.round((env!.rh_n * 100) / envTotal) : 0,
      temp: latest !== null ? latest.temp : null,
      rh: latest !== null ? latest.rh : null,
    },
    gaps_7d: { count: gaps.length, items: gaps.slice(0, 20) },
  };
}
