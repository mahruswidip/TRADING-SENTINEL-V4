import Link from "next/link";
import { BacktestControls } from "@/components/backtest-controls";
import { DataStateBoundary } from "@/components/data-state";
import { JobTable } from "@/components/job-table";
import { Metric } from "@/components/metric";
import { PageHeading } from "@/components/page-heading";
import { Panel } from "@/components/panel";
import { StateMachine } from "@/components/state-machine";
import { StatusPill, statusTone } from "@/components/status-pill";
import { TimeframeFramework } from "@/components/timeframe-framework";
import { D47LiveMonitor } from "@/components/d47-live-monitor";
import { sentinelData } from "@/data";
import { getD47MonitorSnapshot } from "@/data/d47-monitor";
import { bps, costUsd, percent, plainPercent } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function BacktestPage() {
  const [jobs, active, d47] = await Promise.all([sentinelData.getBacktestJobs(), sentinelData.getActiveBacktestRun(), getD47MonitorSnapshot()]);
  const selected = jobs.find((job) => job.source === "REAL_BACKTEST") ?? active;
  const metrics = selected?.metrics;
  const evaluation = selected?.currentEvaluation;
  const source = selected?.source ?? "MOCK";

  return <>
    <PageHeading eyebrow="D3 ready · research only" title="Backtest Monitor" description="Selected run metrics are isolated by source; engineering results remain net of explicit execution costs." />
    {d47 && <Panel title="D4.7 Live Research Monitor" eyebrow="SIGNAL REPLICATION · NOT A TRADE BACKTEST"><D47LiveMonitor initialSnapshot={d47} /></Panel>}
    <DataStateBoundary state={selected ? "success" : "empty"}>
      {selected && <>
        <Panel title={selected.id} eyebrow={`${source} · ${source === "REAL_BACKTEST" ? "ENGINEERING VERIFICATION" : "DETERMINISTIC FIXTURE"}`}>
          <BacktestControls run={selected} />
        </Panel>
        <div className="backtest-grid">
          <Panel title={evaluation?.symbol ?? (selected.status === "COMPLETED" ? "Completed result" : "No current symbol")} eyebrow={evaluation ? "Current evaluation" : "Selected run summary"} action={<div className="panel-actions"><StatusPill label={source} tone={source === "REAL_BACKTEST" ? "positive" : "warning"} /><StatusPill label={selected.tradingState} tone={statusTone(selected.tradingState)} /><Link className="button-link" href={`/backtest/replay/${selected.id}`}>Open replay</Link></div>}>
            <div className="current-task"><div><small>STRATEGY ARTIFACT</small><strong>{selected.strategyVariant.strategyId}_{selected.strategyVariant.strategyVersion}</strong></div><div><small>PROFILE</small><strong>{evaluation?.profile.label ?? "Intraday"}</strong></div><div><small>UNIVERSE</small><strong>{selected.universeProgress.universe}</strong></div></div>
            {evaluation && <TimeframeFramework evaluation={evaluation} />}
          </Panel>
          <Panel title="Trading state progression" eyebrow={`State machine · ${source}`} className="span-2"><StateMachine current={selected.tradingState} /></Panel>
          <Panel title="Selected run performance" eyebrow={`Aggregate fixed-notional research metrics · net of costs · ${source}`} className="span-3">
            <DataStateBoundary state={metrics ? "success" : "empty"}>
              {metrics && <>
                <div className="metrics-grid"><Metric label="Trades" value={metrics.tradeCount} /><Metric label="Aggregate gross return" value={percent(metrics.grossReturnPct)} detail="Before costs" /><Metric label="Aggregate net return" value={percent(metrics.netReturnPct)} tone={metrics.netReturnPct >= 0 ? "positive" : "negative"} detail={`${source} · not portfolio equity`} /><Metric label="Win rate" value={plainPercent(metrics.winRatePct)} /><Metric label="Expectancy" value={`${metrics.expectancyR.toFixed(2)}R`} tone={metrics.expectancyR >= 0 ? "positive" : "negative"} /><Metric label="Profit factor" value={metrics.profitFactor.toFixed(2)} /><Metric label="Aggregate fixed-notional DD" value={plainPercent(metrics.maxDrawdownPct)} tone="warning" /></div>
                <div className="cost-and-direction"><div><h3>Execution costs</h3><dl><div><dt>Fees</dt><dd>{costUsd(metrics.feesUsd)} · {bps(metrics.feesBps)}</dd></div><div><dt>Funding</dt><dd>{costUsd(metrics.fundingUsd)} · {bps(metrics.fundingBps)}</dd></div>{metrics.spreadUsd !== undefined && <div><dt>Spread</dt><dd>{costUsd(metrics.spreadUsd)} · {bps(metrics.spreadBps ?? 0)}</dd></div>}<div><dt>Slippage</dt><dd>{costUsd(metrics.slippageUsd)} · {bps(metrics.slippageBps)}</dd></div></dl></div><div><h3>LONG performance</h3><strong>{percent(metrics.long.netReturnPct)}</strong><span>{metrics.long.trades} trades · PF {metrics.long.profitFactor.toFixed(2)}</span></div><div><h3>SHORT performance</h3><strong>{percent(metrics.short.netReturnPct)}</strong><span>{metrics.short.trades} trades · PF {metrics.short.profitFactor.toFixed(2)}</span></div></div>
              </>}
            </DataStateBoundary>
          </Panel>
        </div>
      </>}
    </DataStateBoundary>
    <Panel title="Backtest jobs" eyebrow={`${jobs.length} provider jobs · MOCK + REAL BACKTEST`}><JobTable jobs={jobs} /></Panel>
  </>;
}
