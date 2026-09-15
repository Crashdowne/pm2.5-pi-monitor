import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { handleRequest } from "../src/app.ts";
import type { Env } from "../src/env.ts";
import { effectiveAlerts, inQuietHours, pollOnce, shouldFire } from "../src/lib/alerts.ts";
import { loadConfig } from "../src/lib/config.ts";
import { createTestDB, type TestDB } from "./d1-adapter.ts";
import { seedWarehouse } from "./seed.ts";

let db: TestDB;

const alertEnv = () =>
  ({
    DB: db,
    ALERTS_ENABLED: "true",
    ALERTS_NOTIFY_FROM: "recommended",
    WEBHOOK_URL: "https://example.test/hook",
  }) as unknown as Env;

const plainEnv = () => ({ DB: db }) as unknown as Env;

beforeEach(async () => {
  db = createTestDB();
  await seedWarehouse(db);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pollOnce", () => {
  it("fires a webhook for the wildfire-high sensor and records state", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const env = alertEnv();
    const events = await pollOnce(env, loadConfig(env));
    const smoky = events.find((e) => e.sensor_id === "smoky");
    expect(smoky).toBeDefined();
    expect(smoky!.level).toBe("indoors");
    expect(smoky!.sent).toBe(true);
    expect(fetchMock).toHaveBeenCalled();

    const view = (await (await handleRequest(new Request("https://x/api/alerts"), env)).json()) as any;
    const stateRow = view.sensors.find((s: any) => s.sensor_id === "smoky");
    expect(stateRow.last_level).toBe("indoors");
  });

  it("does nothing when alerts are disabled", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = plainEnv(); // ALERTS_ENABLED unset -> false
    const events = await pollOnce(env, loadConfig(env));
    expect(events).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("alerts config API", () => {
  it("persists overrides and reflects them", async () => {
    const env = plainEnv();
    const res = await handleRequest(
      new Request("https://x/api/alerts", {
        method: "POST",
        body: JSON.stringify({ enabled: true, notify_from: "strong", min_interval_s: 1800 }),
        headers: { "content-type": "application/json" },
      }),
      env,
    );
    const body = (await res.json()) as any;
    expect(body.enabled).toBe(true);
    expect(body.notify_from).toBe("strong");
    expect(body.min_interval_s).toBe(1800);

    const again = (await (await handleRequest(new Request("https://x/api/alerts"), env)).json()) as any;
    expect(again.notify_from).toBe("strong");
  });

  it("rejects an invalid notify_from level", async () => {
    const res = await handleRequest(
      new Request("https://x/api/alerts", {
        method: "POST",
        body: JSON.stringify({ notify_from: "bogus" }),
        headers: { "content-type": "application/json" },
      }),
      plainEnv(),
    );
    expect(res.status).toBe(400);
  });
});

describe("alert helpers", () => {
  const base = loadConfig(alertEnv()).alerts;

  it("honours quiet hours across midnight", () => {
    const cfg = { ...base, quiet_start_hour: 22, quiet_end_hour: 7 };
    expect(inQuietHours(23 * 3600, cfg)).toBe(true);
    expect(inQuietHours(12 * 3600, cfg)).toBe(false);
  });

  it("fires on escalation and debounces repeats", () => {
    expect(shouldFire("none", "strong", base, 0, 10_000)[0]).toBe(true);
    expect(shouldFire("strong", "strong", base, 9_000, 10_000)[0]).toBe(false);
  });

  it("merges overrides onto the base config", () => {
    const merged = effectiveAlerts(base, { enabled: false });
    expect(merged.enabled).toBe(false);
    expect(merged.notify_from).toBe(base.notify_from);
  });
});
