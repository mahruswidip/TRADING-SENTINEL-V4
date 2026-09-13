# D4.4 Remaining-Family Triage and FVG Pullback Specification

## Scope

D4.4 has two Development-only tracks. Track A triages four immutable V1 families without changing them. Track B defines and evaluates exactly one new hypothesis, `FVG_PULLBACK_V1`. Locked OOS, M1 execution, additional versions, parameter search, D5, Shadow, Canary, and REAL are excluded.

## Track A methodology

The triage reads only `trades/dev.jsonl` from `d4_dynamic_stratified_v3_20260911`. Existing OOS files are ignored. Each family records gross/net expectancy, fees, spread, slippage, funding, LONG/SHORT performance, MAE/MFE, exit distribution, deterministic regimes, symbol breadth, symbol concentration, and three chronological Development segments.

Classification is deterministic and ordered:

1. gross expectancy <= 0 → `KILL_NEGATIVE_RAW_EDGE`;
2. gross positive but net expectancy <= 0 → `KILL_COST_DESTROYED`;
3. fewer than 20 trades → `KILL_INSUFFICIENT_EVIDENCE`;
4. top-symbol positive-PnL share >60% or temporal concentration >60% → `KILL_UNSTABLE`;
5. otherwise → `KEEP_FOR_FUTURE_HYPOTHESIS`.

No V2/V3 family artifacts are created.

## FVG_PULLBACK_V1

Artifact labels are `NEW RESEARCH HYPOTHESIS`, `NOT VALIDATED`, and `DEVELOPMENT ONLY`.

### Profile responsibility

- 1H: Direction / Bias
- 15M: FVG / Setup Area
- 5M: Confirmation / Entry

M1 is inactive. A future `FVG_PULLBACK_V2` may test 1M precision execution only if a separate authorized hypothesis is justified by Development evidence.

### Closed-1H bias

Only fully closed 1H bars are used. The latest two closed bars define BULLISH when the latest has a higher high and higher low, BEARISH when it has a lower high and lower low, and NEUTRAL otherwise. No future swing confirmation or incomplete bar is used.

### Canonical closed-15M FVG

After candle 3 closes:

- bullish: candle 1 high < candle 3 low; zone `[candle 1 high, candle 3 low]`;
- bearish: candle 1 low > candle 3 high; zone `[candle 3 high, candle 1 low]`.

Each record contains ID, direction, formed/available timestamps, bounds, raw and trailing-range-normalized size, fixed expiry, touch age and penetration, full-fill invalidation, displacement metadata, and trade outcome fields when applicable. No minimum-size threshold is applied.

The V1 setup expires four hours after FVG formation. This canonical value is frozen and was not searched. A full fill through the far boundary before confirmation invalidates it.

### Closed-5M confirmation and execution

After touch, LONG requires a closed 5M sell-side/local-low sweep that reclaims the prior three-bar low, followed by a later closed 5M close above the sweep candle high. SHORT is symmetric. Entry occurs at the next 5M open.

The stop is the known sweep extreme. With no reusable opposing-liquidity target primitive, V1 freezes one 1.5R target known before entry. The modeled-cost expected R:R must be at least 1.1. Wrong-side/zero stops, wrong-side targets, stale or filled gaps, changed bias, post-expiry confirmation, or insufficient net R:R are rejected.

Fees, observed funding, modeled spread, and modeled slippage reuse the unchanged D3/D4 model. Stress cases remain BASE, fee +50%, spread +50%, and slippage +50%.

## No-lookahead and replay

Tests prove 1H bias ignores incomplete/future bars, an FVG is unavailable before candle 3 closes, sweep/MSS confirmation uses closed 5M bars, and entry is strictly the next 5M open. Stop and target are fixed at entry.

D2 replay retains the shared state machine and emits 1H bias, 15M FVG zone/touch, 5M sweep/MSS, entry, SL, TP, and close events. The replay profile adds 15M without introducing frontend structure inference.

## Verified Stage A

Development ran from 2026-07-01 through 2026-08-01 over seven dynamically liquidity-stratified symbols across Tier A/B/C, including the history-ready newer listing CAPUSDT. It formed 3,690 FVGs, touched 1,873, confirmed 249, and opened 206 trades.

Net expectancy was -$1.2752, PF 0.7291, Aggregate Net Return -26.27%, Reference Equity Return -2.63%, and Reference Equity Max DD 3.19%. Only one of seven symbols was profitable; all three temporal segments were negative. The candidate is `RESEARCH_REJECTED`.

No `FVG_PULLBACK_V2` exists. Artifacts explicitly record `OOS_NOT_ACCESSED`; D4.4 stops here.
