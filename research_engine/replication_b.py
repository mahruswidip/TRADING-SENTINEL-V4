from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backtest_engine.cli import eligible_symbols
from backtest_engine.data import atomic_json, iso_ms
from backtest_engine.engine import stable_digest
from forensics_engine.analysis import DAY_MS
from research_engine.fvg import PacedBridgeClient
from research_engine.replication import (
    MINIMUM_ROUND_TRIP_COST_BPS,
    _atomic_gzip_json,
    _cache_partition,
    _cross_sectional_detail,
    _enrich_cross_section,
    _load_symbol,
    _read_gzip_json,
    _signal_rows,
    _temporal_detail,
    deterministic_selection,
    file_sha256,
    load_source_signals,
    replication_status,
)
from research_engine.discovery import summarize_slice


ENGINE_VERSION = "d4.6b-broader-signal-replication-v1"
SOURCE_RUN = "d4_5_482ba89ea0075922"
PARENT_RUN = "d4_6_8733a768a0dd3dd4"
STAGE_TARGETS = {"B": 100, "C": 210}


def oos_guard() -> None:
    raise PermissionError("locked OOS is outside D4.6B")


def _root(state_root: Path, run_id: str) -> Path:
    return state_root / "signal-replication" / run_id


def _stage_root(state_root: Path, run_id: str, stage: str) -> Path:
    return _root(state_root, run_id) / "stages" / stage


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and "work" not in path.parts
    }


def _parent_contract(state_root: Path) -> dict[str, Any]:
    root = _root(state_root, PARENT_RUN)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    universe = json.loads((root / "universe.json").read_text(encoding="utf-8"))
    if manifest["oos_access"] != "OOS_NOT_ACCESSED" or manifest["thresholds_changed"]:
        raise ValueError("parent D4.6 run violates the D4.6B source contract")
    return {
        "run_id": PARENT_RUN,
        "path": str(root.resolve()),
        "development_window": manifest["development_window"],
        "source_run": manifest["source_run"],
        "source_signal_hashes": manifest["source_signal_hashes"],
        "stage_a_signal_statuses": json.loads((root / "replication-gate.json").read_text(encoding="utf-8"))["signals"],
        "symbols": [item["symbol"] for item in universe["universe_snapshot"]],
        "artifact_hashes": _artifact_hashes(root),
    }


def signal_b_stage_decision(stage: str, signal_b_status: str) -> tuple[str, str | None]:
    if stage == "C":
        return "STOP_STAGE_C_COMPLETE", None
    if signal_b_status in {"REPLICATED_STRONG", "REPLICATED", "WEAK_REPLICATION"}:
        return "CONTINUE_STAGE_C", "C"
    return f"STOP_SIGNAL_B_{signal_b_status}", None


