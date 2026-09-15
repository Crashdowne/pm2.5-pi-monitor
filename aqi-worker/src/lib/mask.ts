// Asthma-aware mask advisor — TS port of aqi-site/aqi_site/mask.py, with the
// sensitivity presets from aqi-site/aqi_site/config.py. Informational only.

export const DISCLAIMER =
  "Informational only — not medical advice. Follow your asthma action plan.";

export const LEVELS = ["none", "carry", "recommended", "strong", "indoors"] as const;
export type Level = (typeof LEVELS)[number];

// level -> (short label, action text, color)
const META: Record<Level, [string, string, string]> = {
  none: ["No mask needed", "Air is good — enjoy normal activity.", "#2ea043"],
  carry: [
    "Carry one",
    "Carry an N95 and watch for symptoms; ease heavy or prolonged exertion.",
    "#d4a72c",
  ],
  recommended: [
    "Mask recommended",
    "Wear a well-fitted N95/KN95 for outdoor exertion and limit prolonged activity.",
    "#fb8500",
  ],
  strong: [
    "Strongly recommended",
    "Wear an N95/KN95 outdoors, keep trips short, and keep your reliever inhaler handy.",
    "#e5484d",
  ],
  indoors: [
    "Stay indoors",
    "Stay inside with HEPA filtration; wear an N95/KN95 only if you must go out.",
    "#a371f7",
  ],
};

// NowCast-AQI thresholds for (carry, recommended, strong, indoors). Default asthma.
export const MASK_PRESETS: Record<string, [number, number, number, number]> = {
  general: [76, 101, 151, 301],
  asthma: [51, 76, 101, 201],
  very_sensitive: [26, 51, 76, 151],
};

export function severity(level: string): number {
  const i = (LEVELS as readonly string[]).indexOf(level);
  return i < 0 ? 0 : i;
}

export function levelFor(
  aqiValue: number | null,
  thresholds: [number, number, number, number],
): Level {
  if (aqiValue === null || aqiValue === undefined) return "none";
  const [carry, recommended, strong, indoors] = thresholds;
  if (aqiValue >= indoors) return "indoors";
  if (aqiValue >= strong) return "strong";
  if (aqiValue >= recommended) return "recommended";
  if (aqiValue >= carry) return "carry";
  return "none";
}

export function describe(level: Level) {
  const [label, action, color] = META[level];
  const maskType =
    level === "none" || level === "carry" ? "N95 optional" : "Well-fitted N95 or KN95";
  return { level, severity: severity(level), label, action, color, mask_type: maskType };
}

export function allLevels() {
  return LEVELS.map((l) => describe(l));
}

export function recommend(
  aqiValue: number | null,
  thresholds: [number, number, number, number],
  opts: { dominant?: string | null; trend?: string | null } = {},
) {
  const payload = describe(levelFor(aqiValue, thresholds));
  return {
    ...payload,
    aqi: aqiValue,
    dominant: opts.dominant ?? null,
    trend: opts.trend ?? null,
    disclaimer: DISCLAIMER,
  };
}
