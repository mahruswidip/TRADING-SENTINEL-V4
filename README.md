# Trading Sentinel V4 Dashboard

Stable D0+D1 through D4.6B foundations. D4.6B tests the two frozen D4.5 relationships on broader Development-only historical coverage and does not create a strategy, entry, stop, target, or order. The project contains no exchange credentials, Shadow/Canary/Real execution, promotion workflow, brute-force optimizer, or AI trading logic.

## Run locally

Requirements: Node.js 22+ and pnpm 11+.

Keep the V2 market-data SSH tunnel available and set the server-only bridge URL in `.env.local`:

```env
MARKET_DATA_BASE_URL=http://127.0.0.1:8766
```

```bash
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

Production verification:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm start
```

Run a small actual-data D3 engineering backtest while the V2 bridge tunnel is active:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m backtest_engine run --strategy ENGINE_REFERENCE_INTRADAY_V1 --start 2026-08-01 --end 2026-08-02 --symbols BTCUSDT,SOLUSDT,DOGEUSDT --workers 3
```

Use `--verify-set` to choose three liquidity-ranked symbols dynamically, or `--universe all` to accept the full eligible `Universe(t)`. Outputs are written under `state/backtests/<run-id>` and cached market partitions under `data/market`.

Run a bounded D4 engineering research validation (symbols are checked against dynamic `Universe(t)`; they are not a production whitelist):

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m research_engine --dev-start 2026-08-01 --dev-end 2026-08-04 --oos-start 2026-08-04 --oos-end 2026-08-07 --verify-set --workers 3
```

Research artifacts are written under `state/research/<STRATEGY_VERSION>/<research-run-id>` and the batch ranking/checkpoint under `state/research-runs/<research-run-id>`. Interrupted batches resume completed strategy versions, an identical completed run returns `ALREADY_COMPLETED`, and a reused ID with different identity is rejected.

Run immutable V1 forensics and the two evidence-based Development-only V2 checks:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m forensics_engine --research-run d4_dynamic_stratified_v3_20260911 --validate-development
```

Forensic artifacts live under `state/forensics/<FAMILY_VERSION>`. V2 Development artifacts live under `state/research/<FAMILY_VERSION>/<validation-id>`. No locked OOS artifact is read by this command.

Plan and execute the immutable D4.2 Stage A expansion separately so resource use is visible before downloads:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m forensics_engine.expansion plan --stage A --dev-start 2026-07-01 --dev-end 2026-08-01 --workers 3
python -m forensics_engine.expansion execute --run-id d4_2_a_706bdf1b5577051b
```

The first command writes a resource plan; the second reuses cached partitions and checkpoints candidate completion. This command has no OOS mode.

Run the deterministic D4.3 accounting and breakout-regime audit against the completed D4.2 Development run:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m forensics_engine.accounting_audit --d4-2-run d4_2_a_706bdf1b5577051b --starting-equity 10000
```

Artifacts are written under `state/accounting-audit/d4_3_*`. The audit preserves legacy metrics, labels them as aggregate fixed-notional research metrics, and adds a separate research-only reference equity result. It never reads locked OOS.

Plan and execute D4.4 separately. The plan prints universe, dates, estimated candles/jobs, cache state, network requests, and worker count before market history is requested:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m research_engine.fvg plan --dev-start 2026-07-01 --dev-end 2026-08-01 --workers 3
python -m research_engine.fvg execute --run-id d4_4_7c26a8a6736abaf2
```

D4.4 writes triage artifacts under `state/triage/d4_4_*` and the sole FVG hypothesis under `state/research/FVG_PULLBACK_V1/d4_4_*`. Downloads are paced through the V2 bridge; cached 5M history is reused. The command has no OOS or M1 mode.

Plan and execute D4.5 separately so the data capability matrix, frozen feature catalog, universe, cache state, requests, and resource estimate exist before forward-return evaluation:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m research_engine.discovery plan --dev-start 2026-07-01T00:00:00Z --dev-end 2026-07-31T20:00:00Z --workers 3
python -m research_engine.discovery execute --run-id d4_5_482ba89ea0075922
```

D4.5 artifacts live under `state/signal-discovery/d4_5_*`. The command has no strategy-construction or OOS mode. Historical OI, premium/basis, BBO/spread, and depth are explicitly unavailable rather than approximated from current snapshots.

Plan and execute D4.6 one stage at a time. A later stage is rejected unless the prior replication gate explicitly authorizes it:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m research_engine.replication plan --stage A --dev-start 2026-07-01T00:00:00Z --dev-end 2026-07-31T20:00:00Z --workers 2
python -m research_engine.replication execute --run-id d4_6_8733a768a0dd3dd4 --stage A
```

D4.6 artifacts live under `state/signal-replication/d4_6_*`, with per-stage plans/results under `stages/`. The verified Stage A stopped expansion after Signal A was not replicated; no Stage B/C, strategy construction, or OOS access occurred.

D4.6B continues from the immutable D4.6 parent with Signal B as the independent primary progression gate:

```powershell
$env:MARKET_DATA_BASE_URL="http://127.0.0.1:8766"
python -m research_engine.replication_b plan --stage B --dev-start 2026-07-01T00:00:00Z --dev-end 2026-07-31T20:00:00Z --workers 2
python -m research_engine.replication_b execute --run-id d4_6b_d9380c7ff0781bac --stage B
```

The immutable D4.6B run reached Stage C with 189 usable symbols. Signal B remained `WEAK_REPLICATION`, Signal A remained `NOT_REPLICATED`, and locked OOS was not accessed.

## Architecture

