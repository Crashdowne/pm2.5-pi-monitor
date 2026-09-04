// Client-side AQI helpers and mask personalization mirroring the server.

import type { Band, LevelMeta, SiteConfig } from "./api";

export type Thresholds = { carry: number; recommended: number; strong: number; indoors: number };

export function colorForAqi(aqi: number | null, bands: Band[]): string {
  if (aqi === null || aqi === undefined) return "#9ca3af";
  for (const b of bands) if (aqi <= b.upper) return b.color;
  return bands[bands.length - 1]?.color ?? "#7e0023";
}

export function categoryForAqi(aqi: number | null, bands: Band[]): string {
  if (aqi === null || aqi === undefined) return "Unknown";
  for (const b of bands) if (aqi <= b.upper) return b.label;
  return bands[bands.length - 1]?.label ?? "Hazardous";
}

const ORDER = ["none", "carry", "recommended", "strong", "indoors"];

export function levelFor(aqi: number | null, t: Thresholds): string {
  if (aqi === null || aqi === undefined) return "none";
  if (aqi >= t.indoors) return "indoors";
  if (aqi >= t.strong) return "strong";
  if (aqi >= t.recommended) return "recommended";
  if (aqi >= t.carry) return "carry";
  return "none";
}

export function severity(level: string): number {
  const i = ORDER.indexOf(level);
  return i < 0 ? 0 : i;
}

export function levelMeta(cfg: SiteConfig, level: string): LevelMeta {
  return cfg.mask.levels.find((l) => l.level === level) ?? cfg.mask.levels[0];
}

// ECharts markArea pieces that shade AQI bands behind a chart, up to `maxAqi`.
export function bandAreas(bands: Band[], maxAqi: number) {
  let low = 0;
  const pieces: { yAxis: number }[][] = [];
  for (const b of bands) {
    const high = Math.min(b.upper, maxAqi);
    if (high <= low) break;
    pieces.push([{ yAxis: low }, { yAxis: high, itemStyle: { color: b.color } } as { yAxis: number }]);
    low = b.upper;
    if (low >= maxAqi) break;
  }
  return pieces;
}
