# D2 Chart Replay Specification

## Scope

D2 adds a deterministic, provider-driven replay surface without changing the frozen D0+D1 foundation. It does not download Binance data, run a strategy, place orders, or infer trading structure in the browser.

## ReplayClock architecture

`ReplayClock.currentTimestamp` is the only mutable time value. The controller stores a cursor, status, and speed over a deterministic checkpoint list. Candles, events, annotations, state, timeframe status, and the audit timeline are pure projections of the scenario and current timestamp.

```text
ReplayScenario fixture
  → ReplayClock.currentTimestamp
    → deriveReplayView()
      → visible candles
      → visible structured events and annotations
      → trading state
      → timeframe status
      → decisions and audit timeline
```

Changing the chart timeframe changes only the selected `MarketSeries`; it never changes the replay cursor or timestamp.

## Temporal model and no-lookahead rules

Fixture candle timestamps represent the moment a candle is closed and available. At replay time `T`:

- candle visibility requires `candle.timestamp <= T`;
- event visibility requires both `event.timestamp <= T` and `event.availableAt <= T`;
- annotations and decisions are selected only from visible events;
- state is the last visible structured state transition.

`timestamp` records when the market occurrence belongs. `availableAt` records when the strategy/provider could know the confirmed result. This distinction prevents an event such as a 1H MSS from appearing before its confirming candle closes.

## Contracts

`Candle` contains timestamp, OHLC, and volume. `MarketSeries` identifies symbol, timeframe, and candles. Supported replay timeframes are exactly `1D`, `1H`, and `5M`.

`TradingEvent` is a discriminated union. Shared provenance includes ID, type, timestamp, availability time, timeframe, symbol, strategy ID/version, category, label, reason, and constrained metadata. Specialized variants carry only relevant direction, price, price range, decision, or state-transition fields.

Supported event types:

- context: `MARKET_CONTEXT`, `BIAS_LOCKED`, `LIQUIDITY`, `POI`;
- structure: `LIQUIDITY_SWEEP`, `BOS`, `MSS`, `CHOCH`, `DISPLACEMENT`, `FVG`;
- entry/risk: `ENTRY_PLAN`, `ENTRY_TRIGGERED`, `STOP_LOSS`, `TAKE_PROFIT`, `INVALIDATION`, `RISK_VALIDATION`;
- trade/decision: `TRADE_OPEN`, `TRADE_UPDATE`, `TRADE_CLOSED`, `WAIT`, `REJECTED`;
- audit: `STATE_TRANSITION` using the frozen trading-state union.

Range annotations carry bounded start/end times and low/high prices. The chart renderer receives these events and never derives BOS, MSS, CHoCH, liquidity, FVG, POI, bias, entry, stop, or targets from candles.

## Provider and fixture boundary

`ReplayDataProvider` resolves a `ReplayScenario` by run ID. The D2 mock provider exposes one centralized BTCUSDT / TREND_CONTINUATION_V7 / INTRADAY LONG lifecycle fixture with synchronized 1D, 1H, and 5M series. A future backtest, shadow, or live provider can return the same contract without changing replay components.

## Rewind and determinism

Step backward moves the replay cursor to an earlier checkpoint. Nothing is undone or mutated. `deriveReplayView()` reconstructs the earlier view from the immutable fixture, so future candles, events, annotations, decisions, trade state, and transitions disappear automatically. Replaying the same scenario at the same timestamp therefore produces the same result.

## Rendering boundary

Lightweight Charts renders candlesticks, crosshair, price/time scales, zoom, and pan. Structured point events become markers or price lines. Structured price ranges become reusable bounded overlays. Rendering is incremental within the isolated replay client surface; the rest of the dashboard remains server-rendered.

## Error states

The route provides loading, missing-fixture, invalid-scenario, empty-candle, no-event, and replay-complete states. Scenario validation rejects missing timeframe series, non-chronological candles, premature availability, and mismatched provenance.

## Future integration

Later providers may source the same `ReplayScenario` contract from a real backtest or event store. They must preserve the clock, availability, provenance, and no-lookahead invariants. D2 intentionally defines no Binance transport, strategy engine, execution engine, AI logic, or promotion workflow.
