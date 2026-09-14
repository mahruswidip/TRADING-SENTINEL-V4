# AGENTS.md — Trading Sentinel V4

## Purpose

This repository contains **Trading Sentinel V4**, a systematic crypto research, backtesting, promotion, shadow, and eventually live-execution platform.

Agents working in this repository must optimize for:

1. correctness,
2. reproducibility,
3. auditability,
4. execution realism,
5. safety,
6. maintainable architecture.

Do not optimize for flashy output at the expense of system integrity.

## Always-On Efficiency Mode

For every task in this project, including new Codex chats:

- use the Ponytail plugin in `full` mode for coding work,
- use Caveman Mode whenever its plugin capability is available,
- keep responses terse and lead with the result,
- prefer the smallest correct change, existing code, and standard-library or native features,
- avoid subagents, broad searches, repeated validation, and unrelated work unless the user explicitly requests them,
- run only validation proportional to the change and do not run backtests or research pipelines unless explicitly requested.

If Caveman Mode is unavailable, continue with the same terse style without blocking the task.

---

## Source of Truth

Primary product specification:

- `trading_sentinel_v4_PRD.md`

If implementation choices conflict with the PRD, the PRD wins unless the user explicitly approves a change.

Do not silently reinterpret the trading doctrine.

---

## Current Development Phase

### STABLE FOUNDATION: Dashboard D0 + D1

D0+D1 remains frozen. Preserve its application shell, Overview, Backtest Monitor, Backtest Jobs, Strategy Lab, typed contracts, provider boundary, and reusable dashboard components.

### STABLE FOUNDATION: D2 — Chart + Deterministic Replay + Structured Annotations

Current scope:

- deterministic historical replay fixtures,
- one authoritative replay clock,
- 1D / 1H / 5M candlestick rendering,
- provider-supplied structured trading events,
- no-lookahead annotation visibility,
- synchronized state machine and audit timeline,
- deterministic forward/backward replay controls.

### STABLE FOUNDATION: D2.5 — Binance Public Market Data + Dynamic Symbol Universe

Current scope:

- read-only Binance USDⓈ-M Futures metadata and public market data,
- dynamic perpetual-contract discovery,
- typed universe registry and historical `Universe(t)` semantics,
- public historical/current 1D, 1H, and 5M candles,
- one selected-symbol live market stream,
- explicit data-source and provider-health states.

### STABLE FOUNDATION: D3 — Real Deterministic Backtest Engine

Current scope:

- actual historical Binance USDⓈ-M data only through the V2 read-only bridge,
- versioned local history cache and dataset provenance,
- deterministic 5M fast path with closed-only 1H / 1D resampling,
- conservative intrabar execution followed by targeted 1M validation,
- itemized fees, funding, spread, and slippage,
- checkpointed jobs, immutable artifacts, dashboard jobs, and D2 replay artifacts.

The D3 reference strategy remains `ENGINE_REFERENCE_INTRADAY_V1`, explicitly **NOT A VALIDATED TRADING STRATEGY**. D3 validates engine mechanics and is reused without changing its execution or cost semantics.

### STABLE FOUNDATION: D4 — Strategy Research, Validation, and Ranking

D4 owns seven predeclared, deterministic V1 hypotheses, chronological Development/OOS and walk-forward evaluation, cost stress, parameter-neighborhood checks, symbol breadth, transparent robustness scoring, rejection reasons, immutable research artifacts, and Strategy Lab integration. The fixed INTRADAY framework remains 1D Bias, 1H Structure, and 5M Entry. OOS is locked and cannot tune a strategy.

### STABLE FOUNDATION: D4.1 — Strategy Forensics and Hypothesis Refinement

D4.1 analyzes immutable V1 Development trades for entry/exit excursion, direction, regime, costs, symbol/tier, and concentration evidence. It created only two justified immutable V2 hypotheses and both failed unchanged Development gates. Locked OOS was not read. Existing V1 artifacts remain unchanged.

### STABLE FOUNDATION: D4.2 — Development Evidence Expansion

