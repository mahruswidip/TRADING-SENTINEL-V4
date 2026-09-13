import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { backtestJobs, getActiveBacktestRunFixture, getBacktestRunFixture, getStrategyArtifactFixture } from "../src/data/fixtures.ts";
import { backtestProgressPct } from "../src/lib/backtest.ts";

const routes = ["src/app/page.tsx", "src/app/backtest/page.tsx", "src/app/backtest/replay/[runId]/page.tsx", "src/app/strategies/page.tsx", "src/app/shadow/page.tsx", "src/app/real/page.tsx", "src/app/journal/page.tsx", "src/app/risk/page.tsx", "src/app/data-system/page.tsx"];

test("all D0+D1 navigation routes exist", () => {
  for (const route of routes) assert.equal(existsSync(route), true, `${route} is missing`);
});

test("D4.5 signal discovery remains stable, evidence-only, and visible in Strategy Lab", () => {
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  const provider = readFileSync("src/data/d4-provider.ts", "utf8");
  const navigation = readFileSync("src/components/nav.tsx", "utf8");
  const spec = readFileSync("docs/D4_5_SIGNAL_DISCOVERY_SPEC.md", "utf8");
  assert.match(page, /Signal Discovery/);
  assert.match(page, /NOT A TRADING STRATEGY/);
  assert.match(page, /No BUY\/SELL action/);
  assert.match(provider, /getLatestD45Discovery/);
  assert.match(navigation, /through D4\.5 STABLE/);
  assert.match(spec, /OOS_NOT_ACCESSED/);
  assert.match(spec, /HISTORICAL_FEATURE_NOT_AVAILABLE/);
});

test("D2.5 market-data routes stay behind the V2 bridge", () => {
  for (const route of ["src/app/api/market-data/health/route.ts", "src/app/api/market-data/universe/route.ts", "src/app/api/market-data/candles/route.ts", "src/app/api/market-data/[resource]/route.ts"]) assert.equal(existsSync(route), true, `${route} is missing`);
  const routesSource = ["src/app/api/market-data/universe/route.ts", "src/app/api/market-data/candles/route.ts", "src/app/api/market-data/[resource]/route.ts"].map((file) => readFileSync(file, "utf8")).join("\n");
  assert.match(routesSource, /fetchMarketDataBridge/);
  assert.doesNotMatch(routesSource, /fapi\.binance\.com|fstream\.binance\.com/);
});

test("promotion controls remain disabled", () => {
  const card = readFileSync("src/components/strategy-card.tsx", "utf8");
  assert.match(card, /disabled[^>]*>Promote to Shadow/);
  assert.match(card, /disabled>Promote to Canary/);
  assert.match(card, /disabled>Promote to Real/);
});

test("pages consume providers instead of fixtures", () => {
  for (const route of routes.slice(0, 4)) assert.doesNotMatch(readFileSync(route, "utf8"), /data\/fixtures/);
});

test("all backtest views consume the same authoritative run state", () => {
  const active = getActiveBacktestRunFixture();
  assert.ok(active);
  assert.strictEqual(getBacktestRunFixture(active.id), active);
  assert.strictEqual(backtestJobs.find((run) => run.id === active.id), active);

  const overviewProvider = readFileSync("src/data/mock-provider.ts", "utf8");
  const backtestPage = readFileSync("src/app/backtest/page.tsx", "utf8");
  const progressConsumers = ["src/components/active-research-run.tsx", "src/components/backtest-controls.tsx", "src/components/job-table.tsx"];
  assert.match(overviewProvider, /activeJob: getActiveBacktestRunFixture\(\)/);
  assert.match(backtestPage, /getActiveBacktestRun\(\)/);
  for (const file of progressConsumers) assert.match(readFileSync(file, "utf8"), /backtestProgressPct/);
});

test("backtest progress is derived from processed and total symbols", () => {
  const active = getBacktestRunFixture("bt_20260910_001");
  assert.ok(active);
  assert.equal(backtestProgressPct(active.universeProgress), Math.round((130 / 317) * 100));
  assert.equal("progressPct" in active.universeProgress, false);
  assert.equal(backtestProgressPct({ universe: "empty", processed: 0, total: 0 }), 0);
});

test("run metrics reference the authoritative immutable strategy artifact", () => {
  for (const run of backtestJobs) {
    if (!run.metrics) continue;
    const strategy = getStrategyArtifactFixture(run.strategyVariant.strategyId, run.strategyVariant.strategyVersion);
    assert.ok(strategy, `Missing strategy artifact for ${run.id}`);
    assert.strictEqual(run.metrics, strategy.metrics, `Contradictory metrics for ${run.id}`);
  }
});

