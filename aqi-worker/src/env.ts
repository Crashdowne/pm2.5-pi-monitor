// Worker bindings + secrets for aqi-worker.
// DB is the D1 warehouse (raw + rollups + alert state); ASSETS serves the built SPA.
// The dashboard is public; only /ingest + /max_ts are gated, by a bearer token
// (INGEST_TOKEN, a Worker secret). Remaining vars are plain [vars] in wrangler.toml.
export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;

  // ingest auth (bearer token the Pi presents to POST /ingest and GET /max_ts)
  INGEST_TOKEN?: string;

  // display
  SITE_TITLE?: string;
  TEMP_UNIT?: string; // "c" | "f"
  TZ_OFFSET_HOURS?: string;
  DEFAULT_SENSOR?: string;

  // mask thresholds (preset + optional per-level overrides)
  MASK_SENSITIVITY?: string;
  MASK_CARRY_AQI?: string;
  MASK_RECOMMENDED_AQI?: string;
  MASK_STRONG_AQI?: string;
  MASK_INDOORS_AQI?: string;

  // alerts (evaluated by the Cron Trigger)
  ALERTS_ENABLED?: string;
  ALERTS_NOTIFY_FROM?: string;
  ALERTS_MIN_INTERVAL_S?: string;
  ALERTS_QUIET_START_HOUR?: string;
  ALERTS_QUIET_END_HOUR?: string;
  NTFY_URL?: string;
  NTFY_TOPIC?: string;
  NTFY_TOKEN?: string; // secret
  WEBHOOK_URL?: string;
}
