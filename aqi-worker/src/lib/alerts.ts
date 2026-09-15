// Alerting: evaluate the mask level per sensor and push to ntfy / a webhook. Runs from
// the Worker's Cron Trigger. Alert state (last level, last-fired) and runtime overrides
// live in D1. Firing uses hysteresis + quiet hours + a min interval so it won't spam.
import * as analytics from "./analytics.ts";
import type { AlertsConfig, Config } from "./config.ts";
import * as db from "./db.ts";
import type { Env } from "../env.ts";
import * as mask from "./mask.ts";

const OVERRIDE_KEYS = [
  "enabled",
  "notify_from",
  "min_interval_s",
  "quiet_start_hour",
  "quiet_end_hour",
] as const;

const PRIORITY: Record<string, string> = {
  indoors: "urgent",
  strong: "high",
  recommended: "default",
};
const TAGS: Record<string, string> = {
  indoors: "no_entry",
  strong: "rotating_light",
  recommended: "mask",
};

export async function getState(d: D1Database, sensorId: string): Promise<[string, number]> {
  const row = await d
    .prepare("SELECT last_level, last_fired_ts FROM alert_state WHERE sensor_id=?")
    .bind(sensorId)
    .first<{ last_level: string; last_fired_ts: number }>();
  if (row === null) return ["none", 0];
  return [row.last_level, row.last_fired_ts];
}

export async function setState(
  d: D1Database,
  sensorId: string,
  level: string,
  firedTs: number,
): Promise<void> {
  await d
    .prepare(
      "INSERT INTO alert_state (sensor_id, last_level, last_fired_ts) VALUES (?, ?, ?) " +
        "ON CONFLICT(sensor_id) DO UPDATE SET last_level=excluded.last_level, " +
        "last_fired_ts=excluded.last_fired_ts",
    )
    .bind(sensorId, level, firedTs)
    .run();
}

export async function loadOverrides(d: D1Database): Promise<Record<string, unknown>> {
  const row = await d
    .prepare("SELECT data FROM alert_overrides WHERE id=1")
    .first<{ data: string }>();
  if (row === null) return {};
  let data: unknown;
  try {
    data = JSON.parse(row.data);
  } catch {
    return {};
  }
  if (typeof data !== "object" || data === null) return {};
  const out: Record<string, unknown> = {};
  for (const k of OVERRIDE_KEYS) {
    if (k in (data as Record<string, unknown>)) out[k] = (data as Record<string, unknown>)[k];
  }
  return out;
}

export async function saveOverrides(
  d: D1Database,
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const clean: Record<string, unknown> = {};
  for (const k of OVERRIDE_KEYS) {
    if (k in data) clean[k] = data[k];
  }
  await d
    .prepare(
      "INSERT INTO alert_overrides (id, data) VALUES (1, ?) " +
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
    )
    .bind(JSON.stringify(clean))
    .run();
  return clean;
}

export function effectiveAlerts(
  base: AlertsConfig,
  overrides: Record<string, unknown>,
): AlertsConfig {
  if (Object.keys(overrides).length === 0) return base;
  const asInt = (v: unknown, fallback: number) =>
    typeof v === "number" ? Math.trunc(v) : fallback;
  return {
    ...base,
    enabled: "enabled" in overrides ? Boolean(overrides.enabled) : base.enabled,
    notify_from:
      "notify_from" in overrides ? String(overrides.notify_from).toLowerCase() : base.notify_from,
    min_interval_s: asInt(overrides.min_interval_s, base.min_interval_s),
    quiet_start_hour: asInt(overrides.quiet_start_hour, base.quiet_start_hour),
    quiet_end_hour: asInt(overrides.quiet_end_hour, base.quiet_end_hour),
  };
}