D4.2 expands Development-only evidence for the immutable `BREAKOUT_RETEST_V2` and `RANGE_REVERSION_V2` rules across a dynamic liquidity-stratified universe, longer chronological history, temporal segments, deterministic regimes, concentration metrics, and unchanged cost stress. Stage A rejected both candidates; Stage B was therefore not run. Locked OOS remains `OOS_NOT_ACCESSED` and requires explicit user authorization even if a future Development candidate becomes eligible.

### STABLE FOUNDATION: D4.3 — Portfolio Accounting Audit + Regime-Conditioned Breakout Hypothesis

D4.3 separates aggregate fixed-notional research returns from reference portfolio-equity returns, audits peak-to-trough equity drawdown and bankruptcy behavior, and evaluates the pre-existing ex-ante HIGH_VOLATILITY / EXPANSION slice for `BREAKOUT_RETEST_V2`. The slice failed temporal-distribution evidence, so `BREAKOUT_RETEST_V3` was not justified or created. Locked OOS remains `OOS_NOT_ACCESSED`.

### STABLE FOUNDATION: D4.4 — Remaining Family Triage + FVG Pullback V1

D4.4 classifies the four remaining immutable V1 families using Development-only forensic evidence and evaluates exactly one new immutable `FVG_PULLBACK_V1` hypothesis. Its `INTRADAY_FVG` profile is 1H Direction/Bias, 15M FVG/Setup Area, and 5M Confirmation/Entry. The verified Stage A run rejected FVG V1; no V2 was created. Locked OOS remains `OOS_NOT_ACCESSED`.

### STABLE FOUNDATION: D4.5 — Signal Discovery / Feature Research

D4.5 uses Development-only historical data to measure economically interpretable feature relationships with future closed-candle returns. It freezes the feature catalog before evaluation, enforces Universe(t), reports dependence-aware confidence, temporal stability, symbol breadth, direction asymmetry, listing age, and an execution-cost hurdle. It creates signal evidence only. Locked OOS remains `OOS_NOT_ACCESSED`.

### STABLE FOUNDATION: D4.6 — Signal Replication & Development Coverage Expansion

D4.6 loads and hashes exactly the two promising definitions from authoritative D4.5 run `d4_5_482ba89ea0075922`, then tests them on a broader deterministic historical Universe(t). It preserves D4.5 feature, bucket, timestamp, forward-label, dependence, breadth, and temporal semantics. The verified Stage A run produced 48 usable symbols, classified Signal A `NOT_REPLICATED` and Signal B `WEAK_REPLICATION`, and stopped before Stage B/C. It creates replication evidence only; locked OOS remains `OOS_NOT_ACCESSED`.

### STABLE FOUNDATION: D4.6B — Broader Signal Replication

D4.6B references immutable parent run `d4_6_8733a768a0dd3dd4`, preserves both D4.5 definition hashes and the same Development window, and expands deterministic Universe(t) breadth through Stage B and Stage C. Signal B independently controls progression; Signal A cannot veto it. The verified run `d4_6b_d9380c7ff0781bac` reached 189 usable symbols and retained Signal B as `WEAK_REPLICATION`; Signal A remained `NOT_REPLICATED`. Locked OOS remains `OOS_NOT_ACCESSED`.

### STABLE FOUNDATION: D4.7 — Independent Temporal Replication

D4.7 references immutable parent run `d4_6b_d9380c7ff0781bac` and the unchanged Signal B definition hash `79f6169b3289d82c1e7e6b654b93bf7440d14cb1f42b00ad858a3d64f26d49af`. Verified run `d4_7_f38827b40e50d854` used a non-overlapping pre-July Development window and 201 usable symbols. Signal B was `NOT_REPLICATED`: its mean and median were negative and broad, but the daily-block confidence interval crossed zero and temporal evidence showed `SIGN_FLIP`. Locked OOS remains `OOS_NOT_ACCESSED`; no strategy was created.

### STABLE FOUNDATION: D5 — Contract Freeze

D5 freezes transport contract V1.0.0 in `src/domain/contracts-v1.ts`: REST envelopes and payloads, WebSocket envelopes/events and ordering, status enums, no-lookahead chart annotations, immutable strategy identity, and the sequential manual promotion workflow. The read-only manifest is exposed at `/api/contracts/v1`. This does not implement backend trading services, authorize OOS, or enable Shadow, Canary, Real, or automatic promotion.

### D4.8 — Cross-Market Harvest & Strategy Transferability Study

