import type { ReplayScenario, ReplayTimeframe, ReplayView, StateTransitionEvent, TimeframeReplayStatus, TradingEvent } from "../domain/replay.ts";
import type { TradingState } from "../domain/contracts.ts";

const annotationTypes = new Set<TradingEvent["type"]>([
  "MARKET_CONTEXT", "BIAS_LOCKED", "LIQUIDITY", "LIQUIDITY_SWEEP", "BOS", "MSS", "CHOCH", "DISPLACEMENT", "FVG", "POI", "ENTRY_PLAN", "ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT", "INVALIDATION", "TRADE_OPEN", "TRADE_UPDATE", "TRADE_CLOSED",
]);

export function isVisibleAt(event: TradingEvent, timestamp: number): boolean {
  return event.timestamp <= timestamp && event.availableAt <= timestamp;
}

export function getReplayPeriod(scenario: ReplayScenario, timestamp: number): "WARMUP / CONTEXT PERIOD" | "BACKTEST EVALUATION PERIOD" {
  return timestamp < (scenario.evaluationStartTimestamp ?? scenario.startTimestamp) ? "WARMUP / CONTEXT PERIOD" : "BACKTEST EVALUATION PERIOD";
}

export function firstReplayEventTimestamp(scenario: ReplayScenario): number | null {
  return scenario.events.length ? Math.min(...scenario.events.map((event) => event.availableAt)) : null;
}

export function firstReplayTradeTimestamp(scenario: ReplayScenario): number | null {
  const trades = scenario.events.filter((event) => event.type === "TRADE_OPEN");
  return trades.length ? Math.min(...trades.map((event) => event.availableAt)) : null;
}

export function getReplayCheckpoints(scenario: ReplayScenario): readonly number[] {
  const timestamps = new Set<number>([scenario.startTimestamp, scenario.endTimestamp]);
  for (const marketSeries of scenario.series) {
    for (const candle of marketSeries.candles) if (candle.timestamp >= scenario.startTimestamp && candle.timestamp <= scenario.endTimestamp) timestamps.add(candle.timestamp);
  }
  for (const event of scenario.events) if (event.availableAt >= scenario.startTimestamp && event.availableAt <= scenario.endTimestamp) timestamps.add(event.availableAt);
  return [...timestamps].sort((left, right) => left - right);
}

function visibleEvents(scenario: ReplayScenario, timestamp: number): readonly TradingEvent[] {
  return scenario.events.filter((event) => isVisibleAt(event, timestamp)).sort((left, right) => left.availableAt - right.availableAt || left.timestamp - right.timestamp);
}

function currentState(events: readonly TradingEvent[]): TradingState {
  const transitions = events.filter((event): event is StateTransitionEvent => event.type === "STATE_TRANSITION");
  return transitions.at(-1)?.toState ?? "SCANNING";
}

function lastEvent(events: readonly TradingEvent[], timeframe: ReplayTimeframe, types: readonly TradingEvent["type"][]): TradingEvent | undefined {
  return events.filter((event) => event.timeframe === timeframe && types.includes(event.type)).at(-1);
}