def resource_plan(stage: str, start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    if stage not in STAGE_TARGETS:
        raise ValueError("stage must be B or C")
    parent = _parent_contract(state_root)
    source = load_source_signals(state_root, SOURCE_RUN)
    if parent["development_window"] != {"start": start, "end": end}:
        raise ValueError("D4.6B must preserve the parent Development window")
    hashes = [item["definition_hash"] for item in source["definitions"]]
    if hashes != parent["source_signal_hashes"]:
        raise ValueError("D4.5 signal definition hashes differ from the parent D4.6 run")

    universe = PacedBridgeClient(bridge_url).universe()
    eligible, exclusions = eligible_symbols(universe, start, end)
    eligible = [item for item in eligible if item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT"]
    selected = deterministic_selection(eligible, parent["symbols"], STAGE_TARGETS[stage], start)
    symbols = [str(item["symbol"]) for item in selected]
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, math.ceil((end + 4 * 3_600_000) / DAY_MS) * DAY_MS, DAY_MS))
    parts = [(symbol, day) for symbol in sorted(set(symbols + ["BTCUSDT"])) for day in days]
    cached = {symbol: all(_cache_partition(cache_root, symbol, day).exists() for day in days) for symbol in symbols}
    snapshot = [{
        "symbol": str(item["symbol"]), "onboardDate": int(item.get("onboardDate") or 0), "deliveryDate": int(item.get("deliveryDate") or 0),
        "contractType": item.get("contractType"), "quoteAsset": item.get("quoteAsset"), "marginAsset": item.get("marginAsset"),
    } for item in selected]
    base_identity = {
        "engine": ENGINE_VERSION, "parent_run": PARENT_RUN, "source_run": SOURCE_RUN,
        "source_definition_hashes": hashes, "development": {"start": start, "end": end},
    }
    run_id = f"d4_6b_{stable_digest(base_identity)[:16]}"
    if stage == "C":
        gate_path = _stage_root(state_root, run_id, "B") / "replication-gate.json"
        if not gate_path.exists() or json.loads(gate_path.read_text(encoding="utf-8")).get("next_stage") != "C":
            raise ValueError("Stage B must independently authorize Signal B expansion to Stage C")
    return {
        "run_id": run_id, "identity_hash": stable_digest({**base_identity, "stage": stage, "symbols": snapshot}),
        "base_identity_hash": stable_digest(base_identity), "engine_version": ENGINE_VERSION, "stage": stage,
        "target_symbol_count": STAGE_TARGETS[stage], "eligible_universe_count": len(eligible), "selected_symbol_count": len(symbols),
        "symbols": symbols, "universe_snapshot": snapshot,
        "selection_method": "PARENT_COHORT_PLUS_LISTING_AGE_ROUND_ROBIN_STABLE_SYMBOL_HASH",
        "selection_uses_current_ticker": False, "already_cached_symbols": sorted(symbol for symbol in symbols if cached[symbol]),
        "symbols_requiring_backfill": sorted(symbol for symbol in symbols if not cached[symbol]),
        "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * DAY_MS,
        "label_lookahead_end": end + 4 * 3_600_000,
        "expected_5m_candles": len(symbols) * ((end - start) // 300_000),
        "estimated_bridge_requests": sum(not _cache_partition(cache_root, symbol, day).exists() for symbol, day in parts),
        "worker_count": max(1, min(3, workers)),
        "checkpoint_path": str((_root(state_root, run_id) / "checkpoint.json").resolve()),
        "source_run": SOURCE_RUN, "source_signal_hashes": hashes, "parent_run": PARENT_RUN,
        "exclusion_summary": dict(Counter(item["reason"] for item in exclusions)),
        "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    }


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root, stage_root = _root(state_root, plan["run_id"]), _stage_root(state_root, plan["run_id"], plan["stage"])
    path = stage_root / "resource-plan.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["identity_hash"] != plan["identity_hash"]:
        raise ValueError("immutable D4.6B stage-plan collision")
    if not path.exists():
        atomic_json(path, plan)
        atomic_json(stage_root / "universe.json", {key: plan[key] for key in ("stage", "eligible_universe_count", "selection_method", "selection_uses_current_ticker", "universe_snapshot", "exclusion_summary")})
    index_path = root / "resource-plan.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"run_id": plan["run_id"], "base_identity_hash": plan["base_identity_hash"], "stages": {}}
    if index["base_identity_hash"] != plan["base_identity_hash"]:
        raise ValueError("immutable D4.6B run collision")
    index["stages"][plan["stage"]] = str(path.resolve())
    atomic_json(index_path, index)
    if not (root / "parent-run.json").exists():
        atomic_json(root / "parent-run.json", _parent_contract(state_root))
        atomic_json(root / "source-signal-hashes.json", load_source_signals(state_root, SOURCE_RUN))
    return root


def _write_artifacts(root: Path, stage: str, results: list[dict[str, Any]], gate: dict[str, Any], plan: dict[str, Any], quality: list[dict[str, Any]]) -> None:
    stage_root = root / "stages" / stage
    for item in results:
        name = f"signal-{item['signal_id'].lower()}.json"
        atomic_json(stage_root / name, item)
        atomic_json(root / name, item)
    atomic_json(stage_root / "replication-gate.json", gate)
    atomic_json(root / "replication-gate.json", gate)
    atomic_json(root / "temporal-stability.json", {item["signal_id"]: item["temporal_detail"] for item in results})
    atomic_json(root / "symbol-breadth.json", {item["signal_id"]: item["replication"]["breadth"] for item in results})
    backfill = {
        "stage": stage, "selected_symbols": plan["selected_symbol_count"],
        "usable_symbols": sum(item["status"] == "USABLE" for item in quality),
        "planned_worker_count": plan["worker_count"], "effective_worker_count": 1,
        "newly_backfilled_symbols": sorted(item["symbol"] for item in quality if item.get("downloads", 0) > 0 and item["status"] == "USABLE"),
        "partial_backfill_symbols": sorted(item["symbol"] for item in quality if item.get("downloads", 0) > 0 and item["status"] != "USABLE"),
        "failed_symbols": [item for item in quality if item["status"] != "USABLE"],
        "cache_hits": sum(item.get("cache_hits", 0) for item in quality), "downloads": sum(item.get("downloads", 0) for item in quality),
    }
    atomic_json(stage_root / "backfill-summary.json", backfill)
    atomic_json(root / "backfill-summary.json", backfill)
    atomic_json(root / "manifest.json", {
        "run_id": plan["run_id"], "status": "STAGE_COMPLETE" if gate["next_stage"] else "COMPLETED",
        "latest_stage": stage, "next_stage": gate["next_stage"], "engine_version": ENGINE_VERSION,
        "parent_run": PARENT_RUN, "source_run": SOURCE_RUN, "source_signal_hashes": plan["source_signal_hashes"],
        "development_window": plan["development_window"], "eligible_universe_count": plan["eligible_universe_count"],
        "usable_symbol_count": backfill["usable_symbols"], "dataset_version": stable_digest(sorted(dataset_id for item in quality for dataset_id in item.get("dataset_ids", []))),
        "cost_model": "NOT_APPLICABLE_RAW_FORWARD_RETURN_REPLICATION", "cost_hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS,
        "thresholds_changed": False, "current_ticker_used_for_selection_or_features": False,
        "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    })
    lines = ["# D4.6B Broader Signal Replication", "", "**NOT A TRADING STRATEGY.**", "", f"- Parent: `{PARENT_RUN}`", f"- Source: `{SOURCE_RUN}`", f"- Latest stage: {stage}", f"- Usable symbols: {backfill['usable_symbols']}", f"- Decision: {gate['decision']}", ""]
    for item in results:
        result, breadth = item["replication"], item["replication"]["breadth"]
        lines += [f"## Signal {item['signal_id']}", "", f"- Status: {item['replication_status']}", f"- Mean / median 4H: {result['mean_forward_return'] * 10_000:.2f} / {result['median_forward_return'] * 10_000:.2f} bps", f"- Raw / effective: {result['observation_count']} / {result['effective_observation_count']}", f"- Breadth: {breadth['profitable_direction_symbol_count']} aligned / {breadth['opposite_direction_symbol_count']} opposite", f"- 95% CI: [{result['block_bootstrap_95_ci'][0] * 10_000:.2f}, {result['block_bootstrap_95_ci'][1] * 10_000:.2f}] bps", ""]
    (root / "replication-report.md").write_text("\n".join(lines), encoding="utf-8")


def execute(run_id: str, stage: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    root, stage_root = _root(state_root, run_id), _stage_root(state_root, run_id, stage)
    plan = json.loads((stage_root / "resource-plan.json").read_text(encoding="utf-8"))
    gate_path = stage_root / "replication-gate.json"
    if gate_path.exists():
        return {"run_id": run_id, "stage": stage, "status": "ALREADY_COMPLETED", "artifact": str(root.resolve())}
    source = load_source_signals(state_root, SOURCE_RUN)
    checkpoint_path = root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"base_identity_hash": plan["base_identity_hash"], "completed_symbols": {}, "failed_symbols": {}, "analysis_state": {}}
    if checkpoint["base_identity_hash"] != plan["base_identity_hash"]:
        raise ValueError("immutable D4.6B checkpoint collision")
    pending = [symbol for symbol in plan["symbols"] if symbol not in checkpoint["completed_symbols"] and (symbol not in checkpoint["failed_symbols"] or checkpoint["failed_symbols"][symbol].get("status") == "BACKFILL_FAILED")]
    work = root / "work"
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = {pool.submit(_load_symbol, symbol, plan, cache_root, bridge_url): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                rows, quality = future.result()
                atomic_json(work / f"{symbol}.quality.json", quality)
                if quality["status"] == "USABLE":
                    _atomic_gzip_json(work / f"{symbol}.rows.json.gz", rows)
                    checkpoint["completed_symbols"][symbol] = quality
                    checkpoint["failed_symbols"].pop(symbol, None)
                else:
                    checkpoint["failed_symbols"][symbol] = quality
            except Exception as error:
                checkpoint["failed_symbols"][symbol] = {"symbol": symbol, "status": "BACKFILL_FAILED", "detail": f"{type(error).__name__}: {error}", "dataset_ids": [], "cache_hits": 0, "downloads": 0}
            checkpoint["replication_stage"] = stage
            atomic_json(checkpoint_path, checkpoint)
            print(json.dumps({"run_id": run_id, "stage": stage, "completed": len(checkpoint["completed_symbols"]), "failed": len(checkpoint["failed_symbols"]), "target": len(plan["symbols"]), "symbol": symbol}))
    usable = [symbol for symbol in plan["symbols"] if symbol in checkpoint["completed_symbols"]]
    rows = [row for symbol in usable for row in _read_gzip_json(work / f"{symbol}.rows.json.gz")]
    metadata = {item["symbol"]: item for item in plan["universe_snapshot"] if item["symbol"] in usable}
    btc_rows = _read_gzip_json(work / "BTCUSDT.rows.json.gz") if (work / "BTCUSDT.rows.json.gz").exists() else []
    _enrich_cross_section(rows, metadata, btc_rows)
    results = []
    for index, definition in enumerate(source["definitions"]):
        matched = _signal_rows(rows, definition)
        summary = summarize_slice(matched, definition["feature"], definition["condition_bucket"], definition["horizon"])
        direction = 1 if definition["expected_direction"] == "POSITIVE" else -1
        results.append({
            "signal_id": chr(ord("A") + index), "definition_hash": definition["definition_hash"], "source_definition": definition,
            "replication": summary, "replication_status": replication_status(summary, definition),
            "temporal_detail": _temporal_detail(matched, direction), "cross_sectional_stability": _cross_sectional_detail(matched, definition),
            "thresholds_changed": False, "neutral_or_insufficient_symbol_count": len(usable) - summary["breadth"]["active_symbol_count"],
        })
    decision, next_stage = signal_b_stage_decision(stage, results[1]["replication_status"])
    gate = {"stage": stage, "primary_signal": "B", "signals": {item["signal_id"]: item["replication_status"] for item in results}, "decision": decision, "next_stage": next_stage, "signal_a_cannot_veto_signal_b": True, "thresholds_changed": False, "oos_access": "OOS_NOT_ACCESSED"}
    checkpoint["analysis_state"][stage] = "COMPLETED"
    atomic_json(checkpoint_path, checkpoint)
    quality = [*checkpoint["completed_symbols"].values(), *checkpoint["failed_symbols"].values()]
    _write_artifacts(root, stage, results, gate, plan, quality)
    return {"run_id": run_id, "stage": stage, "status": "COMPLETED", "usable_symbols": len(usable), "signals": gate["signals"], "decision": decision, "next_stage": next_stage, "artifact": str(root.resolve())}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.6B broader signal replication")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--stage", choices=tuple(STAGE_TARGETS), required=True); plan.add_argument("--dev-start", required=True); plan.add_argument("--dev-end", required=True)
    plan.add_argument("--workers", type=int, default=2); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market")
    run = commands.add_parser("execute")
    run.add_argument("--run-id", required=True); run.add_argument("--stage", choices=tuple(STAGE_TARGETS), required=True); run.add_argument("--state-root", default="state"); run.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    state_root, cache_root = Path(args.state_root), Path(args.cache_root)
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    try:
        if args.command == "plan":
            plan = resource_plan(args.stage, iso_ms(args.dev_start), iso_ms(args.dev_end), args.workers, state_root, cache_root, bridge_url)
            save_plan(plan, state_root)
            print(json.dumps(plan, sort_keys=True))
        else:
            print(json.dumps(execute(args.run_id, args.stage, state_root, cache_root, bridge_url), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
