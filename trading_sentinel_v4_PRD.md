# Trading Sentinel V4 — Product Requirements Document (PRD)

**Status:** Locked Draft v1.0  
**Primary goal:** Build a systematic Binance USDⓈ-M Futures research-to-real trading platform that can discover, backtest, validate, visualize, shadow, promote, and execute LONG/SHORT strategies with strict risk controls.

---

## 1. Product Vision

Trading Sentinel V4 is not a signal bot. It is a **research → validation → promotion → live execution platform**.

The system must:

1. Scan the full eligible Binance USDⓈ-M perpetual futures universe, including large-cap assets such as BTC, ETH, SOL and smaller symbols.
2. Support both LONG and SHORT.
3. Use a strict fractal framework where each timeframe has one job:
   - HTF = market context / bias
   - MTF = structure / setup confirmation
   - LTF = entry / execution
4. Backtest strategies quickly using cached Binance market data.
5. Re-run promising candidates with more realistic execution assumptions.
6. Include commission, funding, spread, slippage, tick size, step size, and symbol constraints in evaluation.
7. Visualize what the strategy “sees” on the chart: bias, structure, liquidity, BOS/MSS/CHoCH, FVG, POI, entry, stop, targets, and trade lifecycle.
8. Let the operator manually promote a validated strategy into SHADOW, CANARY REAL, and REAL modes.
9. Keep strategy versions immutable after validation.
10. Keep AI subordinate to deterministic strategy and risk guardrails.

---

## 2. Core Doctrine — LOCKED

### 2.1 Timeframe is framework, not strategy

Timeframe only organizes information. Strategy profitability is determined by market context, bias, liquidity, structure, entry model, and risk management.

### 2.2 No overanalysis

For every trading profile, only the explicitly defined timeframe chain is allowed.

Example intraday profile:

- 1D → Bias / Market Context
- 1H → Structure
- 5M → Entry

The engine must not consult unrelated timeframes to “find confirmation”.

### 2.3 Top-down only

State progression:

HTF Context → Bias Locked → MTF Structure → LTF Entry → Risk Gate → Execution

If alignment fails at any stage: **WAIT**.

### 2.4 LTF cannot rewrite HTF bias

Lower timeframe volatility cannot reverse the higher-timeframe bias unless the strategy’s HTF invalidation rule is explicitly satisfied.

### 2.5 Mandatory beats optional

Each strategy defines:

- Mandatory conditions
- Optional evidence

If any mandatory condition fails, the result is NO TRADE regardless of optional confirmations.

### 2.6 Reproducibility is mandatory

Every signal and trade must be reproducible from:

- strategy ID
- strategy version
- config hash
- code commit
- dataset version
- fee model version
- execution model version

---

## 3. Supported Market Scope

### 3.1 Initial market

**Binance USDⓈ-M Perpetual Futures**.

Reasons:

- native LONG/SHORT support
- common quote accounting
- scalable universe
- major coins and altcoins in one venue
- funding and futures metadata available

### 3.2 Eligible symbol filter

A symbol may enter the research universe only if:

- status is tradable
- contract type is perpetual
- quote/margin asset is supported
- sufficient historical data exists
- spread is measurable
- tick size and quantity rules are known

Execution can add stricter filters:

- minimum volume
- maximum spread
- minimum order-book depth
- sufficient recent history
- acceptable funding conditions

### 3.3 Historical universe integrity

Backtests must use **Universe(t)**, not today’s symbol list applied backward.

A symbol may only participate in historical replay after its historical listing date. Delisted symbols must not disappear from historical research simply because they are unavailable today.

---

### 3.4 No static symbol whitelist — LOCKED

Trading Sentinel V4 must dynamically discover the Binance USDⓈ-M Futures perpetual universe. BTC, ETH, and SOL are examples and reference symbols, never an allowlist. Large caps, mid caps, small caps, meme coins, and newly listed perpetual contracts may all participate in research; market capitalization alone is not an exclusion criterion.

Research eligibility and future execution eligibility are determined from Binance trading status, contract type, quote/margin compatibility, historical data availability, listing age, spread, liquidity, order-book depth, volatility, executable market quality, strategy validity, and independent risk constraints.

