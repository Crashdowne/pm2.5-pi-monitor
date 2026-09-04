// Small localStorage-backed settings store.

export interface Settings {
  sensor: string;
  range: string;
  sensitivity: string;
  tempUnit: "c" | "f";
  metric: string;
}

const KEY = "aqi-site-settings";

const DEFAULTS: Settings = {
  sensor: "",
  range: "24h",
  sensitivity: "asthma",
  tempUnit: "c",
  metric: "pm2_5",
};

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}
