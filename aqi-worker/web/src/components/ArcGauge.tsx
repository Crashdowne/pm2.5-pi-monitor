// Half-circle AQI gauge (0–300) matching the BreathEasy design.
export default function ArcGauge({ aqi, color }: { aqi: number; color: string }) {
  const capped = Math.min(Math.max(aqi, 0), 300);
  const pct = capped / 300;
  const r = 36;
  const cx = 44;
  const cy = 44;
  const circumference = Math.PI * r;

  return (
    <svg width="88" height="52" viewBox="0 0 88 52" fill="none" aria-hidden="true">
      <path d={`M8,44 A${r},${r} 0 0,1 ${cx * 2 - 8},44`} fill="none" stroke="#ffffff10" strokeWidth="6" strokeLinecap="round" />
      <path
        d={`M8,44 A${r},${r} 0 0,1 ${cx * 2 - 8},44`}
        fill="none"
        stroke={color}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${pct * circumference} ${circumference}`}
        pathLength={circumference}
      />
      {[50, 100, 150, 200, 300].map((v) => {
        const p = v / 300;
        const angle = Math.PI * p - Math.PI;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        return <circle key={v} cx={x} cy={y} r="2" fill="#ffffff20" />;
      })}
    </svg>
  );
}
