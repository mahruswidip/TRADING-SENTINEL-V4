import type { BacktestCurrentEvaluation, EvaluationStatus } from "@/domain/contracts";
import { StatusPill, statusTone } from "@/components/status-pill";

export function TimeframeFramework({ evaluation }: { evaluation: BacktestCurrentEvaluation }) {
  const statuses: readonly EvaluationStatus[] = [evaluation.biasStatus, evaluation.structureStatus, evaluation.entryStatus];
  return <div className="timeframes">{evaluation.timeframeFramework.map(({ timeframe, responsibility }, index) => <div key={timeframe} className={statuses[index] === "CONFIRMED" ? "is-complete" : "is-active"}><span>{timeframe}</span><div><strong>{responsibility}</strong><StatusPill label={statuses[index]} tone={statusTone(statuses[index])} /></div><b>{statuses[index] === "CONFIRMED" ? "✓" : "●"}</b></div>)}</div>;
}
