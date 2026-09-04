import type { SensorRow } from "@/api";
import { metaFor } from "@/lib/aqi";

interface Props {
  sensors: SensorRow[];
  activeId: string;
  onChange: (id: string) => void;
}

export default function SensorSwitcher({ sensors, activeId, onChange }: Props) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {sensors.map((s) => {
        const meta = metaFor(s.aqi);
        const active = s.sensor_id === activeId;
        return (
          <button
            key={s.sensor_id}
            onClick={() => onChange(s.sensor_id)}
            className={`flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-all
              ${active ? "bg-white/12 text-white" : "bg-white/5 text-white/50 hover:bg-white/8 hover:text-white/80"}`}
          >
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: s.online ? meta.color : "#6b7280" }} />
            <span>{s.sensor_id}</span>
            {s.online ? (
              <span className="font-mono text-xs tabular-nums" style={{ color: meta.color }}>{s.aqi}</span>
            ) : (
              <span className="text-xs text-orange-400">Offline</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
