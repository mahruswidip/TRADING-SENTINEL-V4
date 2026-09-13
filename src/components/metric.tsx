import type { ReactNode } from "react";

export function Metric({ label, value, detail, tone = "neutral" }: { label: string; value: ReactNode; detail?: ReactNode; tone?: "positive" | "negative" | "warning" | "neutral" }) {
  return <div className="metric"><span className="metric__label">{label}</span><strong className={`metric__value text--${tone}`}>{value}</strong>{detail && <span className="metric__detail">{detail}</span>}</div>;
}