function timeframeStatuses(scenario: ReplayScenario, events: readonly TradingEvent[]): readonly TimeframeReplayStatus[] {
  if (scenario.profile.id === "INTRADAY_FVG") {
    const bias = lastEvent(events, "1H", ["BIAS_LOCKED", "MARKET_CONTEXT"]);
    const fvg = lastEvent(events, "15M", ["FVG", "POI", "INVALIDATION"]);
    const entry = lastEvent(events, "5M", ["TRADE_CLOSED", "TRADE_OPEN", "ENTRY_TRIGGERED", "MSS", "LIQUIDITY_SWEEP"]);
    return [
      { timeframe: "1H", label: bias ? "BIAS LOCKED" : "WAITING", detail: bias?.reason ?? "No closed-1H direction is known yet.", tone: bias ? "positive" : "neutral" },
      { timeframe: "15M", label: fvg?.type === "POI" ? "FVG TOUCHED" : fvg ? "FVG FORMED" : "WAITING", detail: fvg?.reason ?? "No confirmed 15M FVG is known yet.", tone: fvg ? "info" : "neutral" },
      { timeframe: "5M", label: entry?.type === "TRADE_CLOSED" ? "TRADE CLOSED" : entry?.type === "TRADE_OPEN" ? "TRADE OPEN" : entry?.type === "ENTRY_TRIGGERED" ? "ENTRY CONFIRMED" : entry ? "CONFIRMING" : "WAITING", detail: entry?.reason ?? "No closed-5M confirmation is known yet.", tone: entry?.type === "TRADE_CLOSED" || entry?.type === "TRADE_OPEN" || entry?.type === "ENTRY_TRIGGERED" ? "positive" : entry ? "warning" : "neutral" },
    ];
  }
  const bias = lastEvent(events, "1D", ["BIAS_LOCKED", "MARKET_CONTEXT"]);
  const structure = lastEvent(events, "1H", ["MSS", "BOS", "CHOCH", "LIQUIDITY_SWEEP"]);
  const entry = lastEvent(events, "5M", ["TRADE_CLOSED", "TRADE_OPEN", "ENTRY_TRIGGERED", "ENTRY_PLAN", "DISPLACEMENT"]);
  return [
    { timeframe: "1D", label: bias?.type === "BIAS_LOCKED" ? "BIAS LOCKED" : bias ? "CONTEXT FOUND" : "WAITING", detail: bias?.reason ?? "No 1D context event is known yet.", tone: bias ? "positive" : "neutral" },
    { timeframe: "1H", label: structure && ["MSS", "BOS", "CHOCH"].includes(structure.type) ? "STRUCTURE CONFIRMED" : structure ? "STRUCTURE FORMING" : "WAITING", detail: structure?.reason ?? "No confirmed 1H structure event is known yet.", tone: structure ? "info" : "neutral" },
    { timeframe: "5M", label: entry?.type === "TRADE_CLOSED" ? "TRADE CLOSED" : entry?.type === "TRADE_OPEN" ? "TRADE OPEN" : entry?.type === "ENTRY_TRIGGERED" ? "ENTRY CONFIRMED" : entry ? "ENTRY FORMING" : "WAITING", detail: entry?.reason ?? "No 5M entry event is known yet.", tone: entry?.type === "TRADE_CLOSED" || entry?.type === "TRADE_OPEN" || entry?.type === "ENTRY_TRIGGERED" ? "positive" : entry ? "warning" : "neutral" },
  ];
}

export function deriveReplayView(scenario: ReplayScenario, timeframe: ReplayTimeframe, timestamp: number): ReplayView {
  const marketSeries = scenario.series.find((item) => item.timeframe === timeframe);
  const events = visibleEvents(scenario, timestamp);
  return {
    currentTimestamp: timestamp,
    timeframe,
    candles: marketSeries?.candles.filter((candle) => candle.timestamp <= timestamp) ?? [],
    events,
    annotations: events.filter((event) => event.timeframe === timeframe && annotationTypes.has(event.type)),
    decisions: events.filter((event): event is StateTransitionEvent => event.type === "STATE_TRANSITION"),
    currentState: currentState(events),
    timeframeStatuses: timeframeStatuses(scenario, events),
  };
}

export function validateReplayScenario(scenario: ReplayScenario): string | null {
  if (scenario.startTimestamp >= scenario.endTimestamp) return "Replay start must be earlier than replay end.";
  for (const { timeframe } of scenario.profile.timeframes) {
    const marketSeries = scenario.series.find((item) => item.timeframe === timeframe);
    if (!marketSeries?.candles.length) return `Replay has no ${timeframe} candles.`;
    if (marketSeries.candles.some((candle, index) => index > 0 && candle.timestamp <= marketSeries.candles[index - 1].timestamp)) return `${timeframe} candles are not strictly chronological.`;
  }
  for (const event of scenario.events) {
    if (event.timestamp > event.availableAt) return `${event.id} is available before its market timestamp.`;
    if (event.symbol !== scenario.symbol || event.strategyId !== scenario.strategyId || event.strategyVersion !== scenario.strategyVersion) return `${event.id} provenance does not match the replay scenario.`;
  }
  return null;
}
