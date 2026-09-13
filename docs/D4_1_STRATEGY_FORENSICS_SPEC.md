# D4.1 Strategy Forensics and Hypothesis Refinement

## Boundary and provenance

D4.1 explains Development failure without weakening D4 gates, tuning on OOS, or changing V1. Source run `d4_dynamic_stratified_v3_20260911` and its V1 files remain byte-identical. The analyzer reads Dev trades plus cached warmup/Dev candles; `locked_oos_read` is always false. It uses the fixed 1D/1H/5M framework and information available at entry for regime and structure measurements.

The original V1 run labeled its universe liquidity-stratified, but the bridge exposes tickers separately from symbols and the old selector had not joined them. The old AVAUSDT/BTCUSDT/GRVTUSDT artifacts are preserved rather than rewritten. The shared eligibility boundary now enriches symbol metadata with ticker/book data for future runs. D4.1 tier labels use a separately recorded current bridge snapshot and are analysis-only, not signal inputs.

## Forensic model

For each trade, D4.1 records raw trade provenance and distributions for:

- LONG/SHORT, win/loss, symbol, current volume tier, new-listing status, UTC hour;
- closed-data market trend, volatility, expansion/compression;
- holding duration, entry location, planned R:R;
- MAE/MFE, ratio, ordering, time-to-extreme, realized MFE, and winner giveback;
- HTF body/range strength, structure age, break distance, displacement, retest depth, liquidity sweep, opposing room in R, and volatility normalization;
- gross result, fees, observed funding, modeled spread/slippage, net result, and exit reason.

Numeric evidence stores count, minimum, p10, p25, median, p75, p90, maximum, and mean. Categoric evidence stores counts plus normal D3 net metrics.

## V1 findings

### BREAKOUT_RETEST_V1

- 27 trades; gross expectancy +0.6057 but net expectancy -0.4891: `EDGE_DESTROYED_BY_COST`.
- LONG expectancy -0.1975 versus SHORT -0.7599.
- Closed-1D `TRENDING_UP` subset: 12 trades, +1.02 net expectancy. Other trend regimes were negative.
- 15/27 had immediate adverse excursion; losing median MFE/MAE ratio was 0.27 versus 3.08 for winners.
- Seven late-location entries averaged -2.58, but the sample is small.

### RANGE_REVERSION_V1

- 80 trades; gross expectancy +0.5318 but net expectancy -0.5658: `EDGE_DESTROYED_BY_COST`.
- LONG: 39 trades, +0.2446 expectancy, PF 1.057. SHORT: 41 trades, -1.3367 expectancy, PF 0.677.
- RANGE regime was +1.02; trending-down was -1.21. Normal volatility was +0.43 while high/low volatility were negative.
- 42/80 achieved positive MFE but still closed net-negative. Losing median MFE/MAE ratio was 0.36 versus 8.20 for winners.

### TREND_CONTINUATION_V1

- 179 trades; gross expectancy +0.1503 but net expectancy -0.9494: `EDGE_DESTROYED_BY_COST`.
- LONG expectancy -0.6701 and SHORT -1.5628; every prospectively known broad direction/regime slice remained negative.
- 91/179 achieved positive MFE but closed net-negative; 69 showed immediate adverse excursion.
- Post-entry excursion ordering separates outcomes strongly, but cannot be used as an entry filter without lookahead. No V2 was justified.

Across all families, take-profit winners and stop-loss losers show materially different excursion distributions. That observation supports future exit research but does not justify changing exits in D4.1.

## Cost attribution

Every primary V1 had positive gross expectancy and negative net expectancy, so all are classified `EDGE_DESTROYED_BY_COST`. Per trade, the configured baseline burden is approximately $0.80 fees + $0.20 spread + $0.10 slippage, with observed signed funding added separately. No cost assumption was relaxed.

## Immutable hypotheses and Development results

Only two new versions were justified:

1. `BREAKOUT_RETEST_V2`: LONG-only and latest closed 1D candle must be bullish above the previous closed daily close. Result: 12 trades, expectancy +1.0177, PF 1.3309, DD 1.54%. Rejected for insufficient sample and 96.7% positive-PnL concentration.
2. `RANGE_REVERSION_V2`: unchanged V1 setup/stop/target, LONG-only. Result: 44 trades, expectancy +0.3757, PF 1.0971, DD 4.70%. Rejected for PF below 1.1, fee-stress expectancy -0.0243, and 100% positive-PnL concentration.

Both used Development only. Neither passed every authoritative D4 gate, so OOS was not opened. No V3, random threshold search, time-of-day filter, ticker whitelist, or exit modification was created.

## Artifacts

Each V1 forensic directory contains `manifest.json`, `entry-forensics.json`, `exit-forensics.json`, `direction-analysis.json`, `regime-analysis.json`, `cost-attribution.json`, `symbol-analysis.json`, and `hypothesis-report.md` under `state/forensics/<FAMILY_VERSION>`.

Each new version has an immutable Development artifact containing identity/config/dataset/cost/execution provenance, hypothesis, exact window, gates, Dev metrics, stress, symbol breadth, trades, and replay under `state/research/<FAMILY_VERSION>/<validation-id>`.

## Stop boundary

D4.1 stops with zero Development passes. It does not read locked OOS, start D5, implement Shadow/Canary/Real, or alter execution behavior.
