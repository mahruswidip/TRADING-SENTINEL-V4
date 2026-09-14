from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from backtest_engine.cli import eligible_symbols
from backtest_engine.data import atomic_json, iso_ms
from backtest_engine.engine import stable_digest
from forensics_engine.analysis import DAY_MS
from research_engine.discovery import (
    MINIMUM_ROUND_TRIP_COST_BPS,
    bucket_value,
    cross_sectional_rank,
    percentile,
    summarize_slice,
    symbol_breadth,
    universe_eligible,
)
from research_engine.fvg import PacedBridgeClient
from research_engine.replication import (
    _atomic_gzip_json,
    _cache_partition,
    _load_symbol,
    _read_gzip_json,
    _temporal_detail,
    deterministic_selection,
    file_sha256,
    load_source_signals,
    replication_status,
)
from research_engine.replication_b import _artifact_hashes


ENGINE_VERSION = "d4.7-signal-b-independent-temporal-replication-v1"
SOURCE_RUN = "d4_5_482ba89ea0075922"
PARENT_RUN = "d4_6b_d9380c7ff0781bac"
TARGET_SYMBOLS = 210
INDEPENDENT_START = "2026-06-01T00:00:00Z"
INDEPENDENT_END = "2026-06-30T20:00:00Z"
TAIL_REMOVAL_COUNT = 5


def oos_guard() -> None:
    raise PermissionError("locked OOS is outside D4.7")


def _root(state_root: Path, run_id: str) -> Path:
    return state_root / "signal-replication" / run_id


