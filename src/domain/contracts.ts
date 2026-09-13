export type Symbol = {
  readonly id: string;
  readonly baseAsset: string;
  readonly quoteAsset: "USDT";
  readonly contractType: "PERPETUAL";
  readonly status: "TRADING" | "HALTED";
};

export type Environment = "RESEARCH" | "SHADOW" | "CANARY" | "REAL";
export type Direction = "LONG" | "SHORT";
export type Decision = Direction | "WAIT" | "REJECTED";
export type HealthLevel = "HEALTHY" | "DEGRADED" | "OFFLINE";
export type LoadState = "loading" | "empty" | "success" | "degraded" | "error";

export type TradingState =
  | "SCANNING"
  | "HTF_CONTEXT_FOUND"
  | "BIAS_LOCKED"
  | "WAITING_MTF_STRUCTURE"
  | "MTF_CONFIRMED"
  | "WAITING_LTF_ENTRY"
  | "ENTRY_TRIGGERED"
  | "RISK_VALIDATION"
  | "TRADE_OPEN"
  | "TRADE_CLOSED"
  | "REJECTED"
  | "WAIT";

export type TradingProfile = {
  readonly id: "INTRADAY";
  readonly label: string;
  readonly timeframes: readonly [
    { readonly timeframe: "1D"; readonly responsibility: "Bias / Market Context" },
    { readonly timeframe: "1H"; readonly responsibility: "Structure / Setup" },
    { readonly timeframe: "5M"; readonly responsibility: "Entry / Execution" },
  ];
} | {
  readonly id: "INTRADAY_FVG";
  readonly label: string;
  readonly timeframes: readonly [
    { readonly timeframe: "1H"; readonly responsibility: "Direction / Bias" },
    { readonly timeframe: "15M"; readonly responsibility: "FVG / Setup Area" },
    { readonly timeframe: "5M"; readonly responsibility: "Confirmation / Entry" },
  ];
};

export type MarketContext = {
  readonly bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  readonly location: "PREMIUM" | "EQUILIBRIUM" | "DISCOUNT";
  readonly poi: string;
  readonly liquidity: string;
  readonly invalidation: string;
};

export type StructureState = {
  readonly status: "CONFIRMED" | "WAIT" | "INVALIDATED";
  readonly event: "BOS" | "MSS" | "CHOCH" | "NONE";
  readonly liquiditySweep: boolean;
  readonly displacement: boolean;
  readonly fvg: boolean;
};

export type EntryState = {
  readonly status: "SEARCHING" | "TRIGGERED" | "INVALIDATED";
  readonly direction: Direction | null;
  readonly entryPrice: number | null;
  readonly stopLoss: number | null;
  readonly targets: readonly number[];
};

export type PerformanceSlice = {
  readonly trades: number;
  readonly netReturnPct: number;
  readonly profitFactor: number;
};

export type BacktestMetrics = {
  /** Aggregate fixed-notional trade return; not portfolio-equity return. */
  readonly grossReturnPct: number;
  /** Aggregate fixed-notional trade return net of costs; may cross -100%. */
  readonly netReturnPct: number;
  readonly winRatePct: number;
  readonly expectancyR: number;
  readonly profitFactor: number;
  /** Aggregate fixed-notional PnL decline; not portfolio-equity drawdown. */
  readonly maxDrawdownPct: number;
  readonly tradeCount: number;
  readonly feesUsd: number;
  readonly feesBps: number;
  readonly fundingUsd: number;
  readonly fundingBps: number;
  readonly spreadUsd?: number;
  readonly spreadBps?: number;
  readonly slippageUsd: number;
  readonly slippageBps: number;
  readonly long: PerformanceSlice;
  readonly short: PerformanceSlice;
};

export type BacktestJobStatus = "QUEUED" | "PREPARING_DATA" | "RUNNING" | "RUNNING_FAST" | "VALIDATING" | "COMPLETED" | "PAUSED" | "FAILED" | "CANCELLED";

export type EvaluationStatus = "CONFIRMED" | "ANALYZING" | "WAIT" | "INVALIDATED" | "PENDING";

export type BacktestUniverseProgress = {
  readonly universe: string;
  readonly processed: number;
  readonly total: number;
};

export type StrategyVariantProgress = {
  readonly strategyId: string;
  readonly strategyVersion: string;
  readonly current: number;
  readonly total: number;
};

export type BacktestCurrentEvaluation = {
  readonly symbol: string;
  readonly strategyId: string;
  readonly strategyVersion: string;
  readonly profile: TradingProfile;
  readonly timeframeFramework: TradingProfile["timeframes"];
  readonly currentState: TradingState;
  readonly currentVariant: number;
  readonly biasStatus: EvaluationStatus;
  readonly structureStatus: EvaluationStatus;
  readonly entryStatus: EvaluationStatus;
  readonly marketContext: MarketContext | null;
  readonly structure: StructureState | null;
  readonly entry: EntryState | null;
};

export type CompletedEvaluation = {
  readonly id: string;
  readonly symbol: string;
  readonly strategyVersion: string;
  readonly finalState: TradingState;
  readonly decision: Decision;
  readonly completedAt: string;
};

