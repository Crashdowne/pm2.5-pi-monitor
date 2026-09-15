import { useState } from "react";
import { exportUrl, getHistory } from "@/api";
import { aqiBand, bandMeta, bandOrder } from "@/lib/aqi";
import { useFetch } from "@/lib/useFetch";

const RANGES = ["6h", "24h", "7d", "30d"];

export default function HistoryView({ activeSensor }: { activeSensor: string }) {
  const [range, setRange] = useState("24h");
  const { data } = useFetch(() => getHistory(activeSensor, range), [activeSensor, range]);
  const points = (data ?? []).filter((p) => p.aqi != null);

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <div className="flex gap-1.5">
        {RANGES.map((r) => (
          <button
            key={r}
            onClick={() => setRange(r)}
            className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all
              ${range === r ? "bg-white/15 text-white" : "bg-white/5 text-white/40 hover:bg-white/8 hover:text-white/70"}`}
          >
            {r}
          </button>
        ))}
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4 relative">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">AQI over time</p>
          <a href={exportUrl(activeSensor, range, "csv")} download className="text-xs text-sky-300/80 hover:text-sky-300">Export CSV ↓</a>
        </div>
        {points.length < 2 ? (
          <p className="text-sm text-white/30 py-10 text-center">Not enough data for this range.</p>
        ) : (
          <LineChart points={points} range={range} />
        )}
      </div>

      <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">AQI scale</p>
        <div className="flex flex-col gap-2">
          {bandOrder.map((band) => {
            const m = bandMeta[band];
            return (
              <div key={band} className="flex items-center gap-3">
                <span className="text-base w-5 text-center" aria-hidden="true">{m.icon}</span>
                <div className="w-16 h-2 rounded-full" style={{ backgroundColor: m.color + "60" }} />
                <span className="text-xs font-mono text-white/50 w-14">{m.range}</span>
                <span className="text-xs text-white/60">{m.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {points.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Min", value: Math.min(...points.map((p) => p.aqi)) },
            { label: "Avg", value: Math.round(points.reduce((s, p) => s + p.aqi, 0) / points.length) },
            { label: "Max", value: Math.max(...points.map((p) => p.aqi)) },
          ].map((s) => (
            <div key={s.label} className="rounded-xl bg-white/5 border border-white/10 p-3 text-center">
              <p className="text-xs text-white/40 uppercase tracking-widest font-medium">{s.label}</p>
              <p className="font-mono text-xl font-bold text-white/90 tabular-nums mt-1">{s.value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LineChart({ points, range }: { points: { t: number; aqi: number }[]; range: string }) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const W = 600, H = 180;
  const PAD = { top: 12, right: 8, bottom: 32, left: 36 };
  const cw = W - PAD.left - PAD.right;
  const ch = H - PAD.top - PAD.bottom;
  const maxAqi = Math.max(...points.map((p) => p.aqi), 100);
  const minAqi = Math.min(...points.map((p) => p.aqi), 0);
  const toX = (i: number) => PAD.left + (i / (points.length - 1)) * cw;
  const toY = (aqi: number) => PAD.top + ch - ((aqi - minAqi) / (maxAqi - minAqi + 1)) * ch;
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p.aqi).toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${toX(points.length - 1).toFixed(1)},${(PAD.top + ch).toFixed(1)} L${PAD.left},${(PAD.top + ch).toFixed(1)} Z`;
  const bandLevels = [50, 100, 150, 200, 300];
  const bandColors = ["#22c55e", "#eab308", "#f97316", "#ef4444", "#a855f7"];
  const labelIndices = Array.from({ length: 5 }, (_, i) => Math.round((i / 4) * (points.length - 1)));
  const hovered = hoveredIdx !== null ? points[hoveredIdx] : null;

  const fmt = (t: number) => {
    const d = new Date(t * 1000);
    return range === "6h" || range === "24h"
      ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString([], { month: "short", day: "numeric" });
  };

  return (
    <>
      {hovered && (
        <div className="absolute top-12 right-4 bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-xs z-10 pointer-events-none">
          <p className="text-white/50">{fmt(hovered.t)}</p>
          <p className="font-mono font-bold text-sm" style={{ color: bandMeta[aqiBand(hovered.aqi)].color }}>{hovered.aqi}</p>
          <p className="text-white/40">{bandMeta[aqiBand(hovered.aqi)].label}</p>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 180 }} onMouseLeave={() => setHoveredIdx(null)}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
          </linearGradient>
        </defs>
        {bandLevels.map((level, i) => {
          const y = toY(level);
          if (y < PAD.top || y > PAD.top + ch) return null;
          return (
            <g key={level}>
              <line x1={PAD.left} y1={y} x2={PAD.left + cw} y2={y} stroke={bandColors[i]} strokeOpacity="0.2" strokeDasharray="4 4" />
              <text x={PAD.left - 4} y={y + 4} textAnchor="end" fontSize="9" fill={bandColors[i]} fillOpacity="0.6">{level}</text>
            </g>
          );
        })}
        <path d={areaPath} fill="url(#areaGrad)" />
        <path d={linePath} fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" />
        {points.map((_, i) => (
          <rect key={i} x={toX(i) - cw / points.length / 2} y={PAD.top} width={cw / points.length} height={ch} fill="transparent" onMouseEnter={() => setHoveredIdx(i)} />
        ))}
        {hoveredIdx !== null && (
          <>
            <line x1={toX(hoveredIdx)} y1={PAD.top} x2={toX(hoveredIdx)} y2={PAD.top + ch} stroke="#ffffff30" strokeWidth="1" />
            <circle cx={toX(hoveredIdx)} cy={toY(points[hoveredIdx].aqi)} r="4" fill={bandMeta[aqiBand(points[hoveredIdx].aqi)].color} stroke="#0f172a" strokeWidth="2" />
          </>
        )}
        {labelIndices.map((idx) => (
          <text key={idx} x={toX(idx)} y={H - 6} textAnchor="middle" fontSize="9" fill="#ffffff35">{fmt(points[idx]?.t ?? Date.now() / 1000)}</text>
        ))}
      </svg>
    </>
  );
}
