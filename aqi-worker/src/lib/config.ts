// Configuration resolved from Worker environment variables. Mask thresholds come from
// a sensitivity preset (general / asthma / very_sensitive) that individual vars can
// override. All values are strings in wrangler.toml [vars]; parsed here.
import type { Env } from "../env.ts";
import { MASK_PRESETS } from "./mask.ts";

export const DEFAULT_SENSITIVITY = "asthma";

export type Thresholds = [number, number, number, number];

export interface MaskConfig {
  sensitivity: string;
  thresholds: Thresholds;
}

export interface AlertsConfig {
  enabled: boolean;
  notify_from: string;
  ntfy_url: string;
  ntfy_topic: string;
  ntfy_token: string;
  webhook_url: string;
  min_interval_s: number;
  quiet_start_hour: number;
  quiet_end_hour: number;
}

export interface DisplayConfig {
  site_title: string;
  tz_offset_hours: number;
  temp_unit: "c" | "f";
}

export interface Config {
  default_sensor: string;
  mask: MaskConfig;
  alerts: AlertsConfig;
  display: DisplayConfig;
  offset_s: number;
}

function bool(raw: string | undefined, fallback: boolean): boolean {
  if (raw === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
}

function int(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function num(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number.parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}

function maskConfig(env: Env): MaskConfig {
  let sensitivity = (env.MASK_SENSITIVITY ?? DEFAULT_SENSITIVITY).toLowerCase();
  if (!(sensitivity in MASK_PRESETS)) sensitivity = DEFAULT_SENSITIVITY;
  const [carry, recommended, strong, indoors] = MASK_PRESETS[sensitivity];
  return {
    sensitivity,
    thresholds: [
      int(env.MASK_CARRY_AQI, carry),
      int(env.MASK_RECOMMENDED_AQI, recommended),
      int(env.MASK_STRONG_AQI, strong),
      int(env.MASK_INDOORS_AQI, indoors),
    ],
  };
}

export function loadConfig(env: Env): Config {
  const unit = (env.TEMP_UNIT ?? "c").toLowerCase() === "f" ? "f" : "c";
  const tzOffsetHours = num(env.TZ_OFFSET_HOURS, 0);
  return {
    default_sensor: env.DEFAULT_SENSOR ?? "",
    mask: maskConfig(env),
    alerts: {
      enabled: bool(env.ALERTS_ENABLED, false),
      notify_from: (env.ALERTS_NOTIFY_FROM ?? "recommended").toLowerCase(),
      ntfy_url: (env.NTFY_URL ?? "").replace(/\/+$/, ""),
      ntfy_topic: env.NTFY_TOPIC ?? "",
      ntfy_token: env.NTFY_TOKEN ?? "",
      webhook_url: env.WEBHOOK_URL ?? "",
      min_interval_s: int(env.ALERTS_MIN_INTERVAL_S, 3600),
      quiet_start_hour: int(env.ALERTS_QUIET_START_HOUR, -1),
      quiet_end_hour: int(env.ALERTS_QUIET_END_HOUR, -1),
    },
    display: {
      site_title: env.SITE_TITLE ?? "Air Quality",
      tz_offset_hours: tzOffsetHours,
      temp_unit: unit,
    },
    offset_s: Math.round(tzOffsetHours * 3600),
  };
}
