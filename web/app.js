import { drawLine, drawBars } from "/charts.js";

const $ = (s) => document.querySelector(s);

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

let currentEtag = "";
let lastCurrent = null;

async function getCurrent() {
  const headers = currentEtag ? { "If-None-Match": currentEtag } : {};
  const response = await fetch("/api/current", { headers });
  if (response.status === 304 && lastCurrent) return { data: lastCurrent, cached: false };
  if (!response.ok) throw new Error(`/api/current -> ${response.status}`);
  currentEtag = response.headers.get("ETag") || "";
  const data = await response.json();
  lastCurrent = data;
  return { data, cached: response.headers.get("X-PM25-Cached") === "1" };
}

const fmt = (v) => (v == null ? "--" : (Math.round(v * 10) / 10).toFixed(1));
const hourLabel = (t) =>
  new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" });
const dayLabel = (t) =>
  new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
const duration = (seconds) => {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
};

function textColorFor(hex) {
  if (!hex) return "#fff";
  const c = hex.replace("#", "");
  const r = parseInt(c.slice(0, 2), 16),
    g = parseInt(c.slice(2, 4), 16),
    b = parseInt(c.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 140 ? "#111" : "#fff";
}

function setState(selector, text, state = "ok") {
  const node = $(selector);
  node.textContent = text;
  node.dataset.state = state;
}

function renderHealth(health) {
  if (health?.last_reading_ts) {
    health.age_s = Math.max(0, Math.floor(Date.now() / 1000 - health.last_reading_ts));
    if (health.age_s <= health.sample_period_s + 30) health.freshness = "fresh";
    else if (health.age_s <= health.sample_period_s * 3) health.freshness = "delayed";
    else health.freshness = "stale";
    if (health.freshness === "stale") health.sensors.pm = "unavailable";
  }
  const coverage = health?.coverage_24h;
  if (!coverage || coverage.received < 3) {
    setState("#coverage", "Building history");
  } else {
    const state = coverage.pct < 80 ? "error" : coverage.pct < 95 ? "warning" : "ok";
    const suffix = coverage.pct < 80 ? " · Incomplete" : coverage.pct < 95 ? " · Some gaps" : "";
    setState("#coverage", `24h ${coverage.pct}%${suffix}`, state);
  }

  const freshnessLabels = { fresh: "Fresh", delayed: "Delayed", stale: "Stale", none: "No readings yet" };
  const freshnessState = health?.freshness === "stale" ? "error" : health?.freshness === "delayed" ? "warning" : "ok";
  const freshnessAge = health?.age_s == null ? "" : ` · ${duration(health.age_s)} ago`;
  setState("#freshness", `${freshnessLabels[health?.freshness] || "Waiting"}${freshnessAge}`, freshnessState);

  const pm = health?.sensors?.pm;
  const humidity = health?.sensors?.humidity;
  let sensorLabel = pm === "recovering" ? "PM sensor recovering" : pm === "unavailable" ? "PM sensor unavailable" : pm === "warming_up" ? "PM sensor warming up" : "Sensors OK";
  let sensorState = pm === "unavailable" ? "error" : pm === "recovering" ? "warning" : "ok";
  if (pm === "ok" && humidity === "unavailable") {
    sensorLabel = "Humidity unavailable · Raw PM2.5";
    sensorState = "warning";
  }
  setState("#sensors", sensorLabel, sensorState);

  const sync = health?.sync || {};
  const syncLabels = {
    off: "Sync off",
    current: "Sync current",
    scheduled: `Sync scheduled · ${sync.pending || 0} pending`,
    error: "Sync error · retrying",
  };
  setState("#sync-state", syncLabels[sync.state] || "Checking", sync.state === "error" ? "error" : "ok");
}

let refreshTimer = null;
let failureCount = 0;
let latestReadingTs = null;
let chartsLoaded = false;
let refreshInFlight = false;

function scheduleRefresh(current, failed = false) {
  clearTimeout(refreshTimer);
  if (document.hidden) return;
  let delayMs = 60000;
  if (failed) {
    delayMs = [30000, 60000, 120000, 300000][Math.min(failureCount - 1, 3)];
  } else if (current?.health?.freshness === "delayed" || current?.health?.sensors?.pm === "recovering") {
    delayMs = 30000;
  } else if (current?.health?.next_reading_ts) {
    delayMs = Math.max(30000, Math.min(120000, current.health.next_reading_ts * 1000 - Date.now() + 3000));
  }
  refreshTimer = setTimeout(refreshCurrent, delayMs);
}

async function refreshCurrent() {
  if (refreshInFlight || document.hidden) return;
  refreshInFlight = true;
  try {
    const { data: c, cached } = await getCurrent();
    failureCount = 0;
    renderHealth(c.health);
    if (c.ts == null) {
      $("#status").textContent = "Waiting for the first reading\u2026";
      scheduleRefresh(c);
      return;
    }
    $("#pm25").textContent = fmt(c.pm2_5);
    $("#pm10").textContent = fmt(c.pm10);

    const a = c.aqi || {};
    const badge = $("#aqi");
    const color = a.color || "#9ca3af";
    badge.style.background = color;
    badge.style.color = textColorFor(color);
    badge.firstChild.textContent = `${a.value ?? "--"} \u00b7 ${a.category || "Unknown"} `;
    $("#dominant").textContent = a.dominant === "pm10" ? "PM10" : "PM2.5";
    document.querySelector('meta[name="theme-color"]').setAttribute("content", color);

    const age = Math.max(0, Math.floor(Date.now() / 1000 - c.ts));
    const rh = c.rh != null ? ` \u00b7 RH ${fmt(c.rh)}%` : "";
    const temp = c.temp != null ? ` \u00b7 ${fmt(c.temp)}\u00b0C` : "";
    $("#status").textContent = cached
      ? `Monitor unavailable · Showing reading from ${new Date(c.ts * 1000).toLocaleString()}`
      : `Updated ${duration(age)} ago${rh}${temp}${c.pm2_5_corr != null ? " · humidity-corrected" : ""}`;
    if (!chartsLoaded || latestReadingTs !== c.ts) {
      latestReadingTs = c.ts;
      await refreshCharts();
    }
    scheduleRefresh(c);
  } catch {
    failureCount += 1;
    $("#status").textContent = lastCurrent?.ts
      ? `Monitor unavailable · Showing reading from ${new Date(lastCurrent.ts * 1000).toLocaleString()}`
      : "Monitor unavailable · No saved reading";
    scheduleRefresh(lastCurrent, true);
  } finally {
    refreshInFlight = false;
  }
}

function updateChartSummary(name, rows) {
  const summary = $(`#${name}-summary`);
  if (!rows.length) {
    summary.textContent = `No ${name} data yet.`;
    return;
  }
  const values = rows.map((row) => row.pm25).filter((value) => value != null);
  const latest = rows.at(-1);
  summary.textContent = `${rows.length} points. PM2.5 minimum ${fmt(Math.min(...values))}, maximum ${fmt(Math.max(...values))}, latest ${fmt(latest.pm25)} micrograms per cubic metre.`;
}

async function refreshCharts() {
  try {
    const a = await getJSON("/api/averages");
    const map = (rows) => rows.map((x) => ({ t: x.t, pm25: x.pm2_5, pm10: x.pm10 }));
    drawLine($("#hourly"), map(a.hourly), hourLabel);
    drawBars($("#daily"), map(a.daily), dayLabel);
    drawBars($("#weekly"), map(a.weekly), dayLabel);
    updateChartSummary("hourly", map(a.hourly));
    updateChartSummary("daily", map(a.daily));
    updateChartSummary("weekly", map(a.weekly));
    chartsLoaded = true;
  } catch {
    /* keep last render */
  }
}

refreshCurrent();

document.addEventListener("visibilitychange", () => {
  clearTimeout(refreshTimer);
  if (!document.hidden) refreshCurrent();
});
window.addEventListener("focus", refreshCurrent);
window.addEventListener("online", refreshCurrent);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
