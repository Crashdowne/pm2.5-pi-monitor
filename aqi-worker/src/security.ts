// Baseline security headers applied to every response (API, ingest, and the SPA).
// The dashboards ship external scripts only, so script-src stays 'self'; any inline
// styles are covered by 'unsafe-inline' in style-src.
const CSP =
  "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; " +
  "img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; " +
  "connect-src 'self'; manifest-src 'self'";

export function withSecurityHeaders(res: Response): Response {
  const out = new Response(res.body, res);
  out.headers.set("X-Content-Type-Options", "nosniff");
  out.headers.set("Referrer-Policy", "no-referrer");
  out.headers.set("X-Frame-Options", "DENY");
  if (!out.headers.has("Content-Security-Policy")) {
    out.headers.set("Content-Security-Policy", CSP);
  }
  return out;
}
