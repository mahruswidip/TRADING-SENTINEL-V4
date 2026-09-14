# D5 Contract Freeze — V1

**Status:** FROZEN  
**Version:** `1.0.0`  
**Frozen:** 2026-09-13

## Boundary

D5 freezes transport contracts only. It does not implement a trading backend, Shadow, Canary, Real execution, authenticated exchange access, automatic promotion, or locked OOS evaluation.

The canonical TypeScript contract is `src/domain/contracts-v1.ts`. Its read-only machine-readable manifest is exposed at `GET /api/contracts/v1`. Existing `/api/market-data/*` bridge routes and `/api/research/d4-7` are internal pre-V1 engineering endpoints and are not part of the frozen public backend contract.

## Compatibility

- Transport fields use `snake_case`; dashboard view models may remain `camelCase` behind adapters.
- Additive optional fields are backward-compatible.
- Removing or renaming fields, changing types/semantics, enum values, ordering rules, or promotion gates requires a new contract major version.
- Every REST response uses `ApiEnvelopeV1<T>` or `ApiErrorV1`.
- UTC timestamps are ISO-8601 strings. Candle/event timestamps are Unix seconds.
- Unknown enum values must be rejected, never silently mapped.

## Frozen REST surface

| Method | Path | Payload |
|---|---|---|
| GET | `/api/v1/backtests/{run_id}` | `ApiEnvelopeV1<BacktestLiveStatusV1>` |
| GET | `/api/v1/replays/{run_id}/annotations` | `ApiEnvelopeV1<ChartAnnotationsV1>` |
| GET | `/api/v1/strategies/{strategy_id}/{strategy_version}` | `ApiEnvelopeV1<StrategyVersionV1>` |
| GET | `/api/v1/system/health` | `ApiEnvelopeV1<SystemHealthV1>` |
| POST | `/api/v1/promotions` | `PromotionRequestV1` → `ApiEnvelopeV1<PromotionResultV1>` |

`strategy_id + strategy_version + config_hash + code_commit + dataset_version + fee_model_version + execution_model_version` is immutable strategy identity. Changing any member creates a different validated artifact.

## WebSocket V1

Endpoint: `/ws/v1/events`

Every event contains `contract_version`, `event_id`, `stream_key`, monotonic `sequence`, `emitted_at`, `type`, and `payload`. Frozen event types are:

- `BACKTEST_STATUS`
- `CHART_ANNOTATION`
- `TRADING_STATE`
- `SYSTEM_HEALTH`
- `PROMOTION_STATE`

Ordering is per `stream_key`. Clients ignore duplicate `event_id` values and sequences already applied, then recover from the matching REST snapshot after reconnecting.

## Annotation rules

Every `ChartAnnotationV1` contains symbol and immutable strategy provenance plus both `ts` and `available_at`. An annotation is invisible before `available_at`; this preserves no-lookahead replay.

The schema separates range annotations, structure-price annotations, and execution-price annotations. Entry, stop loss, and take profit always require explicit price and LONG/SHORT direction.

## Promotion workflow

```text
RESEARCH → FAST_BACKTEST → ACCURATE_REPLAY → OOS → WALK_FORWARD → SHADOW → CANARY_REAL → REAL
```

Only the next transition is legal; stages cannot be skipped. Each transition requires its frozen evidence gates. Every evaluated gate carries its explicit threshold, observed value, and immutable artifact ID. Promotion into `SHADOW`, `CANARY_REAL`, or `REAL` requires manual operator approval. Automatic promotion to REAL is forbidden.

D4.7 created no strategy, so this freeze does not authorize OOS, Shadow, Canary, or Real for Signal B.
