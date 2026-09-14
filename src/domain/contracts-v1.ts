import type { BacktestJobStatus, Environment, ExecutionControlState, GateStatus, HealthLevel, TradingState } from "@/domain/contracts";

export const CONTRACT_VERSION_V1 = "1.0.0" as const;

export const TRADING_STATES_V1 = [
  "SCANNING", "HTF_CONTEXT_FOUND", "BIAS_LOCKED", "WAITING_MTF_STRUCTURE", "MTF_CONFIRMED", "WAITING_LTF_ENTRY",
  "ENTRY_TRIGGERED", "RISK_VALIDATION", "TRADE_OPEN", "TRADE_CLOSED", "REJECTED", "WAIT",
] as const satisfies readonly TradingState[];

export const BACKTEST_JOB_STATUSES_V1 = [
  "QUEUED", "PREPARING_DATA", "RUNNING", "RUNNING_FAST", "VALIDATING", "COMPLETED", "PAUSED", "FAILED", "CANCELLED",
] as const satisfies readonly BacktestJobStatus[];

export const GATE_STATUSES_V1 = ["PASSED", "PENDING", "FAILED", "NOT_STARTED"] as const satisfies readonly GateStatus[];
export const ENVIRONMENTS_V1 = ["RESEARCH", "SHADOW", "CANARY", "REAL"] as const satisfies readonly Environment[];
export const HEALTH_LEVELS_V1 = ["HEALTHY", "DEGRADED", "OFFLINE"] as const satisfies readonly HealthLevel[];
export const EXECUTION_CONTROL_STATES_V1 = ["EXECUTION_LOCKED", "TRADING_ENABLED", "KILL_SWITCH_ACTIVE"] as const satisfies readonly ExecutionControlState[];
export const REPLAY_STATUSES_V1 = ["IDLE", "PLAYING", "PAUSED", "COMPLETE"] as const;
export const PROVIDER_STATES_V1 = ["LOADING", "CONNECTED", "DEGRADED", "ERROR"] as const;
export const EVALUATION_STATUSES_V1 = ["CONFIRMED", "ANALYZING", "WAIT", "INVALIDATED", "PENDING"] as const;
export const EXCHANGE_CONNECTION_STATES_V1 = ["CONNECTED", "DEGRADED", "DISCONNECTED"] as const;
export const ENGINE_STATUSES_V1 = ["RUNNING", "IDLE", "HALTED"] as const;
export const PROMOTION_REQUEST_STATUSES_V1 = ["PENDING_OPERATOR_APPROVAL", "APPROVED", "REJECTED", "APPLIED"] as const;

export const PROMOTION_STAGES_V1 = [
  "RESEARCH", "FAST_BACKTEST", "ACCURATE_REPLAY", "OOS", "WALK_FORWARD", "SHADOW", "CANARY_REAL", "REAL",
] as const;
export type PromotionStageV1 = (typeof PROMOTION_STAGES_V1)[number];

export const PROMOTION_GATES_V1 = [
  "SUFFICIENT_SAMPLE", "POSITIVE_NET_EXPECTANCY", "ACCEPTABLE_PROFIT_FACTOR", "ACCEPTABLE_DRAWDOWN",
  "DIRECTION_STABILITY", "ACCURATE_REPLAY_PASSED", "FEE_STRESS_PASSED", "SLIPPAGE_STRESS_PASSED",
  "OOS_PASSED", "WALK_FORWARD_PASSED", "SHADOW_PASSED", "CANARY_PASSED",
] as const;
export type PromotionGateV1 = (typeof PROMOTION_GATES_V1)[number];

export type PromotionGateEvidenceV1 = {
  readonly gate: PromotionGateV1;
  readonly status: GateStatus;
  readonly threshold: string;
  readonly observed: string;
  readonly artifact_id: string;
};

