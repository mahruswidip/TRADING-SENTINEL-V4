import type {
  BacktestJob,
  BacktestMetrics,
  DecisionLog,
  Position,
  RiskState,
  StrategyActivity,
  StrategyVersion,
  SystemHealth,
  TradingProfile,
} from "@/domain/contracts";

export const intradayProfile: TradingProfile = {
  id: "INTRADAY",
  label: "Intraday",
  timeframes: [
    { timeframe: "1D", responsibility: "Bias / Market Context" },
    { timeframe: "1H", responsibility: "Structure / Setup" },
    { timeframe: "5M", responsibility: "Entry / Execution" },
  ],
};

const trendContinuationV7Metrics: BacktestMetrics = {
  grossReturnPct: 38.4,
  netReturnPct: 34.7,
  winRatePct: 47.2,
  expectancyR: 0.24,
  profitFactor: 1.61,
  maxDrawdownPct: 7.4,
  tradeCount: 328,
  feesUsd: 1892.42,
  feesBps: 8,
  fundingUsd: 184.8,
  fundingBps: 0.8,
  slippageUsd: 706.33,
  slippageBps: 3,
  long: { trades: 184, netReturnPct: 21.8, profitFactor: 1.72 },
  short: { trades: 144, netReturnPct: 12.9, profitFactor: 1.48 },
};

const breakoutRetestV12Metrics: BacktestMetrics = {
  ...trendContinuationV7Metrics,
  netReturnPct: 28.9,
  profitFactor: 1.48,
  maxDrawdownPct: 8.6,
};

const rangeReversionV3Metrics: BacktestMetrics = {
  grossReturnPct: 7.8,
  netReturnPct: -2.6,
  winRatePct: 39.1,
  expectancyR: -0.04,
  profitFactor: 0.91,
  maxDrawdownPct: 16.8,
  tradeCount: 211,
  feesUsd: 2348.12,
  feesBps: 9.4,
  fundingUsd: -96.3,
  fundingBps: -0.4,
  slippageUsd: 1217.9,
  slippageBps: 4.9,
  long: { trades: 96, netReturnPct: 1.4, profitFactor: 1.05 },
  short: { trades: 115, netReturnPct: -4, profitFactor: 0.79 },
};

export const strategyArtifacts = {
  TREND_CONTINUATION_V7: {
    strategyId: "TREND_CONTINUATION", strategyVersion: "V7", name: "Trend Continuation", configHash: "cfg_7d39af2", codeCommit: "4f82c1a", datasetVersion: "binance-usdm-2026.08", feeModelVersion: "fees-v3", profile: intradayProfile, directionSupport: "BOTH",
    lifecycle: { stage: "OOS", backtest: "PASSED", oos: "PENDING", walkForward: "NOT_STARTED", shadow: "NOT_STARTED", canary: "NOT_STARTED", real: "NOT_STARTED" }, metrics: trendContinuationV7Metrics, robustnessScore: 82,
  },
  BREAKOUT_RETEST_V12: {
    strategyId: "BREAKOUT_RETEST", strategyVersion: "V12", name: "Breakout Retest", configHash: "cfg_12b084e", codeCommit: "4f82c1a", datasetVersion: "binance-usdm-2026.08", feeModelVersion: "fees-v3", profile: intradayProfile, directionSupport: "BOTH",
    lifecycle: { stage: "WALK_FORWARD", backtest: "PASSED", oos: "PASSED", walkForward: "PENDING", shadow: "NOT_STARTED", canary: "NOT_STARTED", real: "NOT_STARTED" }, metrics: breakoutRetestV12Metrics, robustnessScore: 76,
  },
  RANGE_REVERSION_V3: {
    strategyId: "RANGE_REVERSION", strategyVersion: "V3", name: "Range Reversion", configHash: "cfg_3ebf100", codeCommit: "30a19de", datasetVersion: "binance-usdm-2026.08", feeModelVersion: "fees-v3", profile: intradayProfile, directionSupport: "BOTH",
    lifecycle: { stage: "FAST_BACKTEST", backtest: "FAILED", oos: "NOT_STARTED", walkForward: "NOT_STARTED", shadow: "NOT_STARTED", canary: "NOT_STARTED", real: "NOT_STARTED" }, metrics: rangeReversionV3Metrics, robustnessScore: 34,
  },
} as const satisfies Record<string, StrategyVersion>;

export const strategies: readonly StrategyVersion[] = Object.values(strategyArtifacts);

