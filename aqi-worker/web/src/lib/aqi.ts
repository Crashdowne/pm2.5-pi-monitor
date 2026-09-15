// Shared AQI band metadata (mirrors the server's EPA bands) and small formatters.

export type AQIBand = "good" | "moderate" | "sensitive" | "unhealthy" | "vunhealthy" | "hazardous";

export function aqiBand(aqi: number | null | undefined): AQIBand {
  if (aqi == null) return "good";
  if (aqi <= 50) return "good";
  if (aqi <= 100) return "moderate";
  if (aqi <= 150) return "sensitive";
  if (aqi <= 200) return "unhealthy";
  if (aqi <= 300) return "vunhealthy";
  return "hazardous";
}

export interface BandMeta {
  label: string;
  color: string;
  icon: string;
  range: string;
}

export const bandMeta: Record<AQIBand, BandMeta> = {
  good: { label: "Good", color: "#22c55e", icon: "●", range: "0–50" },
  moderate: { label: "Moderate", color: "#eab308", icon: "▲", range: "51–100" },
  sensitive: { label: "Unhealthy for Sensitive", color: "#f97316", icon: "◆", range: "101–150" },
  unhealthy: { label: "Unhealthy", color: "#ef4444", icon: "■", range: "151–200" },
  vunhealthy: { label: "Very Unhealthy", color: "#a855f7", icon: "✕", range: "201–300" },
  hazardous: { label: "Hazardous", color: "#9f1239", icon: "⚠", range: "301+" },
};

export const bandOrder: AQIBand[] = [
  "good", "moderate", "sensitive", "unhealthy", "vunhealthy", "hazardous",
];

export function metaFor(aqi: number | null | undefined): BandMeta {
  return bandMeta[aqiBand(aqi)];
}

// Mask levels come from the server (label/action/color); we add an emoji per level.
export const maskIcon: Record<string, string> = {
  none: "😊",
  carry: "😐",
  recommended: "😷",
  strong: "⚠️",
  indoors: "🏠",
};

export const trendMeta: Record<string, { icon: string; color: string; label: string }> = {
  improving: { icon: "↓", color: "#22c55e", label: "Improving" },
  worsening: { icon: "↑", color: "#ef4444", label: "Worsening" },
  steady: { icon: "→", color: "#94a3b8", label: "Stable" },
};

export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} hr ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function fmtDuration(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} hr`;
  return `${(seconds / 86400).toFixed(1)} d`;
}

export function fmtClock(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function tempDisplay(celsius: number | null | undefined, unit: "c" | "f"): string {
  if (celsius == null) return "—";
  return unit === "f" ? `${(celsius * 9 / 5 + 32).toFixed(1)}` : `${celsius.toFixed(1)}`;
}

export const prettyPollutant = (d: string | null | undefined): string =>
  d === "pm2_5" ? "PM2.5" : d === "pm10" ? "PM10" : (d ?? "—").toUpperCase();
