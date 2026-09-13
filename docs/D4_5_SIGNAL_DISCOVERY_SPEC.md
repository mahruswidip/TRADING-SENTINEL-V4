# D4.5 Signal Discovery / Feature Research

## Purpose

D4.5 measures whether market conditions observed at closed candle time `T` have a repeatable relationship with future closed-candle returns. It produces signal evidence, not a trading strategy. Strategy construction, entries, stop losses, targets, position sizing, PnL backtesting, locked OOS, Shadow, Canary, Real, and D5 are forbidden.

## Verified Development run

- Run: `d4_5_482ba89ea0075922`
- Window: 2026-07-01 00:00 UTC through 2026-07-31 20:00 UTC
- Research universe: 19 dynamically eligible USDT perpetual contracts with at least 90% local cache coverage
- BTCUSDT participates because it independently meets the same dynamic eligibility/cache rule; it is not a static allowlist exception
- Raw observations: 168,720
- Effective observations: 168,720 / 56,240 / 28,120 / 14,060 / 3,515 for 5m / 15m / 30m / 1h / 4h
- Locked OOS: `OOS_NOT_ACCESSED`

## Data capabilities

| Data | Historical capability | Use in D4.5 |
|---|---|---|
| 5m OHLCV | Bridge `candles-window` + D3 cache | Available |
| 15m / 1h / 4h OHLCV | Closed-only derivation from 5m | Available |
| Funding | Bridge `funding-window`, exchange timestamps | Available |
| Open interest | Current snapshot only | `HISTORICAL_FEATURE_NOT_AVAILABLE` |
| Premium / basis | No historical bridge endpoint | `HISTORICAL_FEATURE_NOT_AVAILABLE` |
| BBO / spread | Current snapshot only | `HISTORICAL_FEATURE_NOT_AVAILABLE` |
| Order-book depth | Current snapshot only | `HISTORICAL_FEATURE_NOT_AVAILABLE` |
| Listing metadata | Onboard, delivery, contract type | Available |
| Universe(t) | Frozen bridge registry filtered at each `T` | Available |

Current ticker volume, liquidity tier, BBO, depth, spread, and OI snapshots are never copied into historical feature rows. Current 24h quote volume remains descriptive snapshot metadata only and makes no predictive claim.

## Universe(t)

The plan freezes the bridge registry and applies onboard/delivery eligibility at each observation timestamp. The research set is the intersection of this dynamic eligible universe and sufficient Development cache coverage. No ticker whitelist is present. Exclusions and reasons are stored in `universe.json`.

## Frozen feature catalog

The `plan` command writes `feature-catalog.json` before evaluation. The 22 available features cover:

- past closed returns over 5m, 15m, 1h, and 4h;
- trailing high/low distance and range position;
- candle volume and quote-volume expansion;
- past-only volume z-score;
- normalized ATR, realized volatility, and range expansion;
- funding level and past-only funding percentile;
- listing age;
- BTC return context, market breadth, and cross-sectional median return;
- Universe(t) relative-strength ranks over 15m, 1h, and 4h.

Five registered but unavailable features preserve negative capability evidence: OI change, OI percent change, premium/basis, historical spread, and historical depth.

## Forward-return labels and no-lookahead

The observation price is the close of the fully closed 5m candle at `T`. For horizon `h`:

```text
forward_return_h = close(T+h) / close(T) - 1
```

Horizons are 5m, 15m, 30m, 1h, and 4h. Features use candles and events timestamped no later than `T`; labels use a close strictly after `T`. Rolling percentiles exclude the current value from their reference history. Funding is aligned to the most recent exchange funding timestamp at or before `T`. Cross-sectional ranks contain only Universe(T).

## Statistical methodology

Each deterministic feature bucket is evaluated independently before interactions. Reported fields include raw and effective observation count, symbols, dates, mean, median, positive and directional hit rates, standard deviation, 5th/95th tails, effect size, symbol breadth, temporal means, and a deterministic 95% daily-block bootstrap interval.

Overlapping labels are handled by horizon-stride downsampling per symbol: every 1 / 3 / 6 / 12 / 48 observations for 5m / 15m / 30m / 1h / 4h. Confidence intervals resample UTC-day blocks with a stable seed. Raw rows remain visible but are not silently treated as IID.

Only four predeclared two-feature interactions are evaluated:

- 1h momentum × volume expansion;
- funding extreme × price extension;
- 1h relative strength × BTC regime;
- 1h momentum × volatility regime.

No three-way interactions, threshold sweeps, ML, optimizer, or post-result feature additions are allowed.

## Temporal stability and breadth

The Development window is split into fixed chronological thirds: `DEV_A`, `DEV_B`, and `DEV_C`. Classifications are `TEMPORALLY_STABLE`, `TEMPORALLY_WEAK`, `TEMPORALLY_CONCENTRATED`, or `SIGN_FLIP`.

Breadth reports active symbols, aligned/opposite symbol counts, median per-symbol effect, and top-1/top-3/top-5 contribution. One-ticker-dominated findings fail the gate.

## New listings

Listing age uses predeclared buckets: very new below 30 days, young from 30 through 364 days, and established at 365 days or more. D4.5 reports samples, symbols, volatility percentile, returns, and directional asymmetry without tuning cutoffs. Historical OI behavior is unavailable.

## Discovery score and gate

The transparent 0–100 discovery score is:

```text
30 effect magnitude
+ 15 effective sample sufficiency
+ 15 daily-block confidence interval
+ 20 temporal stability
+ 10 active-symbol breadth
+ 10 direction consistency
```

It contains no PnL, profit factor, SL, TP, or strategy metric. A finding becomes `PROMISING_SIGNAL` only when the effect is meaningful, the effective sample and symbol counts are sufficient, the daily-block interval supports its direction, breadth is at least 60%, top-symbol contribution is at most 50%, temporal evidence does not flip/concentrate, and effect magnitude is above the cost hurdle. Other outcomes are `WEAK_EVIDENCE`, `NO_EDGE`, `UNSTABLE`, `INSUFFICIENT_DATA`, or `FEATURE_UNAVAILABLE`.

## Cost hurdle

Raw forward returns are not reduced by fees because no trade exists. The existing configured 4 bps taker fee per side, 2 bps modeled spread, and 1 bp slippage imply an 11 bps minimum round-trip hurdle. Findings are labeled `BELOW_COST_HURDLE`, `MARGINAL_VS_COST`, or `ABOVE_COST_HURDLE`.

## Artifacts and resource control

Artifacts live under `state/signal-discovery/<run-id>`. The pipeline reuses the D3 daily candle and funding cache, accepts at most four workers, retries and paces bridge calls, checkpoints each completed symbol, and writes JSON atomically. An identical completed run returns `ALREADY_COMPLETED` without mutation.

## D4.6 boundary

D4.5 stops at evidence. Even a `PROMISING_SIGNAL` does not authorize entry rules, risk rules, SL/TP, OOS, or a new strategy version. Only an explicit later user instruction may define D4.6.
