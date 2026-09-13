from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from backtest_engine.data import atomic_json
from backtest_engine.engine import metrics, resample_closed, stable_digest
from forensics_engine.analysis import DAY_MS, atomic_text, feature_row, grouped, read_jsonl
from forensics_engine.expansion import chronological_segments, expanded_breadth
from research_engine.research import cost_stress, load_datasets


ENGINE_VERSION = "d4.3-accounting-regime-audit-v1"
STARTING_EQUITY = 10_000.0


def reference_equity(trades: list[dict[str, Any]], starting_equity: float = STARTING_EQUITY) -> dict[str, Any]:
    if starting_equity <= 0: raise ValueError("starting equity must be positive")
    equity = peak = starting_equity
    max_drawdown = 0.0
    peak_time = trough_time = current_peak_time = None
    points = [{"timestamp": None, "trade_id": None, "equity": starting_equity, "realized_pnl": 0.0}]
    skipped = 0
    for trade in sorted(trades, key=lambda item: (int(item.get("exit_time", 0)), str(item.get("trade_id", "")))):
        if equity <= 0:
            skipped += 1
            continue
        previous = equity
        equity = max(0.0, equity + float(trade["net_pnl"]))
        points.append({"timestamp": int(trade.get("exit_time", 0)), "trade_id": trade.get("trade_id"), "equity": equity, "realized_pnl": equity - previous})
        if equity >= peak:
            peak = equity
            current_peak_time = int(trade.get("exit_time", 0))
        drawdown = (peak - equity) / peak * 100 if peak else 100.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            peak_time = current_peak_time
            trough_time = int(trade.get("exit_time", 0))
    aggregate_return = sum(float(trade.get("net_return", 0)) for trade in trades) * 100
    return {"return_metric_type": "REFERENCE_PORTFOLIO_EQUITY_RETURN", "drawdown_metric_type": "PEAK_TO_SUBSEQUENT_TROUGH_EQUITY_PERCENT", "capital_model": "RESEARCH_REFERENCE_FIXED_NOTIONAL_REALIZED_AT_EXIT", "starting_equity": starting_equity, "ending_equity": equity, "portfolio_equity_return_pct": (equity / starting_equity - 1) * 100, "portfolio_max_drawdown_pct": min(100.0, max_drawdown), "position_notional_model": "FIXED_NORMALIZED_1000_USD_PER_TRADE", "compounding": False, "capital_reservation_or_margin_simulation": False, "bankruptcy_behavior": "FLOOR_AT_ZERO_AND_STOP_APPLYING_SUBSEQUENT_TRADES", "bankrupt": equity == 0, "skipped_after_bankruptcy": skipped, "aggregate_normalized_net_return_pct": aggregate_return, "aggregate_fixed_notional_pnl": sum(float(trade["net_pnl"]) for trade in trades), "drawdown_peak_timestamp": peak_time, "drawdown_trough_timestamp": trough_time, "equity_curve": points}


