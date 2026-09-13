# D4 Strategy Research, Validation, and Ranking

## Boundary

D4 answers which deterministic strategy versions show durable net edge; it does not trade, promote, or tune with OOS data. It reuses D3's actual-data cache, next-open execution, itemized cost accounting, metrics, structured events, and D2 replay contract. No browser or React component infers trading structure.

The fixed profile is INTRADAY: closed 1D Bias / Context, closed 1H Structure / Setup, and closed 5M Entry / Execution. A signal is evaluated only after its input candle closes and fills at the next 5M open. No other timeframe combination is searched.

## Predeclared hypotheses and variant discipline

The batch contains exactly one canonical V1 for each family; this is seven hypotheses/versions, not a parameter sweep.

| Family | V1 hypothesis and mandatory evidence |
|---|---|
| TREND_CONTINUATION | Aligned closed 1D/1H direction persists through a decisive 5M body. |
| PULLBACK_CONTINUATION | A directional 5M rejection wick resumes an aligned 1D/1H trend. |
| BREAKOUT_RETEST | A closed 1H breakout is retested and closed directionally on 5M. |
| LIQUIDITY_SWEEP_REVERSAL | A 5M sweep beyond the last closed 1H extreme reclaims it with 1D bias. |
| RANGE_REVERSION | A small-body 1D range reverts inward from a closed 1H boundary. |
| COMPRESSION_EXPANSION | A compressed closed 1H range expands on 5M with 1D bias. |
| MOMENTUM_BREAK | A strong 5M body continues aligned closed 1D/1H momentum. |

Each immutable manifest records the hypothesis, mandatory requirements, WAIT/REJECTED conditions, entry, volatility-distance stop, 1.5R target, parameters, config hash, code commit availability, dataset/engine/cost/execution versions, and multiple-testing metadata. Only the primary threshold is checked at 0.9×, 1.0×, and 1.1×. Neighbors measure fragility; they are never selected as replacements.

## Temporal validation

Development and OOS ranges are explicit half-open UTC windows. `dev_end <= oos_start` is enforced. The OOS manifest is marked `locked: true` and `tuning_allowed: false`; random splits and random cross-validation do not exist.

Two forward-only validation folds are recorded: the second half of Development following its first half, then locked OOS following all Development. Ranking uses validation evidence and never rewrites a strategy after OOS. The initial engineering batch evaluates all seven small hypotheses for pipeline coverage; later broad confirmation is reserved for candidates that survive deterministic gates.

## Universe and compute safety

Symbols are accepted only after lookup in the bridge-provided dynamic USDⓈ-M perpetual `Universe(t)`. `--verify-set` liquidity-ranks the eligible snapshot and selects its high, middle, and low-volume representatives; explicit symbols remain available but are eligibility-validated and are not a production whitelist. Full-universe confirmation remains required before any future production candidacy.

Workers are bounded to 1–8. All strategies reuse the same cached actual 5M and observed funding windows; history is not downloaded per strategy. An atomic per-strategy checkpoint resumes unfinished batches, completed identical run identities are reused, and a run-ID collision with a different identity fails. Research batches deliberately contain a small number of versions.

## Net metrics and stress

Primary comparison is net expectancy after configured taker fees, observed funding, modeled spread, and modeled slippage. Outputs include expectancy and expectancy-R, PF, drawdown, trades, net/gross return, average R, MAE/MFE, and independent LONG/SHORT slices. Direction validity is `LONG_ONLY_VALID`, `SHORT_ONLY_VALID`, `BOTH_VALID`, or `NOT_VALID`.

Cost stress leaves strategy parameters unchanged:

- BASE: 4 bps fee per side, 2 bps spread, 1 bp slippage.
- HIGHER_FEE_50: fee increased 50%.
- HIGHER_SPREAD_50: spread increased 50%.
- HIGHER_SLIPPAGE_50: slippage increased 50%.

## Breadth, concentration, and evidence

Per-symbol outputs include PnL and trade count. Breadth reports profitable and losing symbol counts, top-symbol and top-five profit share, mean/median trades per symbol, and trades per 30-day month. `SYMBOL_CONCENTRATION` is raised when one symbol supplies over 60% of positive PnL. Fewer than 20 Development trades raises `INSUFFICIENT_TRADES` and the score's sample component reaches full credit only at 30 OOS trades.

## Transparent robustness score

The deterministic 0–100 score is the weighted sum of stored components:

| Component | Weight |
|---|---:|
| positive OOS expectancy | 20% |
| positive walk-forward fold share | 15% |
| OOS PF, capped at 1.5 | 10% |
| OOS drawdown penalty | 10% |
| OOS sample size, capped at 30 trades | 10% |
| parameter-neighborhood stability | 10% |
| profitable-symbol breadth | 10% |
| positive-expectancy cost-scenario share | 15% |

Raw Net Return has no score component. The full component and weight maps are stored. Ranking is score descending with strategy identity as the deterministic tie-breaker.

## Gates and rejection

The lifecycle vocabulary supports `FAST_BACKTEST`, `DEV_PASSED`, `OOS_PENDING`, `OOS_PASSED`, `WALK_FORWARD_PENDING`, `WALK_FORWARD_PASSED`, `ROBUSTNESS_PASSED`, `RESEARCH_REJECTED`, and terminal D4 `RESEARCH_READY`. D4 never enters Shadow, Canary, or Real.

Rejections remain visible and preserve: `NEGATIVE_EXPECTANCY`, `PF_BELOW_THRESHOLD`, `MAX_DD_TOO_HIGH`, `INSUFFICIENT_TRADES`, `OOS_FAILED`, `WALK_FORWARD_FAILED`, `PARAMETER_FRAGILE`, `COST_FRAGILE`, `SYMBOL_CONCENTRATION`, `LONG_FAILED`, and `SHORT_FAILED`. Gates are not weakened to manufacture a winner.

## Artifacts and dashboard

Each version writes `manifest.json`, Dev/OOS summaries, walk-forward folds, robustness/components/neighborhood/breadth, cost stress, symbol metrics JSON, Dev/OOS trade JSONL, Dev decision/event JSONL, rejection reasons, replay links, optional `replay.json`, and the Strategy Lab projection beneath `state/research/<STRATEGY_VERSION>/<RUN_ID>`.

Each batch writes its immutable manifest, live/completed research status, and deterministic ranking beneath `state/research-runs/<RUN_ID>`. Strategy Lab labels `RESEARCH_CANDIDATE`, `RESEARCH_REJECTED`, `ENGINEERING_REFERENCE`, and `MOCK` separately. Its progress percentage derives from processed/total. A selected real trade reuses the existing D2 replay route and includes strategy, version, phase, symbol, trade, and dataset identity.

## D5 boundary

D4 stops at research evidence. It contains no exchange credentials, account data, orders, leverage changes, Shadow engine, Canary, Real execution, automatic promotion, AI decisions, or self-modifying strategy. A `RESEARCH_READY` result would still require a separate user-authorized D5 milestone.
