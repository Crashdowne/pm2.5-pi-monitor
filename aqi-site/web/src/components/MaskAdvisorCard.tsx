import type { Advice } from "@/lib/mask";

interface Props {
  advice: Advice;
  sensitivity: string;
  sensitivities: string[];
  onSensitivityChange: (s: string) => void;
  disclaimer: string;
}

const SENSITIVITY_LABEL: Record<string, string> = {
  general: "General",
  asthma: "Asthma",
  very_sensitive: "Very Sensitive",
};

export default function MaskAdvisorCard({ advice, sensitivity, sensitivities, onSensitivityChange, disclaimer }: Props) {
  const c = advice.color;
  return (
    <div
      className="rounded-2xl p-5 flex flex-col gap-4 relative overflow-hidden"
      style={{ background: `linear-gradient(135deg, ${c}18 0%, ${c}08 100%)`, border: `1px solid ${c}30` }}
    >
      <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl pointer-events-none" style={{ backgroundColor: c + "20" }} />

      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Mask Advisor</p>
          <p className="text-2xl leading-tight font-semibold text-white">{advice.label}</p>
        </div>
        <div className="text-4xl flex-shrink-0 mt-1" aria-label={advice.label}>{advice.icon}</div>
      </div>

      <div
        className="inline-flex items-center gap-2 self-start px-3 py-1.5 rounded-full text-sm font-semibold"
        style={{ backgroundColor: c + "22", color: c, border: `1px solid ${c}44` }}
      >
        {advice.maskType}
      </div>

      <p className="text-sm text-white/70 leading-relaxed">{advice.action}</p>

      <div className="flex flex-col gap-1.5 text-xs text-white/50">
        <span>Why: <span className="text-white/70">{advice.reason}</span></span>
        <span>Best time to go outside: <span className="text-white/70">{advice.bestTime}</span></span>
      </div>

      <div className="flex flex-col gap-2 pt-1 border-t border-white/10">
        <p className="text-xs text-white/40 uppercase tracking-widest font-medium">Sensitivity</p>
        <div className="flex gap-1.5">
          {sensitivities.map((s) => (
            <button
              key={s}
              onClick={() => onSensitivityChange(s)}
              className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all
                ${sensitivity === s ? "bg-white/15 text-white" : "bg-white/5 text-white/40 hover:bg-white/8"}`}
            >
              {SENSITIVITY_LABEL[s] ?? s}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-white/25 italic">{disclaimer}</p>
    </div>
  );
}
