import type { Band, HistoryPoint } from "../api";
import { bandAreas } from "../aqi";
import { chartOn, gridStyle, PALETTE, tooltipStyle } from "./base";

const META: Record<string, { label: string; color: string; unit: string }> = {
  aqi: { label: "AQI", color: "#e6edf7", unit: "" },
  pm2_5: { label: "PM2.5", color: PALETTE.pm25, unit: " µg/m³" },
  pm10: { label: "PM10", color: PALETTE.pm10, unit: " µg/m³" },
  temp: { label: "Temp", color: PALETTE.temp, unit: "°" },
  rh: { label: "Humidity", color: PALETTE.rh, unit: "%" },
};

function value(p: HistoryPoint, metric: string, tempUnit: "c" | "f"): number | null {
  if (metric === "aqi") return p.aqi;
  if (metric === "pm2_5") return p.pm2_5;
  if (metric === "pm10") return p.pm10;
  if (metric === "rh") return p.rh;
  if (metric === "temp") return p.temp === null ? null : tempUnit === "f" ? +(p.temp * 9 / 5 + 32).toFixed(1) : p.temp;
  return null;
}

export function renderTimeseries(
  el: HTMLElement,
  points: HistoryPoint[],
  metric: string,
  bands: Band[],
  tempUnit: "c" | "f",
): void {
  const chart = chartOn(el);
  const meta = META[metric] ?? META.pm2_5;
  const unit = metric === "temp" ? (tempUnit === "f" ? "°F" : "°C") : meta.unit;
  const series = points.map((p) => [p.t * 1000, value(p, metric, tempUnit)] as [number, number | null]);
  const showBands = metric === "aqi";
  const numeric = series.map((s) => s[1]).filter((v): v is number => v !== null);
  const dataMax = numeric.length ? Math.max(...numeric) : 60;
  const yMax = showBands ? Math.min(500, Math.max(60, Math.ceil(dataMax / 50) * 50)) : undefined;

  chart.setOption(
    {
      tooltip: {
        trigger: "axis",
        ...tooltipStyle,
        valueFormatter: (v: number | null) => (v === null ? "—" : `${v}${unit}`),
      },
      grid: { ...gridStyle, bottom: 56 },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: PALETTE.line } },
        axisLabel: { color: PALETTE.muted, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        max: yMax,
        axisLabel: { color: PALETTE.muted },
        splitLine: { lineStyle: { color: PALETTE.line } },
      },
      dataZoom: [
        { type: "inside", throttle: 60 },
        { type: "slider", height: 18, bottom: 12, borderColor: PALETTE.line, textStyle: { color: PALETTE.muted } },
      ],
      series: [
        {
          name: meta.label,
          type: "line",
          showSymbol: false,
          smooth: 0.2,
          sampling: "lttb",
          lineStyle: { color: meta.color, width: 2 },
          itemStyle: { color: meta.color },
          areaStyle: metric === "aqi" ? undefined : { color: meta.color, opacity: 0.08 },
          data: series,
          markArea: showBands
            ? { silent: true, data: bandAreas(bands, yMax ?? 500), itemStyle: { opacity: 0.14 } }
            : undefined,
        },
      ],
    },
    true,
  );
}
