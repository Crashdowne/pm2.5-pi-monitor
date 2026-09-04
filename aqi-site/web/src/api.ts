// Typed client for the read-only aqi-site API.

export interface Band { upper: number; label: string; color: string; }

export interface LevelMeta {
  level: string; severity: number; label: string; action: string; color: string; mask_type: string;
}

export interface SiteConfig {
  site_title: string;
  temp_unit: "c" | "f";
  tz_offset_hours: number;
  ranges: string[];
  bands: Band[];
  mask: {
    sensitivity: string;
    thresholds: { carry: number; recommended: number; strong: number; indoors: number };
    presets: Record<string, { carry: number; recommended: number; strong: number; indoors: number }>;
    levels: LevelMeta[];
    disclaimer: string;
  };
}

export interface MaskReco extends LevelMeta {
  aqi: number | null; dominant: string | null; trend: string | null; disclaimer: string;
}

export interface Current {
  sensor_id: string; ts: number; age_s: number;
  pm2_5: number | null; pm2_5_raw: number | null; pm10: number | null;
  rh: number | null; temp: number | null;
  nowcast_aqi: number; category: string; color: string; dominant: string;
  trend: string; mask: MaskReco; good_window: { hour: number; aqi: number } | null;
}

export interface SensorRow {
  sensor_id: string; ts: number; age_s: number; pm2_5: number | null; pm10: number | null;
  rh: number | null; temp: number | null; aqi: number; category: string; color: string;
  mask_level: string; coverage_24h: number;
}

export interface HistoryPoint {
  t: number; pm2_5: number | null; pm10: number | null; temp: number | null; rh: number | null; aqi: number;
}

export interface CalendarDay { date: string; aqi: number; pm2_5: number | null; }
export type HeatCell = [number, number, number]; // hour, weekday, aqi
export interface DistBand { band: number; label: string; color: string; hours: number; pct: number; }
export interface DiurnalHour { hour: number; avg: number | null; min: number | null; max: number | null; aqi: number | null; }

export interface Summary {
  pm25_24h: number | null; aqi_24h: number | null; cigarettes_24h: number | null;
  pm25_7d: number | null; aqi_7d: number | null; cigarettes_7d: number | null;
  pm25_30d: number | null; aqi_30d: number | null; cigarettes_30d: number | null;
  peak_aqi_7d: number | null; exceedance_hours_30d: number;
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
export const getHistory = (s: string, range: string, bucket?: number) =>
  fetch(`/api/sensors/${s}/history?range=${range}${bucket ? `&bucket=${bucket}` : ""}`).then(j<HistoryPoint[]>);
export const getCalendar = (s: string, year: number) =>
  fetch(`/api/sensors/${s}/calendar?year=${year}`).then(j<CalendarDay[]>);
export const getHeatmap = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/heatmap?range=${range}`).then(j<HeatCell[]>);
export const getDistribution = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/distribution?range=${range}`).then(j<DistBand[]>);
export const getDiurnal = (s: string, range: string) =>
  fetch(`/api/sensors/${s}/diurnal?range=${range}`).then(j<DiurnalHour[]>);
export const getSummary = (s: string) => fetch(`/api/sensors/${s}/summary`).then(j<Summary>);
export const getAlerts = () => fetch("/api/alerts").then(j<AlertsView>);
export const postAlerts = (body: Record<string, unknown>) =>
  fetch("/api/alerts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(j<AlertsView>);
export const exportUrl = (s: string, range: string, format: "csv" | "json") =>
  `/api/sensors/${s}/export?range=${range}&format=${format}`;