Operational tiers allocate resources and describe execution quality; they do not ban a symbol from research. The permanent principle is: **NO STATIC SYMBOL WHITELIST.**

---

## 4. Trading Profiles

Profiles define timeframe responsibilities only.

| Profile | Bias / HTF | Structure / MTF | Entry / LTF |
|---|---|---|---|
| Swing Macro | 1M | 1D | 1H |
| Swing | 1W | 4H | 15M |
| Intraday | 1D | 1H | 5M |
| Intraday Fast | 4H | 30M | 3M |
| Scalping | 4H | 15M | 1M |

Initial production priority: **Intraday (1D → 1H → 5M)**.

---

## 5. Fractal Trading Engine

### 5.1 HTF — Market Context / Bias

Responsibilities:

- bullish / bearish / neutral context
- premium / discount location
- HTF POI
- HTF liquidity
- major market structure
- directional bias
- bias invalidation rule

The HTF layer does not create an entry.

### 5.2 MTF — Structure

Responsibilities:

- BOS
- MSS / CHoCH
- liquidity sweep
- displacement
- FVG
- POI
- setup confirmation

MTF output:

- CONFIRMED
- WAIT
- INVALIDATED

### 5.3 LTF — Entry

Responsibilities:

- entry model
- entry confirmation
- entry price / zone
- invalidation / stop placement
- targets
- expected R:R

LTF may only activate after HTF + MTF are valid.

---

## 6. Strategy Factory

Initial strategy families:

- TREND_CONTINUATION
- PULLBACK_CONTINUATION
- BREAKOUT_RETEST
- LIQUIDITY_SWEEP_REVERSAL
- RANGE_REVERSION
- COMPRESSION_EXPANSION
- MOMENTUM_BREAK

Every strategy implements the same interface:

```text
context()
bias()
structure()
setup()
trigger()
entry()
stop()
targets()
invalidate()
```

Each strategy must declare:

- trading profile
- direction support: LONG / SHORT / BOTH
- mandatory conditions
- optional evidence
- risk rules
- exit model

Timeframe combinations are not optimized implicitly. A different timeframe chain creates a different profile/version.

---

## 7. Strategy State Machine

Required lifecycle:

```text
SCANNING
→ HTF_CONTEXT_FOUND
→ BIAS_LOCKED
→ WAITING_MTF_STRUCTURE
→ MTF_CONFIRMED
→ WAITING_LTF_ENTRY
→ ENTRY_TRIGGERED
→ RISK_VALIDATION
→ ORDER_PENDING
→ OPEN
→ MANAGING
→ EXITED
```

Alternative exits:

```text
WAIT
INVALIDATED
RISK_REJECTED
EXECUTION_REJECTED
```

Every transition must be journaled with timestamp and reason.

---

## 8. Backtest Engine

### 8.1 Two-stage architecture

#### Stage A — Fast Discovery

Purpose: rapidly test many symbols / strategies / parameter variants.

Characteristics:

- cached historical data
- vectorized calculations
- local resampling
- lightweight execution approximation
- high throughput

Recommended stack:

- Parquet
- Polars
- NumPy
- optional Numba
- parallel workers

#### Stage B — Accurate Validation

Only promising candidates enter this stage.

Include:

- 1m replay minimum
- exact historical funding where applicable
- mark price where applicable
- realistic fee model
- spread model
- slippage model
- conservative intrabar handling
- order constraints
- optional trade-level or finer-grained replay for final candidates

### 8.2 Required cost model

All reported PnL must have:

```text
Gross PnL
- entry commission
- exit commission
- funding
- spread impact
- slippage
= Net PnL
```

Dashboard must default to NET PnL.

### 8.3 Intrabar ambiguity

If OHLC data cannot determine whether TP or SL was touched first, the engine must use a documented conservative rule or finer data. The engine must never silently choose the favorable path.

---

## 9. Research & Validation Pipeline

Required stages:

```text
RESEARCH
→ FAST_BACKTEST
→ ACCURATE_REPLAY
→ OOS
→ WALK_FORWARD
→ SHADOW
→ CANARY_REAL
→ REAL
```

