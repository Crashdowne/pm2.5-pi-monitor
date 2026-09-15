// Ingest handlers — the Pi-facing write path. Mirrors the server/ingest.py contract
// (NDJSON body, optional gzip, {received, max_ts} ack, GET /max_ts) so the Pi's
// pm25.sync repoints with only a URL + auth-header change.
import { authenticateIngest, type AuthResult } from "./auth.ts";
import type { Env } from "./env.ts";
import { buildRawUpserts, buildRollupUpserts, type RawRow } from "./lib/ingest.ts";
import { MAX_BODY, MAX_INGEST_ROWS, validateRecord, validateSensorId, type CleanRecord } from "./validate.ts";

export interface IngestDeps {
  authenticate: (request: Request, env: Env) => Promise<AuthResult>;
  now: () => number;
}

const defaultDeps: IngestDeps = {
  authenticate: authenticateIngest,
  now: () => Math.floor(Date.now() / 1000),
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Read the request body, decompressing gzip, enforcing MAX_BODY. Returns null on
// oversize/undecodable input (caller responds 413).
async function readBody(request: Request): Promise<string | null> {
  const buf = await request.arrayBuffer();
  if (buf.byteLength > MAX_BODY) return null;
  const enc = (request.headers.get("content-encoding") ?? "").toLowerCase();
  if (enc !== "gzip") return new TextDecoder().decode(buf);
  try {
    const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
    const text = await new Response(stream).text();
    return text.length > MAX_BODY ? null : text;
  } catch {
    return null;
  }
}

export async function handleIngest(
  request: Request,
  env: Env,
  deps: IngestDeps = defaultDeps,
): Promise<Response> {
  const auth = await deps.authenticate(request, env);
  if (!auth.ok) return json({ error: auth.message ?? "unauthorized" }, auth.status ?? 401);

  const sensorId = request.headers.get("X-PM25-Sensor-ID") ?? "default";
  if (!validateSensorId(sensorId)) return json({ error: "invalid sensor id" }, 400);

  const body = await readBody(request);
  if (body === null) return json({ error: "body too large or undecodable" }, 413);

  const now = deps.now();
  const rows: CleanRecord[] = [];
  for (const line of body.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      return json({ error: "invalid json" }, 400);
    }
    const clean = validateRecord(parsed, now);
    if (clean === null) return json({ error: "invalid record" }, 400);
    rows.push(clean);
  }
  if (rows.length === 0) return json({ error: "empty batch" }, 400);
  if (rows.length > MAX_INGEST_ROWS) {
    return json(
      { error: `batch too large (${rows.length} > ${MAX_INGEST_ROWS}); lower sync.batch_size` },
      413,
    );
  }

  let samplePeriod = 180;
  const rawPeriod = request.headers.get("X-PM25-Sample-Period");
  if (rawPeriod != null) {
    const p = Number(rawPeriod);
    if (!Number.isInteger(p)) return json({ error: "invalid sample period" }, 400);
    samplePeriod = Math.max(1, Math.min(3600, p));
  }

  let maxTs = rows[0].ts;
  let minTs = rows[0].ts;
  for (const r of rows) {
    if (r.ts > maxTs) maxTs = r.ts;
    if (r.ts < minTs) minTs = r.ts;
  }

  const stmts = [
    ...buildRawUpserts(sensorId, rows as RawRow[]),
    ...buildRollupUpserts(sensorId, minTs, maxTs),
    {
      sql:
        "INSERT INTO devices (sensor_id, sample_period_s, last_ingest_ts, last_reading_ts) VALUES (?,?,?,?) " +
        "ON CONFLICT(sensor_id) DO UPDATE SET sample_period_s=excluded.sample_period_s, " +
        "last_ingest_ts=excluded.last_ingest_ts, last_reading_ts=max(devices.last_reading_ts, excluded.last_reading_ts)",
      params: [sensorId, samplePeriod, now, maxTs] as (string | number | null)[],
    },
  ];

  await env.DB.batch(stmts.map((s) => env.DB.prepare(s.sql).bind(...s.params)));

  return json({ received: rows.length, max_ts: maxTs });
}

export async function handleMaxTs(
  request: Request,
  env: Env,
  deps: IngestDeps = defaultDeps,
): Promise<Response> {
  const auth = await deps.authenticate(request, env);
  if (!auth.ok) return json({ error: auth.message ?? "unauthorized" }, auth.status ?? 401);

  const sensorId = request.headers.get("X-PM25-Sensor-ID") ?? "default";
  if (!validateSensorId(sensorId)) return json({ error: "invalid sensor id" }, 400);

  const row = await env.DB.prepare("SELECT max(ts) AS m FROM readings_raw WHERE sensor_id=?")
    .bind(sensorId)
    .first<{ m: number | null }>();
  return json({ max_ts: row?.m ?? 0 });
}