const backtestRunFixtures: readonly BacktestJob[] = [
  {
    id: "bt_20260910_001",
    status: "RUNNING",
    universeProgress: { universe: "Binance USDⓈ-M Perpetual", processed: 130, total: 317 },
    strategyVariant: { strategyId: "TREND_CONTINUATION", strategyVersion: "V7", current: 3854, total: 9400 },
    tradingState: "WAITING_LTF_ENTRY",
    currentEvaluation: {
      symbol: "BTCUSDT",
      strategyId: "TREND_CONTINUATION",
      strategyVersion: "V7",
      profile: intradayProfile,
      timeframeFramework: intradayProfile.timeframes,
      currentState: "WAITING_LTF_ENTRY",
      currentVariant: 3854,
      biasStatus: "CONFIRMED",
      structureStatus: "CONFIRMED",
      entryStatus: "ANALYZING",
      marketContext: { bias: "BULLISH", location: "DISCOUNT", poi: "Daily demand 110,800–111,240", liquidity: "Buy-side liquidity above 113,400", invalidation: "Daily close below 109,950" },
      structure: { status: "CONFIRMED", event: "MSS", liquiditySweep: true, displacement: true, fvg: true },
      entry: { status: "SEARCHING", direction: "LONG", entryPrice: null, stopLoss: null, targets: [] },
    },
    completedEvaluations: [
      { id: "eval_8842", symbol: "ETHUSDT", strategyVersion: "TREND_CONTINUATION_V7", finalState: "TRADE_CLOSED", decision: "LONG", completedAt: "2026-09-10T04:32:08Z" },
      { id: "eval_8841", symbol: "SOLUSDT", strategyVersion: "TREND_CONTINUATION_V7", finalState: "REJECTED", decision: "REJECTED", completedAt: "2026-09-10T04:29:17Z" },
    ],
    startedAt: "2026-09-10T02:14:00Z",
    elapsed: "2h 18m",
    eta: "3h 21m",
    workerCount: 8,
    metrics: strategyArtifacts.TREND_CONTINUATION_V7.metrics,
    errorMessage: null,
  },
  {
    id: "bt_20260909_014",
    status: "COMPLETED",
    universeProgress: { universe: "Top 80 liquid perpetuals", processed: 80, total: 80 },
    strategyVariant: { strategyId: "BREAKOUT_RETEST", strategyVersion: "V12", current: 2400, total: 2400 },
    tradingState: "TRADE_CLOSED",
    currentEvaluation: null,
    completedEvaluations: [{ id: "eval_7710", symbol: "BTCUSDT", strategyVersion: "BREAKOUT_RETEST_V12", finalState: "TRADE_CLOSED", decision: "SHORT", completedAt: "2026-09-09T12:47:00Z" }],
    startedAt: "2026-09-09T08:05:00Z",
    elapsed: "4h 42m",
    eta: null,
    workerCount: 8,
    metrics: strategyArtifacts.BREAKOUT_RETEST_V12.metrics,
    errorMessage: null,
  },
  {
    id: "bt_20260910_002",
    status: "QUEUED",
    universeProgress: { universe: "Top 40 liquid perpetuals", processed: 0, total: 40 },
    strategyVariant: { strategyId: "LIQUIDITY_SWEEP_REVERSAL", strategyVersion: "V4", current: 0, total: 1120 },
    tradingState: "SCANNING",
    currentEvaluation: null,
    completedEvaluations: [],
    startedAt: null,
    elapsed: null,
    eta: null,
    workerCount: 0,
    metrics: null,
    errorMessage: null,
  },
  {
    id: "bt_20260908_008",
    status: "PAUSED",
    universeProgress: { universe: "Binance USDⓈ-M Perpetual", processed: 199, total: 317 },
    strategyVariant: { strategyId: "RANGE_REVERSION", strategyVersion: "V3", current: 1890, total: 3000 },
    tradingState: "WAIT",
    currentEvaluation: null,
    completedEvaluations: [],
    startedAt: "2026-09-08T01:30:00Z",
    elapsed: "6h 10m",
    eta: null,
    workerCount: 0,
    metrics: strategyArtifacts.RANGE_REVERSION_V3.metrics,
    errorMessage: null,
  },
  {
    id: "bt_20260907_003",
    status: "FAILED",
    universeProgress: { universe: "Top 120 liquid perpetuals", processed: 32, total: 120 },
    strategyVariant: { strategyId: "MOMENTUM_BREAK", strategyVersion: "V2", current: 509, total: 1880 },
    tradingState: "REJECTED",
    currentEvaluation: null,
    completedEvaluations: [],
    startedAt: "2026-09-07T19:16:00Z",
    elapsed: "1h 04m",
    eta: null,
    workerCount: 0,
    metrics: null,
    errorMessage: "Dataset checksum mismatch; run halted without fallback metrics.",
  },
];

