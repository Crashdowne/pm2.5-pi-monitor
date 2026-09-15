import { useState } from "react";
import { getSummary, type PeriodStat } from "@/api";
import { metaFor } from "@/lib/aqi";
import { useFetch } from "@/lib/useFetch";

const PERIODS = ["24h", "7d", "30d"];

export default function ExposureView({ activeSensor }: { activeSensor: string }) {
  const [period, setPeriod] = useState("7d");
  const { data } = useFetch(() => getSummary(activeSensor), [activeSensor]);
  const all = data?.by_period ?? [];
  const stat = all.find((d) => d.period === period);

  if (!stat) return <div className="p-8 text-center text-white/40">Loading…</div>;

  const avgMeta = metaFor(stat.avg_aqi);
  const peakMeta = metaFor(stat.peak_aqi);
  const cig = stat.cigarettes ?? 0;
  const cigDesc = cig < 1 ? "Less than 1 cigarette equivalent — excellent"
    : cig < 5 ? "Low smoke exposure for the period"
    : cig < 20 ? "Moderate smoke exposure — comparable to light smoking"
    : "Heavy smoke exposure — seek cleaner air";

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <div className="flex gap-1.5">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all
              ${period === p ? "bg-white/15 text-white" : "bg-white/5 text-white/40 hover:bg-white/8 hover:text-white/70"}`}
          >
            {p}
          </button>
        ))}
      </div>

      <div className="rounded-2xl p-5 relative overflow-hidden" style={{ background: `linear-gradient(135deg, ${avgMeta.color}15 0%, #0f172a 80%)`, border: `1px solid ${avgMeta.color}25` }}>
        <div className="absolute -bottom-6 -right-6 w-32 h-32 rounded-full blur-3xl pointer-events-none" style={{ backgroundColor: avgMeta.color + "18" }} />
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-1">{period} average AQI</p>
        <div className="flex items-end gap-3 mb-2">
          <span className="font-mono text-6xl font-bold tabular-nums leading-none" style={{ color: avgMeta.color }}>{stat.avg_aqi ?? "—"}</span>
          <div className="pb-1"><span className="text-sm font-medium" style={{ color: avgMeta.color }}>{avgMeta.label}</span></div>
        </div>
        <div className="flex items-center gap-2 text-sm text-white/50">
          <span className="text-base">{avgMeta.icon}</span>
          <span>Overall {period === "24h" ? "today" : `last ${period}`} air quality</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-2xl bg-white/5 border border-white/10 p-4">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Peak AQI</p>
          <p className="font-mono text-2xl font-bold mt-1 tabular-nums" style={{ color: peakMeta.color }}>{stat.peak_aqi ?? "—"}</p>
          <p className="text-xs text-white/40 mt-0.5">{peakMeta.icon} {peakMeta.label}</p>
        </div>
        <div className="rounded-2xl bg-white/5 border border-white/10 p-4">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Unhealthy hours</p>
          <p className="font-mono text-2xl font-bold mt-1 text-white/90 tabular-nums">{stat.unhealthy_hours}</p>
          <p className="text-xs text-white/40 mt-0.5">AQI above 100</p>
        </div>
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-5">
        <div className="flex items-start gap-4">
          <span className="text-3xl" aria-hidden="true">🚬</span>
          <div className="flex flex-col gap-1">
            <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Cigarette equivalent</p>
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-3xl font-bold text-white/90 tabular-nums">{cig.toFixed(1)}</span>
              <span className="text-sm text-white/50">cigarettes</span>
            </div>
            <p className="text-xs text-white/50 mt-1">{cigDesc}</p>
            <p className="text-xs text-white/25 mt-1 italic">Based on the Berkeley Earth PM2.5 rule of thumb (~22 µg/m³ over a day ≈ 1 cigarette).</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-1.5" aria-hidden="true">
          {Array.from({ length: Math.min(Math.ceil(cig), 50) }, (_, i) => (
            <span key={i} className="text-base" style={{ opacity: i < cig ? 1 : 0.2 }}>🚬</span>
          ))}
          {cig > 50 && <span className="text-xs text-white/40 self-center">+{Math.ceil(cig) - 50} more</span>}
        </div>
      </div>

      <PeriodComparison all={all} />
    </div>
  );
}

function PeriodComparison({ all }: { all: PeriodStat[] }) {
  const maxBar = Math.max(...all.map((d) => d.avg_aqi ?? 0), 1);
  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">Period comparison</p>
      <div className="flex flex-col gap-2">
        {all.map((d) => {
          const m = metaFor(d.avg_aqi);
          return (
            <div key={d.period} className="flex items-center gap-3">
              <span className="text-xs text-white/40 w-8 font-mono">{d.period}</span>
              <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${((d.avg_aqi ?? 0) / maxBar) * 100}%`, backgroundColor: m.color }} />
              </div>
              <span className="font-mono text-xs tabular-nums w-8 text-right" style={{ color: m.color }}>{d.avg_aqi ?? "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
