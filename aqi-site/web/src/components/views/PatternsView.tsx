import { useMemo, useState } from "react";
import { getCalendar, getDistribution, getDiurnal, getHeatmap, type DistBand } from "@/api";
import { aqiBand, bandMeta, bandOrder } from "@/lib/aqi";
import { useFetch } from "@/lib/useFetch";

export default function PatternsView({ activeSensor }: { activeSensor: string }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const calendar = useFetch(() => getCalendar(activeSensor, year), [activeSensor, year]).data ?? [];
  const diurnal = useFetch(() => getDiurnal(activeSensor, "30d"), [activeSensor]).data ?? [];
  const heat = useFetch(() => getHeatmap(activeSensor, "30d"), [activeSensor]).data ?? [];
  const dist = useFetch(() => getDistribution(activeSensor, "30d"), [activeSensor]).data ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <CalendarHeatmap year={year} setYear={setYear} data={calendar} />
      <DailyProfile diurnal={diurnal} />
      <WeeklyHeatmap cells={heat} />
      <TimeInBand dist={dist} />
    </div>
  );
}

function CalendarHeatmap({ year, setYear, data }: { year: number; setYear: (y: number) => void; data: { date: string; aqi: number }[] }) {
  const [hovered, setHovered] = useState<{ date: string; aqi: number } | null>(null);
  const byDate = useMemo(() => new Map(data.map((d) => [d.date, d.aqi])), [data]);

  const weeks = useMemo(() => {
    const first = new Date(Date.UTC(year, 0, 1));
    const startPad = first.getUTCDay();
    const days: ({ date: string; aqi: number | null } | null)[] = Array(startPad).fill(null);
    for (let d = new Date(first); d.getUTCFullYear() === year; d.setUTCDate(d.getUTCDate() + 1)) {
      const iso = d.toISOString().slice(0, 10);
      days.push({ date: iso, aqi: byDate.get(iso) ?? null });
    }
    const cols: ({ date: string; aqi: number | null } | null)[][] = [];
    for (let i = 0; i < days.length; i += 7) cols.push(days.slice(i, i + 7));
    return cols;
  }, [year, byDate]);

  const monthLabels = useMemo(() => {
    const seen = new Set<string>();
    return weeks.map((w, wi) => {
      const day = w.find(Boolean) as { date: string } | undefined;
      if (!day) return null;
      const m = new Date(day.date + "T00:00:00Z").toLocaleDateString("en", { month: "short", timeZone: "UTC" });
      if (seen.has(m)) return null;
      seen.add(m);
      return { wi, label: m };
    }).filter(Boolean) as { wi: number; label: string }[];
  }, [weeks]);

  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Year in air quality</p>
        <div className="flex items-center gap-2">
          {hovered && <span className="text-xs text-white/60">{hovered.date} — <span className="font-mono font-bold" style={{ color: bandMeta[aqiBand(hovered.aqi)].color }}>{hovered.aqi}</span></span>}
          <div className="flex items-center gap-1">
            <button onClick={() => setYear(year - 1)} className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 text-white/60 text-sm">‹</button>
            <span className="text-xs font-mono text-white/60 w-10 text-center">{year}</span>
            <button onClick={() => setYear(year + 1)} className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 text-white/60 text-sm">›</button>
          </div>
        </div>
      </div>

      <div className="flex mb-1 overflow-x-auto">
        {weeks.map((_, wi) => {
          const ml = monthLabels.find((m) => m.wi === wi);
          return <div key={wi} className="flex-shrink-0" style={{ width: 12, marginRight: 2 }}>{ml ? <span className="text-[8px] text-white/30">{ml.label}</span> : null}</div>;
        })}
      </div>

      <div className="flex gap-0.5 overflow-x-auto">
        <div className="flex flex-col gap-0.5 mr-1">
          {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
            <span key={i} className="text-[8px] text-white/20" style={{ width: 10, height: 10, lineHeight: "10px", textAlign: "center" }}>{d}</span>
          ))}
        </div>
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-0.5">
            {week.map((day, di) => (
              <div
                key={di}
                className="rounded-sm transition-transform hover:scale-125"
                style={{ width: 10, height: 10, backgroundColor: day?.aqi != null ? bandMeta[aqiBand(day.aqi)].color + "cc" : "#ffffff08" }}
                onMouseEnter={() => day?.aqi != null && setHovered({ date: day.date, aqi: day.aqi })}
                onMouseLeave={() => setHovered(null)}
                title={day?.aqi != null ? `${day.date}: AQI ${day.aqi}` : day?.date ?? ""}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function DailyProfile({ diurnal }: { diurnal: { hour: number; aqi: number | null; aqi_min: number | null; aqi_max: number | null }[] }) {
  const rows = diurnal.filter((h) => h.aqi != null) as { hour: number; aqi: number; aqi_min: number; aqi_max: number }[];
  if (rows.length < 2) return <Empty title="Average daily profile" />;
  const maxV = Math.max(...rows.map((h) => h.aqi_max), 100);
  const W = 600, H = 120;
  const PAD = { top: 8, right: 8, bottom: 20, left: 32 };
  const cw = W - PAD.left - PAD.right, ch = H - PAD.top - PAD.bottom;
  const toX = (h: number) => PAD.left + (h / 23) * cw;
  const toY = (v: number) => PAD.top + ch - (v / maxV) * ch;
  const avgPath = rows.map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.hour).toFixed(1)},${toY(p.aqi).toFixed(1)}`).join(" ");
  const areaPath = `${avgPath} L${toX(rows[rows.length - 1].hour)},${PAD.top + ch} L${toX(rows[0].hour)},${PAD.top + ch} Z`;
  const rangeTop = rows.map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.hour).toFixed(1)},${toY(p.aqi_max).toFixed(1)}`).join(" ");
  const rangeBottom = [...rows].reverse().map((p, i) => `${i === 0 ? "L" : "L"}${toX(p.hour).toFixed(1)},${toY(p.aqi_min).toFixed(1)}`).join(" ");
  const rangePath = `${rangeTop} ${rangeBottom} Z`;

  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">Average daily profile</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 120 }}>
        {[50, 100, 150].map((v) => { const y = toY(v); return y > PAD.top && y < PAD.top + ch ? <line key={v} x1={PAD.left} y1={y} x2={PAD.left + cw} y2={y} stroke="#ffffff12" strokeDasharray="3 3" /> : null; })}
        <path d={rangePath} fill="#38bdf820" />
        <path d={areaPath} fill="#38bdf815" />
        <path d={avgPath} fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" />
        {[0, 6, 12, 18, 23].map((h) => <text key={h} x={toX(h)} y={H - 4} textAnchor="middle" fontSize="9" fill="#ffffff30">{h}:00</text>)}
        {[50, 100].map((v) => { const y = toY(v); return y > PAD.top && y < PAD.top + ch ? <text key={v} x={PAD.left - 4} y={y + 3} textAnchor="end" fontSize="9" fill="#ffffff25">{v}</text> : null; })}
      </svg>
      <p className="text-xs text-white/30 mt-1">Shaded area shows min–max AQI range by hour</p>
    </div>
  );
}

