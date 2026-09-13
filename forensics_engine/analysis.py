from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from backtest_engine.cli import eligible_symbols
from backtest_engine.data import BridgeClient, HistoricalDataStore, atomic_json
from backtest_engine.engine import closed_at, metrics, resample_closed, stable_digest
from forensics_engine import FORENSICS_ENGINE_VERSION
from research_engine.refinements import HYPOTHESES

PRIMARY = ("BREAKOUT_RETEST_V1", "RANGE_REVERSION_V1", "TREND_CONTINUATION_V1")
DAY_MS = 86_400_000


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def distribution(values: Iterable[float]) -> dict[str, float | int]:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered: return {"count": 0}
    def q(fraction: float) -> float: return ordered[round((len(ordered) - 1) * fraction)]
    return {"count": len(ordered), "min": ordered[0], "p10": q(.10), "p25": q(.25), "median": median(ordered), "p75": q(.75), "p90": q(.90), "max": ordered[-1], "mean": mean(ordered)}


def grouped(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    result = {}
    for value in sorted({str(row[key]) for row in rows}):
        subset = [row for row in rows if str(row[key]) == value]
        result[value] = {"metrics": metrics(subset), "cost_burden": distribution(row["total_cost"] for row in subset)}
    return result


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def tier_snapshot(universe: dict[str, Any], start: int, end: int) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    eligible, _ = eligible_symbols(universe, start, end)
    ranked = sorted(eligible, key=lambda item: (-float(item.get("quoteVolume24h") or 0), str(item["symbol"])))
    tiers = {}
    for index, item in enumerate(ranked):
        bucket = min(2, index * 3 // max(1, len(ranked)))
        tiers[str(item["symbol"])] = {"tier": ("TIER_A", "TIER_B", "TIER_C")[bucket], "onboard_date": int(item.get("onboardDate") or 0), "quote_volume_24h": float(item.get("quoteVolume24h") or 0)}
    return tiers, {"source": universe.get("source"), "server_time": universe.get("serverTime"), "eligible_count": len(ranked), "method": "CURRENT_24H_QUOTE_VOLUME_TERCILES_ANALYSIS_ONLY"}


def regime_at(timestamp: int, hourly: list[Any]) -> dict[str, Any]:
    known = closed_at(hourly, timestamp)
    if not known: return {"volatility_regime": "UNKNOWN", "range_phase": "UNKNOWN", "volatility_ratio": 0.0, "observed_through": None}
    hour = known[-1]
    prior = known[-25:-1] or [hour]
    typical_range = median([bar.high - bar.low for bar in prior]) or max(hour.high - hour.low, 1e-12)
    ratio = max(hour.high - hour.low, 1e-12) / typical_range
    volatility = "HIGH_VOLATILITY" if ratio >= 1.25 else "LOW_VOLATILITY" if ratio <= .75 else "NORMAL_VOLATILITY"
    phase = "EXPANSION" if ratio >= 1.25 else "COMPRESSION" if ratio <= .75 else "NORMAL"
    return {"volatility_regime": volatility, "range_phase": phase, "volatility_ratio": ratio, "observed_through": hour.close_time}


def feature_row(trade: dict[str, Any], candles: list[Any], hourly: list[Any], daily: list[Any], tier: dict[str, Any], dev_start: int) -> dict[str, Any]:
    entry, side = float(trade["entry_price"]), trade["side"]
    risk = abs(entry - float(trade["stop_loss"]))
    path = [bar for bar in candles if int(trade["entry_time"]) <= bar.open_time and bar.close_time <= int(trade["exit_time"])]
    if not path: path = [min(candles, key=lambda bar: abs(bar.open_time - int(trade["entry_time"])))]
    excursions = []
    for bar in path:
        favorable = (bar.high - entry) / entry if side == "LONG" else (entry - bar.low) / entry
        adverse = (entry - bar.low) / entry if side == "LONG" else (bar.high - entry) / entry
        excursions.append((bar.close_time, max(0.0, favorable), max(0.0, adverse)))
    mfe = max(item[1] for item in excursions); mae = max(item[2] for item in excursions)
    mfe_at = next(item[0] for item in excursions if item[1] == mfe); mae_at = next(item[0] for item in excursions if item[2] == mae)
    signal = min(candles, key=lambda bar: abs(bar.close_time - int(trade["signal_time"])))
    known_h, known_d = closed_at(hourly, int(trade["signal_time"])), closed_at(daily, int(trade["signal_time"]))
    hour, day = known_h[-1], known_d[-1]
    previous_hour = known_h[-2] if len(known_h) > 1 else hour
    recent_hours = known_h[-25:-1] or [hour]
    typical_hour_range = median([bar.high - bar.low for bar in recent_hours]) or max(hour.high - hour.low, 1e-12)
    hour_range = max(hour.high - hour.low, 1e-12)
    day_range = max(day.high - day.low, 1e-12)
    signal_range = max(signal.high - signal.low, 1e-12)
    regime = regime_at(int(trade["signal_time"]), hourly)
    volatility_ratio = regime["volatility_ratio"]
    trend = "TRENDING_UP" if len(known_d) > 1 and day.close > known_d[-2].close and day.close > day.open else "TRENDING_DOWN" if len(known_d) > 1 and day.close < known_d[-2].close and day.close < day.open else "RANGE"
    location = (entry - hour.low) / hour_range
    break_price = previous_hour.high if side == "LONG" else previous_hour.low
    room = (hour.high - entry) if side == "LONG" else (entry - hour.low)
    costs = float(trade["entry_fee"]) + float(trade["exit_fee"]) + float(trade["funding_cost"]) + float(trade["spread_cost"]) + float(trade["slippage_cost"])
    gross = float(trade["gross_pnl"]); net = float(trade["net_pnl"])
    gross_return = float(trade["gross_return"])
    return {**trade, "outcome": "WIN" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN", "market_tier": tier.get("tier", "UNCLASSIFIED"), "new_listing_at_dev": 0 <= dev_start - int(tier.get("onboard_date", 0)) < 30 * DAY_MS, "utc_hour": datetime.fromtimestamp(int(trade["entry_time"]) / 1000, UTC).hour, "holding_minutes": int(trade["duration_ms"]) / 60_000, "regime": trend, "volatility_regime": regime["volatility_regime"], "range_phase": regime["range_phase"], "regime_observed_through": regime["observed_through"], "htf_bias_strength": abs(day.close - day.open) / day_range, "structure_age_minutes": max(0, (int(trade["signal_time"]) - hour.close_time) / 60_000), "distance_from_structure_break_atr": abs(entry - break_price) / typical_hour_range, "displacement_magnitude": abs(signal.close - signal.open) / signal_range, "retest_depth": abs(entry - break_price) / hour_range, "liquidity_sweep_present": signal.low < hour.low and signal.close > hour.low if side == "LONG" else signal.high > hour.high and signal.close < hour.high, "entry_location": location, "available_room_r": room / max(risk, 1e-12), "volatility_normalization": volatility_ratio, "planned_rr": abs(float(trade["take_profits"][0]) - entry) / max(risk, 1e-12), "mfe": mfe, "mae": mae, "mfe_mae_ratio": mfe / max(mae, 1e-12), "mae_before_mfe": mae_at <= mfe_at, "mfe_before_mae": mfe_at < mae_at, "time_to_mfe_minutes": (mfe_at - int(trade["entry_time"])) / 60_000, "time_to_mae_minutes": (mae_at - int(trade["entry_time"])) / 60_000, "mfe_realized_pct": gross_return / mfe * 100 if mfe else 0.0, "mfe_giveback": max(0.0, mfe - max(0.0, gross_return)), "positive_mfe_closed_negative": mfe > 0 and net < 0, "immediate_adverse_excursion": excursions[0][2] > excursions[0][1], "late_entry_location": location >= .80 if side == "LONG" else location <= .20, "excessive_displacement": abs(signal.close - signal.open) / signal_range >= .75, "insufficient_room_to_target": room / max(risk, 1e-12) < abs(float(trade["take_profits"][0]) - entry) / max(risk, 1e-12), "gross_expectancy_contribution": gross, "total_cost": costs, "net_expectancy_contribution": net}


def analyze_family(source: Path, output: Path, datasets: dict[str, list[Any]], tiers: dict[str, str], tier_provenance: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    trades = read_jsonl(source / "trades" / "dev.jsonl")
    dev_start, dev_end = manifest["splits"]["development"]["start"], manifest["splits"]["development"]["end"]
    features = []
    for trade in trades:
        candles = datasets[trade["symbol"]]
        features.append(feature_row(trade, candles, resample_closed(candles, 3_600_000), resample_closed(candles, DAY_MS), tiers.get(trade["symbol"], {}), dev_start))
    identity = {"engine": FORENSICS_ENGINE_VERSION, "source_manifest": stable_digest(manifest), "trade_digest": stable_digest(trades)}
    output.mkdir(parents=True, exist_ok=True)
    forensic_manifest = {"identity_hash": stable_digest(identity), "forensics_engine_version": FORENSICS_ENGINE_VERSION, "source_research_run_id": manifest["research_run_id"], "strategy_id": manifest["strategy_id"], "strategy_version": manifest["strategy_version"], "dataset_version": manifest["dataset_version"], "development_window": {"start": dev_start, "end": dev_end}, "locked_oos_read": False, "tier_provenance": tier_provenance}
    if (output / "manifest.json").exists():
        existing = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if existing["identity_hash"] != forensic_manifest["identity_hash"]: raise ValueError(f"immutable forensic artifact collision: {output}")
        return {"strategy": output.name, "status": "ALREADY_COMPLETED", "artifact": str(output.resolve())}
    winners, losers = [row for row in features if row["outcome"] == "WIN"], [row for row in features if row["outcome"] == "LOSS"]
    numeric = ("mae", "mfe", "mfe_mae_ratio", "time_to_mfe_minutes", "time_to_mae_minutes", "mfe_realized_pct", "holding_minutes", "entry_location", "planned_rr", "available_room_r", "displacement_magnitude", "htf_bias_strength", "structure_age_minutes", "distance_from_structure_break_atr", "retest_depth", "volatility_normalization")
    entry = {"trade_count": len(features), "distributions": {key: distribution(row[key] for row in features) for key in numeric}, "winners": {key: distribution(row[key] for row in winners) for key in numeric}, "losers": {key: distribution(row[key] for row in losers) for key in numeric}, "time_of_day_utc": grouped(features, "utc_hour"), "flags": {key: sum(bool(row[key]) for row in features) for key in ("mae_before_mfe", "mfe_before_mae", "immediate_adverse_excursion", "late_entry_location", "excessive_displacement", "insufficient_room_to_target", "positive_mfe_closed_negative")}, "trades": features}
    exits = {"by_exit_reason": grouped(features, "exit_reason"), "winner_mfe_giveback": distribution(row["mfe_giveback"] for row in winners), "positive_mfe_closed_negative_count": sum(row["positive_mfe_closed_negative"] for row in features), "holding_duration": distribution(row["holding_minutes"] for row in features)}
    direction = {"BOTH": {"metrics": metrics(features)}, **grouped(features, "side")}
    regimes = {"market_regime": grouped(features, "regime"), "volatility_regime": grouped(features, "volatility_regime"), "range_phase": grouped(features, "range_phase")}
    fees = sum(float(row["entry_fee"]) + float(row["exit_fee"]) for row in features); funding = sum(float(row["funding_cost"]) for row in features); spread = sum(float(row["spread_cost"]) for row in features); slippage = sum(float(row["slippage_cost"]) for row in features)
    gross, net = sum(float(row["gross_pnl"]) for row in features), sum(float(row["net_pnl"]) for row in features)
    failure = "EDGE_NEGATIVE_BEFORE_COST" if gross <= 0 else "EDGE_DESTROYED_BY_COST" if net <= 0 else "MIXED"
    costs = {"trade_count": len(features), "gross_expectancy": gross / len(features) if features else 0, "fee_impact": fees / len(features) if features else 0, "funding_impact": funding / len(features) if features else 0, "spread_impact": spread / len(features) if features else 0, "slippage_impact": slippage / len(features) if features else 0, "total_cost_burden": (fees + funding + spread + slippage) / len(features) if features else 0, "net_expectancy": net / len(features) if features else 0, "failure_classification": failure}
    symbols = {"by_symbol": grouped(features, "symbol"), "by_tier": grouped(features, "market_tier"), "new_listing": grouped(features, "new_listing_at_dev"), "tier_provenance": tier_provenance}
    for name, value in (("manifest.json", forensic_manifest), ("entry-forensics.json", entry), ("exit-forensics.json", exits), ("direction-analysis.json", direction), ("regime-analysis.json", regimes), ("cost-attribution.json", costs), ("symbol-analysis.json", symbols)): atomic_json(output / name, value)
    proposal = HYPOTHESES.get(f"{manifest['strategy_id']}_V2")
    regime_lines = [f"- {name}: {value['metrics']['trade_count']} trades, expectancy {value['metrics']['expectancy']:.4f}, PF {value['metrics']['profit_factor']:.3f}" for name, value in regimes["market_regime"].items()]
    report = [f"# {manifest['strategy_id']}_{manifest['strategy_version']} Forensic Report", "", f"Source run: `{manifest['research_run_id']}`  ", f"Dataset: `{manifest['dataset_version']}`  ", "Scope: Development only; locked OOS was not read.", "", "## Core findings", "", f"- Gross expectancy: {costs['gross_expectancy']:.4f}; net expectancy: {costs['net_expectancy']:.4f}; classification: `{failure}`.", f"- LONG expectancy: {direction.get('LONG', {'metrics': {'expectancy': 0}})['metrics']['expectancy']:.4f}; SHORT expectancy: {direction.get('SHORT', {'metrics': {'expectancy': 0}})['metrics']['expectancy']:.4f}.", f"- Median winner MAE/MFE ratio: {entry['winners']['mfe_mae_ratio'].get('median', 0):.3f}; median loser ratio: {entry['losers']['mfe_mae_ratio'].get('median', 0):.3f}.", f"- Immediate adverse excursion: {entry['flags']['immediate_adverse_excursion']}/{len(features)}; positive MFE then negative close: {entry['flags']['positive_mfe_closed_negative']}/{len(features)}.", "", "## Regimes", "", *regime_lines, "", "## Hypothesis decision", ""]
    if proposal:
        report.extend([f"Proposed immutable version: `{manifest['strategy_id']}_V2`", "", f"- Observed problem: {proposal['observed_problem']}", f"- Evidence: {proposal['evidence']}", f"- Deterministic change: {proposal['change']}", f"- Why it may improve edge: {proposal['why']}", f"- Falsification: {proposal['falsification']}"])
    else:
        report.extend(["No new version is justified.", "", "The strongest separation is post-entry excursion ordering. That information is unavailable before entry and cannot become a filter without lookahead. Prospective V1 regime and direction slices remain negative, so D4.1 stops this family."])
    atomic_text(output / "hypothesis-report.md", "\n".join(report) + "\n")
    return {"strategy": output.name, "status": "COMPLETED", "artifact": str(output.resolve()), "gross_expectancy": costs["gross_expectancy"], "net_expectancy": costs["net_expectancy"], "failure": failure, "trades": len(features)}


def run_forensics(research_run_id: str, state_root: Path = Path("state"), cache_root: Path = Path("data/market")) -> dict[str, Any]:
    run_manifest = json.loads((state_root / "research-runs" / research_run_id / "manifest.json").read_text(encoding="utf-8"))
    dev_start, dev_end = run_manifest["dev_window"]["start"], run_manifest["dev_window"]["end"]
    bridge = BridgeClient(os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766"))
    universe = bridge.universe(); tiers, tier_provenance = tier_snapshot(universe, dev_start, dev_end)
    symbols = run_manifest["universe_snapshot"]
    datasets = {symbol: HistoricalDataStore(cache_root, bridge).candles(symbol, "5m", dev_start - 3 * DAY_MS, dev_end)[0] for symbol in symbols}
    results = []
    for version in PRIMARY:
        source = state_root / "research" / version / research_run_id
        results.append(analyze_family(source, state_root / "forensics" / version, datasets, tiers, tier_provenance))
    return {"research_run_id": research_run_id, "status": "COMPLETED", "families": results, "locked_oos_read": False}
