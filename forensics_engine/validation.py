from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backtest_engine.cli import jsonl, replay_artifact
from backtest_engine.data import atomic_json
from backtest_engine.engine import stable_digest
from backtest_engine.model import CostModel
from research_engine.refinements import HYPOTHESES, VARIANTS
from research_engine.research import cost_stress, evaluate, load_datasets, symbol_breadth


def development_gates(summary: dict[str, Any], stress: dict[str, Any], breadth: dict[str, Any]) -> dict[str, bool]:
    return {"POSITIVE_NET_EXPECTANCY": summary["expectancy"] > 0, "PF_AT_LEAST_1_1": summary["profit_factor"] >= 1.1, "MAX_DD_AT_MOST_25": summary["max_drawdown"] <= 25, "AT_LEAST_20_TRADES": summary["trade_count"] >= 20, "NO_EXTREME_CONCENTRATION": breadth["top_symbol_pnl_share"] <= .60, "COST_SURVIVAL": all(item["metrics"]["expectancy"] > 0 for item in stress.values())}


def run_development_validation(research_run_id: str, state_root: Path = Path("state"), cache_root: Path = Path("data/market")) -> dict[str, Any]:
    source = json.loads((state_root / "research-runs" / research_run_id / "manifest.json").read_text(encoding="utf-8"))
    start, end, symbols = source["dev_window"]["start"], source["dev_window"]["end"], source["universe_snapshot"]
    datasets = load_datasets(symbols, start, end, cache_root, os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766"), 3)
    results = []
    for variant in VARIANTS:
        version_id = f"{variant.strategy_id}_{variant.strategy_version}"
        identity = {"strategy": asdict(variant), "source_run": research_run_id, "development": {"start": start, "end": end}, "symbols": symbols, "cost": asdict(CostModel())}
        validation_id = f"d4_1_dev_{stable_digest(identity)[:16]}"
        output = state_root / "research" / version_id / validation_id
        manifest_path = output / "manifest.json"
        identity_hash = stable_digest(identity)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["identity_hash"] != identity_hash: raise ValueError(f"immutable Development artifact collision: {output}")
            results.append({"strategy": version_id, "status": "ALREADY_COMPLETED", "passed": manifest["passed"], "artifact": str(output.resolve())})
            continue
        evaluated = evaluate(variant, f"{validation_id}:{version_id}:DEV", symbols, datasets, start, end)
        stress = cost_stress(evaluated["trades"])
        breadth = symbol_breadth(evaluated["symbol_metrics"], (end - start) / 2_592_000_000)
        gates = development_gates(evaluated["metrics"], stress, breadth)
        passed = all(gates.values())
        manifest = {"identity_hash": identity_hash, "validation_id": validation_id, "phase": "DEVELOPMENT_ONLY", "source_research_run_id": research_run_id, "strategy_id": variant.strategy_id, "strategy_version": variant.strategy_version, "hypothesis": HYPOTHESES[version_id], "config_hash": stable_digest(asdict(variant)), "dataset_version": stable_digest(sorted(item["dataset_version"] for item in datasets.values())), "engine_version": "d3-backtest-v1", "cost_model_version": CostModel().version, "execution_model_version": "next-open-market-v1", "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * 86_400_000, "locked_oos_read": False, "symbols": symbols, "gates": gates, "passed": passed, "status": "DEV_PASSED" if passed else "RESEARCH_REJECTED"}
        output.mkdir(parents=True, exist_ok=True)
        atomic_json(manifest_path, manifest); atomic_json(output / "dev-summary.json", evaluated["metrics"]); atomic_json(output / "cost-stress.json", stress); atomic_json(output / "symbol-metrics.json", evaluated["symbol_metrics"]); atomic_json(output / "symbol-breadth.json", breadth); jsonl(output / "trades" / "dev.jsonl", evaluated["trades"])
        replay_result = next((item for item in evaluated["results"] if item["trades"]), None)
        if replay_result:
            replay = replay_artifact(f"{validation_id}-{version_id}", replay_result)
            if replay: atomic_json(output / "replay.json", {**replay, "evaluationStartTimestamp": start // 1000})
        results.append({"strategy": version_id, "status": "COMPLETED", "passed": passed, "metrics": evaluated["metrics"], "gates": gates, "artifact": str(output.resolve())})
    return {"source_research_run_id": research_run_id, "phase": "DEVELOPMENT_ONLY", "locked_oos_read": False, "results": results}