export function inQuietHours(nowTs: number, cfg: AlertsConfig, offset = 0): boolean {
  if (cfg.quiet_start_hour < 0 || cfg.quiet_end_hour < 0) return false;
  const hour = Math.floor((nowTs + offset) / 3600) % 24;
  const start = cfg.quiet_start_hour;
  const end = cfg.quiet_end_hour;
  if (start === end) return false;
  if (start < end) return start <= hour && hour < end;
  return hour >= start || hour < end;
}

export function shouldFire(
  prevLevel: string,
  newLevel: string,
  cfg: AlertsConfig,
  lastFiredTs: number,
  nowTs: number,
): [boolean, string] {
  if (mask.severity(newLevel) < mask.severity(cfg.notify_from)) return [false, "below-threshold"];
  if (mask.severity(newLevel) > mask.severity(prevLevel)) return [true, "escalated"];
  if (nowTs - lastFiredTs >= cfg.min_interval_s) return [true, "reminder"];
  return [false, "debounced"];
}

export async function sendNtfy(
  cfg: AlertsConfig,
  title: string,
  message: string,
  level: string,
): Promise<boolean> {
  if (!cfg.ntfy_url || !cfg.ntfy_topic) return false;
  const headers: Record<string, string> = {
    Title: title,
    Priority: PRIORITY[level] ?? "default",
    Tags: TAGS[level] ?? "mask",
  };
  if (cfg.ntfy_token) headers.Authorization = `Bearer ${cfg.ntfy_token}`;
  try {
    const resp = await fetch(`${cfg.ntfy_url}/${cfg.ntfy_topic}`, {
      method: "POST",
      body: message,
      headers,
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function sendWebhook(
  cfg: AlertsConfig,
  payload: Record<string, unknown>,
): Promise<boolean> {
  if (!cfg.webhook_url) return false;
  try {
    const resp = await fetch(cfg.webhook_url, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "content-type": "application/json" },
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function notify(
  cfg: AlertsConfig,
  sensorId: string,
  snapshot: analytics.Current,
): Promise<boolean> {
  const reco = snapshot.mask;
  const aqiValue = snapshot.nowcast_aqi;
  const title = `${reco.label} — AQI ${aqiValue}`;
  const message = `[${sensorId}] ${reco.action} (dominant ${snapshot.dominant}).`;
  const payload = {
    sensor_id: sensorId,
    aqi: aqiValue,
    level: reco.level,
    label: reco.label,
    action: reco.action,
    ts: snapshot.ts,
  };
  const sentNtfy = await sendNtfy(cfg, title, message, reco.level);
  const sentWebhook = await sendWebhook(cfg, payload);
  return sentNtfy || sentWebhook;
}

export interface AlertEvent {
  sensor_id: string;
  level: string;
  prev_level: string;
  reason: string;
  sent: boolean;
}

/** Evaluate every sensor once and fire alerts as needed. Returns per-sensor events. */
export async function pollOnce(env: Env, config: Config): Promise<AlertEvent[]> {
  const cfg = effectiveAlerts(config.alerts, await loadOverrides(env.DB));
  if (!cfg.enabled) return [];
  const offset = config.offset_s;
  const nowTs = Math.floor(Date.now() / 1000);
  const events: AlertEvent[] = [];
  for (const sensorId of await db.distinctSensors(env.DB)) {
    const snapshot = await analytics.current(env.DB, sensorId, config.mask, offset);
    if (snapshot === null) continue;
    const level = snapshot.mask.level;
    const [prevLevel, lastFired] = await getState(env.DB, sensorId);
    const [fire, reason] = shouldFire(prevLevel, level, cfg, lastFired, nowTs);
    const quiet = inQuietHours(nowTs, cfg, offset);
    let sent = false;
    if (fire && !quiet) sent = await notify(cfg, sensorId, snapshot);
    await setState(env.DB, sensorId, level, sent ? nowTs : lastFired);
    if (fire || level !== prevLevel) {
      events.push({
        sensor_id: sensorId,
        level,
        prev_level: prevLevel,
        reason: fire && quiet ? "quiet" : reason,
        sent,
      });
    }
  }
  return events;
}
