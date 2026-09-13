type Tone = "positive" | "negative" | "warning" | "info" | "neutral";

export function StatusPill({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return <span className={`status status--${tone}`}>{label.replaceAll("_", " ")}</span>;
}

export function statusTone(status: string): Tone {
  if (["HEALTHY", "CONNECTED", "COMPLETED", "PASSED", "LONG", "TRADE_CLOSED", "TRADING_ENABLED", "GOOD_MARKET"].includes(status)) return "positive";
  if (["FAILED", "REJECTED", "REJECT_DEVELOPMENT_EXPANSION", "TRIGGERED", "DISCONNECTED", "SHORT", "KILL_SWITCH_ACTIVE", "UNAVAILABLE", "WIDE_SPREAD"].includes(status)) return "negative";
  if (["WAIT", "WAITING_LTF_ENTRY", "WAITING_MTF_STRUCTURE", "PAUSED", "PENDING", "DEGRADED", "EXECUTION_LOCKED", "THIN_MARKET", "INSUFFICIENT_HISTORY", "NEW_LISTING", "EXTREME_VOLATILITY"].includes(status)) return "warning";
  if (["RUNNING", "BIAS_LOCKED", "MTF_CONFIRMED", "ENTRY_TRIGGERED", "RISK_VALIDATION"].includes(status)) return "info";
  return "neutral";
}
