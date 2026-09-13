from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from backtest_engine import ENGINE_VERSION
from backtest_engine.cli import choose_symbols, eligible_symbols, jsonl, replay_artifact
from backtest_engine.data import BridgeClient, HistoricalDataStore, atomic_json
from backtest_engine.engine import calculate_net, metrics, run_symbol, stable_digest
from backtest_engine.model import Candle, CostModel, FundingEvent
from research_engine import RESEARCH_ENGINE_VERSION
from research_engine.strategies import ResearchStrategy, STRATEGIES


def chronological_splits(dev_start: int, dev_end: int, oos_start: int, oos_end: int) -> dict[str, Any]:
    if not dev_start < dev_end <= oos_start < oos_end: raise ValueError("windows must be chronological and non-overlapping")
    midpoint = dev_start + (dev_end - dev_start) // 2
    return {
        "development": {"start": dev_start, "end": dev_end},
        "oos": {"start": oos_start, "end": oos_end, "locked": True, "tuning_allowed": False},
        "walk_forward": [
            {"train_start": dev_start, "train_end": midpoint, "validation_start": midpoint, "validation_end": dev_end},
            {"train_start": dev_start, "train_end": dev_end, "validation_start": oos_start, "validation_end": oos_end},
        ],
    }


def apply_costs(trades: list[dict[str, Any]], model: CostModel) -> list[dict[str, Any]]:
    result = []
    for source in trades:
        row = dict(source)
        notional = float(row["normalized_notional"])
        row["entry_fee"] = row["exit_fee"] = notional * model.taker_bps / 10_000
        row["spread_cost"] = notional * model.spread_bps / 10_000
        row["slippage_cost"] = notional * model.slippage_bps / 10_000
        row["net_pnl"] = calculate_net(float(row["gross_pnl"]), row["entry_fee"], row["exit_fee"], float(row["funding_cost"]), row["spread_cost"], row["slippage_cost"])
        row["net_return"] = row["net_pnl"] / notional
        row["cost_model_version"] = model.version
        result.append(row)
    return result


def cost_stress(trades: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "BASE": CostModel(),
        "HIGHER_FEE_50": CostModel("stress-fee-150-v1", 6, 2, 1),
        "HIGHER_SPREAD_50": CostModel("stress-spread-150-v1", 4, 3, 1),
        "HIGHER_SLIPPAGE_50": CostModel("stress-slippage-150-v1", 4, 2, 1.5),
    }
    return {name: {"model": asdict(model), "metrics": metrics(apply_costs(trades, model))} for name, model in scenarios.items()}


def symbol_breadth(symbol_metrics: list[dict[str, Any]], research_months: float = 1.0) -> dict[str, Any]:
    pnls = sorted((float(item["net_pnl"]), item["symbol"]) for item in symbol_metrics)
    positive = sorted((value for value in pnls if value[0] > 0), reverse=True)
    total_profit = sum(value for value, _ in positive)
    trades = [int(item["trade_count"]) for item in symbol_metrics]
    return {
        "profitable_symbol_count": len(positive), "losing_symbol_count": sum(value < 0 for value, _ in pnls),
        "top_symbol_pnl_share": positive[0][0] / total_profit if total_profit else 0.0,
        "top_5_symbol_pnl_share": sum(value for value, _ in positive[:5]) / total_profit if total_profit else 0.0,
        "trades_per_symbol": sum(trades) / len(trades) if trades else 0.0,
        "median_trades_per_symbol": median(trades) if trades else 0.0,
        "trades_per_month": sum(trades) / max(research_months, 1 / 30),
    }