export type BacktestRun = {
  readonly id: string;
  readonly source?: "MOCK" | "REAL_BACKTEST";
  readonly status: BacktestJobStatus;
  readonly universeProgress: BacktestUniverseProgress;
  readonly currentEvaluation: BacktestCurrentEvaluation | null;
  readonly strategyVariant: StrategyVariantProgress;
  readonly tradingState: TradingState;
  readonly completedEvaluations: readonly CompletedEvaluation[];
  readonly startedAt: string | null;
  readonly elapsed: string | null;
  readonly eta: string | null;
  readonly workerCount: number;
  readonly metrics: BacktestMetrics | null;
  readonly errorMessage: string | null;
  readonly datasetVersion?: string;
  readonly engineVersion?: string;
};

export type BacktestJob = BacktestRun;

export type GateStatus = "PASSED" | "PENDING" | "FAILED" | "NOT_STARTED";
export type StrategyLifecycleStage =
  | "RESEARCH"
  | "FAST_BACKTEST"
  | "ACCURATE_REPLAY"
  | "OOS"
  | "WALK_FORWARD"
  | "SHADOW"
  | "CANARY_REAL"
  | "REAL"
  | "DEV_PASSED"
  | "OOS_PENDING"
  | "OOS_PASSED"
  | "WALK_FORWARD_PENDING"
  | "WALK_FORWARD_PASSED"
  | "ROBUSTNESS_PASSED"
  | "RESEARCH_READY"
  | "RESEARCH_REJECTED";

export type StrategyLifecycle = {
  readonly stage: StrategyLifecycleStage;
  readonly backtest: GateStatus;
  readonly oos: GateStatus;
  readonly walkForward: GateStatus;
  readonly shadow: GateStatus;
  readonly canary: GateStatus;
  readonly real: GateStatus;
};

export type StrategyVersion = {
  readonly source?: "MOCK" | "ENGINEERING_REFERENCE" | "RESEARCH_CANDIDATE" | "RESEARCH_REJECTED";
  readonly researchRunId?: string;
  readonly strategyId: string;
  readonly strategyVersion: string;
  readonly name: string;
  readonly configHash: string;
  readonly codeCommit: string;
  readonly datasetVersion: string;
  readonly feeModelVersion: string;
  readonly profile: TradingProfile;
  readonly directionSupport: Direction | "BOTH";
  readonly lifecycle: StrategyLifecycle;
  readonly metrics: BacktestMetrics;
  readonly robustnessScore: number;
  readonly family?: string;
  readonly directionValidity?: "LONG_ONLY_VALID" | "SHORT_ONLY_VALID" | "BOTH_VALID" | "NOT_VALID";
  readonly devExpectancy?: number;
  readonly oosExpectancy?: number;
  readonly walkForwardExpectancy?: number;
  readonly rejectionReasons?: readonly string[];
  readonly replayRunId?: string | null;
};

export type ResearchRun = {
  readonly runId: string;
  readonly status: "RUNNING" | "COMPLETED" | "FAILED";
  readonly phase: "FAST_BACKTEST" | "OOS" | "WALK_FORWARD" | "ROBUSTNESS" | "COST_STRESS";
  readonly processed: number;
  readonly total: number;
  readonly currentStrategy: string;
  readonly currentVersion?: string;
  readonly currentSymbol: string;
  readonly currentMetrics?: {
    readonly netExpectancy: number;
    readonly profitFactor: number;
    readonly tradeCount: number;
    readonly robustnessScore: number;
  };
  readonly startedAt: string;
  readonly elapsed: string;
  readonly eta: string | null;
  readonly symbols: readonly string[];
};

export type Position = {
  readonly id: string;
  readonly symbol: string;
  readonly direction: Direction;
  readonly strategyVersion: string;
  readonly entryPrice: number;
  readonly markPrice: number;
  readonly stopLoss: number;
  readonly takeProfit: number;
  readonly executablePnlUsd: number;
};

export type RiskState = {
  readonly accountRiskPct: number;
  readonly dailyPnlUsd: number;
  readonly dailyLossRemainingUsd: number;
  readonly activePositions: number;
  readonly executionControl: ExecutionControlState;
};

export type ExecutionControlState = "EXECUTION_LOCKED" | "TRADING_ENABLED" | "KILL_SWITCH_ACTIVE";

export type DecisionLog = {
  readonly id: string;
  readonly timestamp: string;
  readonly symbol: string;
  readonly strategyVersion: string;
  readonly fromState: TradingState;
  readonly toState: TradingState;
  readonly decision: Decision;
  readonly reason: string;
};

export type SystemService = {
  readonly name: string;
  readonly health: HealthLevel;
  readonly detail: string;
};

export type SystemHealth = {
  readonly overall: HealthLevel;
  readonly environment: Environment;
  readonly exchangeConnection: "CONNECTED" | "DEGRADED" | "DISCONNECTED";
  readonly engineStatus: "RUNNING" | "IDLE" | "HALTED";
  readonly executionControl: ExecutionControlState;
  readonly lastHeartbeat: string;
  readonly services: readonly SystemService[];
};

export type StrategyActivity = {
  readonly id: string;
  readonly timestamp: string;
  readonly strategyVersion: string;
  readonly event: string;
  readonly tone: "positive" | "warning" | "neutral";
};

export type OverviewData = {
  readonly system: SystemHealth;
  readonly risk: RiskState;
  readonly activeJob: BacktestJob | null;
  readonly jobs: readonly BacktestJob[];
  readonly strategies: readonly StrategyVersion[];
  readonly positions: readonly Position[];
  readonly decisions: readonly DecisionLog[];
  readonly activities: readonly StrategyActivity[];
};