export const PROMOTION_TRANSITIONS_V1 = {
  RESEARCH: "FAST_BACKTEST",
  FAST_BACKTEST: "ACCURATE_REPLAY",
  ACCURATE_REPLAY: "OOS",
  OOS: "WALK_FORWARD",
  WALK_FORWARD: "SHADOW",
  SHADOW: "CANARY_REAL",
  CANARY_REAL: "REAL",
  REAL: null,
} as const satisfies Record<PromotionStageV1, PromotionStageV1 | null>;

export const PROMOTION_REQUIREMENTS_V1 = {
  FAST_BACKTEST: [],
  ACCURATE_REPLAY: ["SUFFICIENT_SAMPLE", "POSITIVE_NET_EXPECTANCY", "ACCEPTABLE_PROFIT_FACTOR", "ACCEPTABLE_DRAWDOWN", "DIRECTION_STABILITY"],
  OOS: ["ACCURATE_REPLAY_PASSED", "FEE_STRESS_PASSED", "SLIPPAGE_STRESS_PASSED"],
  WALK_FORWARD: ["OOS_PASSED"],
  SHADOW: ["WALK_FORWARD_PASSED"],
  CANARY_REAL: ["SHADOW_PASSED"],
  REAL: ["CANARY_PASSED"],
} as const satisfies Record<Exclude<PromotionStageV1, "RESEARCH">, readonly PromotionGateV1[]>;

export const MANUAL_APPROVAL_STAGES_V1 = ["SHADOW", "CANARY_REAL", "REAL"] as const satisfies readonly PromotionStageV1[];

export function isPromotionTransitionV1(from: PromotionStageV1, to: PromotionStageV1): boolean {
  return PROMOTION_TRANSITIONS_V1[from] === to;
}

export type StrategyIdentityV1 = {
  readonly strategy_id: string;
  readonly strategy_version: string;
  readonly config_hash: string;
  readonly code_commit: string;
  readonly dataset_version: string;
  readonly fee_model_version: string;
  readonly execution_model_version: string;
};

export type ApiEnvelopeV1<T> = {
  readonly contract_version: typeof CONTRACT_VERSION_V1;
  readonly generated_at: string;
  readonly data: T;
};

export type ApiErrorV1 = {
  readonly contract_version: typeof CONTRACT_VERSION_V1;
  readonly error: {
    readonly code: "VALIDATION_ERROR" | "NOT_FOUND" | "CONFLICT" | "UNAUTHORIZED" | "FORBIDDEN" | "RATE_LIMITED" | "UPSTREAM_UNAVAILABLE" | "INTERNAL_ERROR";
    readonly message: string;
    readonly request_id: string;
  };
};

export type PerformanceSliceV1 = {
  readonly trades: number;
  readonly net_return_pct: number;
  readonly profit_factor: number;
};

export type BacktestMetricsV1 = {
  readonly trades: number;
  readonly gross_return_pct: number;
  readonly net_return_pct: number;
  readonly win_rate_pct: number;
  readonly expectancy_r: number;
  readonly profit_factor: number;
  readonly max_drawdown_pct: number;
  readonly fees_usd: number;
  readonly funding_usd: number;
  readonly spread_usd: number;
  readonly slippage_usd: number;
  readonly long: PerformanceSliceV1;
  readonly short: PerformanceSliceV1;
};

export type BacktestLiveStatusV1 = {
  readonly run_id: string;
  readonly state: BacktestJobStatus;
  readonly progress: {
    readonly symbols_done: number;
    readonly symbols_total: number;
    readonly variants_done: number;
    readonly variants_total: number;
  };
  readonly current: {
    readonly symbol: string;
    readonly strategy: StrategyIdentityV1;
    readonly profile: "INTRADAY" | "INTRADAY_FVG";
    readonly stage: TradingState;
    readonly timeframe: "1d" | "1h" | "15m" | "5m";
  } | null;
  readonly metrics: BacktestMetricsV1 | null;
  readonly updated_at: string;
};