### 9.1 Promotion requirements

A strategy cannot skip directly from backtest to REAL.

Minimum gates before REAL:

- sufficient sample size
- positive net expectancy
- acceptable PF
- acceptable drawdown
- stable LONG/SHORT behavior where relevant
- OOS passed
- walk-forward passed
- fee stress passed
- slippage stress passed
- shadow passed
- canary passed

Thresholds are configurable but must be explicit.

---

## 10. Performance Metrics

Required metrics:

- Net Return
- Gross Return
- Trade count
- Win Rate
- Expectancy per trade
- Expectancy in R
- Profit Factor
- Max Drawdown
- Sharpe
- Sortino
- Average R
- Median R
- LONG performance
- SHORT performance
- fee sensitivity
- slippage sensitivity
- funding impact
- OOS metrics
- walk-forward metrics

### 10.1 Sentinel Robustness Score

A composite score may be used for ranking but cannot replace raw metrics.

Suggested inputs:

- OOS consistency
- PF
- expectancy
- drawdown
- sample size
- stability across periods
- stability across symbols
- fee sensitivity
- slippage sensitivity

---

## 11. Risk Engine

Risk Engine is independent from Strategy Engine.

Pipeline:

```text
Strategy Signal
→ Risk Engine
→ Execution Engine
```

Risk checks:

- equity
- max risk per trade
- daily loss limit
- open portfolio risk
- per-symbol exposure
- per-strategy exposure
- max concurrent trades
- leverage limit
- correlation / crypto-beta concentration
- exchange order constraints
- kill switch state

AI may not bypass any risk limit.

Initial recommended production defaults:

- isolated margin
- one-way mode
- conservative leverage
- small canary allocation

---

## 12. Execution Engine

Modes:

- SIMULATION
- SHADOW
- CANARY_REAL
- REAL

Responsibilities:

- place entry
- confirm fills
- place protective stop
- place/manage targets
- reconcile exchange state
- detect stale / orphaned orders
- recover after restart
- close positions on command

Protective stop orders must be exchange-side whenever technically possible so protection remains active if the VPS or dashboard fails.

---

## 13. Strategy Versioning & Promotion

Validated strategy artifacts are immutable.

Each artifact includes:

```text
strategy_id
strategy_version
profile
parameters
config_hash
code_commit
dataset_version
fee_model_version
execution_model_version
validation_results
promotion_state
```

Changing any strategy parameter creates a new version requiring revalidation.

Example:

```text
BREAKOUT_RETEST_V17
ATR_SL = 1.8
```

Change to 2.2 → new version:

```text
BREAKOUT_RETEST_V18
```

V18 must restart the required validation pipeline.

---

## 14. HoodSniper Concepts Reused in V4

Reusable concepts:

1. Hard guardrails before AI.
2. AI output clamped to allowed ranges.
3. Executable PnL separated from displayed/mark PnL.
4. Decision logs with reason, conviction, outcome, and lesson.
5. Rejected opportunities are journaled, not discarded silently.
6. Liquidity / depth-aware execution checks.

Not reused blindly:

- DEX-specific pair-selection assumptions
- DEX-native price derivation
- chain-specific routing logic

Binance symbol metadata must be explicit and authoritative.

---

# 15. Dashboard — FIRST IMPLEMENTATION TARGET

The dashboard is the first visible component, but it must be **contract-first**, not a disconnected mockup.

Build the UI against stable mock JSON schemas that later become live API/WebSocket contracts.

## 15.1 Dashboard Navigation

Primary navigation:

```text
OVERVIEW
RESEARCH
BACKTEST
STRATEGIES
SHADOW
REAL
DATA
JOURNAL
RISK
SETTINGS
```

Global header:

- current system mode
- exchange connection status
- data freshness
- equity (when live connected)
- today PnL
- current open risk
- kill switch

---

## 15.2 Screen A — Overview

Required widgets:

### System status

- Market Data
- Research Workers
- Backtest Workers
- Shadow Engine
- Real Execution
- Binance connection
- last heartbeat

### Research status

- active run
- symbols completed / total
- current symbol
- current strategy
- current profile
- ETA

