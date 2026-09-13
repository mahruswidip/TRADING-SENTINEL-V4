from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from backtest_engine.cli import eligible_symbols
from backtest_engine.data import HistoricalDataStore, atomic_json, iso_ms
from backtest_engine.engine import stable_digest
from forensics_engine.analysis import DAY_MS
from research_engine.discovery import (
    HORIZONS,
    MINIMUM_ROUND_TRIP_COST_BPS,
    SEGMENTS,
    UNAVAILABLE,
    add_cross_sectional_features,
    bucket_value,
    build_symbol_rows,
    cross_sectional_rank,
    summarize_slice,
    universe_eligible,
)
from research_engine.fvg import PacedBridgeClient


ENGINE_VERSION = "d4.6-signal-replication-v1"
SOURCE_RUN = "d4_5_482ba89ea0075922"
STAGE_TARGETS = {"A": 50, "B": 100, "C": 200}
MIN_VALID_ROWS = 7 * 288


def oos_guard() -> None:
    raise PermissionError("locked OOS is outside D4.6")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source_signals(state_root: Path, source_run: str = SOURCE_RUN) -> dict[str, Any]:
    root = state_root / "signal-discovery" / source_run
    manifest_path, catalog_path, ranking_path = root / "manifest.json", root / "feature-catalog.json", root / "discovery-ranking.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    findings = [item for item in ranking["ranked_findings"] if item["discovery_status"] == "PROMISING_SIGNAL"]
    if len(findings) != 2:
        raise ValueError(f"authoritative D4.5 artifact must expose exactly two promising signals, found {len(findings)}")
    catalog_by_id = {item["id"]: item for item in catalog["catalog"]}
    interactions = {item[2]: item for item in catalog["interactions"]}
    definitions = []
    # Preserve the D4.6 names from the frozen brief: A is the positive signal,
    # B is the negative signal. The direction itself still comes from D4.5.
    findings.sort(key=lambda item: (item["direction"] != "POSITIVE", item["finding_id"]))
    for finding in findings:
        interaction = interactions.get(finding["feature"])
        if not interaction:
            raise ValueError(f"source finding {finding['finding_id']} is not backed by the frozen interaction catalog")
        definition = {
            "source_finding_id": finding["finding_id"], "feature": finding["feature"], "condition_bucket": finding["bucket"],
            "horizon": finding["horizon"], "expected_direction": finding["direction"], "interaction": interaction,
            "component_catalog": [catalog_by_id[interaction[0]], catalog_by_id[interaction[1]]],
            "universe_method": manifest["universe_method"], "source_engine_version": manifest["engine_version"],
            "source_feature_catalog_hash": manifest["feature_catalog_hash"],
            "timestamp_contract": manifest["lookahead_validation"],
            "benchmark": {key: finding[key] for key in (
                "observation_count", "effective_observation_count", "symbol_count", "mean_forward_return", "median_forward_return",
                "direction_hit_rate", "block_bootstrap_95_ci", "effect_size", "temporal_means", "temporal_classification", "breadth", "cost_hurdle_state",
            )},
        }
        definition["definition_hash"] = stable_digest(definition)
        definitions.append(definition)
    return {
        "source_run": source_run, "source_root": str(root.resolve()), "definitions": definitions,
        "source_artifact_hashes": {"manifest.json": file_sha256(manifest_path), "feature-catalog.json": file_sha256(catalog_path), "discovery-ranking.json": file_sha256(ranking_path)},
        "source_engine_file_hash": file_sha256(Path(__file__).with_name("discovery.py")),
    }


def listing_group(item: dict[str, Any], start: int) -> str:
    age = (start - int(item.get("onboardDate") or 0)) / DAY_MS
    return "VERY_NEW" if age < 30 else "YOUNG" if age < 365 else "ESTABLISHED"


