# D4.2 Development Evidence Expansion

## Purpose

D4.2 tests the immutable `BREAKOUT_RETEST_V2` and `RANGE_REVERSION_V2` rules against broader Development evidence. It changes no strategy parameter, execution rule, exit, or cost assumption. `TREND_CONTINUATION` remains V1.

## Locked OOS boundary

The pipeline loads only the declared Development range plus its three-day warmup. It neither resolves nor reads the locked OOS range. Every run and candidate artifact records `OOS_NOT_ACCESSED`. The OOS guard rejects candidates without `OOS_ELIGIBLE` and still requires explicit one-time user authorization after eligibility. D4.2 never launches OOS automatically.

## Staged expansion

- Stage A: two candidates across a moderate liquidity-stratified universe. A clear gate failure stops that candidate.
- Stage B: six representatives per liquidity tier plus a history-ready newer listing, only after Stage A passes.
- Stage C: the full eligible Development universe, only after Stage B passes and a new resource plan is accepted.

Each stage is split into `plan` and `execute`. The immutable resource plan is persisted before market history is loaded. Checkpoints skip completed candidate artifacts and a completed rerun returns the existing bytes.

## Universe and Development window

The universe comes from the V2 bridge's current USDⓈ-M perpetual registry, is filtered for listing history before warmup, and is ranked into current 24-hour quote-volume terciles. Sampling is evenly spaced within Tier A, B, and C; a recent listing is added only when it has the full Development interval and warmup availability. There is no ticker whitelist and BTC receives no special treatment.

Stage A used `2026-07-01T00:00:00Z` through `2026-08-01T00:00:00Z`, with warmup beginning `2026-06-28T00:00:00Z`. This 31-day Development window is separate from the locked OOS evaluation.

## Resource controls

Plans record candidate count, symbol count and snapshot, dates, approximate 5M candle count, expected evaluation jobs, partition cache hit rate, estimated bridge requests, and bounded workers. The historical store reuses D3 daily partitions and funding caches. The bridge client applies bounded retry/backoff only to transient rate-limit and server errors.

## Evidence

Primary metrics are net of the unchanged D4 costs and include overall and direction-level sample, expectancy, expectancy R, PF, return, drawdown, average R, MAE, and MFE. Candidate artifacts additionally contain:

- symbol results and concentration: profitable/losing/active symbols, top/top-three/top-five profit shares, median symbol expectancy, positive-expectancy breadth, trades per symbol, median trades per symbol, and trades per week;
- chronological Development segment A/B/C metrics and `TEMPORAL_CONCENTRATION` detection;
- deterministic market regime, volatility regime, range phase, liquidity tier, and newer-listing class metrics using information known at entry;
- unchanged BASE, fee +50%, spread +50%, and slippage +50% stress results.

No regime or symbol result becomes a new filter in D4.2.

## Gates and Stage A decision

The authoritative D4 Development gates remain unchanged: positive net expectancy, PF at least 1.1, max drawdown at most 25%, at least 20 trades, top-symbol profit share at most 60%, and positive expectancy under every cost scenario. Parameter stability is recorded as satisfied because the V2 rules hash is checked against the immutable D4.1 source artifact and no parameter neighborhood is searched.

Both Stage A candidates failed clearly, so Stage B was not planned or run:

- `BREAKOUT_RETEST_V2`: 479 LONG trades, expectancy -0.5834, PF 0.8597, max DD 52.49%, one profitable and six losing symbols, 100% top-symbol share, all cost scenarios negative, and temporal concentration.
- `RANGE_REVERSION_V2`: 1,461 LONG trades, expectancy -1.0018, PF 0.6803, max DD 154.23%, one profitable and six losing symbols, 100% top-symbol share, and all cost scenarios negative.

These are Development rejections, not OOS results.

## Artifacts

The run lives at `state/research-runs/d4_2_a_706bdf1b5577051b`. Candidate artifacts live under `state/research/<CANDIDATE>/d4_2_a_*` and include the manifest, expanded summary, symbol breadth, temporal stability, regime stability, cost stress, gate result, Development trades, and an optional Development replay.

## D4.3 boundary

D4.3 may only begin by explicit user instruction. It must not reinterpret these Development failures, tune a V3, or unlock OOS. D5 remains out of scope.
