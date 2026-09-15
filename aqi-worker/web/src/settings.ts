import { useCallback, useState } from "react";

export interface Settings {
  activeSensor: string;
  sensitivity: string;
  tempUnit: "c" | "f";
}

const KEY = "aqi-site-settings-v2";
const DEFAULTS: Settings = { activeSensor: "", sensitivity: "asthma", tempUnit: "c" };

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

export function useSettings(): [Settings, (patch: Partial<Settings>) => void] {
  const [settings, setSettings] = useState<Settings>(load);
  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  return [settings, update];
}