def _source_signal_b(state_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source = load_source_signals(state_root, SOURCE_RUN)
    matches = [item for item in source["definitions"] if item["definition_hash"] == "79f6169b3289d82c1e7e6b654b93bf7440d14cb1f42b00ad858a3d64f26d49af"]
    if len(matches) != 1:
        raise ValueError("authoritative Signal B definition hash is missing or ambiguous")
    definition = matches[0]
    if definition["condition_bucket"] != "LOW × BTC_BULLISH" or definition["horizon"] != "4h" or definition["expected_direction"] != "NEGATIVE":
        raise ValueError("authoritative Signal B definition differs from the frozen D4.5 contract")
    return definition, source


def _parent_contract(state_root: Path) -> dict[str, Any]:
    root = _root(state_root, PARENT_RUN)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    signal = json.loads((root / "signal-b.json").read_text(encoding="utf-8"))
    if manifest["oos_access"] != "OOS_NOT_ACCESSED" or manifest["thresholds_changed"]:
        raise ValueError("parent D4.6B run violates the D4.7 source contract")
    return {
        "run_id": PARENT_RUN,
        "path": str(root.resolve()),
        "development_window": manifest["development_window"],
        "signal_b_definition_hash": signal["definition_hash"],
        "artifact_hashes": _artifact_hashes(root),
    }


def _decision(replication: dict[str, Any], tail: dict[str, Any]) -> tuple[str, list[str]]:
    """Frozen pre-result D4.7 decision rules; tail removal is descriptive, never a filter."""
    reasons: list[str] = []
    direction = -1
    breadth = replication["breadth"]
    aligned = breadth["profitable_direction_symbol_count"] / max(1, breadth["active_symbol_count"])
    ci_supports = replication["block_bootstrap_95_ci"][1] < 0
    robust_tail = tail["mean_after_removing_largest_negative_observations"] < 0
    negative_direction = replication["mean_forward_return"] < 0 and replication["median_forward_return"] < 0
    stable = replication["temporal_classification"] == "TEMPORALLY_STABLE"
    broad = breadth["active_symbol_count"] >= 10 and aligned >= .60 and breadth["top_symbol_contribution"] <= .50
    economically_meaningful = direction * replication["mean_forward_return"] * 10_000 >= MINIMUM_ROUND_TRIP_COST_BPS
    if negative_direction and economically_meaningful and ci_supports and broad and stable and robust_tail:
        return "INDEPENDENTLY_REPLICATED", reasons
    if not negative_direction:
        reasons.append("DIRECTION_OR_MEDIAN_NOT_NEGATIVE")
    if not economically_meaningful:
        reasons.append("BELOW_11_BPS_CONTEXT_HURDLE")
    if not ci_supports:
        reasons.append("DAILY_BLOCK_CI_CROSSES_ZERO")
    if not broad:
        reasons.append("INSUFFICIENT_BREADTH_OR_CONCENTRATION")
    if not stable:
        reasons.append(replication["temporal_classification"])
    if not robust_tail:
        reasons.append("RAW_MEAN_REVERSES_AFTER_PREDECLARED_TAIL_DESCRIPTION")
    if negative_direction and broad and stable:
        return "WEAK", reasons
    return "NOT_REPLICATED", reasons


def _slice(rows: list[dict[str, Any]], direction: int = -1) -> dict[str, Any]:
    values = [float(row["labels"]["4h"]) for row in rows if row["labels"].get("4h") is not None]
    return {
        "observations": len(values), "symbols": len({row["symbol"] for row in rows}),
        "mean": mean(values) if values else 0.0, "median": median(values) if values else 0.0,
        "directional_hit_rate": sum(direction * value > 0 for value in values) / len(values) if values else 0.0,
    }


def distribution_tail_forensics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(float(row["labels"]["4h"]) for row in rows if row["labels"].get("4h") is not None)
    negatives, positives = [value for value in values if value < 0], [value for value in values if value > 0]
    largest_negative = values[:TAIL_REMOVAL_COUNT]
    remaining = values[TAIL_REMOVAL_COUNT:]
    negative_total = abs(sum(negatives))
    return {
        "descriptive_only": True, "predeclared_tail_removal_count": TAIL_REMOVAL_COUNT,
        "observation_count": len(values),
        "percentiles": {str(key): percentile(values, key / 100) if values else 0.0 for key in (10, 25, 50, 75, 90)},
        "mean": mean(values) if values else 0.0, "median": median(values) if values else 0.0,
        "negative_observation_count": len(negatives), "positive_observation_count": len(positives),
        "negative_mean_magnitude": abs(mean(negatives)) if negatives else 0.0,
        "positive_mean_magnitude": mean(positives) if positives else 0.0,
        "largest_negative_observations": largest_negative,
        "largest_negative_share_of_total_negative_magnitude": abs(sum(largest_negative)) / negative_total if negative_total else 0.0,
        "mean_after_removing_largest_negative_observations": mean(remaining) if remaining else 0.0,
        "median_after_removing_largest_negative_observations": median(remaining) if remaining else 0.0,
    }


def _descriptive_groups(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = sorted(float(row["features"][key]) for row in rows if isinstance(row["features"].get(key), (float, int)))
    if not values:
        return {"available": False}
    low, high = percentile(values, 1 / 3), percentile(values, 2 / 3)
    groups = {"LOW": [], "NORMAL": [], "HIGH": []}
    for row in rows:
        value = row["features"].get(key)
        if not isinstance(value, (float, int)):
            continue
        groups["LOW" if value < low else "HIGH" if value >= high else "NORMAL"].append(row)
    return {"available": True, "descriptive_tercile_cutpoints": [low, high], "groups": {name: _slice(group) for name, group in groups.items()}}


def mechanism_forensics(rows: list[dict[str, Any]], btc_rows: list[dict[str, Any]]) -> dict[str, Any]:
    btc_atr = {row["timestamp"]: row["features"].get("normalized_atr") for row in btc_rows}
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_time[row["timestamp"]].append(row)
    for timestamp, group in by_time.items():
        ranks = [float(row["features"]["relative_strength_1h"]) for row in group if isinstance(row["features"].get("relative_strength_1h"), (float, int))]
        for row in group:
            row["descriptive"]["btc_normalized_atr"] = btc_atr.get(timestamp)
            row["descriptive"]["relative_strength_1h_dispersion"] = pstdev(ranks) if len(ranks) > 1 else 0.0
    def summary(field: str, source: str = "features") -> dict[str, Any]:
        values = [float(row[source][field]) for row in rows if isinstance(row[source].get(field), (float, int))]
        return {"count": len(values), "mean": mean(values) if values else 0.0, "median": median(values) if values else 0.0, "p25": percentile(values, .25) if values else 0.0, "p75": percentile(values, .75) if values else 0.0}
    stronger = [row for row in rows if float(row["features"].get("btc_return_regime") or 0.0) > .008]
    weaker = [row for row in rows if row not in stronger]
    return {
        "descriptive_only": True,
        "btc_bullish_strength": {"WEAKER_QUALIFYING": _slice(weaker), "STRONGER_QUALIFYING": _slice(stronger)},
        "btc_return_magnitude": summary("btc_return_regime"),
        "btc_volatility": summary("btc_normalized_atr", "descriptive"),
        "cross_sectional_relative_strength_dispersion": summary("relative_strength_1h_dispersion", "descriptive"),
        "market_wide_volatility": _descriptive_groups(rows, "normalized_atr"),
        "market_breadth": _descriptive_groups(rows, "market_breadth"),
        "listing_age": {name: _slice([row for row in rows if row["features"].get("listing_age_days") is not None and (float(row["features"]["listing_age_days"]) < 30 if name == "VERY_NEW" else float(row["features"]["listing_age_days"]) < 365 if name == "YOUNG" else float(row["features"]["listing_age_days"]) >= 365)]) for name in ("VERY_NEW", "YOUNG", "ESTABLISHED")},
        "historical_safe_liquidity_group": {name: _slice([row for row in rows if row["descriptive"].get("historical_quote_volume_bucket") == name]) for name in ("LOW", "NORMAL", "HIGH")},
    }


def _load_matched_rows_bounded(
    work: Path,
    symbols: list[str],
    metadata: dict[str, dict[str, Any]],
    btc_rows: list[dict[str, Any]],
    definition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reconstruct the frozen Signal B slice without retaining every full source row."""
    left, right, _ = definition["interaction"]
    rules = {item["id"]: item["bucket_rule"] for item in definition["component_catalog"]}
    expected_left, expected_right = definition["condition_bucket"].split(" × ", 1)
    btc_by_time = {row["timestamp"]: row["features"].get("return_1h") for row in btc_rows}
    relevant_times = {
        timestamp for timestamp, value in btc_by_time.items()
        if bucket_value(rules[right], value) == expected_right
    }

    # Tuple layout keeps the pre-filter working set compact:
    # symbol, return_1h, historical_quote_volume_4h, label_4h,
    # listing_age_days, normalized_atr, date, segment.
    compact_by_time: dict[int, list[tuple[str, float, float, float, float | None, float | None, str, str]]] = defaultdict(list)
    for symbol in symbols:
        symbol_rows = _read_gzip_json(work / f"{symbol}.rows.json.gz")
        for row in symbol_rows:
            timestamp = int(row["timestamp"])
            if timestamp not in relevant_times:
                continue
            return_1h = row["features"].get("return_1h")
            label_4h = row["labels"].get("4h")
            historical_volume = row["descriptive"].get("historical_quote_volume_4h")
            if not isinstance(return_1h, (float, int)) or not isinstance(label_4h, (float, int)) or not isinstance(historical_volume, (float, int)):
                continue
            listing_age = row["features"].get("listing_age_days")
            normalized_atr = row["features"].get("normalized_atr")
            compact_by_time[timestamp].append((
                symbol, float(return_1h), float(historical_volume), float(label_4h),
                float(listing_age) if isinstance(listing_age, (float, int)) else None,
                float(normalized_atr) if isinstance(normalized_atr, (float, int)) else None,
                str(row["date"]), str(row["segment"]),
            ))
        del symbol_rows

    matched: list[dict[str, Any]] = []
    for timestamp in sorted(compact_by_time):
        group = compact_by_time[timestamp]
        eligible = {symbol for symbol, item in metadata.items() if universe_eligible(item, timestamp)}
        returns = {item[0]: item[1] for item in group}
        return_ranks = cross_sectional_rank(returns, eligible)
        volume_ranks = cross_sectional_rank({item[0]: item[2] for item in group}, eligible)
        market_breadth = sum(value > 0 for value in returns.values()) / len(returns) if returns else None
        btc_return = btc_by_time[timestamp]
        for symbol, _, historical_volume, label_4h, listing_age, normalized_atr, date, segment in group:
            relative_strength = return_ranks.get(symbol)
            if bucket_value(rules[left], relative_strength) != expected_left:
                continue
            matched.append({
                "symbol": symbol,
                "timestamp": timestamp,
                "date": date,
                "segment": segment,
                "features": {
                    left: relative_strength,
                    right: btc_return,
                    "listing_age_days": listing_age,
                    "normalized_atr": normalized_atr,
                    "market_breadth": market_breadth,
                },
                "labels": {"4h": label_4h},
                "descriptive": {
                    "historical_quote_volume_4h": historical_volume,
                    "historical_quote_volume_bucket": bucket_value("TERCILE", volume_ranks.get(symbol)),
                },
            })
    return matched


def resource_plan(start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    definition, source = _source_signal_b(state_root)
    parent = _parent_contract(state_root)
    prior = json.loads((state_root / "signal-discovery" / SOURCE_RUN / "manifest.json").read_text(encoding="utf-8"))["development_window"]
    if end > prior["start"]:
        raise ValueError("D4.7 independent period must not overlap D4.5/D4.6B evidence")
    if parent["signal_b_definition_hash"] != definition["definition_hash"]:
        raise ValueError("D4.6B Signal B definition hash differs from authoritative D4.5")
    universe = PacedBridgeClient(bridge_url).universe()
    eligible, exclusions = eligible_symbols(universe, start, end)
    eligible = [item for item in eligible if item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT"]
    selected = deterministic_selection(eligible, [], TARGET_SYMBOLS, start)
    btc = next((item for item in eligible if item.get("symbol") == "BTCUSDT"), None)
    if btc is None:
        raise ValueError("BTCUSDT must be historically eligible as required frozen market context")
    symbols = [str(item["symbol"]) for item in selected]
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, math.ceil((end + 4 * 3_600_000) / DAY_MS) * DAY_MS, DAY_MS))
    coverage_symbols = sorted(set(symbols + ["BTCUSDT"]))
    cached = {symbol: all(_cache_partition(cache_root, symbol, day).exists() for day in days) for symbol in coverage_symbols}
    snapshot = [{key: item.get(key) for key in ("symbol", "onboardDate", "deliveryDate", "contractType", "quoteAsset", "marginAsset")} for item in selected]
    btc_metadata = {key: btc.get(key) for key in ("symbol", "onboardDate", "deliveryDate", "contractType", "quoteAsset", "marginAsset")}
    identity = {"engine": ENGINE_VERSION, "parent_run": PARENT_RUN, "source_run": SOURCE_RUN, "definition_hash": definition["definition_hash"], "development": {"start": start, "end": end}, "target_symbols": TARGET_SYMBOLS}
    run_id = f"d4_7_{stable_digest(identity)[:16]}"
    return {
        "run_id": run_id, "identity_hash": stable_digest({**identity, "symbols": snapshot}), "base_identity_hash": stable_digest(identity), "engine_version": ENGINE_VERSION,
        "parent_run": PARENT_RUN, "source_run": SOURCE_RUN, "signal_b_definition_hash": definition["definition_hash"], "source_signal_hashes": [item["definition_hash"] for item in source["definitions"]],
        "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * DAY_MS, "label_lookahead_end": end + 4 * 3_600_000,
        "independence": {"prior_evidence_window": prior, "non_overlapping": True, "selection_reason": "PRE_JULY_EQUAL_LENGTH_DEVELOPMENT_WINDOW", "oos_access": "OOS_NOT_ACCESSED"},
        "target_symbol_count": TARGET_SYMBOLS, "eligible_universe_count": len(eligible), "selected_symbol_count": len(symbols), "symbols": symbols, "universe_snapshot": snapshot, "btc_context_metadata": btc_metadata,
        "selection_method": "DYNAMIC_HISTORICAL_ELIGIBILITY_PLUS_LISTING_AGE_ROUND_ROBIN_STABLE_SYMBOL_HASH", "selection_uses_current_ticker": False,
        "already_cached_symbols": sorted(symbol for symbol in symbols if cached[symbol]), "symbols_requiring_backfill": sorted(symbol for symbol in symbols if not cached[symbol]),
        "expected_5m_candles": len(symbols) * ((end - start) // 300_000), "estimated_bridge_requests": sum(not _cache_partition(cache_root, symbol, day).exists() for symbol in coverage_symbols for day in days), "worker_count": max(1, min(3, workers)),
        "checkpoint_path": str((_root(state_root, run_id) / "checkpoint.json").resolve()), "exclusion_summary": dict(Counter(item["reason"] for item in exclusions)), "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
        "decision_criteria": "INDEPENDENTLY_REPLICATED requires negative mean and median, >=11bps magnitude, daily-block CI below zero, >=60% aligned breadth, top symbol <=50%, temporal stability, and negative mean after descriptive removal of five largest negative observations; otherwise WEAK if negative/broad/stable, else NOT_REPLICATED.",
    }


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = _root(state_root, plan["run_id"])
    path = root / "resource-plan.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["identity_hash"] != plan["identity_hash"]:
        raise ValueError("immutable D4.7 run collision")
    if not path.exists():
        atomic_json(path, plan)
        atomic_json(root / "parent-run.json", _parent_contract(state_root))
        atomic_json(root / "source-signal-hash.json", {"signal_b": _source_signal_b(state_root)[0], "source_artifact_hashes": _source_signal_b(state_root)[1]["source_artifact_hashes"]})
        atomic_json(root / "universe.json", {key: plan[key] for key in ("eligible_universe_count", "selected_symbol_count", "selection_method", "selection_uses_current_ticker", "universe_snapshot", "exclusion_summary")})
    return root


def _load_btc(root: Path, plan: dict[str, Any], cache_root: Path, bridge_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if "BTCUSDT" in plan["symbols"]:
        return _read_gzip_json(root / "work" / "BTCUSDT.rows.json.gz"), {"symbol": "BTCUSDT", "status": "RESEARCH_COHORT"}
    btc_plan = {**plan, "universe_snapshot": [*plan["universe_snapshot"], plan["btc_context_metadata"]]}
    return _load_symbol("BTCUSDT", btc_plan, cache_root, bridge_url)


def _write_artifacts(root: Path, plan: dict[str, Any], quality: list[dict[str, Any]], result: dict[str, Any], distribution: dict[str, Any], mechanisms: dict[str, Any], decision: str, reasons: list[str]) -> None:
    usable = sum(item["status"] == "USABLE" for item in quality)
    backfill = {"selected_symbols": plan["selected_symbol_count"], "usable_symbols": usable, "planned_worker_count": plan["worker_count"], "effective_worker_count": 1, "newly_backfilled_symbols": sorted(item["symbol"] for item in quality if item.get("downloads", 0) > 0 and item["status"] == "USABLE"), "failed_symbols": [item for item in quality if item["status"] != "USABLE"], "cache_hits": sum(item.get("cache_hits", 0) for item in quality), "downloads": sum(item.get("downloads", 0) for item in quality)}
    atomic_json(root / "backfill-summary.json", backfill)
    atomic_json(root / "signal-b.json", result)
    atomic_json(root / "distribution-tail.json", distribution)
    atomic_json(root / "temporal-diagnostics.json", result["temporal_detail"])
    atomic_json(root / "symbol-breadth.json", result["replication"]["breadth"])
    atomic_json(root / "mechanism-forensics.json", mechanisms)
    atomic_json(root / "dependence-confidence.json", {"method": "D4.5/D4.6B deterministic 95% UTC daily-block bootstrap over 4H-stride effective samples", "naive_iid_inappropriate": True, "raw_observation_count": result["replication"]["observation_count"], "effective_observation_count": result["replication"]["effective_observation_count"], "ci": result["replication"]["block_bootstrap_95_ci"], "ci_excludes_zero_in_negative_direction": result["replication"]["block_bootstrap_95_ci"][1] < 0})
    atomic_json(root / "cost-context.json", {"hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS, "raw_mean_bps": result["replication"]["mean_forward_return"] * 10_000, "raw_median_bps": result["replication"]["median_forward_return"] * 10_000, "status": result["replication"]["cost_hurdle_state"], "not_trade_pnl": True})
    gate = {"decision": decision, "reasons": reasons, "criteria": plan["decision_criteria"], "oos_access": "OOS_NOT_ACCESSED", "thresholds_changed": False, "not_a_trading_strategy": True}
    atomic_json(root / "replication-gate.json", gate)
    atomic_json(root / "manifest.json", {"run_id": plan["run_id"], "status": "COMPLETED", "engine_version": ENGINE_VERSION, "parent_run": PARENT_RUN, "source_run": SOURCE_RUN, "signal_b_definition_hash": plan["signal_b_definition_hash"], "development_window": plan["development_window"], "warmup_start": plan["warmup_start"], "eligible_universe_count": plan["eligible_universe_count"], "usable_symbol_count": usable, "dataset_version": stable_digest(sorted(dataset for item in quality for dataset in item.get("dataset_ids", []))), "thresholds_changed": False, "current_ticker_used_for_selection_or_features": False, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False, "final_decision": decision})
    r, b = result["replication"], result["replication"]["breadth"]
    report = ["# D4.7 Signal B Independent Temporal Replication", "", "**NOT A TRADING STRATEGY.**", "", f"- Parent: `{PARENT_RUN}`", f"- Independent window: {plan['development_window']}", f"- Usable symbols: {usable}", f"- Decision: {decision}", f"- Signal B hash: `{plan['signal_b_definition_hash']}`", "", "## Primary replication", "", f"- Mean / median 4H: {r['mean_forward_return'] * 10_000:.2f} / {r['median_forward_return'] * 10_000:.2f} bps", f"- Raw / effective observations: {r['observation_count']} / {r['effective_observation_count']}", f"- Daily-block 95% CI: [{r['block_bootstrap_95_ci'][0] * 10_000:.2f}, {r['block_bootstrap_95_ci'][1] * 10_000:.2f}] bps", f"- Breadth: {b['profitable_direction_symbol_count']} aligned / {b['opposite_direction_symbol_count']} opposite", "", "## Decision reasons", "", *(f"- {item}" for item in reasons)]
    (root / "replication-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def execute(run_id: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    root = _root(state_root, run_id)
    plan = json.loads((root / "resource-plan.json").read_text(encoding="utf-8"))
    if (root / "manifest.json").exists():
        return {"run_id": run_id, "status": "ALREADY_COMPLETED", "artifact": str(root.resolve())}
    definition, _ = _source_signal_b(state_root)
    if definition["definition_hash"] != plan["signal_b_definition_hash"]:
        raise ValueError("Signal B definition hash changed after planning")
    checkpoint_path = root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"base_identity_hash": plan["base_identity_hash"], "completed_symbols": {}, "failed_symbols": {}}
    if checkpoint["base_identity_hash"] != plan["base_identity_hash"]:
        raise ValueError("immutable D4.7 checkpoint collision")
    work = root / "work"
    pending = [symbol for symbol in plan["symbols"] if symbol not in checkpoint["completed_symbols"] and (symbol not in checkpoint["failed_symbols"] or checkpoint["failed_symbols"][symbol].get("status") == "BACKFILL_FAILED")]
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
            atomic_json(checkpoint_path, checkpoint)
            print(json.dumps({"run_id": run_id, "completed": len(checkpoint["completed_symbols"]), "failed": len(checkpoint["failed_symbols"]), "target": len(plan["symbols"]), "symbol": symbol}))
    btc_rows, btc_quality = _load_btc(root, plan, cache_root, bridge_url)
    if btc_quality["status"] not in {"USABLE", "RESEARCH_COHORT"}:
        raise ValueError("BTC context lacks sufficient independent historical coverage")
    if btc_quality["status"] == "USABLE":
        _atomic_gzip_json(work / "BTCUSDT.context.rows.json.gz", btc_rows)
        atomic_json(work / "BTCUSDT.context.quality.json", btc_quality)
    usable = [symbol for symbol in plan["symbols"] if symbol in checkpoint["completed_symbols"]]
    metadata = {item["symbol"]: item for item in plan["universe_snapshot"] if item["symbol"] in usable}
    matched = _load_matched_rows_bounded(work, usable, metadata, btc_rows, definition)
    replication = summarize_slice(matched, definition["feature"], definition["condition_bucket"], definition["horizon"])
    replication["direction_hit_rate"] = sum(float(row["labels"]["4h"]) < 0 for row in matched if row["labels"].get("4h") is not None) / max(1, replication["observation_count"])
    replication["breadth"] = symbol_breadth(matched, "4h", -1)
    temporal = _temporal_detail(matched, -1)
    distribution = distribution_tail_forensics(matched)
    mechanisms = mechanism_forensics(matched, btc_rows)
    result = {"signal_id": "B", "definition_hash": definition["definition_hash"], "source_definition": definition, "replication": replication, "temporal_detail": temporal, "thresholds_changed": False, "no_lookahead": definition["timestamp_contract"], "oos_access": "OOS_NOT_ACCESSED"}
    decision, reasons = _decision(replication, distribution)
    quality = [*checkpoint["completed_symbols"].values(), *checkpoint["failed_symbols"].values()]
    _write_artifacts(root, plan, quality, result, distribution, mechanisms, decision, reasons)
    return {"run_id": run_id, "status": "COMPLETED", "usable_symbols": len(usable), "decision": decision, "artifact": str(root.resolve())}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.7 Signal B independent temporal replication")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--dev-start", default=INDEPENDENT_START); plan.add_argument("--dev-end", default=INDEPENDENT_END); plan.add_argument("--workers", type=int, default=2); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market")
    run = commands.add_parser("execute")
    run.add_argument("--run-id", required=True); run.add_argument("--state-root", default="state"); run.add_argument("--cache-root", default="data/market")
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
            plan = resource_plan(start, end, args.workers, state_root, cache_root, bridge_url)
            save_plan(plan, state_root)
            print(json.dumps(plan, sort_keys=True))
        else:
            print(json.dumps(execute(args.run_id, state_root, cache_root, bridge_url), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
