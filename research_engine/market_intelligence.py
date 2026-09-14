from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from backtest_engine.cli import choose_symbols, eligible_symbols
from backtest_engine.data import BridgeClient, HistoricalDataStore, atomic_json, iso_ms
from backtest_engine.engine import resample_closed
from backtest_engine.model import Candle, FundingEvent


ENGINE_VERSION = "d4.8-market-intelligence-v1"
DAY_MS = 86_400_000
FLOW_LOOKBACK_MS = 7 * DAY_MS
FLOW_PERIOD_MS = 3_600_000
WARMUP_MS = 28 * DAY_MS

FLOW_CONTRACTS = {
    "open_interest": ("/api/v1/market/open-interest-window", "openInterest"),
    "basis": ("/api/v1/market/basis-window", "basis"),
    "taker_volume": ("/api/v1/market/taker-volume-window", "takerVolume"),
}

Regime = Literal["TRENDING_BULLISH", "TRENDING_BEARISH", "SIDEWAYS_RANGE", "AMBIGUOUS", "DATA_INSUFFICIENT"]
Route = Literal["TREND_LONG", "TREND_SHORT", "RANGE_MEAN_REVERSION", "WAIT"]


@dataclass(frozen=True)
class RegimeConfig:
    daily_ema_gap: float = 0.002
    hourly_return: float = 0.003
    hourly_efficiency: float = 0.30
    range_efficiency: float = 0.25
    volume_expansion: float = 1.15
    taker_imbalance: float = 0.05
    funding_crowding: float = 0.0005
    funding_change_crowding: float = 0.0002
    basis_crowding: float = 0.001
    minimum_flow_confirmations: int = 2


@dataclass(frozen=True)
class RegimeInputs:
    as_of: int
    daily_direction: int | None
    hourly_direction: int | None
    hourly_efficiency: float | None
    volume_expansion: float | None
    funding_level: float | None
    funding_change: float | None
    open_interest_change: float | None
    basis_rate: float | None
    taker_imbalance: float | None
    missing_features: tuple[str, ...] = ()


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("insufficient EMA history")
    value = sum(values[:period]) / period
    weight = 2 / (period + 1)
    for item in values[period:]:
        value = item * weight + value * (1 - weight)
    return value


def _direction(values: list[float], fast: int, slow: int, minimum_gap: float) -> int | None:
    if len(values) < slow + 1 or not values[-1]:
        return None
    fast_now, slow_now = _ema(values, fast), _ema(values, slow)
    fast_before = _ema(values[:-1], fast)
    gap = (fast_now - slow_now) / values[-1]
    if gap >= minimum_gap and fast_now > fast_before:
        return 1
    if gap <= -minimum_gap and fast_now < fast_before:
        return -1
    return 0


def _hourly_context(hourly: list[Candle], config: RegimeConfig) -> tuple[int | None, float | None]:
    if len(hourly) < 25:
        return None, None
    closes = [bar.close for bar in hourly[-25:]]
    movement = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    efficiency = abs(closes[-1] - closes[0]) / movement if movement else 0.0
    change = closes[-1] / closes[-13] - 1 if closes[-13] else 0.0
    direction = 1 if change >= config.hourly_return else -1 if change <= -config.hourly_return else 0
    return direction, efficiency


def _latest_number(rows: list[dict[str, Any]], keys: tuple[str, ...], as_of: int) -> tuple[float | None, float | None]:
    values: list[tuple[int, float]] = []
    for row in rows:
        try:
            timestamp = int(row.get("timestamp", row.get("time", row.get("fundingTime"))))
            raw = next(row[key] for key in keys if row.get(key) is not None)
            if timestamp + FLOW_PERIOD_MS <= as_of:
                values.append((timestamp, float(raw)))
        except (KeyError, StopIteration, TypeError, ValueError):
            continue
    values.sort()
    if not values:
        return None, None
    return values[-1][1], values[-2][1] if len(values) > 1 else None


def _taker_imbalance(rows: list[dict[str, Any]], as_of: int) -> float | None:
    usable = []
    for row in rows:
        try:
            timestamp = int(row.get("timestamp", row.get("time")))
            buy, sell = float(row["buyVol"]), float(row["sellVol"])
            if timestamp + FLOW_PERIOD_MS <= as_of and buy + sell > 0:
                usable.append((timestamp, (buy - sell) / (buy + sell)))
        except (KeyError, TypeError, ValueError):
            continue
    return max(usable)[1] if usable else None


