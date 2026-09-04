import type { DistBand } from "../api";
import { chartOn, PALETTE, tooltipStyle } from "./base";

export function renderDistribution(el: HTMLElement, dist: DistBand[]): void {
  const chart = chartOn(el);
  const data = dist
    .filter((d) => d.hours > 0)
    .map((d) => ({ value: d.pct, name: d.label, hours: d.hours, itemStyle: { color: d.color } }));
  chart.setOption(
    {
      tooltip: {
        ...tooltipStyle,
        formatter: (p: { name: string; value: number; data: { hours: number } }) =>
          `${p.name}<br/>${p.value}% · ${p.data.hours} h`,
      },
      series: [
        {
          type: "pie",
          radius: ["52%", "80%"],
          center: ["50%", "52%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: PALETTE.bg, borderWidth: 2 },
          label: { color: PALETTE.text, fontSize: 10, formatter: (p: { name: string; value: number }) => `${p.value}%` },
          labelLine: { length: 8, length2: 8, lineStyle: { color: PALETTE.line } },
          data,
        },
      ],
    },
    true,
  );
}
