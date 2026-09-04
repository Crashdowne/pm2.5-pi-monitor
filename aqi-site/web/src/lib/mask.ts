// Client-side mask advisor: recompute the level from the chosen sensitivity so the
// card updates instantly, using thresholds and level metadata from /api/config.
import type { Current, SiteConfig, Thresholds } from "@/api";
import { maskIcon, prettyPollutant } from "@/lib/aqi";

const ORDER = ["none", "carry", "recommended", "strong", "indoors"];

export function severity(level: string): number {
  const i = ORDER.indexOf(level);
  return i < 0 ? 0 : i;
}

export function levelFor(aqi: number | null, t: Thresholds): string {
  if (aqi == null) return "none";
  if (aqi >= t.indoors) return "indoors";
  if (aqi >= t.strong) return "strong";
  if (aqi >= t.recommended) return "recommended";
  if (aqi >= t.carry) return "carry";
  return "none";
}

export interface Advice {
  level: string;
  label: string;
  action: string;
  color: string;
  icon: string;
  maskType: string;
  reason: string;
  bestTime: string;
}

export function computeAdvice(config: SiteConfig, cur: Current, sensitivity: string): Advice {
  const thresholds = config.mask.presets[sensitivity] ?? config.mask.thresholds;
  const level = levelFor(cur.nowcast_aqi, thresholds);
  const meta = config.mask.levels.find((l) => l.level === level) ?? config.mask.levels[0];
  const suffix = cur.trend === "worsening" ? " — worsening" : cur.trend === "improving" ? " — improving" : "";
  const pm = cur.pm2_5 == null ? "—" : cur.pm2_5;
  return {
    level,
    label: meta.label,
    action: meta.action,
    color: meta.color,
    icon: maskIcon[level] ?? "😷",
    maskType: meta.mask_type,
    reason: `AQI ${cur.nowcast_aqi} · ${prettyPollutant(cur.dominant)} ${pm} µg/m³${suffix}`,
    bestTime: cur.good_window
      ? `Typically cleanest around ${String(cur.good_window.hour).padStart(2, "0")}:00 (AQI ${cur.good_window.aqi})`
      : "Not enough data yet",
  };
}
