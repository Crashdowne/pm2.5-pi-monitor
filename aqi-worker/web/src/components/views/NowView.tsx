import { getCurrent, type SensorRow, type SiteConfig } from "@/api";
import { aqiBand, fmtAge, metaFor, prettyPollutant, tempDisplay, trendMeta } from "@/lib/aqi";
import { computeAdvice } from "@/lib/mask";
import { useFetch } from "@/lib/useFetch";
import AQIBadge from "@/components/AQIBadge";
import ArcGauge from "@/components/ArcGauge";
import MaskAdvisorCard from "@/components/MaskAdvisorCard";
import SensorSwitcher from "@/components/SensorSwitcher";
import StatCard from "@/components/StatCard";

interface Props {
  config: SiteConfig;
  sensors: SensorRow[];
  activeSensor: string;
  onSensorChange: (id: string) => void;
  sensitivity: string;
  onSensitivityChange: (s: string) => void;
  tempUnit: "c" | "f";
}

export default function NowView({
  config, sensors, activeSensor, onSensorChange, sensitivity, onSensitivityChange, tempUnit,
}: Props) {
  const { data: cur, loading } = useFetch(() => getCurrent(activeSensor), [activeSensor], 15000);

  if (!cur) {
    return <div className="p-8 text-center text-white/40">{loading ? "Loading…" : "No readings yet."}</div>;
  }

  const meta = metaFor(cur.nowcast_aqi);
  const band = aqiBand(cur.nowcast_aqi);
  const trend = trendMeta[cur.trend] ?? trendMeta.steady;
  const advice = computeAdvice(config, cur, sensitivity);
  const alarming = ["sensitive", "unhealthy", "vunhealthy", "hazardous"].includes(band);
  const sensitivities = Object.keys(config.mask.presets);

  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      {alarming && !cur.stale && (
        <div className="rounded-xl p-3 flex items-start gap-3" style={{ backgroundColor: meta.color + "15", border: `1px solid ${meta.color}30` }}>
          <span className="text-lg mt-0.5" aria-hidden="true">{meta.icon}</span>
          <div>
            <p className="text-sm font-semibold" style={{ color: meta.color }}>{meta.label} air quality</p>
            <p className="text-xs text-white/60 mt-0.5">{advice.action}</p>
          </div>
        </div>
      )}

      {cur.stale && (
        <div className="rounded-xl bg-orange-500/15 border border-orange-500/30 p-3 flex items-start gap-3">
          <span className="text-lg mt-0.5" aria-hidden="true">📡</span>
          <div>
            <p className="text-sm font-semibold text-orange-300">Sensor offline</p>
            <p className="text-xs text-orange-300/70 mt-0.5">Last reading {fmtAge(cur.age_s)}. Data may be stale — check the Network tab.</p>
          </div>
        </div>
      )}

      <SensorSwitcher sensors={sensors} activeId={activeSensor} onChange={onSensorChange} />

      <div className="rounded-2xl p-5 relative overflow-hidden" style={{ background: `linear-gradient(160deg, ${meta.color}16 0%, #0f172a 80%)`, border: `1px solid ${meta.color}25` }}>
        <div className="absolute top-0 left-0 w-40 h-40 rounded-full blur-3xl pointer-events-none" style={{ backgroundColor: meta.color + "15" }} />
        <div className="relative flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <p className="text-xs text-white/40 uppercase tracking-widest font-medium">{cur.sensor_id}</p>
              {cur.stale && <span className="text-xs text-orange-400 font-medium">● Offline</span>}
            </div>
            <div className="flex items-end gap-2">
              <p className="font-mono text-7xl font-bold leading-none tabular-nums" style={{ color: cur.stale ? "#94a3b8" : meta.color }}>
                {cur.nowcast_aqi}
              </p>
              <div className="flex flex-col gap-1 pb-2">
                <span className="font-mono text-sm font-bold" style={{ color: trend.color }}>{trend.icon} {trend.label}</span>
                <span className="text-xs text-white/35">{fmtAge(cur.age_s)}</span>
              </div>
            </div>
            <AQIBadge aqi={cur.nowcast_aqi} size="md" />
          </div>
          <div className="flex-shrink-0">
            <ArcGauge aqi={cur.nowcast_aqi} color={cur.stale ? "#94a3b8" : meta.color} />
          </div>
        </div>
      </div>

      <MaskAdvisorCard
        advice={advice}
        sensitivity={sensitivity}
        sensitivities={sensitivities}
        onSensitivityChange={onSensitivityChange}
        disclaimer={config.mask.disclaimer}
      />

      <div className="grid grid-cols-2 gap-2">
        <StatCard label="PM2.5" value={cur.pm2_5 ?? "—"} unit="µg/m³" sub="Fine particles" />
        <StatCard label="PM10" value={cur.pm10 ?? "—"} unit="µg/m³" sub="Coarse particles" />
        <StatCard label="Temperature" value={tempDisplay(cur.temp, tempUnit)} unit={tempUnit === "f" ? "°F" : "°C"} />
        <StatCard label="Humidity" value={cur.rh ?? "—"} unit="%" />
      </div>

      <div className="rounded-xl bg-white/4 border border-white/10 p-3 flex items-center gap-3">
        <span className="text-2xl" aria-hidden="true">🔬</span>
        <div>
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Dominant Pollutant</p>
          <p className="text-sm text-white/80 font-medium">{prettyPollutant(cur.dominant)}</p>
        </div>
      </div>
    </div>
  );
}
