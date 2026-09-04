import { useState } from "react";
import { getStatus, type SensorRow } from "@/api";
import { fmtAge, fmtClock, fmtDuration, metaFor } from "@/lib/aqi";
import { useFetch } from "@/lib/useFetch";

interface Props {
  sensors: SensorRow[];
  activeSensor: string;
  onSensorChange: (id: string) => void;
}

export default function NetworkView({ sensors, activeSensor, onSensorChange }: Props) {
  const [selected, setSelected] = useState(activeSensor || sensors[0]?.sensor_id || "");
  const online = sensors.filter((s) => s.online).length;

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden="true">📡</span>
            <div>
              <p className="font-semibold text-white">Sensor network</p>
              <p className="text-sm text-white/50">Health and connectivity of your remote monitors.</p>
            </div>
          </div>
          <div className="text-right">
            <p className="font-mono text-xl font-bold tabular-nums" style={{ color: online === sensors.length ? "#22c55e" : "#f97316" }}>{online}/{sensors.length}</p>
            <p className="text-xs text-white/40">online</p>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {sensors.map((s) => {
          const meta = metaFor(s.aqi);
          const isSel = s.sensor_id === selected;
          return (
            <button
              key={s.sensor_id}
              onClick={() => { setSelected(s.sensor_id); onSensorChange(s.sensor_id); }}
              className={`rounded-2xl border p-4 text-left transition-all ${isSel ? "bg-white/10 border-white/20" : "bg-white/4 border-white/10 hover:bg-white/6"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: s.online ? "#22c55e" : "#f97316" }} />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-white truncate">{s.sensor_id}</p>
                    <p className="text-xs text-white/40">{s.online ? `AQI ${s.aqi} · ${meta.label}` : "Offline"}</p>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="text-xs font-medium" style={{ color: s.online ? "#22c55e" : "#f97316" }}>{s.online ? "Online" : "Offline"}</p>
                  <p className="text-xs text-white/35">{fmtAge(s.age_s)}</p>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${s.coverage_24h}%`, backgroundColor: s.coverage_24h >= 80 ? "#22c55e" : s.coverage_24h >= 50 ? "#eab308" : "#ef4444" }} />
                </div>
                <span className="text-xs font-mono text-white/50 tabular-nums w-24 text-right">{s.coverage_24h}% · {s.sht31_ok ? "SHT31 ✓" : "no env"}</span>
              </div>
            </button>
          );
        })}
      </div>

      {selected && <StatusDetail sensorId={selected} />}
    </div>
  );
}

function StatusDetail({ sensorId }: { sensorId: string }) {
  const { data: st } = useFetch(() => getStatus(sensorId), [sensorId], 30000);
  if (!st) return null;

  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium">{sensorId} — details</p>
        <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ backgroundColor: (st.online ? "#22c55e" : "#f97316") + "22", color: st.online ? "#22c55e" : "#f97316" }}>
          {st.online ? "Online" : "Offline"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <Field label="Last reading" value={fmtAge(st.last_reading_age_s)} sub={fmtClock(st.last_reading_ts)} />
        <Field label="Last sync" value={fmtAge(st.last_ingest_age_s)} sub={fmtClock(st.last_ingest_ts)} />
        <Field label="Sample period" value={`${st.sample_period_s}s`} sub={`~${Math.round(3600 / st.sample_period_s)}/hr`} />
        <Field label="GY-SHT31" value={st.sht31.ok ? "Reporting" : "No env data"} sub={`temp ${st.sht31.temp_pct_24h}% · rh ${st.sht31.rh_pct_24h}%`} accent={st.sht31.ok ? "#22c55e" : "#f97316"} />
      </div>

      <CoverageBar label="Coverage (24h)" cov={st.coverage_24h} />
      <CoverageBar label="Coverage (7d)" cov={st.coverage_7d} />

      <div>
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-2">Outages (7 days)</p>
        {st.gaps_7d.count === 0 ? (
          <p className="text-sm text-green-400/80">No outages in the last 7 days ✓</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {st.gaps_7d.items.map((g, i) => (
              <div key={i} className="flex items-center justify-between text-xs rounded-lg bg-white/4 px-3 py-2">
                <span className="text-white/60">{fmtClock(g.start)} → {g.ongoing ? "now" : fmtClock(g.end)}</span>
                <span className="font-mono" style={{ color: g.ongoing ? "#f97316" : "#eab308" }}>{fmtDuration(g.duration_s)}{g.ongoing ? " · ongoing" : ""}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-xl bg-white/4 border border-white/8 p-3">
      <p className="text-xs text-white/40">{label}</p>
      <p className="text-sm font-semibold mt-0.5" style={accent ? { color: accent } : {}}>{value}</p>
      {sub && <p className="text-xs text-white/35 font-mono mt-0.5">{sub}</p>}
    </div>
  );
}

function CoverageBar({ label, cov }: { label: string; cov: { pct: number; actual: number; expected: number } }) {
  const color = cov.pct >= 80 ? "#22c55e" : cov.pct >= 50 ? "#eab308" : "#ef4444";
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs text-white/40">{label}</p>
        <p className="text-xs font-mono text-white/50">{cov.pct}% · {cov.actual}/{cov.expected}</p>
      </div>
      <div className="h-2 rounded-full bg-white/8 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${cov.pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}