def derive_inputs(
    candles: list[Candle],
    funding: list[FundingEvent],
    open_interest: list[dict[str, Any]],
    basis: list[dict[str, Any]],
    taker_volume: list[dict[str, Any]],
    as_of: int,
    config: RegimeConfig = RegimeConfig(),
) -> RegimeInputs:
    known = [bar for bar in candles if bar.close_time <= as_of]
    hourly = resample_closed(known, 3_600_000)
    daily = resample_closed(known, DAY_MS)
    daily_direction = _direction([bar.close for bar in daily], 8, 21, config.daily_ema_gap)
    hourly_direction, hourly_efficiency = _hourly_context(hourly, config)
    volume_expansion = None
    if len(hourly) >= 25:
        baseline = statistics.fmean(bar.volume for bar in hourly[-25:-1])
        volume_expansion = hourly[-1].volume / baseline if baseline > 0 else None

    known_funding = sorted((event for event in funding if event.timestamp <= as_of), key=lambda event: event.timestamp)
    funding_level = known_funding[-1].rate if known_funding else None
    funding_change = known_funding[-1].rate - known_funding[-2].rate if len(known_funding) > 1 else None
    oi_now, oi_before = _latest_number(open_interest, ("sumOpenInterestValue", "sumOpenInterest"), as_of)
    oi_change = oi_now / oi_before - 1 if oi_now is not None and oi_before not in {None, 0} else None
    basis_rate, _ = _latest_number(basis, ("basisRate",), as_of)
    taker_imbalance = _taker_imbalance(taker_volume, as_of)
    available = {
        "DAILY_TREND": daily_direction,
        "HOURLY_DIRECTION": hourly_direction,
        "HOURLY_EFFICIENCY": hourly_efficiency,
        "VOLUME_EXPANSION": volume_expansion,
        "FUNDING_LEVEL": funding_level,
        "FUNDING_CHANGE": funding_change,
        "OPEN_INTEREST_CHANGE": oi_change,
        "BASIS_RATE": basis_rate,
        "TAKER_IMBALANCE": taker_imbalance,
    }
    return RegimeInputs(
        as_of,
        daily_direction,
        hourly_direction,
        hourly_efficiency,
        volume_expansion,
        funding_level,
        funding_change,
        oi_change,
        basis_rate,
        taker_imbalance,
        tuple(key for key, value in available.items() if value is None),
    )


def classify_regime(inputs: RegimeInputs, config: RegimeConfig = RegimeConfig()) -> dict[str, Any]:
    required = (inputs.daily_direction, inputs.hourly_direction, inputs.hourly_efficiency, inputs.volume_expansion)
    if any(value is None for value in required):
        regime: Regime = "DATA_INSUFFICIENT"
        reasons = ["CLOSED_1D_OR_1H_HISTORY_INSUFFICIENT"]
    elif inputs.daily_direction == inputs.hourly_direction and inputs.daily_direction in {-1, 1}:
        side = inputs.daily_direction
        confirmations = [
            cast(float, inputs.volume_expansion) >= config.volume_expansion,
            inputs.open_interest_change is not None and inputs.open_interest_change > 0,
            inputs.taker_imbalance is not None and inputs.taker_imbalance * side >= config.taker_imbalance,
        ]
        crowded = (
            inputs.funding_level is not None and inputs.funding_level * side >= config.funding_crowding
        ) or (
            inputs.funding_change is not None and inputs.funding_change * side >= config.funding_change_crowding
        ) or (
            inputs.basis_rate is not None and inputs.basis_rate * side >= config.basis_crowding
        )
        strong = cast(float, inputs.hourly_efficiency) >= config.hourly_efficiency
        if sum(confirmations) >= config.minimum_flow_confirmations and strong and not crowded:
            regime = "TRENDING_BULLISH" if side > 0 else "TRENDING_BEARISH"
            reasons = ["1D_1H_ALIGNED", "TREND_EFFICIENT", "PARTICIPATION_CONFIRMED"]
        else:
            regime = "AMBIGUOUS"
            reasons = []
            if not strong:
                reasons.append("TREND_EFFICIENCY_WEAK")
            if sum(confirmations) < config.minimum_flow_confirmations:
                reasons.append("PARTICIPATION_NOT_CONFIRMED")
            if crowded:
                reasons.append("POSITIONING_CROWDED")
    elif (
        inputs.daily_direction == 0
        and inputs.hourly_direction == 0
        and cast(float, inputs.hourly_efficiency) <= config.range_efficiency
        and cast(float, inputs.volume_expansion) < config.volume_expansion
    ):
        regime = "SIDEWAYS_RANGE"
        reasons = ["1D_1H_NEUTRAL", "LOW_DIRECTIONAL_EFFICIENCY", "NO_VOLUME_EXPANSION"]
    else:
        regime = "AMBIGUOUS"
        reasons = ["TIMEFRAME_OR_PARTICIPATION_CONFLICT"]

    route = cast(Route, {
        "TRENDING_BULLISH": "TREND_LONG",
        "TRENDING_BEARISH": "TREND_SHORT",
        "SIDEWAYS_RANGE": "RANGE_MEAN_REVERSION",
    }.get(regime, "WAIT"))
    return {
        "regime": regime,
        "route": route,
        "state": "WAITING_MTF_STRUCTURE" if route != "WAIT" else "WAIT",
        "reasons": reasons,
        "entry_authorized": False,
        "required_next_gate": "1H_STRUCTURE_THEN_5M_ENTRY" if route != "WAIT" else None,
    }