```text
App Router page / reusable component
  → sentinelData provider entry point
    → SentinelDataProvider contract
      → deterministic mock provider (D0+D1)

Replay route / ReplayWorkspace
  → ReplayDataProvider
    → deterministic ReplayScenario fixture
      → ReplayClock
        → temporal selectors → chart / annotations / state / audit

Data / System route / MarketDataWorkspace
  → MarketDataProvider
    → same-origin Next.js market-data routes
      → MARKET_DATA_BASE_URL → Trading Sentinel V2 read-only bridge
    → selected-symbol candle polling through the same bridge
      → normalized registry / candles → selector / chart / integrity UI

D3 CLI worker
  → V2 bridge historical candle/funding windows
    → versioned daily gzip JSONL cache
      → closed-only 1D / 1H / 5M reference strategy
        → fast execution + targeted 1M validation
          → immutable run artifact → dashboard provider + D2 replay provider

D4 research CLI
  → cached actual Binance history + dynamic Universe(t) eligibility
    → seven predeclared deterministic V1 hypotheses
      → chronological Dev / locked OOS / walk-forward
        → cost stress + parameter stability + symbol breadth
          → transparent robustness ranking + rejection reasons
            → immutable research artifacts → Strategy Lab + D2 replay provider

D4.1 forensics CLI
  → immutable V1 Development trades + cached candles
    → excursion / entry / exit / direction / regime / cost / tier distributions
      → evidence-based immutable V2 hypotheses
        → Development-only unchanged gates → stop when rejected

D4.2 expansion CLI
  → immutable V2 rules + dynamic liquidity terciles
    → persisted resource plan + D3 cache + bounded bridge retries
      → longer Development + temporal/regime/concentration evidence
        → unchanged Development gates → explicit early stop, OOS_NOT_ACCESSED

D4.3 accounting/regime audit
  → immutable D4.2 Development trades
    → aggregate fixed-notional semantics + $10,000 reference equity
      → peak-to-subsequent-trough equity drawdown bounded at 100%
        → ex-ante 1H high-volatility/expansion forensics
          → temporal gate failure → no V3, OOS_NOT_ACCESSED

D4.4 triage + FVG research
  → immutable V1 Development trade forensics → four KEEP/KILL decisions
  → dynamic stratified Stage A history via V2 bridge/cache
    → closed 1H bias → canonical closed 15M FVG → closed 5M sweep/MSS
      → next-5M-open D3 costs/execution → reference equity + unchanged gates
        → FVG V1 rejected → no V2, M1, or OOS

D4.5 signal discovery
  → frozen feature catalog + dynamic cached Universe(t)
    → past-only OHLCV/funding/listing/context features
      → closed-candle forward labels + horizon downsampling + daily block bootstrap
        → temporal/breadth/asymmetry/listing evidence + 11 bps hurdle

D4.6 signal replication
  → exact D4.5 definitions + hashes
    → deterministic staged Universe(t) expansion through the V2 bridge
      → dependence-aware breadth, temporal, cross-sectional, and cost-hurdle evidence
        → objective gate → stop after Stage A (no strategy, no OOS)
          → immutable signal evidence only → no strategy or OOS

D4.6B broader replication
  → immutable D4.6 parent + exact D4.5 definition hashes
    → Signal B-primary Stage B/C breadth expansion through the same cache/bridge
      → 189 usable symbols → B weak, A not replicated → no strategy or OOS
```

Domain contracts live in `src/domain/contracts.ts`. The backtest run contract separates universe progress, current evaluation, strategy variant, state machine, live metrics, and completed evaluations. Business fixtures are centralized in `src/data/fixtures.ts`; pages never import them. Every run ID resolves through one indexed fixture object, Overview and Backtest consume that same provider state, and progress percentage is derived from processed/total symbols. Strategy metrics are owned by one immutable strategy-artifact registry and referenced by matching runs. `src/data/index.ts` remains the single replacement point for a future API/WebSocket-backed provider.

## Routes

| Route | Status |
|---|---|
| `/` | Overview with operational summaries, system health, activity, decisions, and results |
| `/backtest` | Frozen active monitor plus clearly sourced MOCK / REAL BACKTEST job results |
| `/backtest/replay/bt_20260910_001` | D2 development-fixture replay with synchronized annotations and audit trail |
| `/backtest/replay/d4_4_7c26a8a6736abaf2` | D4.4 FVG V1 Development replay with 1H/15M/5M structured events |
| `/strategies` | D4.6 replication results, D4.5 discovery evidence, real D4 candidate/rejection inventory, and separately labeled legacy mocks |
| `/shadow` | Structured placeholder |
| `/real` | Structured placeholder; no execution |
| `/journal` | Structured placeholder |
| `/risk` | Structured placeholder |
| `/data-system` | Dynamic Binance USDⓈ-M universe, quality registry, symbol selector, and current/historical chart |

## Data and UI states

Fixtures are deterministic and cover LONG, SHORT, WAIT, REJECTED, running, completed, queued, paused, failed, strong/weak strategies, and healthy/degraded services. `DataStateBoundary` supports loading, empty, success, degraded, and error rendering without inventing fallback metrics.

All execution-facing controls are explicitly locked, unavailable, or labeled UI-only. Execution costs include USD impact and normalized basis points. Legacy strategy totals are labeled Aggregate Net Return / Aggregate Fixed-Notional Drawdown; the D4.3 panel separately reports Reference Equity Return / Reference Equity Max DD.

## Milestone boundary

D0+D1, D2, D2.5, D3, D4, D4.1, D4.2, D4.3, D4.4, D4.5, D4.6, and D4.6B are stable. D4.6B completed independent Signal B-primary Stage B/C breadth replication with 189 usable symbols. It stores Development-only evidence, never strategy rules, and locked OOS remains untouched. Account access, orders, M1 execution, Shadow, Canary, Real execution, auto-promotion, optimization, AI decisions, strategy construction, and D5 remain out of scope.
