import type { BacktestJob } from "@/domain/contracts";
import { plainPercent, percent } from "@/lib/format";
import { StatusPill, statusTone } from "@/components/status-pill";
import { backtestProgressPct } from "@/lib/backtest";

export function JobTable({ jobs }: { jobs: readonly BacktestJob[] }) {
  return <div className="table-scroll"><table><thead><tr><th>Run / Strategy</th><th>Source</th><th>Status</th><th>Universe</th><th>Progress</th><th>Current</th><th>Aggregate net return</th><th>PF</th><th>Aggregate DD</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td><strong>{job.strategyVariant.strategyId}_{job.strategyVariant.strategyVersion}</strong><small>{job.id}</small></td><td>{job.source ?? "MOCK"}</td><td><StatusPill label={job.status} tone={statusTone(job.status)} /></td><td>{job.universeProgress.universe}</td><td><strong>{plainPercent(backtestProgressPct(job.universeProgress))}</strong><small>{job.universeProgress.processed} / {job.universeProgress.total} symbols</small></td><td>{job.currentEvaluation?.symbol ?? "—"}</td><td className={job.metrics && job.metrics.netReturnPct < 0 ? "text--negative" : "text--positive"}>{job.metrics ? percent(job.metrics.netReturnPct) : "—"}</td><td>{job.metrics?.profitFactor.toFixed(2) ?? "—"}</td><td>{job.metrics ? plainPercent(job.metrics.maxDrawdownPct) : "—"}</td></tr>)}</tbody></table></div>;
}
