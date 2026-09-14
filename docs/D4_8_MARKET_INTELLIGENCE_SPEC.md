# D4.8 — Market Data & Regime Intelligence

## Purpose

D4.8 adds a deterministic, no-lookahead market-regime router. It does not create a strategy, place a trade, open OOS, or enable Shadow/Real execution.

Realtime snapshots use the dynamically discovered perpetual universe and require current `TRADING` status; there is no static symbol whitelist.

## Inputs

- closed 1D trend from 8/21 EMA direction and slope,
- closed 1H direction and directional efficiency,
- 1H volume expansion,
- funding level and change,
- open-interest change,
- futures basis,
- taker buy/sell imbalance.

The last three historical series are optional bridge capabilities. Missing series are explicit and can force `WAIT`. Historical spread/order-book depth is not supplied by Binance's historical public market-data endpoints and remains `HISTORICAL_FEATURE_NOT_AVAILABLE`; D4.8 does not invent a liquidity proxy.

## Frozen routing rules

The thresholds in `RegimeConfig` are predeclared engineering defaults, not optimized values.

| Regime | Route | Entry permission |
| --- | --- | --- |
| `TRENDING_BULLISH` | `TREND_LONG` | No; wait for 1H structure then 5M entry |
| `TRENDING_BEARISH` | `TREND_SHORT` | No; wait for 1H structure then 5M entry |
| `SIDEWAYS_RANGE` | `RANGE_MEAN_REVERSION` | No; wait for 1H structure then 5M entry |
| `AMBIGUOUS` / `DATA_INSUFFICIENT` | `WAIT` | No |

Trend classification requires aligned 1D/1H direction, adequate 1H efficiency, at least two participation confirmations among volume expansion, rising OI, and directional taker imbalance, and no same-direction funding-level, funding-change, or basis crowding veto.

## V2 read-only bridge extension

D4.8 consumes these versioned wrapper routes when advertised by `/openapi.json`:

- `/api/v1/market/open-interest-window` → Binance `/futures/data/openInterestHist`
- `/api/v1/market/basis-window` → Binance `/futures/data/basis`
- `/api/v1/market/taker-volume-window` → Binance `/futures/data/takerlongshortRatio`

The Binance endpoints expose only recent history (currently 30 days). Long-history validation therefore requires forward collection into versioned local datasets. V4 must continue through the read-only V2 bridge and must not bypass it with direct Binance requests.

## Run

With the V2 bridge tunnel online:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
& "C:\Users\ADMIN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m research_engine.market_intelligence capabilities
& "C:\Users\ADMIN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m research_engine.market_intelligence snapshot --verify-set --workers 15
```

The command fails before downloading candles when any participant-data bridge extension is missing. `--allow-partial` exists only for diagnostics and forces unconfirmed trends to `WAIT`. Use `--universe all` only after a verification snapshot succeeds. Artifacts are immutable under `state/market-intelligence/<run_id>` and retain `OOS_NOT_ACCESSED`, `shadow_enabled: false`, and `real_execution_enabled: false`.

Verified integration snapshot `d4_8_cfd567f19af4f10b` completed with three usable dynamically selected symbols, zero failures, complete OI/basis/taker inputs, one `SIDEWAYS_RANGE` route, and two `AMBIGUOUS`/`WAIT` decisions. This verifies transport and deterministic routing, not profitability.
