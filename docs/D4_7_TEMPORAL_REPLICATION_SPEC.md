# D4.7 Signal B Independent Temporal Replication

## Purpose and boundary

D4.7 is a Development-only independent temporal replication of the unchanged D4.5 Signal B definition inherited through immutable D4.6B run `d4_6b_d9380c7ff0781bac`. It does not define a strategy, entry, stop, target, order, or promotion action. Locked OOS is not resolved or read.

## Frozen identity

- Run: `d4_7_f38827b40e50d854`
- Signal B definition hash: `79f6169b3289d82c1e7e6b654b93bf7440d14cb1f42b00ad858a3d64f26d49af`
- Expected direction: negative
- Condition: `LOW × BTC_BULLISH`
- Horizon: 4H closed-candle forward return
- Window: June 2026, non-overlapping with prior July evidence
- Selection: dynamic historical Universe(t), no current ticker input

## Recovery and bounded-memory aggregation

Per-symbol work is checkpointed atomically. Transport failures are retryable; insufficient valid history remains an explicit data-quality result. Final aggregation reads one symbol artifact at a time, keeps a compact tuple only for timestamps in the required BTC regime, reconstructs the same cross-sectional ranks, and materializes only rows matching the frozen Signal B condition. This changes resource use, not feature, label, bucket, timestamp, breadth, confidence, or gate semantics.

## Verified result

- Status: `COMPLETED`
- Usable symbols: 201 of 210 selected; 535 historically eligible
- Mean / median effect: -18.88 / -24.45 bps
- Raw / effective observations: 82,304 / 1,817
- Daily-block 95% CI: -42.11 to +12.83 bps
- Direction hit rate: 55.50%
- Breadth: 157 aligned, 44 opposite
- Top-symbol contribution: 2.97%
- Tail-adjusted mean: -18.55 bps after the predeclared descriptive removal
- Temporal classification: `SIGN_FLIP`
- Final decision: `NOT_REPLICATED`

The effect cleared the descriptive 11 bps cost hurdle and was broad and unconcentrated. It failed because the dependence-aware confidence interval crossed zero and the direction flipped across temporal segments. No strategy is justified, and OOS remains `OOS_NOT_ACCESSED`.
