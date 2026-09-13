# D2.5 Binance Market Data Specification

## Scope and safety

D2.5 adds read-only Binance USDⓈ-M Futures public market data. It uses no credentials, account endpoints, orders, leverage changes, positions, strategy decisions, or execution. D0+D1 remains frozen and the deterministic D2 fixture remains the replay regression source.

## Dynamic universe discovery

There is no static symbol whitelist. `BinanceMarketDataProvider.discoverUniverse()` joins public `exchangeInfo`, 24-hour ticker, and book-ticker responses by symbol. Every returned contract is recorded. Primary-universe membership is derived from current trading status, `PERPETUAL` contract type, and compatible USDⓈ settlement (`USDT` or `USDC` with matching margin asset), never from symbol name or market capitalization.

BTC, ETH, and SOL are reference assets only. Small-cap, meme, and newly listed perpetual contracts follow the same provider-derived rules.

## Symbol registry and historical universe

`UniverseSymbol` records exchange identity, contract status/type, listing and delivery times, precision, tick/step/quantity/notional filters, optional first/last candle availability, market quality, research eligibility, future execution-quality eligibility, and explicit exclusion reasons.

Historical consumers must call `universeAt(symbols, timestamp)`. A contract is absent before `onboardDate` and after an applicable delivery date. This establishes `Universe(t)` without applying today's list backward. Delisted metadata must be persisted by a future backend dataset; the browser snapshot alone cannot reconstruct contracts Binance no longer returns.

## Provider boundary

```text
MarketDataWorkspace / MarketChart
  → MarketDataProvider
    → same-origin Next.js route handlers
      → Binance public REST metadata + klines
    → one selected-symbol Binance public live kline stream

ReplayWorkspace
  → ReplayDataProvider
    → DEVELOPMENT FIXTURE
```

Browser components never call Binance REST endpoints directly. Same-origin route handlers expose read-only universe and candle responses and preserve upstream HTTP restrictions such as 403, 451, and 429. The selected-symbol public WebSocket remains browser-direct because Binance public streams require no credentials; a server relay belongs in a future deployment only if hosting policy or regional access requires it.

The chart never calls Binance. `FIXTURE`, `BINANCE_HISTORICAL`, and `BINANCE_LIVE` are explicit source identities. The D2 replay is visibly labeled `DEVELOPMENT FIXTURE · NOT CURRENT MARKET DATA`.

## Historical and current data

The provider normalizes Binance klines into `MarketCandle` with separate open/close times and close state. It supports 1D, 1H, and 5M. Current mode loads a bounded REST bootstrap then opens one public kline WebSocket for the selected symbol/timeframe. Historical mode requests a bounded UTC-date snapshot and opens no stream.

Range requests paginate sequentially in batches of at most 1,500 rows and cap one browser request at 5,000 candles. The current screen requests only 300 candles; it never downloads the full universe history on page load.

## Cache and rate limits

The browser provider holds universe data for five minutes and candle snapshots for fifteen seconds. Identical in-flight requests are deduplicated. Symbol changes abort superseded REST requests and close the old stream. Rate-limit HTTP 429, regional/unavailable 403/451, network failures, malformed JSON, and empty data are surfaced as typed provider errors.

For larger research datasets, D3 must move acquisition to a controlled backend cache (for example Parquet with 1m base data and local resampling) rather than scaling browser downloads.

## Data integrity

Normalization rejects malformed and non-finite OHLCV rows, impossible high/low ranges, and negative price/volume. Candles are sorted, duplicate open times are replaced deterministically, and interval gaps become visible warnings. Live updates upsert by open time, so out-of-order or duplicate messages cannot duplicate chart bars. Provider state is shown as loading, connected, degraded, or error.

## Market quality and tiers

Quality dimensions are 24-hour quote volume, bid/ask spread, top-of-book notional depth, 24-hour volatility, listing age, availability, and history. States include `GOOD_MARKET`, `THIN_MARKET`, `WIDE_SPREAD`, `INSUFFICIENT_HISTORY`, `NEW_LISTING`, `EXTREME_VOLATILITY`, and `UNAVAILABLE`.

Dynamic operational tiers are:

- A: highest observed liquidity/quality;
- B: normally liquid;
- C: lower-liquidity or higher execution risk;
- N: under 30 days old / price discovery.

Tiers prioritize scanning and future risk scaling; they are not a tradable/banned list. New and lower-tier contracts remain discoverable. Research gating uses contract/data availability. Future execution-quality readiness additionally requires acceptable spread, depth, volatility, and history.

## Displayed versus executable price

The registry carries bid, ask-derived spread, and top-book depth measurements. D2.5 only displays market candles. A future provider can add deeper order-book snapshots, price-impact curves, executable price estimates, and executable PnL without changing symbol identity or allowing the strategy to bypass risk controls.

## New listings and delistings

Tier N makes new listings explicit rather than silently rejecting them. Very young contracts can be marked insufficient-history while remaining in the discovered universe. Status changes and missing ticker/book data downgrade availability and expose reasons. Historical persistence of delisted contracts belongs to the future data service.

## D3 boundary

D3 may consume normalized datasets and `Universe(t)` for a real backtest engine. It must not move strategy inference into this chart, change D2 replay clock semantics, or introduce authenticated Binance operations. D2.5 stops at public read-only market data.
