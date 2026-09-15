import { describe, expect, it } from "vitest";

import { authenticateIngest } from "../src/auth.ts";
import type { Env } from "../src/env.ts";

function env(token?: string): Env {
  return { INGEST_TOKEN: token } as Env;
}

function reqWith(authorization?: string): Request {
  return new Request("https://x/ingest", {
    method: "POST",
    headers: authorization ? { Authorization: authorization } : {},
  });
}

describe("authenticateIngest", () => {
  it("accepts the correct bearer token", async () => {
    const r = await authenticateIngest(reqWith("Bearer s3cret"), env("s3cret"));
    expect(r.ok).toBe(true);
  });

  it("rejects a wrong token with 401", async () => {
    const r = await authenticateIngest(reqWith("Bearer nope"), env("s3cret"));
    expect(r.ok).toBe(false);
    expect(r.status).toBe(401);
  });

  it("rejects a missing Authorization header", async () => {
    const r = await authenticateIngest(reqWith(), env("s3cret"));
    expect(r.ok).toBe(false);
    expect(r.status).toBe(401);
  });

  it("fails closed (500) when no token is configured", async () => {
    const r = await authenticateIngest(reqWith("Bearer x"), env(undefined));
    expect(r.ok).toBe(false);
    expect(r.status).toBe(500);
  });
});
