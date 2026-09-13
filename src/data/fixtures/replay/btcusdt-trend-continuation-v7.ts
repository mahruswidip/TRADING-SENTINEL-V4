import { intradayProfile } from "../../fixtures.ts";
import type { Candle, MarketSeries, ReplayScenario, ReplayTimeframe, TradingEvent } from "../../../domain/replay.ts";

const minute = 60;
const hour = 60 * minute;
const day = 24 * hour;
const at = (iso: string) => Date.parse(iso) / 1000;

function candles(timeframe: ReplayTimeframe, start: number, interval: number, count: number, priceAt: (index: number) => number): MarketSeries {
  const rows: Candle[] = [];
  let previous = priceAt(0);
  for (let index = 0; index < count; index += 1) {
    const close = Number(priceAt(index).toFixed(2));
    const open = Number(previous.toFixed(2));
    const spread = timeframe === "1D" ? 420 : timeframe === "1H" ? 115 : 34;
    rows.push({ timestamp: start + index * interval, open, high: Math.max(open, close) + spread, low: Math.min(open, close) - spread, close, volume: 900 + index * 37 });
    previous = close;
  }
  return { symbol: "BTCUSDT", timeframe, candles: rows };
}

const scenarioStart = at("2026-09-10T11:55:00Z");
const scenarioEnd = at("2026-09-10T14:45:00Z");
const event = <T extends TradingEvent>(value: T): T => value;
const base = { symbol: "BTCUSDT", strategyId: "TREND_CONTINUATION", strategyVersion: "V7" } as const;

const series: readonly MarketSeries[] = [
  candles("1D", at("2026-08-30T00:00:00Z"), day, 12, (index) => 108_200 + index * 270 + Math.sin(index) * 180),
  candles("1H", at("2026-09-09T18:00:00Z"), hour, 22, (index) => 110_200 + index * 52 + Math.sin(index * 0.9) * 145),
  candles("5M", at("2026-09-10T11:00:00Z"), 5 * minute, 46, (index) => index <= 24 ? 111_420 - index * 8 + Math.sin(index) * 20 : 111_220 + (index - 24) * 59 + Math.sin(index) * 24),
];

