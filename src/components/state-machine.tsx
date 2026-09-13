import type { TradingState } from "@/domain/contracts";

const stages: readonly TradingState[] = ["SCANNING", "HTF_CONTEXT_FOUND", "BIAS_LOCKED", "WAITING_MTF_STRUCTURE", "MTF_CONFIRMED", "WAITING_LTF_ENTRY", "ENTRY_TRIGGERED", "RISK_VALIDATION", "TRADE_OPEN", "TRADE_CLOSED"];

export function StateMachine({ current }: { current: TradingState }) {
  const currentIndex = stages.indexOf(current);
  return <ol className="state-machine">{stages.map((stage, index) => <li key={stage} className={index < currentIndex ? "is-complete" : index === currentIndex ? "is-current" : ""}><span>{index < currentIndex ? "✓" : index + 1}</span><small>{stage.replaceAll("_", " ")}</small></li>)}</ol>;
}
