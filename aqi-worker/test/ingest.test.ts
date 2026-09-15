import { gzipSync } from "node:zlib";

import { describe, expect, it } from "vitest";

import type { Env } from "../src/env.ts";
import { handleIngest, handleMaxTs, type IngestDeps } from "../src/ingest.ts";
import { createTestDB, type TestDB } from "./d1-adapter.ts";

const NOW = 1_800_000_000; // on an exact hour + day boundary, so ts=NOW-x share a bucket
const okDeps: IngestDeps = { authenticate: async () => ({ ok: true }), now: () => NOW };

function makeEnv(): Env & { DB: TestDB } {
  return { DB: createTestDB() } as unknown as Env & { DB: TestDB };
}

function ndjson(rows: object[]): string {
  return rows.map((r) => JSON.stringify(r)).join("\n");
}

function req(body: BodyInit, headers: Record<string, string> = {}): Request {
  return new Request("https://x/ingest", {
    method: "POST",
    body,
    headers: { "content-type": "application/x-ndjson", "x-pm25-sensor-id": "sensor-a", ...headers },
  });
}

const R = (ts: number, pm2_5: number, extra: Record<string, number> = {}) => ({
  ts,
  pm2_5,
  pm10: pm2_5 * 2,
  ...extra,
});

function maxTsReq(): Request {
  return new Request("https://x/max_ts", { headers: { "x-pm25-sensor-id": "sensor-a" } });
}

describe("handleIngest", () => {
  it("ingests NDJSON, acks, and writes raw + rollups + device", async () => {
    const env = makeEnv();
    const rows = [
      R(NOW - 1000, 10, { pm2_5_corr: 9 }),
      R(NOW - 500, 20, { pm2_5_corr: 19 }),
      R(NOW - 100, 30, { pm2_5_corr: 29 }),
    ];
    const res = await handleIngest(req(ndjson(rows), { "x-pm25-sample-period": "180" }), env, okDeps);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ received: 3, max_ts: NOW - 100 });

    const db = env.DB._db;
    expect((db.prepare("select count(*) c from readings_raw").get() as { c: number }).c).toBe(3);

    const h = db.prepare("select pm2_5, pm2_5_corr, samples from readings_hourly").all() as {
      pm2_5: number;
      pm2_5_corr: number;
      samples: number;
    }[];
    expect(h.length).toBe(1);
    expect(h[0].pm2_5).toBeCloseTo(20, 6); // (10+20+30)/3
    expect(h[0].pm2_5_corr).toBeCloseTo(19, 6); // (9+19+29)/3
    expect(h[0].samples).toBe(3);

    const dev = db
      .prepare("select sample_period_s, last_reading_ts from devices where sensor_id='sensor-a'")
      .get() as { sample_period_s: number; last_reading_ts: number };
    expect(dev.sample_period_s).toBe(180);
    expect(dev.last_reading_ts).toBe(NOW - 100);
  });

  it("is idempotent on re-ingest (upsert + rollup recompute)", async () => {
    const env = makeEnv();
    const rows = [R(NOW - 1000, 10), R(NOW - 500, 20), R(NOW - 100, 30)];
    await handleIngest(req(ndjson(rows)), env, okDeps);
    await handleIngest(req(ndjson(rows)), env, okDeps);
    const db = env.DB._db;
    expect((db.prepare("select count(*) c from readings_raw").get() as { c: number }).c).toBe(3);
    expect((db.prepare("select samples from readings_hourly").get() as { samples: number }).samples).toBe(3);
  });

  it("recomputes rollups across multiple hours", async () => {
    const env = makeEnv();
    await handleIngest(req(ndjson([R(NOW - 4000, 10), R(NOW - 100, 30)])), env, okDeps);
    const db = env.DB._db;
    expect((db.prepare("select count(*) c from readings_hourly").get() as { c: number }).c).toBe(2);
  });

  it("accepts gzip bodies", async () => {
    const env = makeEnv();
    const gz = new Uint8Array(gzipSync(Buffer.from(ndjson([R(NOW - 100, 42)]))));
    const res = await handleIngest(req(gz, { "content-encoding": "gzip" }), env, okDeps);
    expect(res.status).toBe(200);
    expect((env.DB._db.prepare("select pm2_5 from readings_raw").get() as { pm2_5: number }).pm2_5).toBe(42);
  });

  it("rejects an invalid record and writes nothing", async () => {
    const env = makeEnv();
    const res = await handleIngest(req(ndjson([R(NOW - 100, 10), R(NOW - 50, 99999)])), env, okDeps);
    expect(res.status).toBe(400);
    expect((env.DB._db.prepare("select count(*) c from readings_raw").get() as { c: number }).c).toBe(0);
  });

  it("returns the auth failure status and writes nothing", async () => {
    const env = makeEnv();
    const denied: IngestDeps = {
      authenticate: async () => ({ ok: false, status: 401, message: "denied" }),
      now: () => NOW,
    };
    const res = await handleIngest(req(ndjson([R(NOW - 100, 10)])), env, denied);
    expect(res.status).toBe(401);
    expect((env.DB._db.prepare("select count(*) c from readings_raw").get() as { c: number }).c).toBe(0);
  });

  it("rejects an invalid sensor id", async () => {
    const env = makeEnv();
    const res = await handleIngest(req(ndjson([R(NOW - 100, 10)]), { "x-pm25-sensor-id": "bad id" }), env, okDeps);
    expect(res.status).toBe(400);
  });

  it("rejects an oversized batch (free-tier query cap) and writes nothing", async () => {
    const env = makeEnv();
    const rows = Array.from({ length: 330 }, (_, i) => R(NOW - i, 10));
    const res = await handleIngest(req(ndjson(rows)), env, okDeps);
    expect(res.status).toBe(413);
    expect((env.DB._db.prepare("select count(*) c from readings_raw").get() as { c: number }).c).toBe(0);
  });
});

describe("handleMaxTs", () => {
  it("returns 0 for an unknown sensor and the batch max after ingest", async () => {
    const env = makeEnv();
    const empty = await handleMaxTs(maxTsReq(), env, okDeps);
    expect(await empty.json()).toEqual({ max_ts: 0 });

    await handleIngest(req(ndjson([R(NOW - 500, 10), R(NOW - 100, 20)])), env, okDeps);
    const after = await handleMaxTs(maxTsReq(), env, okDeps);
    expect(await after.json()).toEqual({ max_ts: NOW - 100 });
  });
});