test("core trading state machine remains frozen", () => {
  const contracts = readFileSync("src/domain/contracts.ts", "utf8");
  for (const state of ["SCANNING", "HTF_CONTEXT_FOUND", "BIAS_LOCKED", "WAITING_MTF_STRUCTURE", "MTF_CONFIRMED", "WAITING_LTF_ENTRY", "ENTRY_TRIGGERED", "RISK_VALIDATION", "TRADE_OPEN", "TRADE_CLOSED", "REJECTED", "WAIT"]) assert.match(contracts, new RegExp(`\\| "${state}"`));
  for (const timeframe of ["1D", "1H", "5M"]) assert.match(contracts, new RegExp(`timeframe: "${timeframe}"`));
});

test("backtest contract separates run concerns", () => {
  const contracts = readFileSync("src/domain/contracts.ts", "utf8");
  for (const field of ["universeProgress", "currentEvaluation", "strategyVariant", "tradingState", "metrics", "completedEvaluations", "biasStatus", "structureStatus", "entryStatus", "currentVariant"]) assert.match(contracts, new RegExp(`readonly ${field}`));
});

test("D1.5 execution and cost semantics are explicit", () => {
  const source = ["src/domain/contracts.ts", "src/components/global-header.tsx", "src/data/fixtures.ts"].map((file) => readFileSync(file, "utf8")).join("\n");
  assert.match(source, /EXECUTION_LOCKED/);
  assert.doesNotMatch(source, /ARMED · SAFE/);
  for (const field of ["feesBps", "fundingBps", "slippageBps"]) assert.match(source, new RegExp(field));
});

test("strategy inventory is filterable and sortable", () => {
  const inventory = readFileSync("src/components/strategy-inventory.tsx", "utf8");
  assert.match(inventory, /type="search"/);
  assert.match(inventory, /changeSort/);
  assert.match(inventory, /Lifecycle stage/);
});

test("backtest monitor prefers and labels real artifacts", () => {
  const page = readFileSync("src/app/backtest/page.tsx", "utf8");
  assert.match(page, /jobs\.find\(\(job\) => job\.source === "REAL_BACKTEST"\)/);
  assert.match(page, /ENGINEERING VERIFICATION/);
  assert.match(page, /Selected run performance/);
});

test("milestone UI reports D4.5 stable and D4.6 complete", () => {
  const nav = readFileSync("src/components/nav.tsx", "utf8");
  assert.match(nav, /D0\+D1 through D4\.5 STABLE/);
  assert.match(nav, /D4\.6 COMPLETE/);
  assert.doesNotMatch(nav, /D2\.5 ACTIVE/);
});

test("D4.6 replication is artifact-backed and never presented as a strategy", () => {
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  const provider = readFileSync("src/data/d4-provider.ts", "utf8");
  const root = "state/signal-replication/d4_6_8733a768a0dd3dd4";
  for (const name of ["manifest.json", "source-signal-hashes.json", "resource-plan.json", "backfill-summary.json", "universe.json", "signal-a-replication.json", "signal-b-replication.json", "symbol-breadth.json", "temporal-stability.json", "cross-sectional-stability.json", "cost-hurdle.json", "replication-gate.json", "replication-report.md"]) assert.equal(existsSync(`${root}/${name}`), true, `${name} is missing`);
  const manifest = JSON.parse(readFileSync(`${root}/manifest.json`, "utf8"));
  const gate = JSON.parse(readFileSync(`${root}/replication-gate.json`, "utf8"));
  assert.equal(manifest.source_run, "d4_5_482ba89ea0075922");
  assert.equal(manifest.thresholds_changed, false);
  assert.equal(manifest.current_ticker_used_for_selection_or_features, false);
  assert.equal(manifest.oos_access, "OOS_NOT_ACCESSED");
  assert.equal(gate.decision, "STOP_NOT_REPLICATED");
  assert.match(page, /Signal Replication/);
  assert.match(page, /No BUY\/SELL action/);
  assert.match(provider, /getLatestD46Replication/);
});

test("D4.6B broader replication is immutable, OOS-safe, and UI-backed", () => {
  const root = "state/signal-replication/d4_6b_d9380c7ff0781bac";
  for (const name of ["manifest.json", "parent-run.json", "source-signal-hashes.json", "resource-plan.json", "backfill-summary.json", "signal-a.json", "signal-b.json", "temporal-stability.json", "symbol-breadth.json", "replication-gate.json", "replication-report.md"]) assert.equal(existsSync(`${root}/${name}`), true, `${name} is missing`);
  const manifest = JSON.parse(readFileSync(`${root}/manifest.json`, "utf8"));
  const gate = JSON.parse(readFileSync(`${root}/replication-gate.json`, "utf8"));
  assert.equal(manifest.parent_run, "d4_6_8733a768a0dd3dd4");
  assert.equal(manifest.oos_access, "OOS_NOT_ACCESSED");
  assert.equal(manifest.thresholds_changed, false);
  assert.equal(gate.primary_signal, "B");
  assert.equal(gate.signal_a_cannot_veto_signal_b, true);
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  assert.match(page, /NOT A TRADING STRATEGY/);
});

