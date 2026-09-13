import type { TradingProfile, TradingState } from "@/domain/contracts";

export type ReplayTimeframe = "1D" | "1H" | "15M" | "5M";
export type ReplayStatus = "IDLE" | "PLAYING" | "PAUSED" | "COMPLETE";
export type ReplaySpeed = 1 | 5 | 20;
export type EventCategory = "CONTEXT" | "STRUCTURE" | "ENTRY" | "RISK" | "TRADE" | "WAIT" | "REJECTED";
export type EventDirection = "LONG" | "SHORT" | "BULLISH" | "BEARISH" | "BUY_SIDE" | "SELL_SIDE" | "NEUTRAL";

export type Candle = {
  readonly timestamp: number;
  readonly open: number;
  readonly high: number;
  readonly low: number;
  readonly close: number;
  readonly volume: number;
};

export type MarketSeries = {
  readonly symbol: string;
  readonly timeframe: ReplayTimeframe;
  readonly candles: readonly Candle[];
};

export type PriceRange = {
  readonly timeStart: number;
  readonly timeEnd: number | null;
  readonly priceLow: number;
  readonly priceHigh: number;
};

type EventBase<TType extends string> = {
  readonly id: string;
  readonly type: TType;
  readonly timestamp: number;
  readonly availableAt: number;
  readonly timeframe: ReplayTimeframe;
  readonly symbol: string;
  readonly strategyId: string;
  readonly strategyVersion: string;
  readonly category: EventCategory;
  readonly label: string;
  readonly reason: string;
  readonly metadata?: Readonly<Record<string, string | number | boolean>>;
};

export type DirectionalTradingEvent = EventBase<"MARKET_CONTEXT" | "BIAS_LOCKED"> & {
  readonly direction: EventDirection;
  readonly priceRange?: PriceRange;
};

export type StructureTradingEvent = EventBase<"LIQUIDITY_SWEEP" | "BOS" | "MSS" | "CHOCH" | "DISPLACEMENT"> & {
  readonly direction: EventDirection;
  readonly price?: number;
};

export type RangeTradingEvent = EventBase<"LIQUIDITY" | "FVG" | "POI" | "ENTRY_PLAN" | "INVALIDATION"> & {
  readonly direction: EventDirection;
  readonly priceRange: PriceRange;
  readonly price?: number;
  readonly riskDistance?: number;
  readonly expectedRiskReward?: number;
};

export type PriceTradingEvent = EventBase<"ENTRY_TRIGGERED" | "STOP_LOSS" | "TAKE_PROFIT" | "TRADE_OPEN" | "TRADE_UPDATE" | "TRADE_CLOSED"> & {
  readonly direction: "LONG" | "SHORT";
  readonly price: number;
};

export type DecisionTradingEvent = EventBase<"RISK_VALIDATION" | "WAIT" | "REJECTED"> & {
  readonly decision: "PASSED" | "WAIT" | "REJECTED";
};

export type StateTransitionEvent = EventBase<"STATE_TRANSITION"> & {
  readonly fromState: TradingState;
  readonly toState: TradingState;
};

export type TradingEvent =
  | DirectionalTradingEvent
  | StructureTradingEvent
  | RangeTradingEvent
  | PriceTradingEvent
  | DecisionTradingEvent
  | StateTransitionEvent;

export type ReplayScenario = {
  readonly id: string;
  readonly runId: string;
  readonly symbol: string;
  readonly strategyId: string;
  readonly strategyVersion: string;
  readonly profile: TradingProfile;
  readonly source: "FIXTURE" | "BACKTEST";
  readonly evaluationStartTimestamp?: number;
  readonly startTimestamp: number;
  readonly endTimestamp: number;
  readonly series: readonly MarketSeries[];
  readonly events: readonly TradingEvent[];
};

export type ReplayClockState = {
  readonly status: ReplayStatus;
  readonly speed: ReplaySpeed;
  readonly currentTimestamp: number;
  readonly startTimestamp: number;
  readonly endTimestamp: number;
  readonly currentIndex: number;
  readonly totalSteps: number;
  readonly isPlaying: boolean;
};

export type TimeframeReplayStatus = {
  readonly timeframe: ReplayTimeframe;
  readonly label: string;
  readonly detail: string;
  readonly tone: "positive" | "warning" | "info" | "neutral";
};

export type ReplayView = {
  readonly currentTimestamp: number;
  readonly timeframe: ReplayTimeframe;
  readonly candles: readonly Candle[];
  readonly events: readonly TradingEvent[];
  readonly annotations: readonly TradingEvent[];
  readonly decisions: readonly StateTransitionEvent[];
  readonly currentState: TradingState;
  readonly timeframeStatuses: readonly TimeframeReplayStatus[];
};
