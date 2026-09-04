import type { Band } from "../api";
import { colorForAqi } from "../aqi";
import { chartOn, PALETTE } from "./base";

export function renderGauge(el: HTMLElement, aqi: number | null, bands: Band[], label: string): void {
  const chart = chartOn(el);
  const max = 500;
  const colorStops = bands.map((b) => [Math.min(b.upper, max) / max, b.color] as [number, string]);
  chart.setOption(
    {
      series: [
        {
          type: "gauge",
          min: 0,
          max,
          startAngle: 210,
          endAngle: -30,
          radius: "96%",
          center: ["50%", "58%"],
          axisLine: { lineStyle: { width: 14, color: colorStops } },
          pointer: { width: 5, length: "62%", itemStyle: { color: PALETTE.text } },
          progress: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            color: PALETTE.muted,
            fontSize: 9,
            distance: 12,
            formatter: (v: number) => ([0, 100, 200, 300, 500].includes(v) ? String(v) : ""),
          },
          anchor: { show: true, size: 10, itemStyle: { color: PALETTE.text } },
          detail: {
            valueAnimation: true,
            fontSize: 40,
            fontWeight: 800,
            offsetCenter: [0, "28%"],
            color: colorForAqi(aqi, bands),
            formatter: (v: number) => String(Math.round(v)),
          },
          title: { offsetCenter: [0, "58%"], color: PALETTE.muted, fontSize: 12 },
          data: [{ value: aqi ?? 0, name: label }],
        },
      ],
    },
    true,
  );
}
