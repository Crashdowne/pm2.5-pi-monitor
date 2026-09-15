// HTTP router: read-only JSON API, the ingest routes, and the static SPA fallback.
// Zero runtime dependencies (no framework) to match the project's minimalist setup.
// Read routes bucket from D1 on demand and mirror the shapes the React dashboard expects.
import * as alerts from "./lib/alerts.ts";
import * as analytics from "./lib/analytics.ts";
import { authenticateAdmin } from "./auth.ts";
import { loadConfig, type AlertsConfig } from "./lib/config.ts";
import * as db from "./lib/db.ts";
import type { Env } from "./env.ts";
import { handleIngest, handleMaxTs } from "./ingest.ts";
import { MASK_PRESETS } from "./lib/mask.ts";
import * as mask from "./lib/mask.ts";
import { validateSensorId } from "./validate.ts";

function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function text(body: string, status: number): Response {
  return new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

async function resolveSensor(d: D1Database, id: string): Promise<string | null> {
  const sensors = await db.distinctSensors(d);
  if (sensors.length === 0) return null;
  return sensors.includes(id) ? id : null;
}

function alertsView(
  cfg: AlertsConfig,
  sensorRows: { sensor_id: string; last_level: string; last_fired_ts: number }[],
) {
  return {
    enabled: cfg.enabled,
    notify_from: cfg.notify_from,
    min_interval_s: cfg.min_interval_s,
    quiet_start_hour: cfg.quiet_start_hour,
    quiet_end_hour: cfg.quiet_end_hour,
    ntfy_configured: Boolean(cfg.ntfy_url && cfg.ntfy_topic),
    webhook_configured: Boolean(cfg.webhook_url),
    levels: [...mask.LEVELS],
    sensors: sensorRows.map((r) => ({
      sensor_id: r.sensor_id,
      last_level: r.last_level,
      last_fired_ts: r.last_fired_ts,
    })),
  };
}

async function alertSensorRows(d: D1Database) {
  const res = await d
    .prepare("SELECT sensor_id, last_level, last_fired_ts FROM alert_state ORDER BY sensor_id")
    .all<{ sensor_id: string; last_level: string; last_fired_ts: number }>();
  return res.results;
}

async function sensorRoute(action: string, id: string, url: URL, env: Env): Promise<Response> {
  if (!validateSensorId(id)) return text("invalid sensor id", 400);
  const config = loadConfig(env);
  const rangeKey = url.searchParams.get("range") ?? "24h";
  const validRange = rangeKey in analytics.RANGES;

  const sid = await resolveSensor(env.DB, id);
  if (sid === null) return text("unknown sensor", 404);

  switch (action) {
    case "current": {
      const data = await analytics.current(env.DB, sid, config.mask, config.offset_s);
      return data === null ? text("no readings", 404) : json(data);
    }
    case "history": {
      if (!validRange) return text("invalid range", 400);
      const bucketRaw = url.searchParams.get("bucket");
      const bucket = bucketRaw !== null ? Number.parseInt(bucketRaw, 10) : null;
      return json(await analytics.history(env.DB, sid, rangeKey, bucket));
    }
    case "calendar": {
      const yearRaw = url.searchParams.get("year");
      const year = yearRaw !== null ? Number.parseInt(yearRaw, 10) : new Date().getUTCFullYear();
      if (!Number.isFinite(year) || year < 1970 || year > 3000) return text("invalid year", 400);
      return json(await analytics.calendar(env.DB, sid, year, config.offset_s));
    }
    case "heatmap":
      if (!validRange) return text("invalid range", 400);
      return json(await analytics.heatmap(env.DB, sid, rangeKey, config.offset_s));
    case "distribution":
      if (!validRange) return text("invalid range", 400);
      return json(await analytics.distribution(env.DB, sid, rangeKey));
    case "diurnal":
      if (!validRange) return text("invalid range", 400);
      return json(await analytics.diurnal(env.DB, sid, rangeKey, config.offset_s));
    case "summary":
      return json(await analytics.summary(env.DB, sid));
    case "status": {
      const data = await analytics.status(env.DB, sid);
      return data === null ? text("no device", 404) : json(data);
    }
    case "mask": {
      const data = await analytics.current(env.DB, sid, config.mask, config.offset_s);
      if (data === null) return text("no readings", 404);
      return json({
        sensor_id: sid,
        aqi: data.nowcast_aqi,
        mask: data.mask,
        trend: data.trend,
        good_window: data.good_window,
      });
    }
    case "export": {
      if (!validRange) return text("invalid range", 400);
      const fmt = url.searchParams.get("format") ?? "csv";
      if (fmt !== "csv" && fmt !== "json") return text("invalid format", 400);
      const rows = await analytics.exportRows(env.DB, sid, rangeKey);
      if (fmt === "json") return json(rows);
      const cell = (v: number | null) => (v === null || v === undefined ? "" : String(v));
      const lines = ["ts,iso_utc,pm2_5,pm10,temp,rh,aqi"];
      for (const r of rows) {
        const iso = new Date(r.t * 1000).toISOString().slice(0, 19) + "Z";
        lines.push([r.t, iso, cell(r.pm2_5), cell(r.pm10), cell(r.temp), cell(r.rh), r.aqi].join(","));
      }
      return new Response(lines.join("\r\n") + "\r\n", {
        headers: {
          "content-type": "text/csv",
          "content-disposition": `attachment; filename="${sid}-${rangeKey}.csv"`,
        },
      });
    }
    default:
      return text("not found", 404);
  }
}

export async function handleRequest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  // --- ingest (bearer-auth via handler default deps) ---
  if (path === "/ingest" && method === "POST") return handleIngest(request, env);
  if (path === "/max_ts" && method === "GET") return handleMaxTs(request, env);

  // --- health ---
  if (path === "/healthz" && method === "GET") {
    try {
      const sensors = await db.distinctSensors(env.DB);
      let latest = 0;
      for (const sensorId of sensors) {
        const row = await db.latestReading(env.DB, sensorId);
        if (row) latest = Math.max(latest, row.ts);
      }
      const age = latest ? Math.max(0, Math.floor(Date.now() / 1000) - latest) : null;
      return json({ ok: true, sensors: sensors.length, last_reading_age_s: age });
    } catch {
      return json({ ok: false, error: "warehouse unavailable" }, 503);
    }
  }

  if (method === "GET" && path === "/api/config") {
    const config = loadConfig(env);
    const [carry, recommended, strong, indoors] = config.mask.thresholds;
    const presets: Record<string, Record<string, number>> = {};
    for (const [name, v] of Object.entries(MASK_PRESETS)) {
      presets[name] = { carry: v[0], recommended: v[1], strong: v[2], indoors: v[3] };
    }
    return json({
      site_title: config.display.site_title,
      temp_unit: config.display.temp_unit,
      tz_offset_hours: config.display.tz_offset_hours,
      ranges: Object.keys(analytics.RANGES),
      bands: analytics.BANDS.map(([upper, label, color]) => ({ upper, label, color })),
      mask: {
        sensitivity: config.mask.sensitivity,
        thresholds: { carry, recommended, strong, indoors },
        presets,
        levels: mask.allLevels(),
        disclaimer: mask.DISCLAIMER,
      },
    });
  }

  if (method === "GET" && path === "/api/sensors") {
    const config = loadConfig(env);
    const data = await analytics.sensorsOverview(env.DB, config.mask, config.offset_s);
    const maxTs = data.reduce((m, s) => Math.max(m, s.ts), 0);
    const etag = `"${maxTs}-${data.length}"`;
    if (request.headers.get("If-None-Match") === etag) return new Response(null, { status: 304 });
    return json(data, 200, { ETag: etag });
  }

  const sensorMatch = path.match(/^\/api\/sensors\/([^/]+)\/([a-z]+)$/);
  if (sensorMatch && method === "GET") {
    return sensorRoute(sensorMatch[2], decodeURIComponent(sensorMatch[1]), url, env);
  }

  if (path === "/api/alerts") {
    const config = loadConfig(env);
    if (method === "GET") {
      const cfg = alerts.effectiveAlerts(config.alerts, await alerts.loadOverrides(env.DB));
      return json(alertsView(cfg, await alertSensorRows(env.DB)));
    }
    if (method === "POST") {
      const auth = await authenticateAdmin(request, env);
      if (!auth.ok) return text(auth.message ?? "unauthorized", auth.status ?? 401);
      let body: unknown;
      try {
        body = await request.json();
      } catch {
        return text("expected a JSON object", 400);
      }
      if (typeof body !== "object" || body === null || Array.isArray(body)) {
        return text("expected a JSON object", 400);
      }
      const obj = body as Record<string, unknown>;
      const invalid = alerts.validateOverrides(obj);
      if (invalid) return text(invalid, 400);
      await alerts.saveOverrides(env.DB, obj);
      const cfg = alerts.effectiveAlerts(config.alerts, await alerts.loadOverrides(env.DB));
      return json(alertsView(cfg, await alertSensorRows(env.DB)));
    }
  }

  // Everything else: the built SPA (index.html for client routes via SPA fallback).
  return env.ASSETS.fetch(request);
}