export type StrategyVersionV1 = {
  readonly identity: StrategyIdentityV1;
  readonly name: string;
  readonly profile: "INTRADAY" | "INTRADAY_FVG";
  readonly direction_support: "LONG" | "SHORT" | "BOTH";
  readonly promotion_stage: PromotionStageV1;
  readonly gate_evidence: readonly PromotionGateEvidenceV1[];
  readonly metrics: BacktestMetricsV1;
  readonly robustness_score: number;
  readonly rejection_reasons: readonly string[];
};

export type SystemHealthV1 = {
  readonly overall: HealthLevel;
  readonly environment: Environment;
  readonly exchange_connection: "CONNECTED" | "DEGRADED" | "DISCONNECTED";
  readonly engine_status: "RUNNING" | "IDLE" | "HALTED";
  readonly execution_control: ExecutionControlState;
  readonly last_heartbeat: string;
  readonly services: readonly {
    readonly name: string;
    readonly health: HealthLevel;
    readonly detail: string;
  }[];
};

type ChartAnnotationBaseV1<T extends string> = {
  readonly id: string;
  readonly type: T;
  readonly symbol: string;
  readonly strategy_id: string;
  readonly strategy_version: string;
  readonly timeframe: "1d" | "1h" | "15m" | "5m";
  readonly ts: number;
  readonly available_at: number;
  readonly label: string;
  readonly reason: string;
};

export type ChartAnnotationV1 =
  | ChartAnnotationBaseV1<"MARKET_CONTEXT" | "BIAS_LOCKED"> & {
      readonly direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH" | "BUY_SIDE" | "SELL_SIDE" | "NEUTRAL";
      readonly from_ts: number;
      readonly to_ts: number | null;
      readonly price_low?: number;
      readonly price_high?: number;
    }
  | ChartAnnotationBaseV1<"LIQUIDITY" | "FVG" | "POI" | "ENTRY_PLAN" | "INVALIDATION"> & {
      readonly direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH" | "BUY_SIDE" | "SELL_SIDE" | "NEUTRAL";
      readonly from_ts: number;
      readonly to_ts: number | null;
      readonly price_low: number;
      readonly price_high: number;
    }
  | ChartAnnotationBaseV1<"LIQUIDITY_SWEEP" | "BOS" | "MSS" | "CHOCH" | "DISPLACEMENT"> & {
      readonly direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH" | "BUY_SIDE" | "SELL_SIDE" | "NEUTRAL";
      readonly price: number;
    }
  | ChartAnnotationBaseV1<"ENTRY_TRIGGERED" | "STOP_LOSS" | "TAKE_PROFIT" | "TRADE_OPEN" | "TRADE_UPDATE" | "TRADE_CLOSED"> & {
      readonly direction: "LONG" | "SHORT";
      readonly price: number;
    };

export type ChartAnnotationsV1 = {
  readonly run_id: string;
  readonly symbol: string;
  readonly profile: "INTRADAY" | "INTRADAY_FVG";
  readonly strategy: StrategyIdentityV1;
  readonly annotations: readonly ChartAnnotationV1[];
};

export type PromotionRequestV1 = {
  readonly strategy: StrategyIdentityV1;
  readonly from_stage: PromotionStageV1;
  readonly to_stage: PromotionStageV1;
  readonly requested_by: string;
  readonly reason: string;
  readonly idempotency_key: string;
};

export type PromotionResultV1 = {
  readonly request_id: string;
  readonly status: (typeof PROMOTION_REQUEST_STATUSES_V1)[number];
  readonly current_stage: PromotionStageV1;
  readonly requested_stage: PromotionStageV1;
  readonly evaluated_gates: readonly PromotionGateEvidenceV1[];
  readonly missing_gates: readonly PromotionGateV1[];
  readonly decided_by: string | null;
  readonly decided_at: string | null;
};