test("D4 Strategy Lab separates real research evidence from mocks", () => {
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  const provider = readFileSync("src/data/d4-provider.ts", "utf8");
  const inventory = readFileSync("src/components/strategy-inventory.tsx", "utf8");
  assert.match(page, /RESEARCH_CANDIDATE/);
  assert.match(page, /RESEARCH_REJECTED/);
  assert.match(page, /Legacy mock fixtures/);
  assert.match(provider, /stateRoot, "research"/);
  for (const label of ["Family", "Direction", "Dev", "OOS", "Walk Forward", "Net Expectancy", "Robustness", "Rejection Reason"]) assert.match(inventory, new RegExp(label, "i"));
});

test("D4 artifacts are available through the existing replay provider", () => {
  const source = readFileSync("src/data/replay-provider.ts", "utf8");
  assert.match(source, /researchScenarios/);
  assert.match(source, /state", "research/);
  assert.match(source, /evaluationStartTimestamp/);
});

test("D4.2 Strategy Lab reads Development expansion artifacts without claiming OOS", () => {
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  const provider = readFileSync("src/data/d4-provider.ts", "utf8");
  assert.match(page, /D4\.2 Development Expansion/);
  assert.match(page, /OOS eligible/);
  assert.match(provider, /expansion-run\.json/);
  assert.match(provider, /OOS_NOT_ACCESSED/);
});

test("D4.3 labels aggregate research metrics separately from portfolio equity", () => {
  const strategyPage = readFileSync("src/app/strategies/page.tsx", "utf8");
  const backtestPage = readFileSync("src/app/backtest/page.tsx", "utf8");
  const strategyCard = readFileSync("src/components/strategy-card.tsx", "utf8");
  assert.match(strategyPage, /Aggregate net return/);
  assert.match(strategyPage, /Reference equity return/);
  assert.match(strategyPage, /Reference equity max DD/);
  assert.match(backtestPage, /not portfolio equity/);
  assert.match(strategyCard, /Aggregate fixed-notional DD/);

  const audit = JSON.parse(readFileSync("state/accounting-audit/d4_3_1235e58bcfd04d0c/accounting-audit.json", "utf8"));
  const semantics = JSON.parse(readFileSync("state/accounting-audit/d4_3_1235e58bcfd04d0c/equity-semantics.json", "utf8"));
  assert.equal(audit.oos_access, "OOS_NOT_ACCESSED");
  assert.equal(audit.v3_created, false);
  assert.equal(audit.breakout_regime_decision, "REGIME_HYPOTHESIS_NOT_JUSTIFIED");
  assert.ok(semantics.reference_portfolio_equity.RANGE_REVERSION_V2.aggregate_normalized_net_return_pct < -100);
  assert.ok(semantics.reference_portfolio_equity.RANGE_REVERSION_V2.portfolio_max_drawdown_pct <= 100);
});

test("D4.4 Strategy Lab exposes triage and the sole FVG V1 Development artifact", () => {
  const page = readFileSync("src/app/strategies/page.tsx", "utf8");
  const provider = readFileSync("src/data/d4-provider.ts", "utf8");
  assert.match(page, /D4\.4 Triage \+ FVG Pullback/);
  assert.match(page, /FVG_PULLBACK_V1/);
  assert.match(page, /1H → 15M → 5M · M1 deferred/);
  assert.match(provider, /remaining-families\.json/);
  assert.match(provider, /fvg-funnel\.json/);
  assert.equal(existsSync("state/research/FVG_PULLBACK_V2"), false);

  const runId = "d4_4_7c26a8a6736abaf2";
  const manifest = JSON.parse(readFileSync(`state/research/FVG_PULLBACK_V1/${runId}/manifest.json`, "utf8"));
  const gate = JSON.parse(readFileSync(`state/research/FVG_PULLBACK_V1/${runId}/gate-result.json`, "utf8"));
  assert.equal(manifest.label, "NEW RESEARCH HYPOTHESIS");
  assert.equal(manifest.validation, "NOT VALIDATED");
  assert.equal(manifest.phase, "DEVELOPMENT ONLY");
  assert.equal(manifest.rules.m1_execution, "DEFERRED_NOT_IMPLEMENTED");
  assert.equal(manifest.oos_access, "OOS_NOT_ACCESSED");
  assert.equal(manifest.locked_oos_resolved_or_read, false);
  assert.equal(gate.status, "RESEARCH_REJECTED");
});
