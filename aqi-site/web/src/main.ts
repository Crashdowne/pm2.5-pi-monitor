import "./styles.css";
import * as api from "./api";
import type { SiteConfig } from "./api";
import { categoryForAqi, colorForAqi, levelFor, levelMeta, severity } from "./aqi";
import { loadSettings, saveSettings, type Settings } from "./state";
import { renderGauge } from "./charts/gauge";
import { renderTimeseries } from "./charts/timeseries";
import { renderCalendar } from "./charts/calendar";
import { renderHeatmap } from "./charts/heatmap";
import { renderDistribution } from "./charts/distribution";
import { renderDiurnal } from "./charts/diurnal";

const METRICS = [
  { key: "aqi", label: "AQI" },
  { key: "pm2_5", label: "PM2.5" },
  { key: "pm10", label: "PM10" },
  { key: "temp", label: "Temp" },
  { key: "rh", label: "RH" },
];
const SENSITIVITY_LABELS: Record<string, string> = {
  general: "General",
  asthma: "Asthma",
  very_sensitive: "Very sensitive",
};
const TREND_ARROW: Record<string, string> = { improving: "↓", worsening: "↑", steady: "→" };
const POLLUTANT_LABEL: Record<string, string> = { pm2_5: "PM2.5", pm10: "PM10" };
const prettyPollutant = (d: string): string => POLLUTANT_LABEL[d] ?? d.toUpperCase();

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el as T;
};

let config: SiteConfig;
let settings: Settings = loadSettings();
let calYear = new Date().getFullYear();
let current: api.Current | null = null;

