# D4.8 — Cross-Market Harvest & Strategy Transferability Study

## Scope

D4.8 inventories previously tested deterministic mechanisms, admits only mechanisms with explicit historical evidence, freezes their rules, and tests market/fold transferability with the unchanged D3/D4 execution and cost semantics. It does not invent or tune a strategy, modify V2, access a locked legacy OOS set, or enable Shadow, Canary, or REAL execution.

The earlier `market_intelligence.py` experiment remains an isolated research precursor. It is not the authoritative D4.8 milestone and does not authorize entries.

## Frozen candidates

The historical admission ledger currently admits five unchanged mechanisms:

- `BREAKOUT_RETEST_V1`
- `RANGE_REVERSION_V1`
- `MOMENTUM_BREAK_V1`
- `BREAKOUT_RETEST_V2`
- `RANGE_REVERSION_V2`

Signals without a complete entry/exit/SL/TP mechanism are classified `INSUFFICIENT_HISTORICAL_EVIDENCE`. Rejected mechanisms remain visible in the harvest inventory.

## Deterministic protocol

Stage A is capped at 24 symbols: 8 high-liquidity, 8 medium-liquidity, and 8 high-beta/lower-liquidity contracts selected from complete local 5M cache history. BTC and ETH are included only when each has complete eligibility history. Selection uses a historical quote-notional proxy and realized volatility; there is no static whitelist.

Four chronological folds each contain a Development portion followed by an OOS portion. OOS never changes rules or selection. Stage A has 960 planned jobs: 5 mechanisms × 24 symbols × 4 folds × 2 phases. Worker count is capped at 15. External downloads are always zero.

The transferability score follows the frozen 30/25/15/15/10/5 weighting for positive-market ratio, median expectancy, median PF, OOS survival, concentration, and trade sufficiency. Stage gates are implemented as conjunctive checks; no average score can override a failed hard gate.

## Current preflight result

Run `d4_8_c7bfd27b45b30eb4` found 120 symbols with 33 complete cached 5M days and built the required 24-symbol Stage A cohort. It then stopped before backtesting because none of those 24 symbols has local funding history covering the evaluation interval. Treating missing funding as zero would violate execution realism.

The run verdict is `INSUFFICIENT_DATA`. Stage A, Stage B, and full-universe execution were not run. No data was downloaded.

## Commands

```powershell
python -m research_engine.transferability plan --workers 15
python -m research_engine.transferability execute --run-id d4_8_c7bfd27b45b30eb4
```

The second command returns the immutable stop report while funding coverage remains incomplete.