class IntelligenceBridge(BridgeClient):
    def capabilities(self) -> dict[str, bool]:
        document = self.get("/openapi.json")
        paths = document.get("paths", {})
        if not isinstance(paths, dict):
            raise RuntimeError("invalid bridge OpenAPI contract")
        return {name: path in paths for name, (path, _) in FLOW_CONTRACTS.items()}

    def flow(self, name: str, symbol: str, start: int, end: int) -> list[dict[str, Any]]:
        path, key = FLOW_CONTRACTS[name]
        payload = self.get(path, symbol=symbol, period="1h", startTime=start, endTime=end - 1, limit=500)
        rows = payload.get(key)
        if payload.get("symbol") != symbol or not isinstance(rows, list):
            raise RuntimeError(f"invalid {name} bridge contract")
        return [row for row in rows if isinstance(row, dict)]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _flow_data(
    bridge: IntelligenceBridge,
    cache_root: Path,
    name: str,
    symbol: str,
    start: int,
    end: int,
    supported: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not supported:
        return [], {"status": "BRIDGE_CAPABILITY_UNAVAILABLE", "dataset_id": None, "row_count": 0}
    path = cache_root / "binance-usdm-v1" / symbol / name / f"{start}-{end}.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
        cache = "HIT"
    else:
        rows = bridge.flow(name, symbol, start, end)
        atomic_json(path, rows)
        cache = "DOWNLOAD"
    if not isinstance(rows, list):
        raise RuntimeError(f"invalid cached {name} dataset")
    clean = [row for row in rows if isinstance(row, dict)]
    return clean, {"status": "AVAILABLE", "dataset_id": _digest(clean), "row_count": len(clean), "cache": cache}


def _process_symbol(symbol: str, end: int, bridge_url: str, cache_root: Path, capabilities: dict[str, bool]) -> dict[str, Any]:
    bridge = IntelligenceBridge(bridge_url)
    store = HistoricalDataStore(cache_root, bridge)
    candles, manifests = store.candles(symbol, "5m", end - WARMUP_MS, end)
    funding = store.funding(symbol, end - FLOW_LOOKBACK_MS, end)
    flow_results = {
        name: _flow_data(bridge, cache_root, name, symbol, end - FLOW_LOOKBACK_MS, end, supported)
        for name, supported in capabilities.items()
    }
    flows = {name: result[0] for name, result in flow_results.items()}
    flow_quality = {name: result[1] for name, result in flow_results.items()}
    inputs = derive_inputs(candles, funding, flows["open_interest"], flows["basis"], flows["taker_volume"], end - 1)
    return {
        "symbol": symbol,
        "inputs": asdict(inputs),
        "decision": classify_regime(inputs),
        "data_quality": {
            "candle_rows": len(candles),
            "funding_events": len(funding),
            "open_interest_rows": len(flows["open_interest"]),
            "basis_rows": len(flows["basis"]),
            "taker_volume_rows": len(flows["taker_volume"]),
            "flow_datasets": flow_quality,
            "historical_order_book_liquidity": "HISTORICAL_FEATURE_NOT_AVAILABLE",
            "dataset_ids": [item["dataset_id"] for item in manifests],
            "cache_hits": store.cache_hits,
            "downloads": store.downloads,
        },
    }


def snapshot(args: argparse.Namespace) -> dict[str, Any]:
    end = iso_ms(args.as_of) if args.as_of else int(datetime.now(UTC).timestamp() * 1000)
    end -= end % 300_000
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    bridge = IntelligenceBridge(bridge_url)
    universe = bridge.universe()
    historical_eligible, exclusions = eligible_symbols(universe, end - WARMUP_MS, end)
    eligible = []
    for item in historical_eligible:
        if item.get("status") == "TRADING":
            eligible.append(item)
        else:
            exclusions.append({"symbol": str(item.get("symbol", "UNKNOWN")), "reason": "NOT_CURRENTLY_TRADING"})
    symbols = choose_symbols(eligible, args.symbols, args.universe == "all", args.verify_set)
    workers = max(1, min(32, args.workers))
    capabilities = bridge.capabilities()
    missing_capabilities = sorted(name for name, available in capabilities.items() if not available)
    if missing_capabilities and not args.allow_partial:
        raise RuntimeError(f"D4.8 bridge extension missing: {', '.join(missing_capabilities)}")
    identity = {
        "engine_version": ENGINE_VERSION,
        "as_of": end,
        "symbols": symbols,
        "config": asdict(RegimeConfig()),
        "capabilities": capabilities,
    }
    run_id = args.run_id or f"d4_8_{_digest(identity)[:16]}"
    root = Path(args.state_root) / "market-intelligence" / run_id
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("identity_hash") != _digest(identity):
            raise ValueError("immutable D4.8 run ID collision")
        return {"run_id": run_id, "status": "ALREADY_COMPLETED", "artifact": str(root.resolve())}

    results, failures = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_symbol, symbol, end, bridge_url, Path(args.cache_root), capabilities): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results[symbol] = future.result()
            except Exception as error:
                failures[symbol] = {"error": type(error).__name__, "detail": str(error)}
            print(json.dumps({"run_id": run_id, "processed": len(results) + len(failures), "target": len(symbols), "symbol": symbol}))

    ordered = [results[symbol] for symbol in sorted(results)]
    counts: dict[str, int] = {}
    for item in ordered:
        regime = item["decision"]["regime"]
        counts[regime] = counts.get(regime, 0) + 1
    atomic_json(root / "routing.json", ordered)
    atomic_json(root / "failures.json", failures)
    manifest = {
        **identity,
        "run_id": run_id,
        "identity_hash": _digest(identity),
        "status": "COMPLETED" if not failures else "DEGRADED",
        "created_at": datetime.now(UTC).isoformat(),
        "universe_selector": "all" if args.universe == "all" else "verification" if args.verify_set else "symbols",
        "universe_exclusions": exclusions,
        "worker_count": workers,
        "usable_symbols": len(ordered),
        "failed_symbols": len(failures),
        "regime_counts": counts,
        "source": "BINANCE_PUBLIC_VIA_TRADING_SENTINEL_V2_MARKET_BRIDGE",
        "ai_decisions": False,
        "oos_access": "OOS_NOT_ACCESSED",
        "shadow_enabled": False,
        "real_execution_enabled": False,
    }
    atomic_json(manifest_path, manifest)
    return {"run_id": run_id, "status": manifest["status"], "artifact": str(root.resolve()), "regime_counts": counts}


def capability_report() -> dict[str, Any]:
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    capabilities = IntelligenceBridge(bridge_url).capabilities()
    return {
        "status": "READY" if all(capabilities.values()) else "BRIDGE_EXTENSION_REQUIRED",
        "capabilities": capabilities,
        "missing": sorted(name for name, available in capabilities.items() if not available),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="D4.8 deterministic market-regime intelligence")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    run = commands.add_parser("snapshot")
    run.add_argument("--as-of", help="UTC ISO timestamp; defaults to now")
    run.add_argument("--symbols")
    run.add_argument("--universe", choices=["all"])
    run.add_argument("--verify-set", action="store_true")
    run.add_argument("--workers", type=int, default=15)
    run.add_argument("--allow-partial", action="store_true", help="diagnostic only; absent participant data routes trends to WAIT")
    run.add_argument("--run-id")
    run.add_argument("--state-root", default="state")
    run.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = capability_report() if args.command == "capabilities" else snapshot(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
