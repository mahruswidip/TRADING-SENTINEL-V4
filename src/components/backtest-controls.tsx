import type { BacktestRun } from "@/domain/contracts";
import { Progress } from "@/components/progress";
import { StatusPill, statusTone } from "@/components/status-pill";
import { backtestProgressPct } from "@/lib/backtest";

export function BacktestControls({ run }: { run: BacktestRun }) {
  return <><div className="mock-controls"><span>Backend controls unavailable</span><StatusPill label={run.status} tone={statusTone(run.status)} /><button disabled title="Pause requires a backtest backend">Pause · unavailable</button><button className="button--danger" disabled title="Cancel requires a backtest backend">Cancel · unavailable</button></div><div className="run-strip"><Progress value={backtestProgressPct(run.universeProgress)} label={`${run.universeProgress.processed} / ${run.universeProgress.total} symbols`} /><dl><div><dt>Variants</dt><dd>{run.strategyVariant.current} / {run.strategyVariant.total}</dd></div><div><dt>Elapsed</dt><dd>{run.elapsed ?? "—"}</dd></div><div><dt>ETA</dt><dd>{run.eta ?? "—"}</dd></div><div><dt>Workers</dt><dd>{run.workerCount}</dd></div></dl></div></>;
}
