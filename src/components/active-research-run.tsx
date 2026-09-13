import type { BacktestRun } from "@/domain/contracts";
import { Progress } from "@/components/progress";
import { StatusPill, statusTone } from "@/components/status-pill";
import { backtestProgressPct } from "@/lib/backtest";

export function ActiveResearchRun({ run }: { run: BacktestRun }) {
  const evaluation = run.currentEvaluation;
  if (!evaluation) return <p className="inline-empty">No evaluation is currently assigned.</p>;

  const stages = [
    ["1D Bias", evaluation.biasStatus],
    ["1H Structure", evaluation.structureStatus],
    ["5M Entry", evaluation.entryStatus],
  ] as const;

  return <div className="active-run-compact">
    <div className="active-run-compact__identity">
      <strong>{evaluation.symbol}</strong>
      <span>{evaluation.strategyId}_{evaluation.strategyVersion}</span>
      <small>{evaluation.profile.label} · 1D → 1H → 5M</small>
    </div>
    <div className="active-run-compact__state"><small>DETERMINISTIC STATE</small><StatusPill label={evaluation.currentState} tone={statusTone(evaluation.currentState)} /></div>
    <div className="active-run-compact__stages">{stages.map(([label, status]) => <div key={label}><span>{label}</span><StatusPill label={status} tone={statusTone(status)} /></div>)}</div>
    <div className="active-run-compact__progress"><Progress value={backtestProgressPct(run.universeProgress)} label={`${run.universeProgress.processed} / ${run.universeProgress.total} symbols`} /></div>
    <dl className="active-run-compact__stats">
      <div><dt>Variant</dt><dd>{run.strategyVariant.current} / {run.strategyVariant.total}</dd></div>
      <div><dt>Elapsed</dt><dd>{run.elapsed ?? "—"}</dd></div>
      <div><dt>ETA</dt><dd>{run.eta ?? "—"}</dd></div>
      <div><dt>Workers</dt><dd>{run.workerCount}</dd></div>
    </dl>
  </div>;
}
