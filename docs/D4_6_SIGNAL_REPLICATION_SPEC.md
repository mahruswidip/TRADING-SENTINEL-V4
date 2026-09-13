# D4.6 Signal Replication & Development Coverage Expansion

## Purpose and boundary

D4.6 is a Development-only falsification pass for exactly two signal definitions emitted by authoritative D4.5 run `d4_5_482ba89ea0075922`. It expands historical coverage and measures whether those frozen relationships survive broader symbol breadth. It does not discover features, tune thresholds, create a strategy, define entries/SL/TP, model trade PnL, access locked OOS, or start D5.

## Frozen source definitions

- Signal A: `RELATIVE_STRENGTH_X_BTC_REGIME`, `NORMAL × BTC_BEARISH`, 4H forward return, expected positive.
- Signal B: `RELATIVE_STRENGTH_X_BTC_REGIME`, `LOW × BTC_BULLISH`, 4H forward return, expected negative.

The engine loads the finding, interaction components, bucket rules, timestamp contract, benchmark, and feature-catalog hash from the D4.5 artifacts. It records a canonical hash for each complete definition plus SHA-256 hashes of the source manifest, catalog, ranking, and source engine file. D4.6 imports the D4.5 feature calculation, bucketing, Universe(t), forward-label, downsampling, bootstrap, breadth, and temporal functions directly. No copied threshold table exists.

## Expansion and Universe(t)

The primary window is `2026-07-01 00:00 UTC` through `2026-07-31 20:00 UTC`. The V2 read-only bridge is the only network source. Canonical 5M OHLCV is cached in atomic daily partitions; 15M/1H/4H values remain closed-candle derivations in the frozen feature pipeline. Funding is not required by either source signal and is therefore not fetched.

Eligible contracts must be USDⓈ-M USDT perpetuals active during the requested historical window. Onboard and delivery timestamps remain enforced at every observation. Selection is deterministic and performance-independent: preserve the D4.5 cohort, then round-robin the listing-age groups using a stable symbol hash. Current ticker volume is never read. Historical quote-volume slices use only the trailing 4H OHLCV available at that timestamp and are descriptive only.

## Staged backfill and recovery

- Stage A targets approximately 50 symbols.
- Stage B targets approximately 100 only if the Stage A gate authorizes it.
- Stage C targets approximately 200 only if the Stage B gate authorizes it.

Every stage has a resource plan and immutable stage artifacts. Backfill records completed/failed symbols, candle coverage, funding coverage (`NOT_REQUIRED`), dataset IDs, cache hits/downloads, stage, and analysis state. Atomic cache and checkpoint writes make restarts resumable. Completed work is reused; transport failures are retryable. One effective bridge worker prevents bursts through the single upstream public-data client.

## Statistics and gates

For each signal the artifact reports raw and 4H-downsampled effective sample sizes, date and symbol breadth, mean/median forward return, directional hit rate, daily-block-bootstrap 95% interval, effect size, and the unchanged 11 bps economic hurdle. The 11 bps reference is a comparison only; no fees are subtracted as though trades occurred.

Breadth includes aligned/opposite symbols, median per-symbol effect, and top/top-3/top-5 contribution. Temporal evidence reuses frozen `DEV_A`, `DEV_B`, and `DEV_C` boundaries. Cross-sectional diagnostics cover listing age, past-only historical quote-volume, past-only volatility percentile, and weaker/stronger observations within the same qualifying BTC regime. These slices do not change signal eligibility.

Final statuses are `REPLICATED_STRONG`, `REPLICATED`, `WEAK_REPLICATION`, `NOT_REPLICATED`, or `INSUFFICIENT_DATA`. Direction, economics, median behavior, confidence, breadth, concentration, and temporal stability must all support a positive replication result. A clearly failed Stage A stops expansion; gates are not relaxed to force continuation.

## Verified Stage A outcome

Run `d4_6_8733a768a0dd3dd4` selected 50 of 532 eligible contracts and produced 48 usable symbols. Two contracts could not supply the minimum seven Development days. Signal A was `NOT_REPLICATED`; Signal B was `WEAK_REPLICATION`. The gate returned `STOP_NOT_REPLICATED`, so Stages B and C were correctly not run. This is a complete D4.6 result, not a platform error and not a trading recommendation.

## Capability gaps and next boundary

Historical OI, premium/basis, BBO/spread, and order-book depth remain unavailable and are not approximated using current snapshots. They are not required by the frozen signals. D4.6 stops after replication artifacts and minimal read-only Strategy Lab presentation. Any strategy construction or D5 work requires explicit future authorization.
