// Ingest auth — bearer token. The dashboard is public; only /ingest and /max_ts are
// gated. The Pi presents `Authorization: Bearer <INGEST_TOKEN>`; there is no network
// isolation on Cloudflare's edge, so the token is the sole ingest trust boundary.
import type { Env } from "./env.ts";

export interface AuthResult {
  ok: boolean;
  status?: number;
  message?: string;
}

// Constant-time comparison so the token check does not leak via timing.
function timingSafeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const ab = enc.encode(a);
  const bb = enc.encode(b);
  if (ab.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ab.length; i++) diff |= ab[i] ^ bb[i];
  return diff === 0;
}

export async function authenticateIngest(request: Request, env: Env): Promise<AuthResult> {
  const expected = env.INGEST_TOKEN ?? "";
  if (!expected) return { ok: false, status: 500, message: "ingest token not configured" };
  const provided = request.headers.get("Authorization") ?? "";
  if (!timingSafeEqual(provided, `Bearer ${expected}`)) {
    return { ok: false, status: 401, message: "unauthorized" };
  }
  return { ok: true };
}