const WEEK = [
  { day: "Mon", dow: 1 }, { day: "Tue", dow: 2 }, { day: "Wed", dow: 3 }, { day: "Thu", dow: 4 },
  { day: "Fri", dow: 5 }, { day: "Sat", dow: 6 }, { day: "Sun", dow: 0 },
];

function WeeklyHeatmap({ cells }: { cells: [number, number, number][] }) {
  const [hovered, setHovered] = useState<{ day: string; hour: number; aqi: number } | null>(null);
  const map = useMemo(() => {
    const m = new Map<string, number>();
    for (const [hour, dow, aqi] of cells) m.set(`${dow}:${hour}`, aqi);
    return m;
  }, [cells]);
  const maxAqi = Math.max(...cells.map((c) => c[2]), 1);

  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Typical weekly pattern</p>
        {hovered && <span className="text-xs text-white/50">{hovered.day} {hovered.hour}:00 — AQI <span className="font-mono font-bold text-white/80">{hovered.aqi}</span></span>}
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[400px]">
          <div className="flex mb-1 pl-10">
            {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => <div key={h} className="flex-1 text-[9px] text-white/25 text-center">{h}</div>)}
          </div>
          {WEEK.map(({ day, dow }) => (
            <div key={day} className="flex items-center gap-1 mb-0.5">
              <span className="text-[10px] text-white/30 w-9 flex-shrink-0">{day}</span>
              <div className="flex flex-1 gap-px">
                {Array.from({ length: 24 }, (_, hour) => {
                  const aqi = map.get(`${dow}:${hour}`);
                  const color = aqi == null ? "#ffffff08" : bandMeta[aqiBand(aqi)].color + Math.round((0.2 + (aqi / maxAqi) * 0.7) * 255).toString(16).padStart(2, "0");
                  return (
                    <div
                      key={hour}
                      className="flex-1 rounded-sm transition-transform hover:scale-110"
                      style={{ height: 14, backgroundColor: color }}
                      onMouseEnter={() => aqi != null && setHovered({ day, hour, aqi })}
                      onMouseLeave={() => setHovered(null)}
                      title={aqi != null ? `${day} ${hour}:00 — AQI ${aqi}` : ""}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TimeInBand({ dist }: { dist: DistBand[] }) {
  const shown = dist.filter((b) => b.pct > 0);
  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">Time in band (30 days)</p>
      {shown.length === 0 ? (
        <p className="text-sm text-white/30">No data yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {shown.map((b) => (
            <div key={b.band} className="flex items-center gap-3">
              <span className="text-base w-5 text-center" aria-hidden="true">{bandMeta[bandOrder[b.band]]?.icon ?? "●"}</span>
              <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${b.pct}%`, backgroundColor: b.color }} />
              </div>
              <span className="font-mono text-xs text-white/60 w-10 text-right tabular-nums">{b.pct}%</span>
              <span className="text-xs text-white/40 hidden sm:block">{b.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Empty({ title }: { title: string }) {
  return (
    <div className="rounded-2xl bg-white/4 border border-white/10 p-4">
      <p className="text-xs text-white/40 uppercase tracking-widest font-medium mb-3">{title}</p>
      <p className="text-sm text-white/30 py-6 text-center">Not enough data yet.</p>
    </div>
  );
}