def temporal_slice(trades: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    rows = []
    for segment in chronological_segments(start, end):
        subset = [trade for trade in trades if int(segment["start"]) <= int(trade["signal_time"]) < int(segment["end"])]
        rows.append({**segment, "metrics": metrics(subset)})
    positive = [max(0.0, float(row["metrics"]["net_pnl"])) for row in rows]
    total = sum(positive)
    max_share = max(positive) / total if total else 0.0
    return {"segments": rows, "positive_segment_count": sum(float(row["metrics"]["expectancy"]) > 0 for row in rows), "max_positive_pnl_segment_share": max_share, "flag": "TEMPORAL_CONCENTRATION" if max_share > .60 else "BROADLY_DISTRIBUTED"}


def hypothesis_decision(evidence: dict[str, Any]) -> dict[str, Any]:
    summary, breadth, temporal, stress = evidence["metrics"], evidence["symbol_breadth"], evidence["temporal_stability"], evidence["cost_stress"]
    gates = {"POSITIVE_NET_EXPECTANCY": summary["expectancy"] > 0, "PF_ABOVE_1": summary["profit_factor"] > 1, "SUFFICIENT_SAMPLE": summary["trade_count"] >= 20, "MORE_THAN_ONE_PROFITABLE_SYMBOL": breadth["profitable_symbol_count"] > 1, "NO_EXTREME_CONCENTRATION": breadth["top_symbol_pnl_share"] <= .60, "TEMPORALLY_DISTRIBUTED": temporal["positive_segment_count"] > 1 and temporal["max_positive_pnl_segment_share"] <= .60, "REGIME_IDENTIFIABLE_EX_ANTE": evidence["ex_ante_proof"]["all_observations_available_by_signal"], "BASE_COST_EDGE_MEANINGFUL": summary["expectancy"] > 0, "COST_SURVIVAL": all(value["metrics"]["expectancy"] > 0 for value in stress.values()), "NO_PARAMETER_SEARCH": True}
    justified = all(gates.values())
    return {"gates": gates, "justified": justified, "decision": "BREAKOUT_RETEST_V3_JUSTIFIED" if justified else "REGIME_HYPOTHESIS_NOT_JUSTIFIED", "v3_created": False, "oos_access": "OOS_NOT_ACCESSED"}


def run_audit(d4_2_run_id: str, state_root: Path = Path("state"), cache_root: Path = Path("data/market"), starting_equity: float = STARTING_EQUITY) -> dict[str, Any]:
    run_root = state_root / "research-runs" / d4_2_run_id
    run = json.loads((run_root / "expansion-run.json").read_text(encoding="utf-8"))
    plan = json.loads((run_root / "resource-plan.json").read_text(encoding="utf-8"))
    sources = {item["strategy"]: Path(item["artifact"]) for item in run["candidates"]}
    source_hashes = {name: {"manifest": stable_digest(json.loads((root / "manifest.json").read_text(encoding="utf-8"))), "trades": stable_digest(read_jsonl(root / "trades" / "dev.jsonl"))} for name, root in sources.items()}
    identity = {"engine": ENGINE_VERSION, "source_run": d4_2_run_id, "source_hashes": source_hashes, "starting_equity": starting_equity}
    audit_id = f"d4_3_{stable_digest(identity)[:16]}"
    output = state_root / "accounting-audit" / audit_id
    audit_path = output / "accounting-audit.json"
    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding="utf-8"))
        if existing["identity_hash"] != stable_digest(identity): raise ValueError("immutable D4.3 accounting artifact collision")
        return {"audit_id": audit_id, "status": "ALREADY_COMPLETED", "artifact": str(output.resolve()), "decision": existing["breakout_regime_decision"]}

    accounting = {}
    drawdowns = {}
    for version, root in sources.items():
        trades = read_jsonl(root / "trades" / "dev.jsonl")
        old = metrics(trades)
        equity = reference_equity(trades, starting_equity)
        accounting[version] = equity
        drawdowns[version] = {"legacy_field": "max_drawdown", "legacy_value_pct_of_one_normalized_notional": old["max_drawdown"], "corrected_field": "portfolio_max_drawdown_pct", "corrected_value": equity["portfolio_max_drawdown_pct"], "formula": "max((peak_equity - subsequent_equity) / peak_equity) * 100", "bounded_at_100": equity["portfolio_max_drawdown_pct"] <= 100}

    start, end, symbols = plan["development_window"]["start"], plan["development_window"]["end"], plan["symbols"]
    datasets = load_datasets(symbols, start, end, cache_root, os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766"), min(3, int(plan["worker_count"])))
    tiers = {item["symbol"]: item for item in plan["universe_snapshot"]}
    breakout_trades = read_jsonl(sources["BREAKOUT_RETEST_V2"] / "trades" / "dev.jsonl")
    features = []
    for trade in breakout_trades:
        candles = datasets[trade["symbol"]]["candles"]
        tier = tiers[trade["symbol"]]
        features.append(feature_row(trade, candles, resample_closed(candles, 3_600_000), resample_closed(candles, DAY_MS), {"tier": tier["tier"], "onboard_date": tier["onboard_date"]}, start))
    selected = [row for row in features if row["volatility_regime"] == "HIGH_VOLATILITY" and row["range_phase"] == "EXPANSION"]
    symbol_metrics = [{"symbol": symbol, **metrics([row for row in selected if row["symbol"] == symbol])} for symbol in symbols]
    stress = cost_stress(selected)
    evidence = {"source_strategy": "BREAKOUT_RETEST_V2", "slice": "HIGH_VOLATILITY_AND_EXPANSION", "regime_definition": {"timeframe": "1H", "observation": "latest fully closed 1H high-low range divided by median high-low range of up to 24 preceding closed 1H bars", "threshold": ">= 1.25", "threshold_provenance": "PRE_EXISTING_D4_1_D4_2_DEFINITION_NOT_SEARCHED", "future_data_used": False}, "metrics": metrics(selected), "reference_equity": reference_equity(selected, starting_equity), "symbol_metrics": symbol_metrics, "symbol_breadth": expanded_breadth(symbol_metrics, (end - start) / (7 * DAY_MS)), "by_tier": grouped(selected, "market_tier"), "temporal_stability": temporal_slice(selected, start, end), "cost_stress": stress, "ex_ante_proof": {"all_observations_available_by_signal": all(row["regime_observed_through"] is not None and int(row["regime_observed_through"]) <= int(row["signal_time"]) for row in selected), "maximum_observation_minus_signal_ms": max((int(row["regime_observed_through"]) - int(row["signal_time"]) for row in selected), default=0)}}
    decision = hypothesis_decision(evidence)
    audit = {"identity_hash": stable_digest(identity), "audit_id": audit_id, "status": "COMPLETED", "source_d4_2_run_id": d4_2_run_id, "engine_version": ENGINE_VERSION, "finding": "SEMANTIC_LABEL_BUG_NOT_TRADE_PNL_FORMULA_BUG", "before": {"net_return": "SUM_OF_PER_TRADE_NORMALIZED_NET_RETURNS", "max_drawdown": "MAX_CUMULATIVE_FIXED_NOTIONAL_PNL_DECLINE_DIVIDED_BY_ONE_1000_USD_TRADE_NOTIONAL", "portfolio_equity_simulated": False}, "after": {"legacy_fields_preserved": True, "aggregate_return_label": "Aggregate Net Return", "legacy_drawdown_label": "Aggregate Fixed-Notional Drawdown", "reference_equity_fields_added": True}, "accounting_provenance": {"return_metric_type": "AGGREGATE_NORMALIZED_TRADE_RETURN_AND_SEPARATE_REFERENCE_PORTFOLIO_EQUITY_RETURN", "drawdown_metric_type": "LEGACY_FIXED_NOTIONAL_DECLINE_AND_SEPARATE_PEAK_TO_TROUGH_EQUITY_DRAWDOWN", "capital_model": "RESEARCH_REFERENCE_FIXED_NOTIONAL_REALIZED_AT_EXIT", "starting_equity": starting_equity, "position_notional_model": "FIXED_NORMALIZED_1000_USD_PER_TRADE", "compounding": False, "bankruptcy_behavior": "FLOOR_AT_ZERO_AND_STOP_APPLYING_SUBSEQUENT_TRADES"}, "breakout_regime_decision": decision["decision"], "v3_created": False, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False}
    semantics = {"aggregate_net_return": {"formula": "sum(trade.net_return) * 100", "may_be_below_minus_100": True, "is_portfolio_equity_return": False}, "aggregate_fixed_notional_drawdown": {"formula": "max peak-to-trough decline in cumulative fixed-notional PnL / 1000 * 100", "may_exceed_100": True, "is_portfolio_equity_drawdown": False}, "reference_portfolio_equity": {key: value for key, value in accounting.items()}}
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(audit_path, audit)
    atomic_json(output / "equity-semantics.json", semantics)
    atomic_json(output / "drawdown-audit.json", drawdowns)
    atomic_json(output / "breakout-regime-forensics.json", {**evidence, "hypothesis_decision": decision, "oos_access": "OOS_NOT_ACCESSED"})
    report = ["# D4.3 Accounting and Breakout Regime Audit", "", "The prior `net_return` is aggregate normalized trade return, not portfolio equity return. The prior `max_drawdown` is a cumulative fixed-notional PnL decline normalized by one $1,000 trade, not standard equity drawdown. Values beyond 100% are therefore mathematically possible but were misleadingly named.", "", f"The research-only $10,000 reference equity applies fixed $1,000 trade PnL chronologically at exit, does not compound or model margin reservation, floors equity at zero, and stops applying later trades after bankruptcy.", "", f"BREAKOUT_RETEST_V2 high-volatility/expansion: {evidence['metrics']['trade_count']} trades, expectancy {evidence['metrics']['expectancy']:.4f}, PF {evidence['metrics']['profit_factor']:.4f}, {evidence['symbol_breadth']['profitable_symbol_count']} profitable symbols, top-symbol share {evidence['symbol_breadth']['top_symbol_pnl_share']:.1%}.", "", f"Decision: `{decision['decision']}`. V3 was not created. Locked OOS was not accessed.", ""]
    atomic_text(output / "accounting-report.md", "\n".join(report))
    return {"audit_id": audit_id, "status": "COMPLETED", "artifact": str(output.resolve()), "decision": decision["decision"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Trading Sentinel V4 D4.3 accounting and breakout regime audit")
    parser.add_argument("--d4-2-run", required=True); parser.add_argument("--state-root", default="state"); parser.add_argument("--cache-root", default="data/market"); parser.add_argument("--starting-equity", type=float, default=STARTING_EQUITY)
    args = parser.parse_args()
    try:
        print(json.dumps(run_audit(args.d4_2_run, Path(args.state_root), Path(args.cache_root), args.starting_equity), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
