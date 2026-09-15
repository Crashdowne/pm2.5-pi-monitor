import { aqiBand, bandMeta } from "@/lib/aqi";

interface Props {
  aqi: number;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

export default function AQIBadge({ aqi, size = "md", showLabel = true }: Props) {
  const meta = bandMeta[aqiBand(aqi)];
  const sizeClasses = {
    sm: "text-xs px-2 py-0.5 gap-1",
    md: "text-sm px-2.5 py-1 gap-1.5",
    lg: "text-base px-3 py-1.5 gap-2",
  }[size];

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium font-mono ${sizeClasses}`}
      style={{ backgroundColor: meta.color + "22", color: meta.color, border: `1px solid ${meta.color}44` }}
    >
      <span aria-hidden="true" className="leading-none">{meta.icon}</span>
      {showLabel && <span>{meta.label}</span>}
    </span>
  );
}