### Best candidates

- strategy
- symbol scope
- net return
- PF
- expectancy
- drawdown
- OOS status
- current promotion state

### Real / Shadow positions

- symbol
- direction
- strategy version
- entry
- mark
- SL
- TP
- executable PnL

---

## 15.3 Screen B — Backtest Monitor

This is a primary V4 screen.

Top panel:

```text
RUN ID
RUNNING / PAUSED / COMPLETE
symbols complete / total
strategy variants complete / total
elapsed
ETA
worker count
```

Current task card:

```text
Current Symbol
Current Strategy
Current Profile
Current Timeframe Stage
Current Data Range
Current Test Mode
```

Live metrics:

- trades
- gross return
- net return
- win rate
- PF
- expectancy
- drawdown
- fee paid
- funding paid/received
- slippage estimate

Required actions:

- Pause
- Resume
- Cancel
- View Chart
- View Journal

---

## 15.4 Screen C — Strategy Lab

Each strategy version card shows:

```text
Strategy ID / Version
Profile
Direction support
Backtest status
OOS status
Walk-forward status
Shadow status
Canary status
Promotion state
```

Metrics:

- Net Return
- PF
- Expectancy
- Max DD
- Trades
- LONG PF
- SHORT PF
- Robustness Score

Actions depend on gate:

```text
[OPEN REPORT]
[REPLAY]
[PROMOTE TO SHADOW]
[PROMOTE TO CANARY]
[PROMOTE TO REAL]
[ARCHIVE]
```

Promotion buttons must be disabled if requirements fail.

---

## 15.5 Screen D — Chart / Replay

The chart must visually expose what Sentinel sees.

### HTF chart overlays

- major structure
- range high / low
- premium
- equilibrium
- discount
- HTF liquidity
- HTF POI
- bias label

### MTF chart overlays

- BOS
- MSS / CHoCH
- liquidity sweep
- displacement
- FVG
- POI

### LTF chart overlays

- entry zone
- confirmation
- entry
- stop
- TP1 / TP2 / TPn
- invalidation
- trailing stop if active

Colors:

- entry = neutral/blue
- profit targets = green
- stop / invalidation = red

### Replay controls

```text
|<  <  PLAY  >  >|
1x 2x 4x 10x
```

Event timeline shows:

```text
HTF BIAS LOCKED
MTF SWEEP
MTF MSS
LTF TRIGGER
RISK PASSED
ENTRY FILLED
TP / SL / EXIT
```

---

## 15.6 Screen E — Live / Real Trading

Position card:

```text
BTCUSDT LONG
Strategy: TREND_CONTINUATION_V27
Profile: Intraday

Entry
Mark
Executable Exit Estimate
SL
TP1
TP2
Position Size
Leverage
Risk $ / %
Mark PnL
Executable PnL
```

Actions:

- close 25%
- close 50%
- close all
- move stop if strategy allows
- emergency close

Manual controls must be logged.

---

## 15.7 Screen F — Decision Funnel / Journal

Example:

```text
BTCUSDT — Intraday

HTF contexts found        8,421
MTF structures confirmed  2,130
LTF triggers                712
Risk passed                 584
Trades                      584
TP                          301
SL                          205
BE                           78
```

Journal row:

```text
timestamp
symbol
strategy
profile
state transition
decision
reason
metrics snapshot
chart snapshot reference
outcome
```

Rejected trades must be queryable.

---

## 15.8 Screen G — Risk

Show:

- account equity
- total open risk
- daily realized PnL
- daily loss remaining
- open positions
- symbol concentration
- strategy concentration
- correlated exposure
- leverage exposure
- kill switch

Controls:

- enable/disable real execution
- max risk/trade
- daily loss limit
- max concurrent positions
- max strategy allocation

High-impact changes require explicit confirmation.

---

## 16. Dashboard Technology

Recommended stack:

### Frontend

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui or equivalent controlled component layer
- TradingView Lightweight Charts
- custom annotation overlay
- WebSocket client

### Backend API

- FastAPI
- Pydantic
- REST for state/history/actions
- WebSocket for live status and chart events

