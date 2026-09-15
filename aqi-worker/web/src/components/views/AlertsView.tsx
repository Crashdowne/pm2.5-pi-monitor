import { useEffect, useState } from "react";
import { getAlerts, postAlerts, type AlertsView as AlertsData } from "@/api";
import { fmtAge, maskIcon } from "@/lib/aqi";

const LEVEL_LABEL: Record<string, string> = {
  none: "Everything", carry: "Carry", recommended: "Recommended", strong: "Strongly", indoors: "Stay indoors",
};

export default function AlertsView() {
  const [data, setData] = useState<AlertsData | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [notifyFrom, setNotifyFrom] = useState("recommended");
  const [interval, setInterval] = useState(60);
  const [quietEnabled, setQuietEnabled] = useState(false);
  const [quietStart, setQuietStart] = useState(22);
  const [quietEnd, setQuietEnd] = useState(7);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getAlerts().then((d) => {
      setData(d);
      setEnabled(d.enabled);
      setNotifyFrom(d.notify_from);
      setInterval(Math.round(d.min_interval_s / 60));
      setQuietEnabled(d.quiet_start_hour >= 0 && d.quiet_end_hour >= 0);
      if (d.quiet_start_hour >= 0) setQuietStart(d.quiet_start_hour);
      if (d.quiet_end_hour >= 0) setQuietEnd(d.quiet_end_hour);
    }).catch(() => {});
  }, []);

  async function save() {
    const updated = await postAlerts({
      enabled,
      notify_from: notifyFrom,
      min_interval_s: Math.max(300, interval * 60),
      quiet_start_hour: quietEnabled ? quietStart : -1,
      quiet_end_hour: quietEnabled ? quietEnd : -1,
    });
    setData(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const levels = data?.levels.filter((l) => l !== "none") ?? ["carry", "recommended", "strong", "indoors"];

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden="true">🔔</span>
            <div>
              <p className="font-semibold text-white">Alert settings</p>
              <p className="text-sm text-white/50">Push a notification when the air crosses a level that matters to you.</p>
            </div>
          </div>
          <Toggle on={enabled} onToggle={() => setEnabled((v) => !v)} />
        </div>
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">Notify me from</p>
        <div className="grid grid-cols-2 gap-2">
          {levels.map((l) => (
            <button
              key={l}
              onClick={() => setNotifyFrom(l)}
              className={`flex items-center gap-2 py-2 px-3 rounded-xl text-sm font-medium transition-all
                ${notifyFrom === l ? "bg-white/15 text-white" : "bg-white/5 text-white/45 hover:bg-white/8"}`}
            >
              <span>{maskIcon[l] ?? "😷"}</span>
              <span>{LEVEL_LABEL[l] ?? l}</span>
            </button>
          ))}
        </div>
        <p className="text-xs text-white/30 mt-3">You'll be alerted when the mask advisor reaches this level or higher.</p>
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4 flex items-center justify-between">
        <div>
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Minimum interval</p>
          <p className="text-xs text-white/30 mt-1">Avoid repeat alerts within this window.</p>
        </div>
        <div className="flex items-center gap-2">
          <input type="number" min={5} value={interval} onChange={(e) => setInterval(+e.target.value)}
            className="w-20 bg-white/8 border border-white/12 rounded-lg px-3 py-2 text-sm text-white font-mono text-right focus:outline-none focus:border-sky-500/50" />
          <span className="text-sm text-white/50">min</span>
        </div>
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Quiet hours</p>
          <Toggle on={quietEnabled} onToggle={() => setQuietEnabled((v) => !v)} />
        </div>
        {quietEnabled && (
          <>
            <div className="flex items-center gap-3">
              <HourInput label="From" value={quietStart} onChange={setQuietStart} />
              <HourInput label="To" value={quietEnd} onChange={setQuietEnd} />
            </div>
            <p className="text-xs text-white/30 mt-2">No alerts between {String(quietStart).padStart(2, "0")}:00 and {String(quietEnd).padStart(2, "0")}:00.</p>
          </>
        )}
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-2">Delivery channels</p>
        <div className="flex flex-col gap-1.5 text-sm">
          <Channel label="ntfy push" ok={!!data?.ntfy_configured} />
          <Channel label="Webhook" ok={!!data?.webhook_configured} />
        </div>
        <p className="text-xs text-white/25 mt-2 italic">Channels are configured in the server config (config.toml).</p>
      </div>

      {data && data.sensors.length > 0 && (
        <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-2">Recent alert state</p>
          <div className="flex flex-col gap-1.5">
            {data.sensors.map((s) => (
              <div key={s.sensor_id} className="flex items-center justify-between text-sm">
                <span className="text-white/70">{s.sensor_id}</span>
                <span className="text-white/40">{maskIcon[s.last_level] ?? ""} {s.last_level}{s.last_fired_ts ? ` · fired ${fmtAge(Math.floor(Date.now() / 1000) - s.last_fired_ts)}` : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={save}
        className={`rounded-xl py-3.5 font-semibold text-sm transition-all
          ${saved ? "bg-green-500/20 border border-green-500/40 text-green-400" : "bg-sky-500/20 border border-sky-500/30 text-sky-300 hover:bg-sky-500/30"}`}
      >
        {saved ? "✓ Saved" : "Save alert settings"}
      </button>
    </div>
  );
}

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <div
      role="checkbox" aria-checked={on} tabIndex={0}
      onClick={onToggle} onKeyDown={(e) => e.key === " " && onToggle()}
      className={`w-11 h-6 rounded-full transition-all relative cursor-pointer flex-shrink-0
        ${on ? "bg-sky-500/40 border border-sky-500/60" : "bg-white/10 border border-white/15"}`}
    >
      <div className="absolute top-0.5 w-5 h-5 rounded-full transition-all" style={{ left: on ? "calc(100% - 22px)" : "2px", backgroundColor: on ? "#38bdf8" : "#6b7280" }} />
    </div>
  );
}

function HourInput({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-1 flex-1">
      <label className="text-xs text-white/40">{label}</label>
      <input type="number" min={0} max={23} value={value}
        onChange={(e) => onChange(Math.max(0, Math.min(23, +e.target.value)))}
        className="bg-white/8 border border-white/12 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-sky-500/50" />
    </div>
  );
}

function Channel({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-white/70">{label}</span>
      <span className={ok ? "text-green-400" : "text-white/30"}>{ok ? "✓ configured" : "✗ not set"}</span>
    </div>
  );
}
