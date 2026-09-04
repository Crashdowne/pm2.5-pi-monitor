// Shared ECharts setup: one reusable instance per element, dark palette.

import * as echarts from "echarts";

const registry = new WeakMap<HTMLElement, echarts.ECharts>();
let resizeBound = false;
const instances: echarts.ECharts[] = [];

export const PALETTE = {
  bg: "#0b1220",
  panel: "#111a2e",
  text: "#e6edf7",
  muted: "#93a1b8",
  line: "#1e293b",
  pm25: "#38bdf8",
  pm10: "#a78bfa",
  temp: "#f59e0b",
  rh: "#34d399",
};

export function chartOn(el: HTMLElement): echarts.ECharts {
  let chart = registry.get(el);
  if (!chart) {
    chart = echarts.init(el, undefined, { renderer: "canvas" });
    registry.set(el, chart);
    instances.push(chart);
    if (!resizeBound) {
      resizeBound = true;
      window.addEventListener("resize", () => instances.forEach((c) => c.resize()));
    }
  }
  return chart;
}

export const tooltipStyle = {
  backgroundColor: "#0f172a",
  borderColor: PALETTE.line,
  textStyle: { color: PALETTE.text },
};

export const gridStyle = { left: 44, right: 16, top: 24, bottom: 28 };
