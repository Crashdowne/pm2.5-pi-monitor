import { drawClimate, drawLine } from "/charts.js";

const fleet = document.querySelector("#fleet");
const status = document.querySelector("#status");
const detail = document.querySelector("#detail");
const history = document.querySelector("#history");
const environmentHistory = document.querySelector("#environment-history");
let etag = "";
let timer = null;

const fmt = (value) => (value == null ? "--" : Number(value).toFixed(1));
const age = (ts) => {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  return seconds < 60 ? `${seconds}s ago` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : `${Math.floor(seconds / 3600)}h ago`;
};

async function selectSensor(sensorId) {
  const response = await fetch(`/api/sensors/${encodeURIComponent(sensorId)}/history?range=24h`);
  if (!response.ok) return;
  const rows = await response.json();
  document.querySelector("#detail-name").textContent = sensorId;
  detail.hidden = false;
  drawLine(history, rows.map((row) => ({ t: row.t, pm25: row.pm2_5, pm10: row.pm10 })), (ts) =>
    new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
  drawClimate(environmentHistory, rows.map((row) => ({ t: row.t, temp: row.temp, rh: row.rh })), (ts) =>
    new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

function render(rows) {
  rows.sort((a, b) => ((Date.now() / 1000 - b.ts > 600) - (Date.now() / 1000 - a.ts > 600)) || b.aqi.value - a.aqi.value);
  fleet.replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;

    const cell = (text) => {
      const td = document.createElement("td");
      td.textContent = text;
      return td;
    };

    const aqiTd = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "aqi";
    badge.textContent = row.aqi.value;
    badge.style.background = row.aqi.color;
    aqiTd.append(badge, ` ${row.aqi.category}`);

    tr.append(
      cell(row.sensor_id),
      aqiTd,
      cell(`${fmt(row.pm2_5)} µg/m³`),
      cell(age(row.ts)),
      cell(`${row.coverage_24h}%`),
      cell(`${fmt(row.temp)}°C / ${fmt(row.rh)}%`),
    );

    tr.addEventListener("click", () => selectSensor(row.sensor_id));
    tr.addEventListener("keydown", (event) => { if (event.key === "Enter") selectSensor(row.sensor_id); });
    return tr;
  }));
  status.textContent = `${rows.length} monitor${rows.length === 1 ? "" : "s"} · updated now`;
}

async function refresh() {
  clearTimeout(timer);
  if (document.hidden) return;
  try {
    const response = await fetch("/api/fleet", { headers: etag ? { "If-None-Match": etag } : {} });
    if (response.status !== 304) {
      if (!response.ok) throw new Error(String(response.status));
      etag = response.headers.get("ETag") || "";
      render(await response.json());
    }
  } catch {
    status.textContent = "Fleet unavailable · showing last update";
  } finally {
    timer = setTimeout(refresh, 60000);
  }
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
window.addEventListener("online", refresh);
refresh();