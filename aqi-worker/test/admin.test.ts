import { beforeEach, describe, expect, it } from "vitest";

import { handleRequest } from "../src/app.ts";
import type { Env } from "../src/env.ts";
import { createTestDB, type TestDB } from "./d1-adapter.ts";
import { seedWarehouse } from "./seed.ts";

const ADMIN = "s3cret-admin";
let db: TestDB;

beforeEach(async () => {
  db = createTestDB();
  await seedWarehouse(db);
});

const adminEnv = () => ({ DB: db, ADMIN_TOKEN: ADMIN }) as unknown as Env;
const noAdminEnv = () => ({ DB: db }) as unknown as Env;

function post(env: Env, body: unknown, token?: string): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  return handleRequest(
    new Request("https://x/api/alerts", { method: "POST", body: JSON.stringify(body), headers }),
    env,
  );
}

describe("POST /api/alerts admin gate", () => {
  it("returns 503 when ADMIN_TOKEN is not configured (writes disabled)", async () => {
    expect((await post(noAdminEnv(), { enabled: false }, ADMIN)).status).toBe(503);
  });

  it("returns 401 without a token", async () => {
    expect((await post(adminEnv(), { enabled: false })).status).toBe(401);
  });

  it("returns 401 with a wrong token", async () => {
    expect((await post(adminEnv(), { enabled: false }, "nope")).status).toBe(401);
  });

  it("accepts and persists with the correct token", async () => {
    const res = await post(adminEnv(), { enabled: true, notify_from: "strong" }, ADMIN);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { enabled: boolean; notify_from: string };
    expect(body.enabled).toBe(true);
    expect(body.notify_from).toBe("strong");
  });

  it("keeps GET /api/alerts public", async () => {
    expect((await handleRequest(new Request("https://x/api/alerts"), noAdminEnv())).status).toBe(200);
  });
});

describe("POST /api/alerts input validation", () => {
  it("rejects an out-of-range min_interval_s", async () => {
    expect((await post(adminEnv(), { min_interval_s: 10 }, ADMIN)).status).toBe(400);
  });

  it("rejects an out-of-range or non-integer quiet hour", async () => {
    expect((await post(adminEnv(), { quiet_start_hour: 25 }, ADMIN)).status).toBe(400);
    expect((await post(adminEnv(), { quiet_end_hour: 2.5 }, ADMIN)).status).toBe(400);
  });

  it("accepts quiet hours of -1 (disabled)", async () => {
    expect((await post(adminEnv(), { quiet_start_hour: -1, quiet_end_hour: -1 }, ADMIN)).status).toBe(200);
  });

  it("rejects a non-boolean enabled", async () => {
    expect((await post(adminEnv(), { enabled: "yes" }, ADMIN)).status).toBe(400);
  });
});