const backtestRunsById = new Map(backtestRunFixtures.map((run) => [run.id, run]));

export const backtestJobs = backtestRunFixtures;
export const getBacktestRunFixture = (runId: string): BacktestJob | null => backtestRunsById.get(runId) ?? null;
export const getActiveBacktestRunFixture = (): BacktestJob | null => backtestRunFixtures.find((run) => run.status === "RUNNING") ?? null;
export const getStrategyArtifactFixture = (strategyId: string, strategyVersion: string): StrategyVersion | null =>
  strategies.find((strategy) => strategy.strategyId === strategyId && strategy.strategyVersion === strategyVersion) ?? null;

export const positions: readonly Position[] = [];

export const riskState: RiskState = { accountRiskPct: 0, dailyPnlUsd: 0, dailyLossRemainingUsd: 500, activePositions: 0, executionControl: "EXECUTION_LOCKED" };

export const systemHealth: SystemHealth = {
  overall: "DEGRADED",
  environment: "RESEARCH",
  exchangeConnection: "CONNECTED",
  engineStatus: "RUNNING",
  executionControl: "EXECUTION_LOCKED",
  lastHeartbeat: "2026-09-10T04:35:20Z",
  services: [
    { name: "Market Data", health: "HEALTHY", detail: "12s fresh" },
    { name: "Research Workers", health: "HEALTHY", detail: "8 / 8 online" },
    { name: "Backtest Workers", health: "HEALTHY", detail: `${getActiveBacktestRunFixture()?.workerCount ?? 0} active` },
    { name: "Shadow Engine", health: "OFFLINE", detail: "D0+D1 disabled" },
    { name: "Real Execution", health: "OFFLINE", detail: "Execution locked" },
    { name: "Archive Store", health: "DEGRADED", detail: "1 delayed write" },
  ],
};

export const decisions: readonly DecisionLog[] = [
  { id: "dec_1004", timestamp: "2026-09-10T04:34:51Z", symbol: "BTCUSDT", strategyVersion: "TREND_CONTINUATION_V7", fromState: "MTF_CONFIRMED", toState: "WAITING_LTF_ENTRY", decision: "WAIT", reason: "5M entry displacement has not closed." },
  { id: "dec_1003", timestamp: "2026-09-10T04:32:08Z", symbol: "ETHUSDT", strategyVersion: "TREND_CONTINUATION_V7", fromState: "ENTRY_TRIGGERED", toState: "RISK_VALIDATION", decision: "LONG", reason: "HTF bullish, 1H MSS confirmed, 5M trigger validated." },
  { id: "dec_1002", timestamp: "2026-09-10T04:29:17Z", symbol: "SOLUSDT", strategyVersion: "TREND_CONTINUATION_V7", fromState: "WAITING_MTF_STRUCTURE", toState: "REJECTED", decision: "REJECTED", reason: "Mandatory 1H displacement condition failed." },
  { id: "dec_1001", timestamp: "2026-09-10T04:25:44Z", symbol: "XRPUSDT", strategyVersion: "BREAKOUT_RETEST_V12", fromState: "WAITING_LTF_ENTRY", toState: "ENTRY_TRIGGERED", decision: "SHORT", reason: "5M retest rejected from premium with protected high." },
];

export const activities: readonly StrategyActivity[] = [
  { id: "act_31", timestamp: "2026-09-10T04:30:00Z", strategyVersion: "TREND_CONTINUATION_V7", event: `${getActiveBacktestRunFixture()?.universeProgress.processed ?? 0} / ${getActiveBacktestRunFixture()?.universeProgress.total ?? 0} symbols processed`, tone: "neutral" },
  { id: "act_30", timestamp: "2026-09-09T12:47:00Z", strategyVersion: "BREAKOUT_RETEST_V12", event: "Fast backtest passed; OOS gate passed", tone: "positive" },
  { id: "act_29", timestamp: "2026-09-08T07:40:00Z", strategyVersion: "RANGE_REVERSION_V3", event: "Paused after weak net expectancy", tone: "warning" },
];
