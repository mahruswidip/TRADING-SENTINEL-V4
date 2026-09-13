# D4.3 Accounting and Regime Hypothesis Specification

## Boundary

D4.3 audits Development-only accounting semantics and tests one existing `BREAKOUT_RETEST_V2` regime observation. It does not change the backtest engine's trade PnL, cost, entry, stop, target, timing, or timeframe rules. It does not access locked OOS, create allocation or sizing machinery, or start D5.

## Accounting definitions

The legacy `net_return` is **Aggregate Net Return**:

```text
sum(trade.net_return) × 100
```

Each trade uses the engine's fixed normalized $1,000 notional. This statistic is cumulative normalized trade return, not an account-equity return, and may be below -100%.

The legacy `max_drawdown` is **Aggregate Fixed-Notional Drawdown**:

```text
maximum peak-to-trough decline in cumulative fixed-notional PnL
÷ $1,000 normalized trade notional × 100
```

It is not portfolio-equity drawdown and may exceed 100%. Earlier immutable artifacts remain unchanged; D4.3 corrects the interpretation and UI labels.

## Reference portfolio equity

D4.3 adds a research-only reference model for interpretation, not capital allocation:

- starting equity is configurable and is $10,000 for the verified artifact;
- each trade retains its fixed $1,000 normalized notional;
- realized net PnL is applied chronologically at exit, with `trade_id` as the deterministic tie-breaker;
- there is no compounding, leverage optimization, dynamic sizing, margin reservation, or capital-allocation optimization;
- equity is floored at zero and later trade PnL is not applied after bankruptcy.

Reference Equity Return is `(ending equity / starting equity - 1) × 100`. Reference Equity Max DD is the maximum `(peak equity - subsequent trough equity) / peak equity × 100`; it cannot exceed 100%.

Every audit records `return_metric_type`, `drawdown_metric_type`, `capital_model`, `starting_equity`, `position_notional_model`, `compounding`, and `bankruptcy_behavior` in its accounting provenance or referenced equity result.

## Verified accounting result

| Strategy | Aggregate Net Return | Reference Equity Return | Reference Equity Max DD | Ending equity |
|---|---:|---:|---:|---:|
| `BREAKOUT_RETEST_V2` | -27.94% | -2.79% | 5.19% | $9,720.57 |
| `RANGE_REVERSION_V2` | -146.36% | -14.64% | 15.16% | $8,536.37 |

Neither reference equity path reached bankruptcy. The audit finding is `SEMANTIC_LABEL_BUG_NOT_TRADE_PNL_FORMULA_BUG`.

## Ex-ante regime definition

At signal time `T`, the regime classifier uses only fully closed 1H candles with `close_time <= T`. It compares the latest closed 1H high-low range with the median range of up to 24 preceding closed 1H bars:

```text
volatility_ratio = latest_closed_1H_range / median(prior_closed_1H_ranges)
HIGH_VOLATILITY and EXPANSION when volatility_ratio >= 1.25
```

The 1.25 threshold was already used by D4.1/D4.2 and was not searched against outcomes. Each forensic row records `regime_observed_through`; tests prove a future candle cannot change an earlier classification.

## Breakout regime evidence

The HIGH_VOLATILITY / EXPANSION slice contains 155 Development trades across seven symbols: 41 Tier A, 71 Tier B, and 43 Tier C trades. Net expectancy is $0.7174 per normalized trade, Profit Factor is 1.1526, Aggregate Net Return is 11.12%, Aggregate Fixed-Notional Drawdown is 15.67%, Reference Equity Return is 1.11%, and Reference Equity Max DD is 1.01%.

Six of seven symbols are profitable. The top symbol contributes 31.25% of positive PnL, while the top three contribute 79.55%. Cost stress remains positive at base, fee +50%, spread +50%, and slippage +50%.

Temporal evidence fails: Segment A has negative expectancy and PF below 1, and Segment C contributes 72.59% of positive segment PnL. This exceeds the unchanged 60% concentration limit. The result is `REGIME_HYPOTHESIS_NOT_JUSTIFIED`.

## V3 and OOS decision

`BREAKOUT_RETEST_V3` was not created. Although the slice has positive expectancy, PF, sample size, breadth, concentration, ex-ante identifiability, and cost-stress gates, it fails temporal distribution. There is no threshold search, parameter change, V4, or substitute hypothesis.

Locked OOS was neither resolved nor read. Artifacts record `OOS_NOT_ACCESSED`. D4.4/OOS requires a separate explicit user authorization; D4.3 stops here.