def stability_score(expectancies: list[float]) -> float:
    if not expectancies: return 0.0
    scale = max(1.0, abs(expectancies[len(expectancies) // 2]))
    return round(max(0.0, 100 * (1 - (max(expectancies) - min(expectancies)) / scale)), 2)


def robustness(dev: dict[str, Any], oos: dict[str, Any], folds: list[dict[str, Any]], stability: float, breadth: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    components = {
        "oos_expectancy": 100 if oos["expectancy"] > 0 else 0,
        "walk_forward_consistency": 100 * sum(fold["metrics"]["expectancy"] > 0 for fold in folds) / len(folds),
        "profit_factor": min(100, max(0, oos["profit_factor"] / 1.5 * 100)),
        "drawdown": max(0, 100 - oos["max_drawdown"] * 4),
        "sample_size": min(100, oos["trade_count"] / 30 * 100),
        "parameter_stability": stability,
        "symbol_breadth": 100 * breadth["profitable_symbol_count"] / max(1, breadth["profitable_symbol_count"] + breadth["losing_symbol_count"]),
        "cost_survival": 100 * sum(value["metrics"]["expectancy"] > 0 for value in stress.values()) / len(stress),
    }
    weights = {"oos_expectancy": .20, "walk_forward_consistency": .15, "profit_factor": .10, "drawdown": .10, "sample_size": .10, "parameter_stability": .10, "symbol_breadth": .10, "cost_survival": .15}
    return {"score": round(sum(components[key] * weights[key] for key in weights), 2), "components": components, "weights": weights}


def rejection_reasons(dev: dict[str, Any], oos: dict[str, Any], folds: list[dict[str, Any]], stability: float, breadth: dict[str, Any], stress: dict[str, Any]) -> list[str]:
    reasons = []
    if dev["expectancy"] <= 0: reasons.append("NEGATIVE_EXPECTANCY")
    if dev["profit_factor"] < 1.1: reasons.append("PF_BELOW_THRESHOLD")
    if dev["max_drawdown"] > 25: reasons.append("MAX_DD_TOO_HIGH")
    if dev["trade_count"] < 20: reasons.append("INSUFFICIENT_TRADES")
    if oos["expectancy"] <= 0 or oos["profit_factor"] < 1.1: reasons.append("OOS_FAILED")
    if any(fold["metrics"]["expectancy"] <= 0 for fold in folds): reasons.append("WALK_FORWARD_FAILED")
    if stability < 60: reasons.append("PARAMETER_FRAGILE")
    if any(value["metrics"]["expectancy"] <= 0 for value in stress.values()): reasons.append("COST_FRAGILE")
    if breadth["top_symbol_pnl_share"] > .60: reasons.append("SYMBOL_CONCENTRATION")
    if dev["LONG"]["trade_count"] and dev["LONG"]["expectancy"] <= 0: reasons.append("LONG_FAILED")
    if dev["SHORT"]["trade_count"] and dev["SHORT"]["expectancy"] <= 0: reasons.append("SHORT_FAILED")
    return list(dict.fromkeys(reasons))


def dashboard_metrics(value: dict[str, Any]) -> dict[str, Any]:
    notional = max(1, value["trade_count"]) * 1_000
    return {
        "grossReturnPct": value["gross_return"], "netReturnPct": value["net_return"], "winRatePct": value["win_rate"], "expectancyR": value["expectancy_R"],
        "profitFactor": value["profit_factor"], "maxDrawdownPct": value["max_drawdown"], "tradeCount": value["trade_count"],
        "feesUsd": value["fees_total"], "feesBps": value["fees_total"] / notional * 10_000, "fundingUsd": value["funding_total"], "fundingBps": value["funding_total"] / notional * 10_000,
        "spreadUsd": value["spread_total"], "spreadBps": value["spread_total"] / notional * 10_000, "slippageUsd": value["slippage_total"], "slippageBps": value["slippage_total"] / notional * 10_000,
        "long": {"trades": value["LONG"]["trade_count"], "netReturnPct": value["LONG"]["net_return"], "profitFactor": value["LONG"]["profit_factor"]},
        "short": {"trades": value["SHORT"]["trade_count"], "netReturnPct": value["SHORT"]["net_return"], "profitFactor": value["SHORT"]["profit_factor"]},
    }


def evaluate(strategy: ResearchStrategy, run_id: str, symbols: list[str], datasets: dict[str, dict[str, Any]], start: int, end: int, cost: CostModel | None = None) -> dict[str, Any]:
    results = []
    for symbol in symbols:
        data = datasets[symbol]
        results.append(run_symbol(run_id, symbol, data["candles"], data["funding"], data["dataset_version"], cost or CostModel(), start, end, strategy))
    trades = [trade for result in results for trade in result["trades"]]
    return {"metrics": metrics(trades), "trades": trades, "results": results, "symbol_metrics": [{"symbol": result["symbol"], **metrics(result["trades"])} for result in results]}


def rank_research(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (-item["score"], item["strategy"]))


def verify_immutable_run(manifest_path: Path, identity_hash: str) -> bool:
    """Return True for an identical completed run; reject an ID collision."""
    if not manifest_path.exists(): return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("identity_hash") != identity_hash: raise ValueError("immutable research run ID collision")
    return True


def load_datasets(symbols: list[str], start: int, end: int, cache_root: Path, bridge_url: str, workers: int) -> dict[str, dict[str, Any]]:
    def load(symbol: str) -> tuple[str, dict[str, Any]]:
        store = HistoricalDataStore(cache_root, BridgeClient(bridge_url))
        candles, manifests = store.candles(symbol, "5m", start - 3 * 86_400_000, end)
        funding = store.funding(symbol, start, end)
        return symbol, {"candles": candles, "funding": funding, "dataset_version": stable_digest([item["dataset_id"] for item in manifests])}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(load, symbols))


def run_research(args: Any) -> dict[str, Any]:
    dev_start, dev_end, oos_start, oos_end = map(args.parse_time, (args.dev_start, args.dev_end, args.oos_start, args.oos_end))
    splits = chronological_splits(dev_start, dev_end, oos_start, oos_end)
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    bridge = BridgeClient(bridge_url)
    eligible, exclusions = eligible_symbols(bridge.universe(), dev_start, oos_end)
    requested = choose_symbols(eligible, args.symbols, False, args.verify_set)
    strategies = list(STRATEGIES)
    identity = {"engine": RESEARCH_ENGINE_VERSION, "strategies": [(item.strategy_id, item.strategy_version, item.threshold) for item in strategies], "symbols": requested, "splits": splits}
    identity_hash = stable_digest(identity)
    run_id = args.run_id or f"research_{stable_digest(identity)[:16]}"
    run_root = Path(args.state_root) / "research-runs" / run_id
    manifest_path = run_root / "manifest.json"
    if verify_immutable_run(manifest_path, identity_hash):
        return {"run_id": run_id, "status": "ALREADY_COMPLETED", "artifact": str(run_root.resolve())}
    started = datetime.now(UTC)
    run_root.mkdir(parents=True, exist_ok=True)
    identity_path, checkpoint_path = run_root / "identity.json", run_root / "checkpoint.json"
    if not verify_immutable_run(identity_path, identity_hash): atomic_json(identity_path, {"identity_hash": identity_hash, "identity": identity})
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"identity_hash": identity_hash, "completed": {}}
    if checkpoint.get("identity_hash") != identity_hash: raise ValueError("immutable research checkpoint identity mismatch")
    completed: dict[str, dict[str, Any]] = checkpoint["completed"]
    if not (run_root / "research-run.json").exists(): atomic_json(run_root / "research-run.json", {"runId": run_id, "status": "RUNNING", "phase": "FAST_BACKTEST", "processed": len(completed), "total": len(strategies), "currentStrategy": strategies[min(len(completed), len(strategies) - 1)].strategy_id, "currentSymbol": requested[0], "startedAt": started.isoformat(), "elapsed": "0:00:00", "eta": None, "symbols": requested})
    datasets = load_datasets(requested, dev_start, oos_end, Path(args.cache_root), bridge_url, args.workers)
    rankings = []
    for index, strategy in enumerate(strategies, 1):
        version_id = f"{strategy.strategy_id}_{strategy.strategy_version}"
        if version_id in completed:
            rankings.append(completed[version_id])
            continue
        artifact = Path(args.state_root) / "research" / version_id / run_id
        dev = evaluate(strategy, f"{run_id}:{version_id}:DEV", requested, datasets, dev_start, dev_end)
        oos = evaluate(strategy, f"{run_id}:{version_id}:OOS", requested, datasets, oos_start, oos_end)
        folds = []
        for fold_index, fold in enumerate(splits["walk_forward"], 1):
            value = evaluate(strategy, f"{run_id}:{version_id}:WF{fold_index}", requested, datasets, fold["validation_start"], fold["validation_end"])
            folds.append({**fold, "metrics": value["metrics"]})
        neighbors = []
        for multiplier in (.9, 1.0, 1.1):
            value = dev if multiplier == 1.0 else evaluate(strategy.neighbor(multiplier), f"{run_id}:{version_id}:N{multiplier}", requested, datasets, dev_start, dev_end)
            neighbors.append({"multiplier": multiplier, "parameter": strategy.threshold * multiplier, "expectancy": value["metrics"]["expectancy"]})
        stability = stability_score([item["expectancy"] for item in neighbors])
        stress = cost_stress(dev["trades"])
        breadth = symbol_breadth(dev["symbol_metrics"], (dev_end - dev_start) / 2_592_000_000)
        robust = robustness(dev["metrics"], oos["metrics"], folds, stability, breadth, stress)
        reasons = rejection_reasons(dev["metrics"], oos["metrics"], folds, stability, breadth, stress)
        stage = "RESEARCH_READY" if not reasons and robust["score"] >= 60 else "RESEARCH_REJECTED"
        direction = "BOTH_VALID" if dev["metrics"]["LONG"]["expectancy"] > 0 and dev["metrics"]["SHORT"]["expectancy"] > 0 else "LONG_ONLY_VALID" if dev["metrics"]["LONG"]["expectancy"] > 0 else "SHORT_ONLY_VALID" if dev["metrics"]["SHORT"]["expectancy"] > 0 else "NOT_VALID"
        config_hash = stable_digest(asdict(strategy))
        dataset_version = stable_digest(sorted(data["dataset_version"] for data in datasets.values()))
        manifest = {"research_run_id": run_id, "strategy_id": strategy.strategy_id, "strategy_version": strategy.strategy_version, "family": strategy.family, "hypothesis": strategy.hypothesis, "mandatory_conditions": strategy.mandatory, "wait_condition": strategy.wait_condition, "rejected_condition": strategy.rejected_condition, "parameters": {"threshold": strategy.threshold, "risk_multiplier": strategy.risk_multiplier, "reward_risk": strategy.reward_risk}, "config_hash": config_hash, "code_commit": "WORKSPACE_NO_GIT", "dataset_version": dataset_version, "engine_version": ENGINE_VERSION, "research_engine_version": RESEARCH_ENGINE_VERSION, "cost_model_version": CostModel().version, "execution_model_version": "next-open-market-v1", "cost_provenance": {"fees": "CONFIGURED", "funding": "OBSERVED", "spread": "MODELED", "slippage": "MODELED"}, "splits": splits, "selection_method": "SEVEN_PREDECLARED_HYPOTHESES_NO_OOS_TUNING", "universe_selection": "DYNAMIC_LIQUIDITY_STRATIFIED" if args.verify_set else "EXPLICIT_ELIGIBILITY_VALIDATED", "hypothesis_count": len(strategies), "variant_count": len(strategies), "universe_snapshot": requested, "lifecycle_gates": {"FAST_BACKTEST": "PASSED" if dev["metrics"]["expectancy"] > 0 else "FAILED", "OOS": "PASSED" if oos["metrics"]["expectancy"] > 0 else "FAILED", "WALK_FORWARD": "PASSED" if all(fold["metrics"]["expectancy"] > 0 for fold in folds) else "FAILED", "ROBUSTNESS": "PASSED" if not reasons and robust["score"] >= 60 else "FAILED"}, "status": stage, "created_at": datetime.now(UTC).isoformat()}
        replay_result = next((result for result in dev["results"] if result["trades"]), None)
        replay = replay_artifact(f"{run_id}-{version_id}", replay_result) if replay_result else None
        atomic_json(artifact / "manifest.json", manifest); atomic_json(artifact / "dev-summary.json", dev["metrics"]); atomic_json(artifact / "oos-summary.json", oos["metrics"])
        atomic_json(artifact / "walk-forward.json", folds); atomic_json(artifact / "robustness.json", {**robust, "parameter_neighborhood": neighbors, "parameter_stability": stability, "symbol_breadth": breadth})
        atomic_json(artifact / "cost-stress.json", stress); atomic_json(artifact / "symbol-metrics.json", dev["symbol_metrics"]); jsonl(artifact / "trades" / "dev.jsonl", dev["trades"]); jsonl(artifact / "trades" / "oos.jsonl", oos["trades"])
        jsonl(artifact / "decisions" / "dev.jsonl", [event for result in dev["results"] for event in result["events"]])
        atomic_json(artifact / "rejection-reasons.json", reasons); atomic_json(artifact / "replay-links.json", [] if not replay else [{"runId": replay["runId"], "strategyId": strategy.strategy_id, "strategyVersion": strategy.strategy_version, "symbol": replay["symbol"], "tradeId": replay_result["trades"][0]["trade_id"], "phase": "DEVELOPMENT", "datasetVersion": dataset_version}])
        if replay: atomic_json(artifact / "replay.json", {**replay, "evaluationStartTimestamp": dev_start // 1000})
        strategy_json = {"source": "RESEARCH_CANDIDATE" if stage == "RESEARCH_READY" else "RESEARCH_REJECTED", "researchRunId": run_id, "strategyId": strategy.strategy_id, "strategyVersion": strategy.strategy_version, "name": strategy.label, "family": strategy.family, "configHash": config_hash[:12], "codeCommit": "NO_GIT", "datasetVersion": dataset_version[:16], "feeModelVersion": CostModel().version, "profile": {"id": "INTRADAY", "label": "Intraday", "timeframes": [{"timeframe": "1D", "responsibility": "Bias / Market Context"}, {"timeframe": "1H", "responsibility": "Structure / Setup"}, {"timeframe": "5M", "responsibility": "Entry / Execution"}]}, "directionSupport": "BOTH", "directionValidity": direction, "lifecycle": {"stage": stage, "backtest": "PASSED" if dev["metrics"]["expectancy"] > 0 else "FAILED", "oos": "PASSED" if oos["metrics"]["expectancy"] > 0 else "FAILED", "walkForward": "PASSED" if all(fold["metrics"]["expectancy"] > 0 for fold in folds) else "FAILED", "shadow": "NOT_STARTED", "canary": "NOT_STARTED", "real": "NOT_STARTED"}, "metrics": dashboard_metrics(dev["metrics"]), "robustnessScore": robust["score"], "devExpectancy": dev["metrics"]["expectancy"], "oosExpectancy": oos["metrics"]["expectancy"], "walkForwardExpectancy": sum(fold["metrics"]["expectancy"] for fold in folds) / len(folds), "rejectionReasons": reasons, "replayRunId": replay["runId"] if replay else None}
        atomic_json(artifact / "strategy.json", strategy_json)
        rankings.append({"strategy": version_id, "stage": stage, "score": robust["score"], "dev": dev["metrics"], "oos": oos["metrics"], "walk_forward": folds, "cost_stress": {key: value["metrics"]["expectancy"] for key, value in stress.items()}, "rejection_reasons": reasons, "artifact": str(artifact.resolve())})
        completed[version_id] = rankings[-1]
        atomic_json(checkpoint_path, {"identity_hash": identity_hash, "completed": completed})
        elapsed = datetime.now(UTC) - started
        atomic_json(run_root / "research-run.json", {"runId": run_id, "status": "RUNNING" if index < len(strategies) else "COMPLETED", "phase": "ROBUSTNESS", "processed": index, "total": len(strategies), "currentStrategy": strategy.strategy_id, "currentVersion": strategy.strategy_version, "currentSymbol": requested[-1], "currentMetrics": {"netExpectancy": dev["metrics"]["expectancy"], "profitFactor": dev["metrics"]["profit_factor"], "tradeCount": dev["metrics"]["trade_count"], "robustnessScore": robust["score"]}, "startedAt": started.isoformat(), "elapsed": str(elapsed).split(".")[0], "eta": str(elapsed / index * (len(strategies) - index)).split(".")[0], "symbols": requested})
    rankings = rank_research(rankings)
    completed_at = datetime.now(UTC)
    run_manifest = {"research_run_id": run_id, "identity_hash": identity_hash, "status": "COMPLETED", "strategy_versions": [item["strategy"] for item in rankings], "universe_snapshot": requested, "universe_selection": "DYNAMIC_LIQUIDITY_STRATIFIED" if args.verify_set else "EXPLICIT_ELIGIBILITY_VALIDATED", "universe_exclusion_count": len(exclusions), "dev_window": splits["development"], "oos_window": splits["oos"], "walk_forward_windows": splits["walk_forward"], "cost_model": asdict(CostModel()), "engine_version": ENGINE_VERSION, "research_engine_version": RESEARCH_ENGINE_VERSION, "started_at": started.isoformat(), "completed_at": completed_at.isoformat(), "expected_jobs": len(strategies) * len(requested) * 6, "selection_method": "PREDECLARED_HYPOTHESES_RANKED_BY_ROBUSTNESS_NOT_RETURN"}
    atomic_json(run_root / "ranking.json", rankings); atomic_json(manifest_path, run_manifest)
    return {"run_id": run_id, "status": "COMPLETED", "strategies": len(strategies), "symbols": requested, "expected_jobs": run_manifest["expected_jobs"], "ranking": rankings, "artifact": str(run_root.resolve())}
