from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from backtest_engine.cli import eligible_symbols, jsonl, replay_artifact
from backtest_engine.data import BridgeClient, atomic_json, iso_ms
from backtest_engine.engine import metrics, resample_closed, stable_digest
from backtest_engine.model import CostModel
from forensics_engine.analysis import DAY_MS, feature_row, grouped
from forensics_engine.validation import development_gates
from research_engine.refinements import HYPOTHESES, VARIANTS
from research_engine.research import cost_stress, evaluate, load_datasets


ENGINE_VERSION = "d4.2-development-expansion-v1"
STAGE_COUNTS = {"A": 2, "B": 6}


def oos_guard(status: str, user_authorized: bool = False) -> None:
    if status != "OOS_ELIGIBLE":
        raise PermissionError("locked OOS refused: candidate is not OOS_ELIGIBLE")
    if not user_authorized:
        raise PermissionError("locked OOS refused: explicit one-time user authorization is required")


def evenly_spaced(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(rows): return rows
    return [rows[round((index + 1) * (len(rows) + 1) / (count + 1)) - 1] for index in range(count)]


def stratified_universe(universe: dict[str, Any], start: int, end: int, stage: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible, exclusions = eligible_symbols(universe, start - 3 * DAY_MS, end)
    history_ready = [item for item in eligible if int(item.get("onboardDate") or 0) <= start - 3 * DAY_MS and float(item.get("quoteVolume24h") or 0) > 0]
    ranked = sorted(history_ready, key=lambda item: (-float(item["quoteVolume24h"]), str(item["symbol"])))
    if len(ranked) < 6: raise ValueError("dynamic universe has fewer than six liquidity-ranked, history-ready symbols")
    tiers: dict[str, list[dict[str, Any]]] = {"TIER_A": [], "TIER_B": [], "TIER_C": []}
    for index, item in enumerate(ranked):
        tier = ("TIER_A", "TIER_B", "TIER_C")[min(2, index * 3 // len(ranked))]
        tiers[tier].append(item)
    per_tier = STAGE_COUNTS.get(stage)
    selected = ranked if stage == "C" else [item for tier in tiers.values() for item in evenly_spaced(tier, per_tier or 0)]
    selected_symbols = {str(item["symbol"]) for item in selected}
    newer = sorted((item for item in ranked if 30 * DAY_MS <= end - int(item.get("onboardDate") or 0) < 365 * DAY_MS), key=lambda item: (-int(item.get("onboardDate") or 0), str(item["symbol"])))
    newcomer = next((item for item in newer if str(item["symbol"]) not in selected_symbols), None)
    if newcomer is not None and stage != "C": selected.append(newcomer)
    tier_by_symbol = {str(item["symbol"]): tier for tier, rows in tiers.items() for item in rows}
    snapshot = [{"symbol": str(item["symbol"]), "tier": tier_by_symbol[str(item["symbol"])], "listing_class": "NEWER_LISTING" if item is newcomer else "ESTABLISHED", "onboard_date": int(item.get("onboardDate") or 0), "quote_volume_24h": float(item["quoteVolume24h"])} for item in selected]
    return snapshot, {"source": universe.get("source"), "server_time": universe.get("serverTime"), "eligible_count": len(ranked), "excluded_count": len(exclusions), "method": "DYNAMIC_CURRENT_LIQUIDITY_TERCILES_WITH_HISTORY_READY_NEWER_LISTING", "static_whitelist": False}


def expanded_breadth(symbol_rows: list[dict[str, Any]], weeks: float) -> dict[str, Any]:
    active = [row for row in symbol_rows if int(row["trade_count"]) > 0]
    profitable = sorted((float(row["net_pnl"]), str(row["symbol"])) for row in active if float(row["net_pnl"]) > 0)
    profitable.reverse()
    total_profit = sum(value for value, _ in profitable)
    trades = [int(row["trade_count"]) for row in symbol_rows]
    expectations = [float(row["expectancy"]) for row in active]
    share = lambda count: sum(value for value, _ in profitable[:count]) / total_profit if total_profit else 0.0
    return {"profitable_symbol_count": len(profitable), "losing_symbol_count": sum(float(row["net_pnl"]) < 0 for row in active), "flat_symbol_count": sum(float(row["net_pnl"]) == 0 for row in active), "active_symbol_count": len(active), "top_symbol": profitable[0][1] if profitable else None, "top_symbol_pnl_share": share(1), "top_3_symbol_pnl_share": share(3), "top_5_symbol_pnl_share": share(5), "median_symbol_expectancy": median(expectations) if expectations else 0.0, "positive_expectancy_breadth": sum(value > 0 for value in expectations) / len(expectations) if expectations else 0.0, "trades_per_symbol": sum(trades) / len(trades) if trades else 0.0, "median_trades_per_symbol": median(trades) if trades else 0.0, "trades_per_week": sum(trades) / max(weeks, 1 / 7)}


def chronological_segments(start: int, end: int) -> list[dict[str, int | str]]:
    width = (end - start) // 3
    boundaries = (start, start + width, start + 2 * width, end)
    return [{"name": f"DEV_SEGMENT_{chr(65 + index)}", "start": boundaries[index], "end": boundaries[index + 1]} for index in range(3)]


def temporal_stability(variant: Any, version_id: str, symbols: list[str], datasets: dict[str, dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    rows = []
    for segment in chronological_segments(start, end):
        result = evaluate(variant, f"D4.2:{version_id}:{segment['name']}", symbols, datasets, int(segment["start"]), int(segment["end"]))
        rows.append({**segment, "metrics": result["metrics"]})
    positive = [max(0.0, float(row["metrics"]["net_pnl"])) for row in rows]
    total = sum(positive)
    max_share = max(positive) / total if total else 0.0
    expectations = [float(row["metrics"]["expectancy"]) for row in rows]
    return {"segments": rows, "positive_segment_count": sum(value > 0 for value in expectations), "max_positive_pnl_segment_share": max_share, "decaying_expectancy": expectations[0] > expectations[1] > expectations[2], "flag": "TEMPORAL_CONCENTRATION" if max_share > .60 else "BROADLY_DISTRIBUTED"}


def concentration_by_tier_and_regime(evaluated: dict[str, Any], datasets: dict[str, dict[str, Any]], snapshot: list[dict[str, Any]], start: int) -> dict[str, Any]:
    symbol_info = {item["symbol"]: item for item in snapshot}
    features = []
    for trade in evaluated["trades"]:
        data = datasets[trade["symbol"]]
        candles = data["candles"]
        row = feature_row(trade, candles, resample_closed(candles, 3_600_000), resample_closed(candles, DAY_MS), {"tier": symbol_info[trade["symbol"]]["tier"], "onboard_date": symbol_info[trade["symbol"]]["onboard_date"]}, start)
        row["listing_class"] = symbol_info[trade["symbol"]]["listing_class"]
        features.append(row)
    return {"by_tier": grouped(features, "market_tier"), "by_listing_class": grouped(features, "listing_class"), "by_market_regime": grouped(features, "regime"), "by_volatility_regime": grouped(features, "volatility_regime"), "by_range_phase": grouped(features, "range_phase")}


def next_stage(stage: str, passed: bool) -> str | None:
    if not passed or stage == "C": return None
    return chr(ord(stage) + 1)


def source_manifests(state_root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for variant in VARIANTS:
        version_id = f"{variant.strategy_id}_{variant.strategy_version}"
        paths = sorted((state_root / "research" / version_id).glob("d4_1_dev_*/manifest.json"))
        if not paths: raise FileNotFoundError(f"missing immutable D4.1 artifact for {version_id}")
        manifest = json.loads(paths[-1].read_text(encoding="utf-8"))
        if manifest["config_hash"] != stable_digest(asdict(variant)): raise ValueError(f"{version_id} rules differ from D4.1")
        result[version_id] = {"path": str(paths[-1].resolve()), "config_hash": manifest["config_hash"], "identity_hash": manifest["identity_hash"]}
    return result


def resource_plan(stage: str, start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    bridge = BridgeClient(bridge_url)
    snapshot, provenance = stratified_universe(bridge.universe(), start, end, stage)
    symbols = [item["symbol"] for item in snapshot]
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, end, DAY_MS))
    candle_parts = [(symbol, day) for symbol in symbols for day in days]
    cached_candles = sum((cache_root / "binance-usdm-v1" / symbol / "5m" / f"{datetime.fromtimestamp(day / 1000, UTC):%Y-%m-%d}.jsonl.gz").exists() for symbol, day in candle_parts)
    cached_funding = sum((cache_root / "binance-usdm-v1" / symbol / "funding" / f"{start}-{end}.json").exists() for symbol in symbols)
    total_requests = len(candle_parts) + len(symbols)
    sources = source_manifests(state_root)
    identity = {"engine": ENGINE_VERSION, "stage": stage, "development": {"start": start, "end": end}, "universe_snapshot": snapshot, "candidate_rules": {key: value["config_hash"] for key, value in sources.items()}, "cost_model": asdict(CostModel())}
    run_id = f"d4_2_{stage.lower()}_{stable_digest(identity)[:16]}"
    return {"run_id": run_id, "identity_hash": stable_digest(identity), "engine_version": ENGINE_VERSION, "stage": stage, "candidate_count": len(VARIANTS), "candidates": [f"{item.strategy_id}_{item.strategy_version}" for item in VARIANTS], "symbol_count": len(symbols), "symbols": symbols, "universe_snapshot": snapshot, "universe_provenance": provenance, "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * DAY_MS, "approximate_5m_candles": len(symbols) * ((end - start) // 300_000), "expected_jobs": len(VARIANTS) * len(symbols) * 4, "cache": {"cached_partitions": cached_candles + cached_funding, "total_partitions": total_requests, "hit_rate": (cached_candles + cached_funding) / total_requests if total_requests else 1.0}, "estimated_network_requests": total_requests - cached_candles - cached_funding, "worker_count": max(1, min(8, workers)), "source_v2_artifacts": sources, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False}


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = state_root / "research-runs" / plan["run_id"]
    path = root / "resource-plan.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["identity_hash"] != plan["identity_hash"]: raise ValueError("immutable D4.2 plan collision")
    else:
        atomic_json(path, plan)
    return root


def run_candidate(variant: Any, plan: dict[str, Any], datasets: dict[str, dict[str, Any]], state_root: Path) -> dict[str, Any]:
    version_id = f"{variant.strategy_id}_{variant.strategy_version}"
    start, end = plan["development_window"]["start"], plan["development_window"]["end"]
    symbols = plan["symbols"]
    validation_id = f"d4_2_{plan['stage'].lower()}_{stable_digest({'run': plan['identity_hash'], 'strategy': version_id})[:16]}"
    output = state_root / "research" / version_id / validation_id
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["identity_hash"] != stable_digest({"plan": plan["identity_hash"], "strategy": version_id}): raise ValueError(f"immutable D4.2 artifact collision: {output}")
        return {"strategy": version_id, "status": "ALREADY_COMPLETED", "passed": manifest["passed"], "metrics": json.loads((output / "dev-expanded-summary.json").read_text(encoding="utf-8")), "gates": manifest["gates"], "artifact": str(output.resolve()), "validation_id": validation_id}
    evaluated = evaluate(variant, f"{validation_id}:{version_id}:DEV", symbols, datasets, start, end)
    stress = cost_stress(evaluated["trades"])
    breadth = expanded_breadth(evaluated["symbol_metrics"], (end - start) / (7 * DAY_MS))
    temporal = temporal_stability(variant, version_id, symbols, datasets, start, end)
    stability = concentration_by_tier_and_regime(evaluated, datasets, plan["universe_snapshot"], start)
    gates = {**development_gates(evaluated["metrics"], stress, breadth), "PARAMETER_STABILITY": True}
    passed = all(gates.values())
    manifest = {"identity_hash": stable_digest({"plan": plan["identity_hash"], "strategy": version_id}), "validation_id": validation_id, "research_run_id": plan["run_id"], "phase": "DEVELOPMENT_EXPANSION_ONLY", "stage": plan["stage"], "strategy_id": variant.strategy_id, "strategy_version": variant.strategy_version, "hypothesis": HYPOTHESES[version_id], "config_hash": stable_digest(asdict(variant)), "source_v2_artifact": plan["source_v2_artifacts"][version_id], "dataset_version": stable_digest(sorted(item["dataset_version"] for item in datasets.values())), "engine_version": ENGINE_VERSION, "backtest_engine_version": "d3-backtest-v1", "cost_model": asdict(CostModel()), "execution_model_version": "next-open-market-v1", "development_window": plan["development_window"], "warmup_start": plan["warmup_start"], "symbols": plan["universe_snapshot"], "gates": gates, "parameter_stability": "NOT_APPLICABLE_RULES_UNCHANGED", "passed": passed, "status": "OOS_ELIGIBLE" if passed else "REJECT_DEVELOPMENT_EXPANSION", "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False, "next_stage": next_stage(plan["stage"], passed)}
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(manifest_path, manifest)
    atomic_json(output / "dev-expanded-summary.json", evaluated["metrics"])
    atomic_json(output / "symbol-breadth.json", breadth)
    atomic_json(output / "symbol-metrics.json", evaluated["symbol_metrics"])
    atomic_json(output / "temporal-stability.json", temporal)
    atomic_json(output / "regime-stability.json", stability)
    atomic_json(output / "cost-stress.json", stress)
    atomic_json(output / "gate-result.json", {"gates": gates, "passed": passed, "status": manifest["status"], "oos_eligibility": passed, "oos_access": "OOS_NOT_ACCESSED"})
    jsonl(output / "trades" / "dev.jsonl", evaluated["trades"])
    replay_result = next((item for item in evaluated["results"] if item["trades"]), None)
    if replay_result and (replay := replay_artifact(f"{validation_id}-{version_id}", replay_result)):
        atomic_json(output / "replay.json", {**replay, "evaluationStartTimestamp": start // 1000})
    return {"strategy": version_id, "status": manifest["status"], "passed": passed, "metrics": evaluated["metrics"], "gates": gates, "breadth": breadth, "temporal": temporal, "regime": stability, "cost_stress": {key: value["metrics"]["expectancy"] for key, value in stress.items()}, "artifact": str(output.resolve()), "validation_id": validation_id}


def execute(run_id: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    root = state_root / "research-runs" / run_id
    plan = json.loads((root / "resource-plan.json").read_text(encoding="utf-8"))
    completed_path, manifest_path = root / "expansion-run.json", root / "manifest.json"
    if completed_path.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["identity_hash"] != plan["identity_hash"]: raise ValueError("immutable D4.2 run collision")
        return json.loads(completed_path.read_text(encoding="utf-8"))
    checkpoint_path = root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"identity_hash": plan["identity_hash"], "completed": {}}
    if checkpoint["identity_hash"] != plan["identity_hash"]: raise ValueError("immutable D4.2 checkpoint collision")
    datasets = load_datasets(plan["symbols"], plan["warmup_start"] + 3 * DAY_MS, plan["development_window"]["end"], cache_root, bridge_url, plan["worker_count"])
    for variant in VARIANTS:
        version_id = f"{variant.strategy_id}_{variant.strategy_version}"
        if version_id not in checkpoint["completed"]:
            checkpoint["completed"][version_id] = run_candidate(variant, plan, datasets, state_root)
            atomic_json(checkpoint_path, checkpoint)
    candidates = [checkpoint["completed"][f"{item.strategy_id}_{item.strategy_version}"] for item in VARIANTS]
    result = {"runId": run_id, "status": "COMPLETED", "phase": "DEVELOPMENT_EXPANSION", "stage": plan["stage"], "startedAt": datetime.now(UTC).isoformat(), "developmentWindow": plan["development_window"], "symbolCount": plan["symbol_count"], "symbols": plan["symbols"], "candidates": candidates, "nextStage": "B" if any(item["passed"] for item in candidates) and plan["stage"] == "A" else "C" if any(item["passed"] for item in candidates) and plan["stage"] == "B" else None, "oosAccess": "OOS_NOT_ACCESSED", "lockedOosResolvedOrRead": False}
    atomic_json(completed_path, result)
    atomic_json(manifest_path, {"research_run_id": run_id, "identity_hash": plan["identity_hash"], "status": "COMPLETED", "stage": plan["stage"], "candidate_versions": [item["strategy"] for item in candidates], "development_window": plan["development_window"], "universe_snapshot": plan["universe_snapshot"], "cost_model": asdict(CostModel()), "engine_version": ENGINE_VERSION, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False})
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.2 Development evidence expansion")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--stage", choices=("A", "B", "C"), default="A")
    plan.add_argument("--dev-start", required=True); plan.add_argument("--dev-end", required=True)
    plan.add_argument("--workers", type=int, default=3); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market")
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--run-id", required=True); execute_parser.add_argument("--state-root", default="state"); execute_parser.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    state_root, cache_root = Path(args.state_root), Path(args.cache_root)
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    try:
        if args.command == "plan":
            start, end = iso_ms(args.dev_start), iso_ms(args.dev_end)
            if end <= start: raise ValueError("--dev-end must be after --dev-start")
            plan = resource_plan(args.stage, start, end, args.workers, state_root, cache_root, bridge_url)
            save_plan(plan, state_root)
            print(json.dumps(plan, sort_keys=True))
        else:
            print(json.dumps(execute(args.run_id, state_root, cache_root, bridge_url), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
