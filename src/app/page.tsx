import { ActiveResearchRun } from "@/components/active-research-run";
import { DataStateBoundary } from "@/components/data-state";
import { Metric } from "@/components/metric";
import { PageHeading } from "@/components/page-heading";
import { Panel } from "@/components/panel";
import { StatusPill, statusTone } from "@/components/status-pill";
import { sentinelData } from "@/data";
import { compactTime, percent, usd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const data = await sentinelData.getOverview();
  const active = data.activeJob;
  const completed = data.jobs.filter((job) => job.status === "COMPLETED");

  return <>
    <PageHeading eyebrow="Research operations" title="Overview" description="Deterministic status across research, validation, and risk boundaries." />
    <div className="summary-grid">
      <Metric label="Running backtests" value={data.jobs.filter((job) => ["RUNNING", "RUNNING_FAST", "VALIDATING", "PREPARING_DATA"].includes(job.status)).length} detail={active?.currentEvaluation?.symbol ?? "No active symbol"} />
      <Metric label="Symbols processed" value={active ? `${active.universeProgress.processed} / ${active.universeProgress.total}` : "—"} detail={active?.eta ? `ETA ${active.eta}` : "No ETA"} />
      <Metric label="Strategies in research" value={data.strategies.filter((strategy) => strategy.lifecycle.stage !== "REAL").length} />
      <Metric label="Shadow strategies" value={data.strategies.filter((strategy) => strategy.lifecycle.stage === "SHADOW").length} />
      <Metric label="Real strategies" value={data.strategies.filter((strategy) => strategy.lifecycle.stage === "REAL").length} />
      <Metric label="Active positions" value={data.risk.activePositions} detail="Execution locked" />
      <Metric label="Account risk" value={`${data.risk.accountRiskPct.toFixed(1)}%`} tone="positive" />
      <Metric label="Daily PnL" value={usd(data.risk.dailyPnlUsd)} tone="neutral" />
      <Metric label="System health" value={data.system.overall} tone={data.system.overall === "HEALTHY" ? "positive" : "warning"} />
    </div>
    <div className="dashboard-grid">
      <Panel title="Active research run" eyebrow="Backtest monitor" className="span-2" action={active && <StatusPill label={active.status} tone="info" />}>
        <DataStateBoundary state={active ? "success" : "empty"}>{active && <ActiveResearchRun run={active} />}</DataStateBoundary>
      </Panel>
      <Panel title="System services" eyebrow="Health"><div className="service-list">{data.system.services.map((service) => <div key={service.name}><span><i className={`dot dot--${service.health.toLowerCase()}`} />{service.name}</span><small>{service.detail}</small></div>)}</div></Panel>
      <Panel title="Recent decisions" eyebrow="Audit trail" className="span-2"><div className="feed">{data.decisions.map((decision) => <article key={decision.id}><time>{compactTime(decision.timestamp)} UTC</time><div><strong>{decision.symbol} · {decision.strategyVersion}</strong><p>{decision.reason}</p></div><StatusPill label={decision.decision} tone={statusTone(decision.decision)} /></article>)}</div></Panel>
      <Panel title="Strategy activity" eyebrow="Recent"><div className="feed feed--compact">{data.activities.map((activity) => <article key={activity.id}><time>{compactTime(activity.timestamp)}</time><div><strong>{activity.strategyVersion}</strong><p>{activity.event}</p></div></article>)}</div></Panel>
      <Panel title="Recent backtest results" eyebrow="Aggregate fixed-notional · net of costs" className="span-3"><DataStateBoundary state={completed.length ? "success" : "empty"}><div className="result-row">{completed.map((job) => <div key={job.id}><span>{job.strategyVariant.strategyId}_{job.strategyVariant.strategyVersion}</span><strong className="text--positive">{job.metrics ? percent(job.metrics.netReturnPct) : "—"} aggregate net</strong><small>PF {job.metrics?.profitFactor.toFixed(2) ?? "—"} · Aggregate DD {job.metrics?.maxDrawdownPct.toFixed(1) ?? "—"}%</small></div>)}</div></DataStateBoundary></Panel>
    </div>
  </>;
}