def deterministic_selection(eligible: list[dict[str, Any]], source_symbols: list[str], target: int, start: int) -> list[dict[str, Any]]:
    by_symbol = {str(item["symbol"]): item for item in eligible if item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT"}
    selected = [by_symbol[symbol] for symbol in sorted(source_symbols) if symbol in by_symbol]
    selected_symbols = {str(item["symbol"]) for item in selected}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in by_symbol.values():
        if str(item["symbol"]) not in selected_symbols:
            groups[listing_group(item, start)].append(item)
    for group in groups.values():
        group.sort(key=lambda item: (hashlib.sha256(f"D4.6:{item['symbol']}".encode()).hexdigest(), str(item["symbol"])))
    order = ("VERY_NEW", "YOUNG", "ESTABLISHED")
    while len(selected) < target and any(groups.values()):
        for name in order:
            if groups[name] and len(selected) < target:
                selected.append(groups[name].pop(0))
    return sorted(selected, key=lambda item: str(item["symbol"]))


def _cache_partition(cache_root: Path, symbol: str, day: int) -> Path:
    date = datetime.fromtimestamp(day / 1000, UTC).strftime("%Y-%m-%d")
    return cache_root / "binance-usdm-v1" / symbol / "5m" / f"{date}.jsonl.gz"


def _stage_root(state_root: Path, run_id: str, stage: str) -> Path:
    return state_root / "signal-replication" / run_id / "stages" / stage


def resource_plan(stage: str, start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str, source_run: str = SOURCE_RUN) -> dict[str, Any]:
    if stage not in STAGE_TARGETS:
        raise ValueError("stage must be A, B, or C")
    source = load_source_signals(state_root, source_run)
    bridge = PacedBridgeClient(bridge_url)
    universe = bridge.universe()
    eligible, base_exclusions = eligible_symbols(universe, start, end)
    eligible = [item for item in eligible if item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT"]
    source_manifest = json.loads((state_root / "signal-discovery" / source_run / "manifest.json").read_text(encoding="utf-8"))
    source_symbols = [item["symbol"] for item in source_manifest["symbols"]]
    selected = deterministic_selection(eligible, source_symbols, STAGE_TARGETS[stage], start)
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, math.ceil((end + 4 * 3_600_000) / DAY_MS) * DAY_MS, DAY_MS))
    symbols = [str(item["symbol"]) for item in selected]
    parts = [(symbol, day) for symbol in sorted(set(symbols + ["BTCUSDT"])) for day in days]
    cached_by_symbol = {symbol: all(_cache_partition(cache_root, symbol, day).exists() for day in days) for symbol in symbols}
    cached_parts = sum(_cache_partition(cache_root, symbol, day).exists() for symbol, day in parts)
    snapshot = [{
        "symbol": str(item["symbol"]), "onboardDate": int(item.get("onboardDate") or 0), "deliveryDate": int(item.get("deliveryDate") or 0),
        "contractType": item.get("contractType"), "quoteAsset": item.get("quoteAsset"), "marginAsset": item.get("marginAsset"),
        "listing_group_at_start": listing_group(item, start), "selection_key": hashlib.sha256(f"D4.6:{item['symbol']}".encode()).hexdigest(),
    } for item in selected]
    base_identity = {"engine": ENGINE_VERSION, "source_run": source_run, "source_definition_hashes": [item["definition_hash"] for item in source["definitions"]], "development": {"start": start, "end": end}}
    run_id = f"d4_6_{stable_digest(base_identity)[:16]}"
    prior = None if stage == "A" else chr(ord(stage) - 1)
    if prior:
        prior_gate_path = _stage_root(state_root, run_id, prior) / "replication-gate.json"
        if not prior_gate_path.exists():
            raise ValueError(f"Stage {prior} must complete before planning Stage {stage}")
        prior_gate = json.loads(prior_gate_path.read_text(encoding="utf-8"))
        if prior_gate.get("next_stage") != stage:
            raise ValueError(f"Stage {prior} gate does not authorize Stage {stage}")
    requiring_backfill = [symbol for symbol in symbols if not cached_by_symbol[symbol]]
    return {
        "run_id": run_id, "identity_hash": stable_digest({**base_identity, "stage": stage, "symbols": snapshot}), "base_identity_hash": stable_digest(base_identity),
        "engine_version": ENGINE_VERSION, "stage": stage, "target_symbol_count": STAGE_TARGETS[stage], "eligible_universe_count": len(eligible),
        "selected_symbol_count": len(symbols), "symbols": symbols, "universe_snapshot": snapshot,
        "selection_method": "SOURCE_COHORT_PLUS_LISTING_AGE_ROUND_ROBIN_STABLE_SYMBOL_HASH", "selection_uses_current_ticker": False,
        "already_cached_symbols": sorted(symbol for symbol in symbols if cached_by_symbol[symbol]), "symbols_requiring_backfill": requiring_backfill,
        "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * DAY_MS, "label_lookahead_end": end + 4 * 3_600_000,
        "expected_5m_candles": len(symbols) * ((end - start) // 300_000), "estimated_bridge_requests": len(parts) - cached_parts,
        "expected_funding_requests": 0, "funding_required": False, "expected_disk_bytes": len(requiring_backfill) * len(days) * 7_000 + len(symbols) * 1_500_000,
        "worker_count": max(1, min(3, workers)), "checkpoint_path": str((state_root / "signal-replication" / run_id / "checkpoint.json").resolve()),
        "source_signal_hashes": [item["definition_hash"] for item in source["definitions"]], "source_run": source_run,
        "exclusion_summary": dict(Counter(item["reason"] for item in base_exclusions)), "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    }


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = state_root / "signal-replication" / plan["run_id"]
    stage_root = _stage_root(state_root, plan["run_id"], plan["stage"])
    path = stage_root / "resource-plan.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["identity_hash"] != plan["identity_hash"]:
        raise ValueError("immutable D4.6 stage-plan collision")
    if not path.exists():
        atomic_json(path, plan)
        atomic_json(stage_root / "universe.json", {key: plan[key] for key in ("stage", "eligible_universe_count", "selection_method", "selection_uses_current_ticker", "universe_snapshot", "exclusion_summary")})
    index_path = root / "resource-plan.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"run_id": plan["run_id"], "base_identity_hash": plan["base_identity_hash"], "stages": {}}
    if index["base_identity_hash"] != plan["base_identity_hash"]:
        raise ValueError("immutable D4.6 run collision")
    index["stages"][plan["stage"]] = str(path.resolve())
    atomic_json(index_path, index)
    source = load_source_signals(state_root, plan["source_run"])
    hashes_path = root / "source-signal-hashes.json"
    if not hashes_path.exists():
        atomic_json(hashes_path, source)
    return root


def _atomic_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as target:
        json.dump(value, target, sort_keys=True, separators=(",", ":"))
    os.replace(temporary, path)


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _load_symbol(symbol: str, plan: dict[str, Any], cache_root: Path, bridge_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata = next(item for item in plan["universe_snapshot"] if item["symbol"] == symbol)
    available_start = max(plan["development_window"]["start"], int(metadata["onboardDate"]))
    available_end = min(plan["development_window"]["end"], int(metadata["deliveryDate"]))
    if max(0, (available_end - available_start) // 300_000) < MIN_VALID_ROWS:
        return [], {
            "symbol": symbol, "candle_count": 0, "feature_rows": 0, "coverage": 0.0,
            "cache_hits": 0, "downloads": 0, "dataset_ids": [],
            "funding_coverage": "NOT_REQUIRED",
            "status": "INSUFFICIENT_VALID_HISTORY",
            "detail": "contract cannot provide the minimum seven Development days",
        }
    store = HistoricalDataStore(cache_root, PacedBridgeClient(bridge_url))
    candles, manifests = store.candles(symbol, "5m", plan["warmup_start"], plan["label_lookahead_end"])
    rows = build_symbol_rows(symbol, candles, [], metadata, plan["development_window"]["start"], plan["development_window"]["end"])
    index_by_close = {candle.close_time: index for index, candle in enumerate(candles)}
    for row in rows:
        index = index_by_close[row["timestamp"]]
        trailing = candles[max(0, index - 47):index + 1]
        row["descriptive"] = {"historical_quote_volume_4h": mean(item.volume * item.close for item in trailing)}
    eligible_start = max(plan["warmup_start"], int(metadata["onboardDate"]))
    expected = max(0, (plan["label_lookahead_end"] - eligible_start) // 300_000)
    coverage = len([item for item in candles if item.open_time >= eligible_start]) / max(1, expected)
    quality = {
        "symbol": symbol, "candle_count": len(candles), "feature_rows": len(rows), "coverage": coverage,
        "cache_hits": store.cache_hits, "downloads": store.downloads, "dataset_ids": [item["dataset_id"] for item in manifests],
        "funding_coverage": "NOT_REQUIRED",
        "status": "USABLE" if len(rows) >= MIN_VALID_ROWS and coverage >= .95 else "INSUFFICIENT_VALID_HISTORY",
    }
    return rows if quality["status"] == "USABLE" else [], quality


def _enrich_cross_section(rows: list[dict[str, Any]], metadata: dict[str, dict[str, Any]], btc_rows: list[dict[str, Any]]) -> None:
    add_cross_sectional_features(rows, metadata, btc_rows)
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_time[row["timestamp"]].append(row)
    for timestamp, group in by_time.items():
        eligible = {symbol for symbol, item in metadata.items() if universe_eligible(item, timestamp)}
        volume_ranks = cross_sectional_rank({row["symbol"]: row["descriptive"]["historical_quote_volume_4h"] for row in group}, eligible)
        for row in group:
            row["descriptive"]["historical_quote_volume_bucket"] = bucket_value("TERCILE", volume_ranks.get(row["symbol"]))


def _signal_rows(rows: list[dict[str, Any]], definition: dict[str, Any]) -> list[dict[str, Any]]:
    left, right, _ = definition["interaction"]
    rules = {item["id"]: item["bucket_rule"] for item in definition["component_catalog"]}
    expected_left, expected_right = definition["condition_bucket"].split(" × ", 1)
    return [row for row in rows if bucket_value(rules[left], row["features"].get(left)) == expected_left and bucket_value(rules[right], row["features"].get(right)) == expected_right]


def _slice_metrics(rows: list[dict[str, Any]], direction: int) -> dict[str, Any]:
    values = [float(row["labels"]["4h"]) for row in rows if row["labels"].get("4h") is not None]
    return {"observations": len(values), "symbols": len({row["symbol"] for row in rows}), "mean": mean(values) if values else 0.0, "median": median(values) if values else 0.0, "directional_hit_rate": sum(direction * value > 0 for value in values) / len(values) if values else 0.0}


def _temporal_detail(rows: list[dict[str, Any]], direction: int) -> dict[str, Any]:
    return {segment: _slice_metrics([row for row in rows if row["segment"] == segment], direction) for segment in SEGMENTS}


def _cross_sectional_detail(rows: list[dict[str, Any]], definition: dict[str, Any]) -> dict[str, Any]:
    direction = 1 if definition["expected_direction"] == "POSITIVE" else -1
    btc_rule = next(item["bucket_rule"] for item in definition["component_catalog"] if item["id"] == "btc_return_regime")
    expected_btc = definition["condition_bucket"].split(" × ", 1)[1]
    slices: dict[str, dict[str, list[dict[str, Any]]]] = {
        "listing_age": defaultdict(list), "historical_quote_volume": defaultdict(list), "volatility": defaultdict(list), "btc_regime_magnitude": defaultdict(list),
    }
    for row in rows:
        age = bucket_value("LISTING_AGE", row["features"].get("listing_age_days"))
        volume = row["descriptive"].get("historical_quote_volume_bucket")
        volatility = bucket_value("PAST_PERCENTILE", row["features"].get("normalized_atr"))
        btc_value = row["features"].get("btc_return_regime")
        stronger = isinstance(btc_value, (int, float)) and bucket_value(btc_rule, btc_value / 2) == expected_btc
        if age: slices["listing_age"][age].append(row)
        if volume: slices["historical_quote_volume"][volume].append(row)
        if volatility: slices["volatility"][volatility].append(row)
        slices["btc_regime_magnitude"]["STRONGER_QUALIFYING" if stronger else "WEAKER_QUALIFYING"].append(row)
    return {name: {bucket: _slice_metrics(group, direction) for bucket, group in sorted(groups.items())} for name, groups in slices.items()}


def replication_status(summary: dict[str, Any], definition: dict[str, Any]) -> str:
    direction = 1 if definition["expected_direction"] == "POSITIVE" else -1
    breadth = summary["breadth"]
    effective = int(summary["effective_observation_count"])
    ci = summary["block_bootstrap_95_ci"]
    mean_bps, median_bps = direction * float(summary["mean_forward_return"]) * 10_000, direction * float(summary["median_forward_return"]) * 10_000
    aligned_ratio = breadth["profitable_direction_symbol_count"] / max(1, breadth["active_symbol_count"])
    ci_supports = ci[0] > 0 if direction > 0 else ci[1] < 0
    ci_reverses = ci[1] < 0 if direction > 0 else ci[0] > 0
    if effective < 100 or breadth["active_symbol_count"] < 10:
        return "INSUFFICIENT_DATA"
    if mean_bps <= 0 or ci_reverses:
        return "NOT_REPLICATED"
    stable = summary["temporal_classification"] not in {"SIGN_FLIP", "TEMPORALLY_CONCENTRATED"}
    if mean_bps >= 2 * MINIMUM_ROUND_TRIP_COST_BPS and median_bps >= MINIMUM_ROUND_TRIP_COST_BPS and ci_supports and aligned_ratio >= .75 and breadth["top_symbol_contribution"] <= .25 and stable:
        return "REPLICATED_STRONG"
    if mean_bps >= MINIMUM_ROUND_TRIP_COST_BPS and median_bps >= 0 and ci_supports and aligned_ratio >= .60 and breadth["top_symbol_contribution"] <= .50 and stable:
        return "REPLICATED"
    if mean_bps >= 5 and median_bps >= 0 and stable:
        return "WEAK_REPLICATION"
    return "NOT_REPLICATED"


def stage_decision(stage: str, statuses: list[str]) -> str:
    if any(status == "NOT_REPLICATED" for status in statuses):
        return "STOP_NOT_REPLICATED"
    if any(status == "INSUFFICIENT_DATA" for status in statuses):
        return "STOP_INSUFFICIENT_DATA" if stage != "A" else "CONTINUE_STAGE_B_AMBIGUOUS"
    if stage == "A":
        return "CONTINUE_STAGE_B" if all(status.startswith("REPLICATED") for status in statuses) else "CONTINUE_STAGE_B_AMBIGUOUS"
    if stage == "B":
        return "CONTINUE_STAGE_C" if all(status.startswith("REPLICATED") for status in statuses) else "STOP_WEAK_REPLICATION"
    return "STOP_STAGE_C_COMPLETE"


def _write_latest(root: Path, stage: str, results: list[dict[str, Any]], gate: dict[str, Any], plan: dict[str, Any], quality: list[dict[str, Any]], source: dict[str, Any]) -> None:
    signal_a, signal_b = results
    atomic_json(root / "signal-a-replication.json", signal_a)
    atomic_json(root / "signal-b-replication.json", signal_b)
    atomic_json(root / "symbol-breadth.json", {item["signal_id"]: item["replication"]["breadth"] for item in results})
    atomic_json(root / "temporal-stability.json", {item["signal_id"]: item["temporal_detail"] for item in results})
    atomic_json(root / "cross-sectional-stability.json", {item["signal_id"]: item["cross_sectional_stability"] for item in results})
    atomic_json(root / "cost-hurdle.json", {item["signal_id"]: {"hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS, "mean_effect_bps": item["replication"]["mean_forward_return"] * 10_000, "median_effect_bps": item["replication"]["median_forward_return"] * 10_000, "status": item["replication"]["cost_hurdle_state"]} for item in results})
    atomic_json(root / "replication-gate.json", gate)
    backfill = {
        "stage": stage, "selected_symbols": plan["selected_symbol_count"], "usable_symbols": len(quality) - sum(item["status"] != "USABLE" for item in quality),
        "planned_worker_count": plan["worker_count"], "effective_worker_count": 1,
        "newly_backfilled_symbols": sorted(item["symbol"] for item in quality if item["downloads"] > 0 and item["status"] == "USABLE"),
        "partial_backfill_symbols": sorted(item["symbol"] for item in quality if item["downloads"] > 0 and item["status"] != "USABLE"),
        "failed_symbols": [item for item in quality if item["status"] != "USABLE"],
        "cache_hits": sum(item["cache_hits"] for item in quality), "downloads": sum(item["downloads"] for item in quality),
    }
    atomic_json(root / "backfill-summary.json", backfill)
    atomic_json(_stage_root(root.parent.parent, plan["run_id"], stage) / "backfill-summary.json", backfill)
    atomic_json(root / "universe.json", {
        key: plan[key] for key in (
            "stage", "eligible_universe_count", "selection_method", "selection_uses_current_ticker",
            "universe_snapshot", "exclusion_summary",
        )
    })
    manifest = {
        "run_id": plan["run_id"], "status": "COMPLETED" if gate["decision"].startswith("STOP") else "STAGE_COMPLETE",
        "latest_stage": stage, "next_stage": gate.get("next_stage"), "engine_version": ENGINE_VERSION, "source_run": source["source_run"],
        "source_signal_hashes": [item["definition_hash"] for item in source["definitions"]], "development_window": plan["development_window"],
        "eligible_universe_count": plan["eligible_universe_count"], "usable_symbol_count": backfill["usable_symbols"], "dataset_version": stable_digest(sorted(dataset_id for item in quality for dataset_id in item["dataset_ids"])),
        "cost_model": "NOT_APPLICABLE_RAW_FORWARD_RETURN_REPLICATION", "cost_hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS,
        "thresholds_changed": False, "current_ticker_used_for_selection_or_features": False, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    }
    atomic_json(root / "manifest.json", manifest)
    lines = ["# D4.6 Signal Replication Report", "", "**NOT A TRADING STRATEGY.** Definitions are loaded from the authoritative D4.5 artifact.", "", f"- Source: `{source['source_run']}`", f"- Latest stage: {stage}", f"- Usable symbols: {backfill['usable_symbols']}", f"- Decision: {gate['decision']}", ""]
    for item in results:
        result = item["replication"]
        lines += [f"## {item['signal_id']}", "", f"- Status: {item['replication_status']}", f"- Mean / median 4h effect: {result['mean_forward_return'] * 10_000:.2f} / {result['median_forward_return'] * 10_000:.2f} bps", f"- Raw / effective n: {result['observation_count']} / {result['effective_observation_count']}", f"- Symbols: {result['symbol_count']}", f"- Temporal: {result['temporal_classification']}", ""]
    (root / "replication-report.md").write_text("\n".join(lines), encoding="utf-8")


def execute(run_id: str, stage: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    root = state_root / "signal-replication" / run_id
    stage_root = _stage_root(state_root, run_id, stage)
    plan = json.loads((stage_root / "resource-plan.json").read_text(encoding="utf-8"))
    gate_path = stage_root / "replication-gate.json"
    if gate_path.exists():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        source = load_source_signals(state_root, plan["source_run"])
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        checkpoint["funding_coverage"] = "NOT_REQUIRED"
        for collection in (checkpoint["completed_symbols"], checkpoint["failed_symbols"]):
            for quality_item in collection.values():
                quality_item.setdefault("funding_coverage", "NOT_REQUIRED")
        atomic_json(root / "checkpoint.json", checkpoint)
        results = [json.loads((stage_root / f"signal-{name}-replication.json").read_text(encoding="utf-8")) for name in ("a", "b")]
        usable_count = len(checkpoint["completed_symbols"])
        for item in results:
            item["neutral_or_insufficient_symbol_count"] = usable_count - item["replication"]["breadth"]["active_symbol_count"]
        atomic_json(stage_root / "signal-a-replication.json", results[0]); atomic_json(stage_root / "signal-b-replication.json", results[1])
        quality = [*checkpoint["completed_symbols"].values(), *checkpoint["failed_symbols"].values()]
        _write_latest(root, stage, results, gate, plan, quality, source)
        return {"run_id": run_id, "stage": stage, "status": "ALREADY_COMPLETED", "decision": gate["decision"], "artifact": str(root.resolve())}
    source = load_source_signals(state_root, plan["source_run"])
    checkpoint_path = root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"base_identity_hash": plan["base_identity_hash"], "completed_symbols": {}, "failed_symbols": {}, "analysis_state": {}}
    if checkpoint["base_identity_hash"] != plan["base_identity_hash"]:
        raise ValueError("immutable D4.6 checkpoint collision")
    work = root / "work"
    # Completed symbol work is immutable/reused. Transport failures remain
    # retryable so a resumed run cannot turn a temporary bridge outage into a
    # research conclusion.
    pending = [
        symbol for symbol in plan["symbols"]
        if symbol not in checkpoint["completed_symbols"]
        and (
            symbol not in checkpoint["failed_symbols"]
            or checkpoint["failed_symbols"][symbol].get("status") == "BACKFILL_FAILED"
        )
    ]
    # The localhost V2 bridge fronts one upstream public-data client. A single
    # effective worker avoids aggregate bursts from independently paced clients.
    effective_workers = 1
    checkpoint["effective_worker_count"] = effective_workers
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
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
                checkpoint["failed_symbols"][symbol] = {
                    "symbol": symbol, "status": "BACKFILL_FAILED",
                    "detail": f"{type(error).__name__}: {error}",
                    "dataset_ids": [], "cache_hits": 0, "downloads": 0, "funding_coverage": "NOT_REQUIRED",
                }
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
        replication = summarize_slice(matched, definition["feature"], definition["condition_bucket"], definition["horizon"])
        status = replication_status(replication, definition)
        direction = 1 if definition["expected_direction"] == "POSITIVE" else -1
        results.append({
            "signal_id": chr(ord("A") + index), "definition_hash": definition["definition_hash"], "source_definition": definition,
            "replication": replication, "replication_status": status, "temporal_detail": _temporal_detail(matched, direction),
            "cross_sectional_stability": _cross_sectional_detail(matched, definition), "thresholds_changed": False,
            "neutral_or_insufficient_symbol_count": len(usable) - replication["breadth"]["active_symbol_count"],
        })
    decision = stage_decision(stage, [item["replication_status"] for item in results])
    next_stage = "B" if decision.startswith("CONTINUE_STAGE_B") else "C" if decision == "CONTINUE_STAGE_C" else None
    gate = {"stage": stage, "signals": {item["signal_id"]: item["replication_status"] for item in results}, "decision": decision, "next_stage": next_stage, "thresholds_changed": False, "oos_access": "OOS_NOT_ACCESSED"}
    atomic_json(stage_root / "signal-a-replication.json", results[0]); atomic_json(stage_root / "signal-b-replication.json", results[1])
    atomic_json(stage_root / "replication-gate.json", gate)
    checkpoint["analysis_state"][stage] = "COMPLETED"; atomic_json(checkpoint_path, checkpoint)
    quality = [*checkpoint["completed_symbols"].values(), *checkpoint["failed_symbols"].values()]
    _write_latest(root, stage, results, gate, plan, quality, source)
    return {"run_id": run_id, "stage": stage, "status": "COMPLETED", "usable_symbols": len(usable), "signals": gate["signals"], "decision": decision, "next_stage": next_stage, "artifact": str(root.resolve())}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.6 signal replication")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--stage", choices=tuple(STAGE_TARGETS), required=True); plan.add_argument("--dev-start", required=True); plan.add_argument("--dev-end", required=True)
    plan.add_argument("--workers", type=int, default=2); plan.add_argument("--source-run", default=SOURCE_RUN); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market")
    run = commands.add_parser("execute")
    run.add_argument("--run-id", required=True); run.add_argument("--stage", choices=tuple(STAGE_TARGETS), required=True); run.add_argument("--state-root", default="state"); run.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    state_root, cache_root = Path(args.state_root), Path(args.cache_root)
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    try:
        if args.command == "plan":
            start, end = iso_ms(args.dev_start), iso_ms(args.dev_end)
            if end <= start:
                raise ValueError("--dev-end must be after --dev-start")
            plan = resource_plan(args.stage, start, end, args.workers, state_root, cache_root, bridge_url, args.source_run)
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
