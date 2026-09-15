interface Props {
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  accent?: string;
  className?: string;
}

export default function StatCard({ label, value, unit, sub, accent, className = "" }: Props) {
  return (
    <div className={`rounded-2xl bg-white/5 border border-white/10 p-4 flex flex-col gap-1 ${className}`}>
      <p className="text-xs text-white/40 uppercase tracking-widest font-medium">{label}</p>
      <p className="font-mono text-2xl font-bold leading-none" style={accent ? { color: accent } : {}}>
        {value}
        {unit && <span className="text-sm font-normal text-white/50 ml-1">{unit}</span>}
      </p>
      {sub && <p className="text-xs text-white/40">{sub}</p>}
    </div>
  );
}