function fmtAge(s: number): string {
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function convTemp(t: number | null): string {
  if (t === null) return "—";
  return settings.tempUnit === "f" ? `${(t * 9 / 5 + 32).toFixed(1)}°F` : `${t.toFixed(1)}°C`;
}

function seg(container: HTMLElement, items: { key: string; label: string }[], active: string, onPick: (key: string) => void): void {
  container.innerHTML = "";
  for (const it of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = it.label;
    b.dataset.key = it.key;
    b.className = "seg-btn" + (it.key === active ? " active" : "");
    b.addEventListener("click", () => {
      container.querySelectorAll<HTMLElement>(".seg-btn").forEach((x) => x.classList.toggle("active", x.dataset.key === it.key));
      onPick(it.key);
    });
    container.appendChild(b);
  }
}

function thresholds() {
  const preset = config.mask.presets[settings.sensitivity] ?? config.mask.thresholds;
  return preset;
}

function renderHero(): void {
  if (!current) return;
  const aqi = current.nowcast_aqi;
  renderGauge($("gauge"), aqi, config.bands, categoryForAqi(aqi, config.bands));
  $("gauge-meta").innerHTML = [
    ["PM2.5", current.pm2_5 === null ? "—" : `${current.pm2_5} µg/m³`],
    ["PM10", current.pm10 === null ? "—" : `${current.pm10} µg/m³`],
    ["Temp", convTemp(current.temp)],
    ["Humidity", current.rh === null ? "—" : `${current.rh}%`],
    ["Dominant", prettyPollutant(current.dominant)],
    ["Updated", fmtAge(current.age_s)],
  ]
    .map(([k, v]) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`)
    .join("");
  renderMaskCard();
}

function renderMaskCard(): void {
  if (!current) return;
  const aqi = current.nowcast_aqi;
  const level = levelFor(aqi, thresholds());
  const meta = levelMeta(config, level);
  const trend = current.trend;
  const gw = current.good_window;
  const gwText = gw ? ` Typically cleanest around ${String(gw.hour).padStart(2, "0")}:00 (AQI ${gw.aqi}).` : "";
  $("mask-card").innerHTML = `
    <div class="mask-head" style="border-color:${meta.color}">
      <span class="mask-dot" style="background:${meta.color}"></span>
      <div class="mask-head-text">
        <div class="mask-level">${meta.label}</div>
        <div class="muted">${meta.mask_type}</div>
      </div>
      <div class="mask-aqi" style="color:${colorForAqi(aqi, config.bands)}">AQI ${aqi} <span class="trend">${TREND_ARROW[trend] ?? ""}</span></div>
    </div>
    <p class="mask-action">${meta.action}</p>
    <div class="mask-why muted">Based on the ${prettyPollutant(current.dominant)} NowCast AQI for the ${SENSITIVITY_LABELS[settings.sensitivity] ?? settings.sensitivity} profile.${gwText}</div>
    <div class="mask-disclaimer">${config.mask.disclaimer}</div>`;
  renderBanner(level);
}

function renderBanner(level: string): void {
  const banner = $("banner");
  if (severity(level) >= severity("recommended")) {
    const meta = levelMeta(config, level);
    banner.textContent = `${meta.label}: ${meta.action}`;
    banner.style.background = meta.color;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

function statCard(label: string, value: string, aqi: number | null): string {
  const dot = aqi === null ? "" : `<span class="dot" style="background:${colorForAqi(aqi, config.bands)}"></span>`;
  return `<div class="stat"><div class="stat-label">${dot}${label}</div><div class="stat-value">${value}</div></div>`;
}

async function loadSummary(sensor: string): Promise<void> {
  const s = await api.getSummary(sensor);
  $("report").innerHTML = [
    statCard("24h avg", s.aqi_24h === null ? "—" : `AQI ${s.aqi_24h}`, s.aqi_24h),
    statCard("7-day avg", s.aqi_7d === null ? "—" : `AQI ${s.aqi_7d}`, s.aqi_7d),
    statCard("30-day avg", s.aqi_30d === null ? "—" : `AQI ${s.aqi_30d}`, s.aqi_30d),
    statCard("Peak (7d)", s.peak_aqi_7d === null ? "—" : `AQI ${s.peak_aqi_7d}`, s.peak_aqi_7d),
    statCard("Unhealthy hrs (30d)", `${s.exceedance_hours_30d} h`, s.exceedance_hours_30d > 0 ? 150 : 50),
    statCard("Cigarettes (30d)", s.cigarettes_30d === null ? "—" : `≈ ${s.cigarettes_30d}`, null),
  ].join("");
}

async function loadFleet(): Promise<void> {
  const rows = await api.getSensors();
  $("fleet").innerHTML = rows
    .map((r) => {
      const meta = levelMeta(config, r.mask_level);
      return `<button class="fleet-row${r.sensor_id === settings.sensor ? " active" : ""}" data-sensor="${r.sensor_id}">
        <span class="badge" style="background:${r.color}">${r.aqi}</span>
        <span class="fleet-name">${r.sensor_id}</span>
        <span class="chip" style="border-color:${meta.color};color:${meta.color}">${meta.label}</span>
        <span class="muted">${r.pm2_5 === null ? "—" : `${r.pm2_5} µg/m³`} · ${fmtAge(r.age_s)} · ${r.coverage_24h}%</span>
      </button>`;
    })
    .join("");
  $("fleet").querySelectorAll<HTMLButtonElement>(".fleet-row").forEach((b) => {
    b.addEventListener("click", () => selectSensor(b.dataset.sensor as string));
  });
}

async function loadCharts(sensor: string, range: string): Promise<void> {
  const [history, heatmap, distribution, diurnal] = await Promise.all([
    api.getHistory(sensor, range),
    api.getHeatmap(sensor, range),
    api.getDistribution(sensor, range),
    api.getDiurnal(sensor, range),
  ]);
  renderTimeseries($("timeseries"), history, settings.metric, config.bands, settings.tempUnit);
  renderHeatmap($("heatmap"), heatmap, config.bands);
  renderDistribution($("distribution"), distribution);
  const gw = current?.good_window ?? null;
  renderDiurnal($("diurnal"), diurnal, gw);
  const goodWindow = $("good-window");
  goodWindow.textContent = gw ? `cleanest ~${String(gw.hour).padStart(2, "0")}:00` : "";
}

async function loadCalendar(sensor: string): Promise<void> {
  const data = await api.getCalendar(sensor, calYear);
  renderCalendar($("calendar"), data, calYear, config.bands);
  $("year-label").textContent = String(calYear);
}

async function loadCurrent(sensor: string): Promise<void> {
  current = await api.getCurrent(sensor);
  renderHero();
}

function updateExport(): void {
  ($("export") as HTMLAnchorElement).href = api.exportUrl(settings.sensor, settings.range, "csv");
}

async function refreshAll(): Promise<void> {
  updateExport();
  await loadCurrent(settings.sensor);
  await Promise.all([
    loadCharts(settings.sensor, settings.range),
    loadCalendar(settings.sensor),
    loadSummary(settings.sensor),
    loadFleet(),
  ]);
}

function selectSensor(sensor: string): void {
  settings.sensor = sensor;
  saveSettings(settings);
  ($("sensor") as HTMLSelectElement).value = sensor;
  void refreshAll();
}

async function initAlertsPanel(): Promise<void> {
  const panel = $("alerts-panel");
  const view = await api.getAlerts();
  panel.innerHTML = `
    <div class="panel-head"><h2>Alerts</h2><button class="btn" id="alerts-close" type="button">Close</button></div>
    <label class="row"><input type="checkbox" id="al-enabled" ${view.enabled ? "checked" : ""}/> Enable push alerts</label>
    <label class="row">Notify from
      <select id="al-from">${view.levels.map((l) => `<option value="${l}"${l === view.notify_from ? " selected" : ""}>${l}</option>`).join("")}</select>
    </label>
    <label class="row">Min interval (min) <input type="number" id="al-interval" min="5" value="${Math.round(view.min_interval_s / 60)}"/></label>
    <label class="row">Quiet hours <input type="number" id="al-qs" min="-1" max="23" value="${view.quiet_start_hour}"/> to <input type="number" id="al-qe" min="-1" max="23" value="${view.quiet_end_hour}"/></label>
    <div class="muted">Channels (set in server config): ntfy ${view.ntfy_configured ? "✓" : "✗"} · webhook ${view.webhook_configured ? "✓" : "✗"}</div>
    <div class="al-sensors muted">${view.sensors.map((s) => `${s.sensor_id}: ${s.last_level}`).join(" · ") || "no alert state yet"}</div>
    <button class="btn primary" id="alerts-save" type="button">Save</button>`;
  panel.hidden = false;
  $("alerts-close").addEventListener("click", () => (panel.hidden = true));
  $("alerts-save").addEventListener("click", async () => {
    await api.postAlerts({
      enabled: (document.getElementById("al-enabled") as HTMLInputElement).checked,
      notify_from: (document.getElementById("al-from") as HTMLSelectElement).value,
      min_interval_s: Math.max(300, +(document.getElementById("al-interval") as HTMLInputElement).value * 60),
      quiet_start_hour: +(document.getElementById("al-qs") as HTMLInputElement).value,
      quiet_end_hour: +(document.getElementById("al-qe") as HTMLInputElement).value,
    });
    panel.hidden = true;
  });
}

function buildControls(sensors: string[]): void {
  const sensorSel = $("sensor") as HTMLSelectElement;
  sensorSel.innerHTML = sensors.map((s) => `<option value="${s}">${s}</option>`).join("");
  sensorSel.value = settings.sensor;
  sensorSel.addEventListener("change", () => selectSensor(sensorSel.value));

  seg($("range"), config.ranges.map((r) => ({ key: r, label: r })), settings.range, (key) => void selectRange(key));

  seg($("metric"), METRICS, settings.metric, (key) => {
    settings.metric = key;
    saveSettings(settings);
    void loadCharts(settings.sensor, settings.range);
  });

  const sensSel = $("sensitivity") as HTMLSelectElement;
  sensSel.innerHTML = Object.keys(config.mask.presets)
    .map((k) => `<option value="${k}"${k === settings.sensitivity ? " selected" : ""}>${SENSITIVITY_LABELS[k] ?? k}</option>`)
    .join("");
  sensSel.addEventListener("change", () => {
    settings.sensitivity = sensSel.value;
    saveSettings(settings);
    renderMaskCard();
  });

  const unitBtn = $("unit") as HTMLButtonElement;
  unitBtn.textContent = settings.tempUnit === "f" ? "°F" : "°C";
  unitBtn.addEventListener("click", () => {
    settings.tempUnit = settings.tempUnit === "f" ? "c" : "f";
    saveSettings(settings);
    unitBtn.textContent = settings.tempUnit === "f" ? "°F" : "°C";
    renderHero();
    void loadCharts(settings.sensor, settings.range);
  });

  $("alerts-btn").addEventListener("click", () => void initAlertsPanel());

  const yearNav = $("year-nav");
  yearNav.innerHTML = `<button class="seg-btn" id="year-prev" type="button">‹</button><span class="seg-btn" id="year-label">${calYear}</span><button class="seg-btn" id="year-next" type="button">›</button>`;
  $("year-prev").addEventListener("click", () => {
    calYear -= 1;
    void loadCalendar(settings.sensor);
  });
  $("year-next").addEventListener("click", () => {
    calYear += 1;
    void loadCalendar(settings.sensor);
  });
}

async function selectRange(range: string): Promise<void> {
  settings.range = range;
  saveSettings(settings);
  updateExport();
  await loadCharts(settings.sensor, range);
}

async function init(): Promise<void> {
  config = await api.getConfig();
  document.title = config.site_title;
  $("site-title").textContent = config.site_title;
  $("disclaimer").textContent = config.mask.disclaimer;
  if (!settings.sensitivity) settings.sensitivity = config.mask.sensitivity;
  if (!settings.tempUnit) settings.tempUnit = config.temp_unit;

  const sensors = await api.getSensors();
  if (!sensors.length) {
    $("mask-card").innerHTML = '<div class="muted">No sensor data in the warehouse yet.</div>';
    return;
  }
  const ids = sensors.map((s) => s.sensor_id);
  if (!settings.sensor || !ids.includes(settings.sensor)) settings.sensor = ids[0];
  saveSettings(settings);

  buildControls(ids);
  await refreshAll();

  setInterval(() => void loadCurrent(settings.sensor).then(loadFleet), 30_000);
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

void init().catch((err) => {
  document.getElementById("mask-card")!.innerHTML = `<div class="muted">Failed to load: ${err}</div>`;
});
