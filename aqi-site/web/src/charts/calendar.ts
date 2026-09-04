import type { Band, CalendarDay } from "../api";
import { chartOn, PALETTE, tooltipStyle } from "./base";

function pieces(bands: Band[]) {
  return bands.map((b, i) => ({
    gt: i === 0 ? -1 : bands[i - 1].upper,
    lte: b.upper,
    color: b.color,
  }));
}

export function renderCalendar(el: HTMLElement, data: CalendarDay[], year: number, bands: Band[]): void {
  const chart = chartOn(el);
  chart.setOption(
    {
      tooltip: {
        ...tooltipStyle,
        formatter: (p: { value: [string, number] }) => `${p.value[0]}<br/>AQI ${p.value[1]}`,
      },
      visualMap: { type: "piecewise", show: false, min: 0, max: 500, pieces: pieces(bands) },
      calendar: {
        range: String(year),
        cellSize: ["auto", 13],
        top: 24,
        left: 30,
        right: 8,
        bottom: 0,
        itemStyle: { color: PALETTE.panel, borderColor: PALETTE.bg, borderWidth: 2 },
        dayLabel: { color: PALETTE.muted, fontSize: 9, firstDay: 1 },
        monthLabel: { color: PALETTE.muted, fontSize: 10 },
        yearLabel: { show: false },
        splitLine: { show: false },
      },
      series: [
        {
          type: "heatmap",
          coordinateSystem: "calendar",
          data: data.map((d) => [d.date, d.aqi]),
        },
      ],
    },
    true,
  );
}