D4.8 inventories prior deterministic mechanisms, freezes admissible rules, and measures cross-market/fold transferability with unchanged D3/D4 execution and costs. Preflight run `d4_8_c7bfd27b45b30eb4` built a deterministic 24-symbol Stage A cohort. D4.8A subsequently completed its official historical funding cache, resolving the data blocker without changing the cohort or launching Stage A. Stage A, Stage B, full-universe, Shadow, Canary, and REAL remain unexecuted. The earlier market-intelligence router remains an isolated precursor, not an entry authority or the authoritative D4.8 milestone.

### STABLE FOUNDATION: D4.8A — Historical Funding Cache Backfill

D4.8A fetched only the frozen 24-symbol Stage A cohort from Binance's official USDⓈ-M public funding endpoint through the existing read-only V2 bridge. It cached 4,482 actual funding events for the minimum evaluation range plus a deterministic one-day boundary buffer. All 24 contracts and coverage checks passed; no symbol, strategy, execution rule, or score/gate changed. D4.8 data is ready, but its 960-job Stage A run still requires a separate explicit action.

### OUT OF SCOPE FOR D4.6 / D4.6B / D4.7

Do **not** implement:

- real Binance order execution,
- API-key order placement,
- live money deployment,
- canary execution,
- shadow engine,
- authenticated/account WebSocket streams,
- brute-force strategy optimizer,
- AI trading decisions,
- automatic promotion,
- functional Promote to Shadow / Canary / Real actions.

Promotion buttons remain disabled. D4.6 does not create strategies, entries, stop losses, take profits, parameter sweeps, machine-learning models, optimizers, locked OOS evaluations, Shadow, Canary, or REAL execution.

Do not continue into D5 automatically.

---

# Core Trading Doctrine

## No static symbol whitelist

Trading Sentinel V4 must dynamically discover the Binance USDⓈ-M Futures perpetual universe. BTC, ETH, and SOL are reference symbols only; large caps, mid caps, small caps, meme coins, and newly listed perpetual contracts may all participate in research.

A symbol must never be excluded merely because of market capitalization or because it is absent from a hand-maintained list. Research and future execution eligibility must be derived from Binance trading status, contract and quote/margin compatibility, historical availability, listing age, spread, liquidity, order-book depth, volatility, executable market quality, strategy validity, and risk constraints.

**NO STATIC SYMBOL WHITELIST.**

## Timeframe is a framework, not a strategy

For the default INTRADAY profile:

- `1D` = Bias / Market Context
- `1H` = Structure / Setup
- `5M` = Entry / Execution

Do not add random extra timeframe confirmation.

Do not allow the UI or mock logic to imply:

- 1D + 4H + 1H + 30M + 15M + 5M + 1M analysis,
- timeframe hopping to justify a trade,
- lower timeframe data changing higher timeframe bias arbitrarily.

If required alignment is incomplete:

`WAIT`

---

## Responsibility by timeframe

### 1D — Market Context / Bias

May contain:

- bullish / bearish / neutral,
- premium / equilibrium / discount,
- HTF POI,
- liquidity,
- major market structure,
- directional bias.

The 1D layer does **not** create an entry by itself.

### 1H — Structure / Setup

May contain:

- BOS,
- MSS / CHoCH,
- liquidity sweep,
- displacement,
- FVG,
- POI,
- structural confirmation.

The 1H layer confirms whether the setup is structurally valid.

### 5M — Entry / Execution

May contain:

- entry model,
- entry confirmation,
- entry price,
- stop loss,
- target(s),
- risk placement.

The 5M layer may only search for an entry after HTF + MTF conditions are valid.

---

# Trading State Machine

The shared domain model must support these states:

```text
SCANNING
HTF_CONTEXT_FOUND
BIAS_LOCKED
WAITING_MTF_STRUCTURE
MTF_CONFIRMED
WAITING_LTF_ENTRY
ENTRY_TRIGGERED
RISK_VALIDATION
TRADE_OPEN
TRADE_CLOSED
REJECTED
WAIT
```

Do not replace these with vague status strings like only:

- Running
- Done
- Failed

UI should expose meaningful state progression.

---

# Architecture Rules

## Contract-first

The dashboard is being built before the trading backend.

Therefore:

- UI components must consume typed interfaces,
- mock data must come through a provider abstraction,
- components must not contain embedded mock datasets,
- backend replacement later should not require rewriting page structure.

Preferred flow:

```text
UI Component
    ↓
View Model / Hook
    ↓
Data Provider Interface
    ↓
Mock Provider (now)
    ↓
API Provider (later)
```

---

## Required typed domain models

Create or maintain strongly typed contracts for at least:

- `Symbol`
- `TradingProfile`
- `MarketContext`
- `StructureState`
- `EntryState`
- `StrategyVersion`
- `BacktestJob`
- `BacktestMetrics`
- `StrategyLifecycle`
- `Position`
- `RiskState`
- `DecisionLog`
- `SystemHealth`

Avoid `any`.

Avoid untyped dictionaries for core domain data.

---

# Strategy Identity

A strategy version must be treated as immutable conceptually.

Future backend identity should be compatible with:

```text
strategy_id
strategy_version
config_hash
code_commit
dataset_version
fee_model_version
```

Do not design UI state that assumes a strategy can mutate in place after validation.

---

# Metrics Semantics

The dashboard must clearly distinguish realistic metrics.

Use:

- Net Return
- Win Rate
- Expectancy
- Profit Factor
- Max Drawdown
- Trade Count
- Fees
- Funding
- Slippage
- LONG metrics
- SHORT metrics
- Robustness Score

Do not present only gross profit.

Do not label gross PnL as net PnL.

Do not invent performance figures that are not present in the provider data.

---

# Risk and Safety Doctrine

Even though real execution is out of scope now, the architecture must reserve space for independent risk controls.

Future execution flow:

```text
Strategy Engine
      ↓
Signal
      ↓
Risk Engine
      ↓
Execution Engine
```

The Risk Engine must conceptually remain independent from strategy logic.

AI or strategy code must never be designed to bypass:

- max risk,
- max leverage,
- kill switch,
- symbol restrictions,
- account limits,
- protective stops.

---

# Dashboard Information Hierarchy

## Main navigation

Required sections:

- Overview
- Backtest
- Strategies
- Shadow
- Real
- Journal
- Risk
- Data / System

For D0+D1, Shadow/Real/etc. may be placeholders but routes should not be broken.

---

## Global Header

Show:

- Trading Sentinel V4
- Binance connection state
- environment
- engine status
- kill switch
- UTC and/or local time

Environment enum should support:

```text
RESEARCH
SHADOW
CANARY
REAL
```

---

## Overview

Include:

- active backtest jobs,
- processed / total symbols,
- strategies under research,
- shadow strategies,
- real strategies,
- active positions,
- account risk,
- daily PnL,
- system health,
- recent strategy activity,
- recent decisions,
- recent backtest results.

---

## Backtest Monitor

Must support:

- current symbol,
- strategy name/version,
- trading profile,
- timeframe framework,
- current state-machine stage,
- progress,
- processed/total symbols,
- ETA,
- trades,
- net return,
- win rate,
- expectancy,
- profit factor,
- max drawdown,
- fees,
- funding,
- slippage,
- LONG vs SHORT stats.

Prefer visible state transitions over generic loading indicators.

---

## Strategy Cards

Display:

- strategy name,
- version,
- lifecycle stage,
- backtest status,
- OOS status,
- shadow status,
- canary status,
- real status,
- metrics,
- robustness score.

Promotion controls during D0+D1:

- `Promote to Shadow`
- `Promote to Canary`
- `Promote to Real`

These controls must be disabled or clearly mock-only.

---

# Visual Design

Use a professional dark trading-terminal aesthetic.

Priorities:

1. information hierarchy,
2. readability,
3. density,
4. state visibility,
5. responsive desktop-first layout.

Avoid:

- excessive glassmorphism,
- giant decorative cards,
- unnecessary gradients,
- huge empty spacing,
- gimmicky animations,
- dashboards that look like a crypto landing page.

Semantic colors:

- green = positive / LONG / TP / healthy,
- red = negative / SHORT / SL / danger,
- amber = waiting / warning,
- blue = informational / active,
- gray = inactive / neutral.

Do not rely on color alone; pair colors with text/icons/status labels.

---

# Frontend Technical Rules

Preferred stack:

- Next.js
- TypeScript
- reusable components
- linting
- tests where reasonable

Follow the existing repository package manager and conventions if the repo already exists.

Do not introduce a second framework or state library without need.

Avoid premature global state.

Prefer server/client component boundaries that match actual needs.

---

# Mock Data Rules

Mock data is temporary infrastructure, not disposable junk.

Requirements:

- centralized mock fixtures,
- provider abstraction,
- realistic values,
- deterministic where possible,
- representative edge states,
- include healthy, warning, waiting, rejected, and failed cases.

Do not place large hardcoded objects directly in page components.

Include examples for:

- LONG,
- SHORT,
- WAIT,
- REJECTED,
- active backtest,
- completed backtest,
- failed/paused job,
- positive metrics,
- weak metrics,
- system warning.

---

# Naming Conventions

Prefer descriptive domain names.

Good:

```text
BacktestMetrics
StrategyLifecycleStage
TradingProfile
MarketContext
RiskState
DecisionLog
```

Avoid:

```text
Data1
Info
Temp
Thing
ResultObj
Misc
```

---

# Error Handling

Do not hide errors.

The dashboard must have explicit states for:

- loading,
- empty,
- success,
- degraded,
- error.

Do not fabricate fallback metrics if provider data is unavailable.

---

# Testing Expectations

At minimum verify:

- TypeScript build passes,
- lint passes,
- routes render,
- mock provider works,
- critical components handle empty/error states,
- no broken navigation,
- no hydration/runtime console errors.

If a test framework exists, add appropriate tests.

Do not add a large testing framework solely for trivial coverage unless justified.

---

# Completion Checklist for D0 + D1

Before declaring completion:

- [ ] app installs successfully,
- [ ] app builds successfully,
- [ ] lint passes,
- [ ] tests pass if present,
- [ ] all D0/D1 routes render,
- [ ] navigation has no broken links,
- [ ] mock provider is separated from UI,
- [ ] core types are centralized,
- [ ] Backtest Monitor exposes state-machine stage,
- [ ] strategy cards exist,
- [ ] promotion buttons are non-functional,
- [ ] README contains run instructions,
- [ ] architecture is documented,
- [ ] no REAL execution code was added,
- [ ] no D2 chart/replay implementation was started.

---

# Required Agent Workflow

When starting work:

1. inspect repository structure,
2. read `AGENTS.md`,
3. read `trading_sentinel_v4_PRD.md`,
4. identify existing frontend conventions,
5. inspect current package scripts,
6. make a short implementation plan,
7. implement incrementally,
8. run validation commands,
9. fix failures,
10. report exact results.

Do not claim success before running the validation commands.

---

# Scope Discipline

If a feature is not required for D0+D1, do not add it just because it is interesting.

Especially avoid:

- live trading,
- Binance order execution,
- strategy optimizer,
- replay engine,
- AI decision engine,
- real promotion workflows,
- production secrets,
- wallet/private key handling.

Prefer a clean milestone over a half-built platform.

---

# Security

Never commit:

- Binance API keys,
- API secrets,
- private keys,
- wallet seed phrases,
- credentials,
- production tokens.

Use environment variables and `.env.example`.

Ensure secret files remain gitignored.

Do not log secrets.

---

# Future Compatibility

Even though D0+D1 are mock-only, avoid architectural decisions that block:

- live WebSocket updates,
- real backtest progress streaming,
- chart annotations,
- replay mode,
- strategy promotion,
- shadow trading,
- canary deployment,
- risk gating,
- real execution,
- audit logs.

Design for replacement, not rewrite.

---

# Agent Completion Report

At the end of the task, report:

1. files created,
2. files changed,
3. routes implemented,
4. architecture summary,
5. typed contracts created,
6. mock provider design,
7. validation commands run,
8. build/lint/test results,
9. known limitations,
10. exact command to run the dashboard,
11. readiness status for D2.

Use one of:

```text
D0+D1 READY
D0+D1 PARTIAL
D0+D1 BLOCKED
```

If not fully verified, do not use `READY`.

---

# Final Rule

The objective is not to make Trading Sentinel V4 look intelligent.

The objective is to make it:

**deterministic, inspectable, reproducible, safe, and eventually profitable after realistic execution costs.**

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
