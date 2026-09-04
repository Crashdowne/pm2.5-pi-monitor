import type { DiurnalHour } from "../api";
import { chartOn, gridStyle, PALETTE, tooltipStyle } from "./base";

export function renderDiurnal(
  el: HTMLElement,
  rows: DiurnalHour[],
  goodWindow: { hour: number; aqi: number } | null,
): void {
  const chart = chartOn(el);
  const hours = rows.map((r) => `${String(r.hour).padStart(2, "0")}`);
  const avg = rows.map((r) => r.avg);
  const min = rows.map((r) => r.min);
  const range = rows.map((r) => (r.max !== null && r.min !== null ? +(r.max - r.min).toFixed(1) : null));

  const markPoint =
    goodWindow && rows[goodWindow.hour]?.avg !== null
      ? {
          symbol: "pin",
          symbolSize: 42,
          itemStyle: { color: "#2ea043" },
          label: { color: "#fff", fontSize: 9, formatter: "best" },
          data: [{ coord: [goodWindow.hour, rows[goodWindow.hour].avg], value: "" }],
        }
      : undefined;

  chart.setOption(
    {
      tooltip: {
        trigger: "axis",
        ...tooltipStyle,
        valueFormatter: (v: number | null) => (v === null ? "—" : `${v} µg/m³`),
      },
      grid: gridStyle,
      xAxis: {
        type: "category",
        data: hours,
        boundaryGap: false,
        axisLabel: { color: PALETTE.muted, fontSize: 9, interval: 2 },
        axisLine: { lineStyle: { color: PALETTE.line } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: PALETTE.muted },
        splitLine: { lineStyle: { color: PALETTE.line } },
      },
      series: [
        { name: "min", type: "line", stack: "band", data: min, symbol: "none", lineStyle: { opacity: 0 }, silent: true },
        {
          name: "range",
          type: "line",
          stack: "band",
          data: range,
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { color: PALETTE.pm25, opacity: 0.12 },
          silent: true,
        },
        {
          name: "avg",
          type: "line",
          data: avg,
          smooth: 0.3,
          symbol: "none",
          lineStyle: { color: PALETTE.pm25, width: 2 },
          markPoint,
        },
      ],
    },
    true,
  );
}