### State / persistence

- PostgreSQL for metadata, journal, strategies, runs, promotions, trades
- Parquet for large historical market datasets
- Redis optional for live state / queues

---

## 17. Dashboard API Contracts — Initial Mock Schema

### Backtest live status

```json
{
  "run_id": "bt_20260910_001",
  "state": "RUNNING",
  "progress": {
    "symbols_done": 14,
    "symbols_total": 317,
    "variants_done": 1240,
    "variants_total": 9400
  },
  "current": {
    "symbol": "BTCUSDT",
    "strategy": "TREND_CONTINUATION_V7",
    "profile": "INTRADAY",
    "stage": "LTF_ENTRY",
    "timeframe": "5m"
  },
  "metrics": {
    "trades": 328,
    "gross_return_pct": 38.4,
    "net_return_pct": 34.7,
    "win_rate_pct": 47.2,
    "profit_factor": 1.61,
    "expectancy_r": 0.24,
    "max_drawdown_pct": 7.4
  }
}
```

### Chart annotations

```json
{
  "symbol": "BTCUSDT",
  "profile": "INTRADAY",
  "strategy": "TREND_CONTINUATION_V7",
  "annotations": [
    {
      "type": "BIAS",
      "timeframe": "1d",
      "direction": "BULLISH",
      "from_ts": 0,
      "to_ts": 0
    },
    {
      "type": "BOS",
      "timeframe": "1h",
      "price": 112000,
      "ts": 0
    },
    {
      "type": "ENTRY",
      "timeframe": "5m",
      "price": 111920,
      "ts": 0
    },
    {
      "type": "STOP",
      "timeframe": "5m",
      "price": 111510,
      "ts": 0
    },
    {
      "type": "TARGET",
      "timeframe": "5m",
      "price": 113350,
      "ts": 0,
      "label": "TP2"
    }
  ]
}
```

---

## 18. Non-Goals for V4.0

Not required in the first release:

- autonomous strategy mutation in live mode
- AI bypassing deterministic execution rules
- unsupported exchanges
- copy trading
- social sentiment as a mandatory signal
- arbitrary timeframe hopping
- automatic promotion to REAL without operator approval

---

## 19. Delivery Plan — Dashboard First

### Phase D0 — Dashboard Shell

Deliver:

- Next.js app
- navigation
- theme
- global system header
- mock system state
- responsive layout

### Phase D1 — Backtest Monitor

Deliver:

- run progress
- current symbol / strategy / timeframe
- live metrics
- worker state
- pause/resume/cancel mock actions

### Phase D2 — Chart & Replay

Deliver:

- candlestick chart
- timeframe switcher
- HTF/MTF/LTF overlays
- Entry / SL / TP visualization
- replay timeline

### Phase D3 — Strategy Lab

Deliver:

- strategy cards/table
- validation gates
- promotion state
- disabled/enabled promotion buttons based on mocks

### Phase D4 — Shadow / Real

Deliver:

- live position cards
- executable PnL field
- risk panel
- kill switch UI
- manual close controls (mock only initially)

### Phase D5 — Contract Freeze

Freeze:

- API schemas
- WebSocket event schemas
- status enums
- chart annotation schema
- promotion workflow

Only after D5 should backend services implement the same contracts.

---

## 20. Acceptance Criteria for Dashboard-First Milestone

The dashboard milestone is complete when:

1. Operator can open the dashboard and understand system mode immediately.
2. Operator can see which symbol and strategy a mock backtest is processing.
3. Operator can watch backtest progress update without page refresh.
4. Operator can open a strategy and see validation status and metrics.
5. Operator can open chart replay and see HTF/MTF/LTF annotations.
6. Entry, TP, and SL are visually distinct.
7. Promotion actions are gated by validation state.
8. REAL controls are visually separated from RESEARCH controls.
9. Kill switch is globally visible.
10. UI uses the same contracts later required by backend implementation.

---

## 21. Final Product Principle

Trading Sentinel V4 must never optimize for “more signals”.

It must optimize for:

**explainable edge → realistic validation → controlled promotion → safe execution**.

If alignment is incomplete, the correct action is **WAIT**.
