// aqi-worker entry — serves the ingest routes, the read API, and the static SPA, and
// runs the alert poller on a Cron Trigger (replacing aqi-site's background thread).
import { handleRequest } from "./app.ts";
import type { Env } from "./env.ts";
import * as alerts from "./lib/alerts.ts";
import { loadConfig } from "./lib/config.ts";

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(alerts.pollOnce(env, loadConfig(env)));
  },
};
