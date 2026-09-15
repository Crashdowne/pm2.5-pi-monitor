import { beforeEach, describe, expect, it } from "vitest";

import { handleRequest } from "../src/app.ts";
import type { Env } from "../src/env.ts";
import { createTestDB, type TestDB } from "./d1-adapter.ts";
import { seedWarehouse } from "./seed.ts";

let env: Env & { DB: TestDB };

beforeEach(async () => {
  env = { DB: createTestDB() } as unknown as Env & { DB: TestDB };
  await seedWarehouse(env.DB);
});

function req(path: string, init?: RequestInit): Promise<Response> {
  return handleRequest(new Request("https://x" + path, init), env);
}

describe("health + config", () => {
  it("reports warehouse health", async () => {
    const res = await req("/healthz");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; sensors: number };
    expect(body.ok).toBe(true);
    expect(body.sensors).toBe(3);
  });

  it("serves site config with mask presets", async () => {
    const body = (await (await req("/api/config")).json()) as any;
    expect(body.mask.sensitivity).toBe("asthma");
    expect(body.mask.presets.asthma.carry).toBe(51);
    expect(body.ranges).toContain("24h");
    expect(body.bands).toHaveLength(6);
  });
});

describe("sensors", () => {
  it("lists all seeded sensors with AQI + mask level", async () => {
    const body = (await (await req("/api/sensors")).json()) as any[];
    expect(body).toHaveLength(3);
    const smoky = body.find((s) => s.sensor_id === "smoky");
    expect(smoky.aqi).toBeGreaterThan(150);
    expect(smoky.mask_level).toBe("indoors");
    expect(smoky.online).toBe(true);
  });

  it("supports conditional requests via ETag", async () => {
    const first = await req("/api/sensors");
    const etag = first.headers.get("ETag");
    expect(etag).toBeTruthy();
    const second = await req("/api/sensors", { headers: { "If-None-Match": etag! } });
    expect(second.status).toBe(304);
  });

  it("returns the current snapshot with a mask recommendation", async () => {
    const body = (await (await req("/api/sensors/smoky/current")).json()) as any;
    expect(body.sensor_id).toBe("smoky");
    expect(body.nowcast_aqi).toBeGreaterThan(150);
    expect(body.mask.level).toBe("indoors");
    expect(body.pm2_5).not.toBeNull();
  });

  it("404s for unknown sensors and 400s for malformed ids", async () => {
    expect((await req("/api/sensors/nope/current")).status).toBe(404);
    expect((await req("/api/sensors/bad!/current")).status).toBe(400);
  });
});

describe("analytics endpoints", () => {
  it("history buckets from raw (short) and rollups (long)", async () => {
    const short = (await (await req("/api/sensors/backyard/history?range=24h")).json()) as any[];
    expect(short.length).toBeGreaterThan(0);
    expect(short[0]).toHaveProperty("t");
    expect(short[0]).toHaveProperty("aqi");
    const long = (await (await req("/api/sensors/backyard/history?range=7d")).json()) as any[];
    expect(long.length).toBeGreaterThan(0);
  });

  it("rejects an invalid range", async () => {
    expect((await req("/api/sensors/backyard/history?range=bogus")).status).toBe(400);
  });

  it("calendar returns daily AQI from the daily rollup", async () => {
    const year = new Date().getUTCFullYear();
    const body = (await (await req(`/api/sensors/backyard/calendar?year=${year}`)).json()) as any[];
    expect(Array.isArray(body)).toBe(true);
    if (body.length) expect(body[0]).toHaveProperty("date");
  });

  it("heatmap returns [hour, dow, aqi] cells", async () => {
    const body = (await (await req("/api/sensors/backyard/heatmap?range=7d")).json()) as number[][];
    expect(body.length).toBeGreaterThan(0);
    expect(body[0]).toHaveLength(3);
  });

  it("distribution returns six bands", async () => {
    const body = (await (await req("/api/sensors/backyard/distribution?range=7d")).json()) as any[];
    expect(body).toHaveLength(6);
  });

  it("diurnal returns 24 hours", async () => {
    const body = (await (await req("/api/sensors/backyard/diurnal?range=7d")).json()) as any[];
    expect(body).toHaveLength(24);
  });

  it("summary returns per-period stats", async () => {
    const body = (await (await req("/api/sensors/backyard/summary")).json()) as any;
    expect(body.by_period).toHaveLength(3);
    expect(body).toHaveProperty("aqi_24h");
  });

  it("status reflects GY-SHT31 presence", async () => {
    const withEnv = (await (await req("/api/sensors/backyard/status")).json()) as any;
    expect(withEnv.sht31.ok).toBe(true);
    const noEnv = (await (await req("/api/sensors/rooftop/status")).json()) as any;
    expect(noEnv.sht31.ok).toBe(false);
  });

  it("mask endpoint returns the recommendation", async () => {
    const body = (await (await req("/api/sensors/smoky/mask")).json()) as any;
    expect(body.mask.level).toBe("indoors");
    expect(body.aqi).toBeGreaterThan(150);
  });
});

describe("export", () => {
  it("exports CSV with a header row", async () => {
    const res = await req("/api/sensors/backyard/export?range=24h&format=csv");
    expect(res.headers.get("content-type")).toContain("text/csv");
    const body = await res.text();
    expect(body.split("\r\n")[0]).toBe("ts,iso_utc,pm2_5,pm10,temp,rh,aqi");
  });

  it("exports JSON", async () => {
    const body = (await (await req("/api/sensors/backyard/export?range=24h&format=json")).json()) as any[];
    expect(Array.isArray(body)).toBe(true);
  });
});