type StreamEnvelopeV1<TType extends string, TPayload> = {
  readonly contract_version: typeof CONTRACT_VERSION_V1;
  readonly event_id: string;
  readonly stream_key: string;
  readonly sequence: number;
  readonly emitted_at: string;
  readonly type: TType;
  readonly payload: TPayload;
};

export type WebSocketEventV1 =
  | StreamEnvelopeV1<"BACKTEST_STATUS", BacktestLiveStatusV1>
  | StreamEnvelopeV1<"CHART_ANNOTATION", ChartAnnotationV1>
  | StreamEnvelopeV1<"TRADING_STATE", { readonly run_id: string; readonly from_state: TradingState; readonly to_state: TradingState; readonly reason: string }>
  | StreamEnvelopeV1<"SYSTEM_HEALTH", { readonly overall: HealthLevel; readonly environment: Environment; readonly execution_control: ExecutionControlState; readonly last_heartbeat: string }>
  | StreamEnvelopeV1<"PROMOTION_STATE", PromotionResultV1>;

export type BacktestStatusResponseV1 = ApiEnvelopeV1<BacktestLiveStatusV1>;
export type ChartAnnotationsResponseV1 = ApiEnvelopeV1<ChartAnnotationsV1>;
export type StrategyResponseV1 = ApiEnvelopeV1<StrategyVersionV1>;
export type SystemHealthResponseV1 = ApiEnvelopeV1<SystemHealthV1>;
export type PromotionResponseV1 = ApiEnvelopeV1<PromotionResultV1>;

export const CONTRACT_V1 = {
  version: CONTRACT_VERSION_V1,
  casing: "snake_case",
  rest: {
    backtest_status: { method: "GET", path: "/api/v1/backtests/{run_id}", response: "ApiEnvelopeV1<BacktestLiveStatusV1>" },
    chart_annotations: { method: "GET", path: "/api/v1/replays/{run_id}/annotations", response: "ApiEnvelopeV1<ChartAnnotationsV1>" },
    strategy: { method: "GET", path: "/api/v1/strategies/{strategy_id}/{strategy_version}", response: "ApiEnvelopeV1<StrategyVersionV1>" },
    system_health: { method: "GET", path: "/api/v1/system/health", response: "ApiEnvelopeV1<SystemHealthV1>" },
    promotion: { method: "POST", path: "/api/v1/promotions", request: "PromotionRequestV1", response: "ApiEnvelopeV1<PromotionResultV1>" },
  },
  websocket: {
    path: "/ws/v1/events",
    event_types: ["BACKTEST_STATUS", "CHART_ANNOTATION", "TRADING_STATE", "SYSTEM_HEALTH", "PROMOTION_STATE"],
    ordering: "sequence is monotonic per stream_key; duplicate event_id values are ignored",
  },
  enums: {
    trading_state: TRADING_STATES_V1,
    backtest_job_status: BACKTEST_JOB_STATUSES_V1,
    gate_status: GATE_STATUSES_V1,
    environment: ENVIRONMENTS_V1,
    health_level: HEALTH_LEVELS_V1,
    execution_control: EXECUTION_CONTROL_STATES_V1,
    replay_status: REPLAY_STATUSES_V1,
    provider_state: PROVIDER_STATES_V1,
    evaluation_status: EVALUATION_STATUSES_V1,
    exchange_connection: EXCHANGE_CONNECTION_STATES_V1,
    engine_status: ENGINE_STATUSES_V1,
    promotion_stage: PROMOTION_STAGES_V1,
    promotion_gate: PROMOTION_GATES_V1,
    promotion_request_status: PROMOTION_REQUEST_STATUSES_V1,
  },
  promotion: {
    transitions: PROMOTION_TRANSITIONS_V1,
    requirements: PROMOTION_REQUIREMENTS_V1,
    manual_approval_stages: MANUAL_APPROVAL_STAGES_V1,
    skipping_forbidden: true,
    automatic_real_promotion_forbidden: true,
  },
} as const;
