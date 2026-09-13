# D3 Real Backtest Engine Specification

## Boundary and architecture

D3 is a research-only engine milestone. `backtest_engine` is a standalone Python boundary; React never performs strategy evaluation. Actual history flows from the local V2 read-only bridge (`MARKET_DATA_BASE_URL`, normally `127.0.0.1:8766`) into `HistoricalDataStore`, then into the strategy, execution/cost accounting, metrics, artifact writer, dashboard provider, and existing D2 replay provider. V4 never calls Binance directly.

The only implemented ruleset is `ENGINE_REFERENCE_INTRADAY_V1`, labeled **NOT A VALIDATED TRADING STRATEGY**. It exists only to prove engine behavior. D4 owns strategy research, optimization, OOS, and walk-forward work.

## Historical data and Universe(t)

The bridge provides dynamic USDⓈ-M contract metadata plus paginated candle and funding windows. Eligibility uses contract type, compatible quote/margin assets, onboard date, delivery/trading state, and the requested historical window. Explicit exclusions are recorded; there is no production symbol whitelist.

Canonical fast data is 5M. Complete contiguous 5M groups are resampled locally into 1H and UTC 1D candles. A higher-timeframe candle is visible only when its `close_time <= decision_time`. Strategy events carry both `timestamp` and `availableAt`; they cannot affect replay or strategy evaluation earlier than availability.

## Cache and dataset provenance

To keep dependencies and operational surface small, D3 uses standard-library gzip JSONL rather than adding a Parquet stack. Each symbol/timeframe has immutable daily partitions under `data/market/binance-usdm-v1/<symbol>/<timeframe>/YYYY-MM-DD.jsonl.gz`, accompanied by a manifest. Funding is cached by exact requested range. Partitions are sorted, deduplicated, atomically replaced, reused on subsequent runs, and report gaps.

Each partition manifest records dataset ID (content digest), provider, market, symbol, timeframe, requested range, row count, download time, first/last timestamps, gap count, source, and schema version. A run dataset version hashes the exact partition identities used.

## Strategy and temporal semantics

The interface is deterministic and split conceptually into bias, structure, entry, and trade-plan evaluation. The reference rule requires the last closed 1D candle, last closed 1H candle, and a closed 5M body of at least 2 bps to agree. Otherwise it returns WAIT. A signal executes at the next 5M open; one position is evaluated at a time. Stops use the larger of the previous twelve 5M average ranges and 10 bps, with a 1.5R target and a 24-bar maximum hold.

The frozen state vocabulary and 1D Bias → 1H Structure → 5M Entry responsibilities are preserved in structured events.

## Fast and accurate stages

Stage A uses 5M OHLC. If a bar touches TP and SL, it records `INTRABAR_AMBIGUOUS` and assumes the stop in the fast result; it never chooses favorable sequencing. Stage B downloads only that trade's affected 5M window as 1M bars. The first unambiguous 1M touch resolves the exit. If one 1M candle still touches both levels, worst-case stop remains. Repriced trades recompute gross result, relevant funding, net result, R, duration, and event output.

## Execution and costs

Execution model `next-open-market-v1` enters at the next 5M open. It uses normalized $1,000 notional and does not claim fill-queue realism.

- Fee model: configured taker 4 bps per side; provenance `CONFIGURED`.
- Funding: actual bridge funding timestamps; applied only when `entry_time < funding_time <= exit_time`. Positive funding is a LONG cost and a SHORT credit.
- Spread: 2 bps round-trip cost; provenance `MODELED`.
- Slippage: 1 bp round-trip cost; provenance `MODELED`.

Net PnL equals gross PnL minus entry fee, exit fee, signed funding cost, spread, and slippage. Gross and every cost remain itemized.

## Jobs, checkpoint, and artifacts

Workers are bounded to 1–8 and parallelize by symbol. Results are sorted before aggregation, so completion order cannot alter output. A checkpoint is atomically updated after every symbol and stores completed and failed symbol results; restarting the same run resumes pending work. Cache access avoids repeat downloads.

A completed run writes `manifest.json`, `summary.json`, `symbol-metrics.json`, `trades.jsonl`, `decisions.jsonl`, `events.jsonl`, `data-quality.json`, `replay.json` when a trade exists, `dashboard-job.json`, and a final checkpoint beneath `state/backtests/<run-id>`. Existing completed artifacts are not overwritten by the same deterministic run ID.

Metrics include trade outcome counts, win rate, gross/net return, expectancy and expectancy-R, PF, max drawdown, average R, MAE/MFE, itemized cost totals, ambiguity count, and LONG/SHORT slices. The decision artifact records the 1D/1H/5M funnel, entries, risk acceptance, trades, WAITs, and failures/exclusions.

## Dashboard and replay integration

The server-side D3 provider supplements, rather than replaces, frozen mock jobs and labels artifact rows `REAL_BACKTEST`. The Backtest table derives progress from authoritative processed/total values. `replay.json` uses the existing `ReplayScenario` and structured event contracts with source `BACKTEST`; the existing clock, no-lookahead selectors, chart annotations, state machine, and audit trail consume it unchanged.

## CLI

```text
python -m backtest_engine run --start <ISO> --end <ISO> --symbols BTCUSDT,SOLUSDT,DOGEUSDT --workers 3
python -m backtest_engine run --start <ISO> --end <ISO> --verify-set
python -m backtest_engine run --start <ISO> --end <ISO> --universe all
```

`--verify-set` dynamically selects a high-, middle-, and low-ranked eligible contract from bridge metadata. A full-universe run is supported but is intentionally not part of short automated verification.

## Known D3 limitations and D4 boundary

The reference rules are intentionally simple and unvalidated. Fees are configurable rather than account-specific, historical spread/slippage are modeled, 1M OHLC can remain ambiguous, funding cache partitions are range-keyed, delisted-contract survivorship depends on what the bridge universe currently exposes, and artifacts use JSON/JSONL rather than columnar Parquet. D3 does not place orders, inspect balances, optimize parameters, promote strategies, or claim profitability. Those concerns remain outside D3.
