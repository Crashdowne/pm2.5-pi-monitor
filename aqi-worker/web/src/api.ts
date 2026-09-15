// Typed client for the read-only aqi-site API (real data).

export interface LevelMeta {
  level: string; severity: number; label: string; action: string; color: string; mask_type: string;
}

export interface SiteConfig {
  site_title: string;
  temp_unit: "c" | "f";
  tz_offset_hours: number;
  ranges: string[];
  bands: { upper: number; label: string; color: string }[];
  mask: {
    sensitivity: string;
    thresholds: Thresholds;
    presets: Record<string, Thresholds>;
    levels: LevelMeta[];
    disclaimer: string;
  };
}

export interface Thresholds { carry: number; recommended: number; strong: number; indoors: number; }

export interface MaskReco extends LevelMeta {
  aqi: number | null; dominant: string | null; trend: string | null; disclaimer: string;
}

export interface Current {
  sensor_id: string; ts: number; age_s: number;
  online: boolean; stale: boolean;
  last_ingest_ts: number | null; last_ingest_age_s: number | null; sample_period_s: number;
  pm2_5: number | null; pm2_5_raw: number | null; pm10: number | null;
  rh: number | null; temp: number | null;
  nowcast_aqi: number; category: string; color: string; dominant: string;
  trend: string; mask: MaskReco; good_window: { hour: number; aqi: number } | null;
}

export interface SensorRow {
  sensor_id: string; ts: number; age_s: number;
  pm2_5: number | null; pm10: number | null; rh: number | null; temp: number | null;
  aqi: number; category: string; color: string; mask_level: string; coverage_24h: number;
  online: boolean; stale: boolean; last_ingest_ts: number | null; last_ingest_age_s: number | null;
  sample_period_s: number; sht31_ok: boolean;
}

export interface HistoryPoint {
  t: number; pm2_5: number | null; pm10: number | null; temp: number | null; rh: number | null; aqi: number;
}
export interface CalendarDay { date: string; aqi: number; pm2_5: number | null; }
export type HeatCell = [number, number, number]; // hour, weekday(0=Sun), aqi
export interface DistBand { band: number; label: string; color: string; hours: number; pct: number; }
export interface DiurnalHour {
  hour: number; avg: number | null; min: number | null; max: number | null;
  aqi: number | null; aqi_min: number | null; aqi_max: number | null;
}
export interface PeriodStat {
  period: string; avg_aqi: number | null; peak_aqi: number | null;
  unhealthy_hours: number; cigarettes: number | null; pm25: number | null;
}
export interface Summary { by_period: PeriodStat[]; [k: string]: unknown; }

export interface Gap { start: number; end: number; duration_s: number; ongoing: boolean; }
export interface Coverage { expected: number; actual: number; pct: number; }
export interface Status {
  sensor_id: string; online: boolean; stale: boolean;
  last_reading_ts: number | null; last_reading_age_s: number | null;
  last_ingest_ts: number | null; last_ingest_age_s: number | null; sample_period_s: number;
  coverage_24h: Coverage; coverage_7d: Coverage;
  sht31: { ok: boolean; temp_pct_24h: number; rh_pct_24h: number; temp: number | null; rh: number | null };
  gaps_7d: { count: number; items: Gap[] };
}

export interface AlertsView {
  enabled: boolean; notify_from: string; min_interval_s: number;
  quiet_start_hour: number; quiet_end_hour: number;
  ntfy_configured: boolean; webhook_configured: boolean;
  levels: string[];
  sensors: { sensor_id: string; last_level: string; last_fired_ts: number }[];
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const getConfig = () => fetch("/api/config").then(j<SiteConfig>);
export const getSensors = () => fetch("/api/sensors").then(j<SensorRow[]>);
export const getCurrent = (s: string) => fetch(`/api/sensors/${s}/current`).then(j<Current>);
export const getHistory = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/history?range=${range}`).then(j<HistoryPoint[]>);
export const getCalendar = (s: string, year: number) =>
  fetch(`/api/sensors/${s}/calendar?year=${year}`).then(j<CalendarDay[]>);
export const getHeatmap = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/heatmap?range=${range}`).then(j<HeatCell[]>);
export const getDistribution = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/distribution?range=${range}`).then(j<DistBand[]>);
export const getDiurnal = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/diurnal?range=${range}`).then(j<DiurnalHour[]>);
export const getSummary = (s: string) => fetch(`/api/sensors/${s}/summary`).then(j<Summary>);
export const getStatus = (s: string) => fetch(`/api/sensors/${s}/status`).then(j<Status>);
export const getAlerts = () => fetch("/api/alerts").then(j<AlertsView>);
export const postAlerts = (body: Record<string, unknown>, token: string) =>
  fetch("/api/alerts", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  }).then(j<AlertsView>);
export const exportUrl = (s: string, range: string, format: "csv" | "json") =>
  `/api/sensors/${s}/export?range=${range}&format=${format}`;