const events: readonly TradingEvent[] = [
  event({ ...base, id: "evt-001", type: "MARKET_CONTEXT", timestamp: at("2026-09-09T00:00:00Z"), availableAt: at("2026-09-10T12:00:00Z"), timeframe: "1D", category: "CONTEXT", label: "Bullish market context", reason: "The closed daily candle retained bullish structure inside the prior demand zone.", direction: "BULLISH", priceRange: { timeStart: at("2026-09-08T00:00:00Z"), timeEnd: scenarioEnd, priceLow: 110_800, priceHigh: 111_240 } }),
  event({ ...base, id: "evt-002", type: "STATE_TRANSITION", timestamp: at("2026-09-10T12:00:00Z"), availableAt: at("2026-09-10T12:00:00Z"), timeframe: "1D", category: "CONTEXT", label: "HTF context found", reason: "Closed 1D context met the mandatory market-context rule.", fromState: "SCANNING", toState: "HTF_CONTEXT_FOUND" }),
  event({ ...base, id: "evt-003", type: "BIAS_LOCKED", timestamp: at("2026-09-09T00:00:00Z"), availableAt: at("2026-09-10T12:05:00Z"), timeframe: "1D", category: "CONTEXT", label: "Bullish bias locked", reason: "Daily demand held and the strategy locked LONG-only search conditions.", direction: "BULLISH" }),
  event({ ...base, id: "evt-004", type: "STATE_TRANSITION", timestamp: at("2026-09-10T12:05:00Z"), availableAt: at("2026-09-10T12:05:00Z"), timeframe: "1D", category: "CONTEXT", label: "Bias locked", reason: "1D bullish bias became authoritative for this replay session.", fromState: "HTF_CONTEXT_FOUND", toState: "BIAS_LOCKED" }),
  event({ ...base, id: "evt-005", type: "POI", timestamp: at("2026-09-09T00:00:00Z"), availableAt: at("2026-09-10T12:05:00Z"), timeframe: "1D", category: "CONTEXT", label: "Daily demand POI", reason: "The provider supplied the bounded HTF point-of-interest range.", direction: "BULLISH", priceRange: { timeStart: at("2026-09-08T00:00:00Z"), timeEnd: scenarioEnd, priceLow: 110_800, priceHigh: 111_240 } }),
  event({ ...base, id: "evt-006", type: "LIQUIDITY", timestamp: at("2026-09-09T00:00:00Z"), availableAt: at("2026-09-10T12:05:00Z"), timeframe: "1D", category: "CONTEXT", label: "HTF buy-side liquidity", reason: "The strategy event located resting buy-side liquidity above the prior daily high.", direction: "BUY_SIDE", priceRange: { timeStart: at("2026-09-09T00:00:00Z"), timeEnd: scenarioEnd, priceLow: 112_380, priceHigh: 112_520 } }),
  event({ ...base, id: "evt-007", type: "STATE_TRANSITION", timestamp: at("2026-09-10T12:10:00Z"), availableAt: at("2026-09-10T12:10:00Z"), timeframe: "1H", category: "STRUCTURE", label: "Waiting for 1H structure", reason: "Bias was valid, but the current 1H candle had not confirmed structure.", fromState: "BIAS_LOCKED", toState: "WAITING_MTF_STRUCTURE" }),
  event({ ...base, id: "evt-008", type: "LIQUIDITY_SWEEP", timestamp: at("2026-09-10T12:00:00Z"), availableAt: at("2026-09-10T13:00:00Z"), timeframe: "1H", category: "STRUCTURE", label: "Sell-side sweep", reason: "The 1H candle closed after sweeping the provider-defined sell-side liquidity level.", direction: "SELL_SIDE", price: 111_030 }),
  event({ ...base, id: "evt-009", type: "MSS", timestamp: at("2026-09-10T13:00:00Z"), availableAt: at("2026-09-10T13:00:00Z"), timeframe: "1H", category: "STRUCTURE", label: "Bullish MSS confirmed", reason: "The closed 1H candle confirmed the structured bullish market-state shift.", direction: "BULLISH", price: 111_460 }),
  event({ ...base, id: "evt-010", type: "FVG", timestamp: at("2026-09-10T13:00:00Z"), availableAt: at("2026-09-10T13:00:00Z"), timeframe: "1H", category: "STRUCTURE", label: "1H bullish FVG", reason: "The provider supplied the imbalance range after the confirming candle closed.", direction: "BULLISH", priceRange: { timeStart: at("2026-09-10T12:00:00Z"), timeEnd: at("2026-09-10T14:00:00Z"), priceLow: 111_180, priceHigh: 111_360 } }),
  event({ ...base, id: "evt-011", type: "STATE_TRANSITION", timestamp: at("2026-09-10T13:00:00Z"), availableAt: at("2026-09-10T13:00:00Z"), timeframe: "1H", category: "STRUCTURE", label: "MTF confirmed", reason: "Sweep, displacement, and MSS requirements were confirmed by structured 1H events.", fromState: "WAITING_MTF_STRUCTURE", toState: "MTF_CONFIRMED" }),
  event({ ...base, id: "evt-012", type: "STATE_TRANSITION", timestamp: at("2026-09-10T13:05:00Z"), availableAt: at("2026-09-10T13:05:00Z"), timeframe: "5M", category: "ENTRY", label: "Waiting for 5M entry", reason: "HTF and MTF were valid; no closed 5M trigger was available yet.", fromState: "MTF_CONFIRMED", toState: "WAITING_LTF_ENTRY" }),
  event({ ...base, id: "evt-013", type: "DISPLACEMENT", timestamp: at("2026-09-10T13:20:00Z"), availableAt: at("2026-09-10T13:20:00Z"), timeframe: "5M", category: "ENTRY", label: "5M displacement", reason: "The provider emitted bullish displacement after the 5M candle closed.", direction: "BULLISH", price: 111_340 }),
  event({ ...base, id: "evt-014", type: "ENTRY_PLAN", timestamp: at("2026-09-10T13:20:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "ENTRY", label: "LONG entry plan", reason: "The closed confirmation candle made entry, invalidation, and targets available.", direction: "LONG", price: 111_360, riskDistance: 410, expectedRiskReward: 2.5, priceRange: { timeStart: at("2026-09-10T13:20:00Z"), timeEnd: at("2026-09-10T13:35:00Z"), priceLow: 111_300, priceHigh: 111_390 } }),
  event({ ...base, id: "evt-015", type: "ENTRY_TRIGGERED", timestamp: at("2026-09-10T13:25:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "ENTRY", label: "LONG entry 111,360", reason: "The 5M confirmation closed inside the provider-defined entry zone.", direction: "LONG", price: 111_360 }),
  event({ ...base, id: "evt-016", type: "STOP_LOSS", timestamp: at("2026-09-10T13:25:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "RISK", label: "Stop loss 110,950", reason: "Protective invalidation was supplied with the entry plan.", direction: "LONG", price: 110_950 }),
  event({ ...base, id: "evt-017", type: "TAKE_PROFIT", timestamp: at("2026-09-10T13:25:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "TRADE", label: "TP1 111,900", reason: "First deterministic target was supplied with the entry plan.", direction: "LONG", price: 111_900 }),
  event({ ...base, id: "evt-018", type: "TAKE_PROFIT", timestamp: at("2026-09-10T13:25:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "TRADE", label: "TP2 112,400", reason: "Second deterministic target was supplied with the entry plan.", direction: "LONG", price: 112_400 }),
  event({ ...base, id: "evt-019", type: "STATE_TRANSITION", timestamp: at("2026-09-10T13:25:00Z"), availableAt: at("2026-09-10T13:25:00Z"), timeframe: "5M", category: "ENTRY", label: "Entry triggered", reason: "The structured 5M entry event satisfied all mandatory trigger conditions.", fromState: "WAITING_LTF_ENTRY", toState: "ENTRY_TRIGGERED" }),
  event({ ...base, id: "evt-020", type: "RISK_VALIDATION", timestamp: at("2026-09-10T13:26:00Z"), availableAt: at("2026-09-10T13:26:00Z"), timeframe: "5M", category: "RISK", label: "Risk validation passed", reason: "Fixture risk limits accepted the predefined size, stop distance, and exposure.", decision: "PASSED" }),
  event({ ...base, id: "evt-021", type: "STATE_TRANSITION", timestamp: at("2026-09-10T13:26:00Z"), availableAt: at("2026-09-10T13:26:00Z"), timeframe: "5M", category: "RISK", label: "Risk validated", reason: "Independent fixture risk checks passed without changing strategy logic.", fromState: "ENTRY_TRIGGERED", toState: "RISK_VALIDATION" }),
  event({ ...base, id: "evt-022", type: "TRADE_OPEN", timestamp: at("2026-09-10T13:30:00Z"), availableAt: at("2026-09-10T13:30:00Z"), timeframe: "5M", category: "TRADE", label: "Trade open", reason: "The deterministic simulation recorded the LONG position as open.", direction: "LONG", price: 111_380 }),
  event({ ...base, id: "evt-023", type: "STATE_TRANSITION", timestamp: at("2026-09-10T13:30:00Z"), availableAt: at("2026-09-10T13:30:00Z"), timeframe: "5M", category: "TRADE", label: "Trade open", reason: "Risk validation completed and the simulated position became active.", fromState: "RISK_VALIDATION", toState: "TRADE_OPEN" }),
  event({ ...base, id: "evt-024", type: "TRADE_UPDATE", timestamp: at("2026-09-10T14:00:00Z"), availableAt: at("2026-09-10T14:00:00Z"), timeframe: "5M", category: "TRADE", label: "TP1 reached", reason: "The 14:00 candle closed through the first predefined target.", direction: "LONG", price: 111_900 }),
  event({ ...base, id: "evt-025", type: "TRADE_CLOSED", timestamp: at("2026-09-10T14:45:00Z"), availableAt: at("2026-09-10T14:45:00Z"), timeframe: "5M", category: "TRADE", label: "Trade closed at TP2", reason: "The final visible candle reached the second predefined target.", direction: "LONG", price: 112_400 }),
  event({ ...base, id: "evt-026", type: "STATE_TRANSITION", timestamp: at("2026-09-10T14:45:00Z"), availableAt: at("2026-09-10T14:45:00Z"), timeframe: "5M", category: "TRADE", label: "Trade closed", reason: "The deterministic lifecycle ended after TP2.", fromState: "TRADE_OPEN", toState: "TRADE_CLOSED" }),
];

export const btcusdtTrendContinuationV7Replay: ReplayScenario = {
  id: "replay_btcusdt_trend_continuation_v7",
  runId: "bt_20260910_001",
  symbol: "BTCUSDT",
  strategyId: "TREND_CONTINUATION",
  strategyVersion: "V7",
  profile: intradayProfile,
  source: "FIXTURE",
  startTimestamp: scenarioStart,
  endTimestamp: scenarioEnd,
  series,
  events,
};
