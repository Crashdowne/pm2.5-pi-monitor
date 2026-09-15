import { useEffect, useMemo, useState } from "react";
import { getConfig, getSensors } from "@/api";
import { useFetch } from "@/lib/useFetch";
import { useSettings } from "@/settings";
import NowView from "@/components/views/NowView";
import HistoryView from "@/components/views/HistoryView";
import PatternsView from "@/components/views/PatternsView";
import ExposureView from "@/components/views/ExposureView";
import NetworkView from "@/components/views/NetworkView";
import AlertsView from "@/components/views/AlertsView";

type Tab = "now" | "history" | "patterns" | "exposure" | "network" | "alerts";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "now", label: "Now", icon: "◉" },
  { id: "history", label: "History", icon: "↗" },
  { id: "patterns", label: "Patterns", icon: "⊞" },
  { id: "exposure", label: "Exposure", icon: "🫁" },
  { id: "network", label: "Network", icon: "📡" },
  { id: "alerts", label: "Alerts", icon: "🔔" },
];

export default function App() {
  const config = useFetch(getConfig, []).data;
  const sensors = useFetch(getSensors, [], 30000).data ?? [];
  const [settings, update] = useSettings();
  const [tab, setTab] = useState<Tab>("now");

  const sensorIds = useMemo(() => sensors.map((s) => s.sensor_id), [sensors]);
  const preferred = useMemo(() => {
    if (sensors.length === 0) return "";
    const pool = sensors.some((s) => s.online) ? sensors.filter((s) => s.online) : sensors;
    return [...pool].sort((a, b) => a.age_s - b.age_s)[0].sensor_id;
  }, [sensors]);
  const activeSensor = sensorIds.includes(settings.activeSensor) ? settings.activeSensor : preferred;

  useEffect(() => {
    if (activeSensor && activeSensor !== settings.activeSensor) update({ activeSensor });
  }, [activeSensor, settings.activeSensor, update]);

  const sensitivity = config && !config.mask.presets[settings.sensitivity] ? config.mask.sensitivity : settings.sensitivity;

  if (!config) {
    return <div className="h-full flex items-center justify-center text-white/40">Loading…</div>;
  }

  const offline = sensors.filter((s) => !s.online).length;

  return (
    <div className="h-full flex flex-col bg-[#0b1120] text-white overflow-hidden">
      <header className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-white/8">
        <div className="flex items-center gap-2">
          <span className="text-lg" aria-hidden="true">🌬️</span>
          <span className="font-semibold text-sm tracking-tight">{config.site_title}</span>
        </div>
        <div className="flex items-center gap-3">
          {offline > 0 && (
            <button onClick={() => setTab("network")} className="text-xs text-orange-300 bg-orange-500/15 border border-orange-500/30 rounded-lg px-2 py-1">
              {offline} offline
            </button>
          )}
          <button
            onClick={() => update({ tempUnit: settings.tempUnit === "f" ? "c" : "f" })}
            className="text-xs font-mono text-white/60 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1 hover:bg-white/10"
          >
            {settings.tempUnit === "f" ? "°F" : "°C"}
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="h-full flex lg:flex-row flex-col">
          <nav className="hidden lg:flex flex-col gap-1 p-3 w-48 flex-shrink-0 border-r border-white/8">
            <p className="text-xs text-white/25 uppercase tracking-widest font-medium px-3 mb-2 mt-1">Navigation</p>
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all text-left
                  ${tab === t.id ? "bg-white/12 text-white" : "text-white/45 hover:bg-white/6 hover:text-white/80"}`}
              >
                <span className="text-base w-5 text-center" aria-hidden="true">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>

          <div className="flex-1 overflow-y-auto lg:max-w-2xl lg:mx-auto w-full">
            {sensorIds.length === 0 ? (
              <div className="p-8 text-center text-white/40">No sensor data in the warehouse yet.</div>
            ) : tab === "now" ? (
              <NowView
                config={config}
                sensors={sensors}
                activeSensor={activeSensor}
                onSensorChange={(id) => update({ activeSensor: id })}
                sensitivity={sensitivity}
                onSensitivityChange={(s) => update({ sensitivity: s })}
                tempUnit={settings.tempUnit}
              />
            ) : tab === "history" ? (
              <HistoryView activeSensor={activeSensor} />
            ) : tab === "patterns" ? (
              <PatternsView activeSensor={activeSensor} />
            ) : tab === "exposure" ? (
              <ExposureView activeSensor={activeSensor} />
            ) : tab === "network" ? (
              <NetworkView sensors={sensors} activeSensor={activeSensor} onSensorChange={(id) => update({ activeSensor: id })} />
            ) : (
              <AlertsView />
            )}
          </div>
        </div>
      </main>

      <nav className="lg:hidden flex-shrink-0 flex border-t border-white/8 bg-[#0b1120]/95 backdrop-blur-sm safe-bottom" aria-label="Main navigation">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition-all
              ${tab === t.id ? "text-sky-400" : "text-white/35 hover:text-white/60"}`}
          >
            <span className="text-lg leading-none">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
