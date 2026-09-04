import type { Band, HeatCell } from "../api";
import { chartOn, PALETTE, tooltipStyle } from "./base";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));

function pieces(bands: Band[]) {
  return bands.map((b, i) => ({
    gt: i === 0 ? -1 : bands[i - 1].upper,
    lte: b.upper,
    color: b.color,
  }));
}

export function renderHeatmap(el: HTMLElement, cells: HeatCell[], bands: Band[]): void {
  const chart = chartOn(el);
  chart.setOption(
    {
      tooltip: {
        ...tooltipStyle,
        formatter: (p: { value: HeatCell }) =>
          `${DAYS[p.value[1]]} ${HOURS[p.value[0]]}:00<br/>AQI ${p.value[2]}`,
      },
      grid: { left: 40, right: 12, top: 8, bottom: 40 },
      xAxis: {
        type: "category",
        data: HOURS,
        axisLabel: { color: PALETTE.muted, fontSize: 9, interval: 2 },
        axisLine: { lineStyle: { color: PALETTE.line } },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: DAYS,
        axisLabel: { color: PALETTE.muted, fontSize: 10 },
        axisLine: { lineStyle: { color: PALETTE.line } },
        splitArea: { show: false },
      },
      visualMap: { type: "piecewise", show: false, min: 0, max: 500, dimension: 2, pieces: pieces(bands) },
      series: [
        {
          type: "heatmap",
          data: cells,
          itemStyle: { borderColor: PALETTE.bg, borderWidth: 1 },
          emphasis: { itemStyle: { borderColor: PALETTE.text, borderWidth: 1 } },
        },
      ],
    },
    true,
  );
}
