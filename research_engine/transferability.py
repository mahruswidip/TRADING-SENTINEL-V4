from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from backtest_engine.data import DAY_MS, INTERVAL_MS, atomic_json
from backtest_engine.engine import metrics, run_symbol, stable_digest
from backtest_engine.model import Candle, CostModel, FundingEvent
from forensics_engine.analysis import feature_row
from research_engine.refinements import VARIANTS
from research_engine.strategies import STRATEGIES


ENGINE_VERSION = "d4.8-transferability-v1"
STAGE_LIMITS = {"A": 24, "B": 100}
VERDICTS = {
    "REJECTED", "INSUFFICIENT_DATA", "WEAK_SIGNAL", "STAGE_A_SURVIVOR",
    "STAGE_B_SURVIVOR", "TRANSFERABILITY_CANDIDATE",
}


def _historical_inventory() -> list[dict[str, Any]]:
    """Frozen evidence ledger. Values are transcribed from immutable D4.x reports."""
    v1 = {
        "BREAKOUT_RETEST_V1": (-0.4891, None, "positive TRENDING_UP subset: 12 trades, +1.02 expectancy"),
        "RANGE_REVERSION_V1": (-0.5658, None, "positive LONG subset: 39 trades, +0.2446 expectancy, PF 1.057"),
        "TREND_CONTINUATION_V1": (-0.9494, None, "all prospectively known broad slices negative"),
        "PULLBACK_CONTINUATION_V1": (-1.23, None, "negative raw edge in D4.4 triage"),
        "LIQUIDITY_SWEEP_REVERSAL_V1": (-1.4829, None, "negative raw edge in D4.4 triage"),
        "COMPRESSION_EXPANSION_V1": (-1.47, None, "negative raw edge in D4.4 triage"),
        "MOMENTUM_BREAK_V1": (-1.09, 0.83, "strongest relative remaining family; gross edge survived before costs"),
    }
    rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        key = f"{strategy.strategy_id}_{strategy.strategy_version}"
        expectancy, pf, note = v1[key]
        admitted = key in {"BREAKOUT_RETEST_V1", "RANGE_REVERSION_V1", "MOMENTUM_BREAK_V1"}
        rows.append({
            "mechanism": key, "rules_hash": stable_digest(asdict(strategy)),
            "historical_expectancy_usd": expectancy, "historical_profit_factor": pf,
            "historical_note": note, "source": "docs/D4_1_STRATEGY_FORENSICS_SPEC.md" if key in v1 and key not in {"PULLBACK_CONTINUATION_V1", "LIQUIDITY_SWEEP_REVERSAL_V1", "COMPRESSION_EXPANSION_V1", "MOMENTUM_BREAK_V1"} else "state/triage/d4_4_61376443a744250c/remaining-families.json",
            "harvest_status": "ADMITTED" if admitted else "REJECTED",
            "admission_reason": "positive identifiable subset" if key in {"BREAKOUT_RETEST_V1", "RANGE_REVERSION_V1"} else "strongest relative performer despite failure" if admitted else "no admission criterion met",
        })
    for variant in VARIANTS:
        key = f"{variant.strategy_id}_{variant.strategy_version}"
        expanded = {
            "BREAKOUT_RETEST_V2": (-0.5834, 0.8597, "PF >= 0.85 and earlier positive Development subset"),
            "RANGE_REVERSION_V2": (-1.0018, 0.6803, "earlier immutable Development run was positive: +0.3757, PF 1.0971"),
        }[key]
        rows.append({
            "mechanism": key, "rules_hash": stable_digest(asdict(variant)),
            "historical_expectancy_usd": expanded[0], "historical_profit_factor": expanded[1],
            "historical_note": expanded[2], "source": "docs/D4_2_DEVELOPMENT_EVIDENCE_EXPANSION_SPEC.md",
            "harvest_status": "ADMITTED", "admission_reason": expanded[2],
        })
    rows.extend((
        {"mechanism": "FVG_PULLBACK_V1", "source": "docs/D4_4_REMAINING_TRIAGE_AND_FVG_SPEC.md", "historical_expectancy_usd": -1.2752, "historical_profit_factor": 0.7291, "historical_note": "all temporal segments negative", "harvest_status": "REJECTED", "admission_reason": "no admission criterion met", "rules_hash": None},
        {"mechanism": "D4_5_TO_D4_7_SIGNAL_B", "source": "state/signal-replication/d4_7_f38827b40e50d854", "historical_expectancy_usd": None, "historical_profit_factor": None, "historical_note": "signal evidence has no frozen entry/exit/SL/TP mechanism", "harvest_status": "INSUFFICIENT_HISTORICAL_EVIDENCE", "admission_reason": "cannot reconstruct a complete strategy without invention", "rules_hash": None},
    ))
    return rows


def harvested_mechanisms() -> dict[str, Any]:
    strategies = {f"{item.strategy_id}_{item.strategy_version}": item for item in STRATEGIES}
    strategies.update({f"{item.strategy_id}_{item.strategy_version}": item for item in VARIANTS})
    admitted = {row["mechanism"]: strategies[row["mechanism"]] for row in _historical_inventory() if row["harvest_status"] == "ADMITTED"}
    return admitted


def transferability_score(positive_market_ratio: float, median_expectancy: float, median_pf: float,
                          oos_survival: float, concentration_score: float, sufficiency: float) -> float:
    expectancy_score = min(1.0, max(0.0, 0.5 + median_expectancy / 3.0))
    pf_score = min(1.0, max(0.0, median_pf / 1.5))
    return round(100 * (
        .30 * positive_market_ratio + .25 * expectancy_score + .15 * pf_score
        + .15 * oos_survival + .10 * concentration_score + .05 * sufficiency
    ), 2)


def stage_gate(stage: str, summary: dict[str, Any]) -> bool:
    minimum_symbols, minimum_trades = (20, 100) if stage == "A" else (80, 300)
    checks = (
        summary["valid_symbols"] >= minimum_symbols,
        summary["positive_market_ratio"] >= .55,
        summary["aggregate_trades"] >= minimum_trades,
        summary["median_market_expectancy"] > 0,
        summary["median_market_profit_factor"] > 1.05,
        summary["aggregate_oos_expectancy"] > 0,
        summary["positive_oos_fold_ratio"] >= .50,
    )
    if stage == "B":
        checks += (summary["aggregate_expectancy"] > 0,)
    return all(checks)


def _full_days(symbol_dir: Path) -> set[str]:
    days = set()
    for path in (symbol_dir / "5m").glob("*.manifest.json") if (symbol_dir / "5m").exists() else ():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("row_count") == 288 and value.get("gap_count") == 0:
            days.add(path.name[:10])
    return days


def _read_candles(cache_root: Path, symbol: str, dates: Iterable[str]) -> tuple[list[Candle], list[str]]:
    rows: list[Candle] = []
    dataset_ids = []
    for date in dates:
        folder = cache_root / "binance-usdm-v1" / symbol / "5m"
        manifest = json.loads((folder / f"{date}.manifest.json").read_text(encoding="utf-8"))
        dataset_ids.append(str(manifest["dataset_id"]))
        with gzip.open(folder / f"{date}.jsonl.gz", "rt", encoding="utf-8") as source:
            rows.extend(Candle(**json.loads(line)) for line in source if line.strip())
    return rows, dataset_ids


def _market_profile(cache_root: Path, symbol: str, dates: list[str]) -> tuple[float, float]:
    notionals, closes = [], []
    folder = cache_root / "binance-usdm-v1" / symbol / "5m"
    for date in dates:
        with gzip.open(folder / f"{date}.jsonl.gz", "rt", encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                closes.append(float(row["close"]))
                notionals.append(float(row["close"]) * float(row["volume"]))
    returns = [math.log(right / left) for left, right in zip(closes, closes[1:]) if left > 0 and right > 0]
    volatility = math.sqrt(sum(value * value for value in returns) / len(returns)) if returns else 0.0
    return median(notionals) if notionals else 0.0, volatility


def _funding_path(cache_root: Path, symbol: str, start: int, end: int) -> Path | None:
    folder = cache_root / "binance-usdm-v1" / symbol / "funding"
    for path in sorted(folder.glob("*.json")) if folder.exists() else ():
        try:
            cached_start, cached_end = map(int, path.stem.split("-", 1))
        except ValueError:
            continue
        if cached_start <= start and cached_end >= end:
            return path
    return None


def _cached_funding(cache_root: Path, symbol: str, start: int, end: int) -> list[FundingEvent]:
    path = _funding_path(cache_root, symbol, start, end)
    if path is None:
        raise FileNotFoundError(f"missing local funding history: {symbol}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    events = []
    for row in rows:
        timestamp, rate = int(row["fundingTime"]), float(row["fundingRate"])
        if start <= timestamp < end:
            events.append(FundingEvent(timestamp, rate))
    if not events:
        raise ValueError(f"empty local funding history: {symbol}")
    return sorted(events, key=lambda item: item.timestamp)


def _folds(start: int, end: int) -> list[dict[str, Any]]:
    width = (end - start) // 4
    result = []
    for index in range(4):
        left, right = start + index * width, end if index == 3 else start + (index + 1) * width
        split = left + (right - left) * 5 // 8
        result.append({"fold": index + 1, "development": {"start": left, "end": split}, "oos": {"start": split, "end": right, "tuning_allowed": False}})
    return result


def build_plan(cache_root: Path, state_root: Path, workers: int = 8) -> dict[str, Any]:
    market_root = cache_root / "binance-usdm-v1"
    available = {path.name: _full_days(path) for path in market_root.iterdir() if path.is_dir()}
    frequency: dict[str, int] = {}
    for dates in available.values():
        for date in dates:
            frequency[date] = frequency.get(date, 0) + 1
    common = sorted(date for date, count in frequency.items() if count >= STAGE_LIMITS["A"])
    if not common:
        raise RuntimeError("fewer than 24 symbols share a complete cached day")
    longest: list[str] = []
    current: list[str] = []
    for date in common:
        if current and (datetime.fromisoformat(date) - datetime.fromisoformat(current[-1])).days != 1:
            if len(current) > len(longest): longest = current
            current = []
        current.append(date)
    if len(current) > len(longest): longest = current
    eligible = sorted(symbol for symbol, dates in available.items() if set(longest) <= dates)
    if len(eligible) < STAGE_LIMITS["A"]:
        raise RuntimeError("fewer than 24 symbols have complete common cached history")
    profiles = {symbol: _market_profile(cache_root, symbol, longest) for symbol in eligible}
    ranked = sorted(eligible, key=lambda symbol: (-profiles[symbol][0], symbol))
    third = max(8, len(ranked) // 3)
    high, medium, lower = ranked[:third], ranked[third:2 * third], ranked[2 * third:]
    high_pick = high[:8]
    if "BTCUSDT" in eligible and "BTCUSDT" not in high_pick: high_pick[-1] = "BTCUSDT"
    if "ETHUSDT" in eligible and "ETHUSDT" not in high_pick: high_pick[-2] = "ETHUSDT"
    medium_pick = medium[:8]
    beta_pick = sorted(lower, key=lambda symbol: (-profiles[symbol][1], symbol))[:8]
    selected = [(symbol, "HIGH_LIQUIDITY") for symbol in high_pick] + [(symbol, "MEDIUM_LIQUIDITY") for symbol in medium_pick] + [(symbol, "HIGH_BETA_LOWER_LIQUIDITY") for symbol in beta_pick]
    start = int(datetime.fromisoformat(longest[3]).replace(tzinfo=UTC).timestamp() * 1000)
    end = int(datetime.fromisoformat(longest[-1]).replace(tzinfo=UTC).timestamp() * 1000) + DAY_MS
    missing_funding = [symbol for symbol, _ in selected if _funding_path(cache_root, symbol, start, end) is None]
    mechanisms = harvested_mechanisms()
    identity = {"engine": ENGINE_VERSION, "symbols": selected, "dates": longest, "mechanisms": {key: stable_digest(asdict(value)) for key, value in mechanisms.items()}, "folds": _folds(start, end), "cost": asdict(CostModel())}
    run_id = f"d4_8_{stable_digest(identity)[:16]}"
    stop_reasons = []
    if len(_folds(start, end)) < 2: stop_reasons.append("FEWER_THAN_TWO_VALID_FOLDS")
    if len(selected) < 20: stop_reasons.append("FEWER_THAN_20_VALID_STAGE_A_SYMBOLS")
    if missing_funding: stop_reasons.append("MISSING_LOCAL_FUNDING_HISTORY")
    return {
        "run_id": run_id, "identity_hash": stable_digest(identity), "engine_version": ENGINE_VERSION,
        "stage": "A", "status": "BLOCKED" if stop_reasons else "READY",
        "execution_plan": {"mechanisms": len(mechanisms), "symbols": len(selected), "folds": 4, "phases_per_fold": 2, "jobs": len(mechanisms) * len(selected) * 8, "workers": max(1, min(15, workers)), "external_downloads": 0},
        "history": {"warmup_dates": longest[:3], "evaluation_dates": longest[3:], "start": start, "end": end, "source": "EXISTING_LOCAL_CACHE_ONLY"},
        "universe": [{"symbol": symbol, "bucket": bucket, "median_5m_notional_proxy": profiles[symbol][0], "realized_5m_volatility": profiles[symbol][1]} for symbol, bucket in selected],
        "folds": _folds(start, end), "mechanisms": list(mechanisms), "missing_funding_symbols": missing_funding,
        "stop_reasons": stop_reasons, "full_universe_authorized": False,
        "oos_policy": "FOLD_OOS_EVALUATION_ONLY_NO_TUNING", "shadow_enabled": False, "real_enabled": False,
    }


def _write_markdown(path: Path, title: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([f"# {title}", "", *rows, ""]), encoding="utf-8")


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = state_root / "transferability" / plan["run_id"]
    root.mkdir(parents=True, exist_ok=True)
    inventory = _historical_inventory()
    atomic_json(root / "harvest_inventory.json", {"items": inventory})
    _write_markdown(root / "harvest_inventory.md", "D4.8 Harvest Inventory", [f"- `{row['mechanism']}` — **{row['harvest_status']}**: {row['historical_note']}" for row in inventory])
    atomic_json(root / "frozen_mechanisms.json", {"mechanisms": plan["mechanisms"], "rule_changes": 0, "tuning": False})
    atomic_json(root / "stage_a_universe.json", {"symbols": plan["universe"], "selection": "8 high liquidity + 8 medium liquidity + 8 high-beta/lower-liquidity", "static_whitelist": False})
    atomic_json(root / "temporal_folds.json", {"folds": plan["folds"], "tuning_allowed": False})
    atomic_json(root / "execution_plan.json", plan)
    checkpoint = {"identity_hash": plan["identity_hash"], "status": "BLOCKED" if plan["stop_reasons"] else "PLANNED", "completed_jobs": [], "stop_reasons": plan["stop_reasons"]}
    atomic_json(root / "checkpoint.json", checkpoint)
    if plan["stop_reasons"]:
        report = {"run_id": plan["run_id"], "status": "STOPPED", "verdict": "INSUFFICIENT_DATA", "reasons": plan["stop_reasons"], "missing_funding_symbols": plan["missing_funding_symbols"], "stage_a_executed": False, "stage_b_executed": False, "full_universe_executed": False}
        atomic_json(root / "final_report.json", report)
        _write_markdown(root / "final_report.md", "D4.8 Final Report", ["Verdict: **INSUFFICIENT_DATA**", "", "Stage A was not executed because realistic local funding history is unavailable for the selected 24-symbol cohort.", "", "No external data was downloaded; no tuning, OOS mutation, Shadow, Canary, or REAL action occurred."])
    return root


def execute(run_id: str, state_root: Path, cache_root: Path) -> dict[str, Any]:
    root = state_root / "transferability" / run_id
    plan_path = root / "execution_plan.json"
    if not plan_path.exists(): raise FileNotFoundError(f"unknown D4.8 run: {run_id}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["stop_reasons"]:
        return json.loads((root / "final_report.json").read_text(encoding="utf-8"))
    # A ready plan must still recheck immutable local inputs before any expensive work.
    missing = [item["symbol"] for item in plan["universe"] if _funding_path(cache_root, item["symbol"], plan["history"]["start"], plan["history"]["end"]) is None]
    if missing: raise RuntimeError("local funding preflight changed; rerun plan")
    raise RuntimeError("Stage A execution is intentionally fail-closed until a complete cache-only funding cohort is present")


def _metric_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    value = metrics(trades)
    wins = [float(row["net_pnl"]) for row in trades if float(row["net_pnl"]) > 0]
    losses = [float(row["net_pnl"]) for row in trades if float(row["net_pnl"]) < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    return {
        "trades": value["trade_count"], "wins": value["wins"], "losses": value["losses"],
        "win_rate": value["win_rate"], "gross_pnl": sum(float(row["gross_pnl"]) for row in trades),
        "net_pnl": value["net_pnl"], "expectancy": value["expectancy"],
        "expectancy_pct": value["expectancy"] / 1_000 * 100, "profit_factor": value["profit_factor"],
        "max_drawdown": value["max_drawdown"], "average_win": average_win, "average_loss": average_loss,
        "payoff_ratio": average_win / abs(average_loss) if average_loss else (999.0 if average_win else 0.0),
        "fees": value["fees_total"], "funding": value["funding_total"],
        "spread": value["spread_total"], "slippage": value["slippage_total"],
        "mfe": value["MFE"], "mae": value["MAE"],
        "positive_pnl": sum(wins), "negative_pnl": sum(losses),
    }


def _combine(values: list[dict[str, Any]]) -> dict[str, Any]:
    trades = sum(int(value["trades"]) for value in values)
    wins = sum(int(value["wins"]) for value in values)
    losses = sum(int(value["losses"]) for value in values)
    net = sum(float(value["net_pnl"]) for value in values)
    positive = sum(float(value["positive_pnl"]) for value in values)
    negative = sum(float(value["negative_pnl"]) for value in values)
    average_win = positive / wins if wins else 0.0
    average_loss = negative / losses if losses else 0.0
    weighted = lambda key: sum(float(value[key]) * int(value["trades"]) for value in values) / trades if trades else 0.0
    return {
        "trades": trades, "wins": wins, "losses": losses, "win_rate": wins / trades * 100 if trades else 0.0,
        "gross_pnl": sum(float(value["gross_pnl"]) for value in values), "net_pnl": net,
        "expectancy": net / trades if trades else 0.0, "expectancy_pct": net / trades / 1_000 * 100 if trades else 0.0,
        "profit_factor": positive / abs(negative) if negative else (999.0 if positive else 0.0),
        "max_drawdown": max((float(value["max_drawdown"]) for value in values), default=0.0),
        "average_win": average_win, "average_loss": average_loss,
        "payoff_ratio": average_win / abs(average_loss) if average_loss else (999.0 if average_win else 0.0),
        "fees": sum(float(value["fees"]) for value in values), "funding": sum(float(value["funding"]) for value in values),
        "spread": sum(float(value["spread"]) for value in values), "slippage": sum(float(value["slippage"]) for value in values),
        "mfe": weighted("mfe"), "mae": weighted("mae"), "positive_pnl": positive, "negative_pnl": negative,
    }


def _regime_metrics(trades: list[dict[str, Any]], candles: list[Candle], hourly: list[Candle], daily: list[Candle], bucket: str, start: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        regime = feature_row(trade, candles, hourly, daily, {"tier": bucket, "onboard_date": 0}, start)["regime"]
        groups.setdefault(str(regime), []).append(trade)
    return {name: _metric_summary(rows) for name, rows in sorted(groups.items())}


def _evaluate_market(strategy: Any, strategy_name: str, symbol_row: dict[str, Any], plan: dict[str, Any], cache_root: Path) -> list[dict[str, Any]]:
    symbol = str(symbol_row["symbol"])
    dates = [*plan["history"]["warmup_dates"], *plan["history"]["evaluation_dates"]]
    candles, dataset_ids = _read_candles(cache_root, symbol, dates)
    funding = _cached_funding(cache_root, symbol, int(plan["history"]["start"]), int(plan["history"]["end"]))
    dataset_version = stable_digest(dataset_ids)
    rows = []
    for fold in plan["folds"]:
        phases = {}
        for phase_name in ("development", "oos"):
            window = fold[phase_name]
            result = run_symbol(
                f"{plan['run_id']}:{strategy_name}:{symbol}:F{fold['fold']}:{phase_name}", symbol,
                candles, funding, dataset_version, CostModel(), int(window["start"]), int(window["end"]), strategy,
            )
            trades = result["trades"]
            phases[phase_name] = {
                "metrics": _metric_summary(trades),
                "LONG": _metric_summary([row for row in trades if row["side"] == "LONG"]),
                "SHORT": _metric_summary([row for row in trades if row["side"] == "SHORT"]),
                "regimes": _regime_metrics(trades, candles, result["hourly"], result["daily"], str(symbol_row["bucket"]), int(window["start"])),
            }
        rows.append({"strategy": strategy_name, "symbol": symbol, "bucket": symbol_row["bucket"], "fold": fold["fold"], "dataset_version": dataset_version, **phases})
    return rows


def _atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(temporary, path)


def _flatten_metrics(rows: list[dict[str, Any]], phase: str | None = None, side: str | None = None) -> list[dict[str, Any]]:
    phases = (phase,) if phase else ("development", "oos")
    return [row[name][side] if side else row[name]["metrics"] for row in rows for name in phases]


def _strategy_summary(strategy: str, rows: list[dict[str, Any]], valid_symbols: int, early: bool = False) -> dict[str, Any]:
    symbols = sorted({str(row["symbol"]) for row in rows})
    market = {symbol: _combine(_flatten_metrics([row for row in rows if row["symbol"] == symbol])) for symbol in symbols}
    expectations = [value["expectancy"] for value in market.values()]
    pfs = [value["profit_factor"] for value in market.values()]
    oos = _combine(_flatten_metrics(rows, "oos"))
    aggregate = _combine(_flatten_metrics(rows))
    long_value = _combine(_flatten_metrics(rows, side="LONG"))
    short_value = _combine(_flatten_metrics(rows, side="SHORT"))
    folds = {int(fold): _combine(_flatten_metrics([row for row in rows if int(row["fold"]) == fold], "oos")) for fold in sorted({int(row["fold"]) for row in rows})}
    profitable = sorted(((value["net_pnl"], symbol) for symbol, value in market.items() if value["net_pnl"] > 0), reverse=True)
    profit = sum(value for value, _ in profitable)
    shares = [value / profit for value, _ in profitable] if profit else []
    positive_ratio = sum(value > 0 for value in expectations) / valid_symbols if valid_symbols else 0.0
    survival = sum(value["expectancy"] > 0 for value in folds.values()) / len(folds) if folds else 0.0
    concentration_score = max(0.0, 1.0 - sum(share * share for share in shares))
    summary = {
        "strategy": strategy, "valid_symbols": valid_symbols, "aggregate_trades": aggregate["trades"],
        "aggregate_expectancy": aggregate["expectancy"], "positive_market_ratio": positive_ratio,
        "median_market_expectancy": median(expectations) if expectations else 0.0,
        "median_market_expectancy_pct": median(expectations) / 1_000 * 100 if expectations else 0.0,
        "median_market_profit_factor": median(pfs) if pfs else 0.0,
        "aggregate_oos_expectancy": oos["expectancy"], "positive_oos_fold_ratio": survival,
        "LONG_expectancy": long_value["expectancy"], "LONG_trades": long_value["trades"],
        "SHORT_expectancy": short_value["expectancy"], "SHORT_trades": short_value["trades"],
        "top_1_positive_profit_concentration": sum(shares[:1]), "top_3_positive_profit_concentration": sum(shares[:3]),
        "hhi_concentration": sum(share * share for share in shares),
        "concentration_warning": sum(shares[:1]) >= .40 or sum(shares[:3]) >= .65,
        "markets": market, "oos_folds": folds,
    }
    summary["transferability_score"] = transferability_score(positive_ratio, summary["median_market_expectancy"], summary["median_market_profit_factor"], survival, concentration_score, min(1.0, aggregate["trades"] / 100))
    summary["passed"] = False if early else stage_gate("A", summary)
    summary["verdict"] = "EARLY_REJECTED" if early else "STAGE_A_SURVIVOR" if summary["passed"] else "WEAK_SIGNAL" if aggregate["expectancy"] > 0 or oos["expectancy"] > 0 else "REJECTED"
    return summary


def _combined_regimes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for phase in ("development", "oos"):
            for regime, value in row[phase]["regimes"].items():
                result.setdefault(regime, []).append(value)
    return {regime: _combine(values) for regime, values in sorted(result.items())}


def _validate_frozen(plan: dict[str, Any], root: Path, cache_root: Path) -> dict[str, Any]:
    universe = json.loads((root / "stage_a_universe.json").read_text(encoding="utf-8"))["symbols"]
    folds = json.loads((root / "temporal_folds.json").read_text(encoding="utf-8"))["folds"]
    mechanisms = json.loads((root / "frozen_mechanisms.json").read_text(encoding="utf-8"))["mechanisms"]
    if universe != plan["universe"] or folds != plan["folds"] or mechanisms != plan["mechanisms"]:
        raise ValueError("frozen D4.8 artifacts disagree")
    if len(universe) != 24 or len(folds) != 4 or len(mechanisms) != 5 or int(plan["execution_plan"]["jobs"]) != 960:
        raise ValueError("Stage-A scope exceeds or differs from approved 960 jobs")
    strategies = harvested_mechanisms()
    if list(strategies) != mechanisms:
        raise ValueError("frozen strategy definitions changed")
    dates = [*plan["history"]["warmup_dates"], *plan["history"]["evaluation_dates"]]
    missing_candles = [item["symbol"] for item in universe if any(not (cache_root / "binance-usdm-v1" / item["symbol"] / "5m" / f"{date}.jsonl.gz").exists() for date in dates)]
    missing_funding = [item["symbol"] for item in universe if _funding_path(cache_root, item["symbol"], int(plan["history"]["start"]), int(plan["history"]["end"])) is None]
    return {"strategies": mechanisms, "symbols": len(universe), "folds": len(folds), "projected_jobs": 960, "candle_data": "COMPLETE" if not missing_candles else "INCOMPLETE", "funding": "COMPLETE" if not missing_funding else "INCOMPLETE", "missing_candles": missing_candles, "missing_funding": missing_funding}


def run_stage_a(run_id: str, state_root: Path, cache_root: Path, workers: int) -> dict[str, Any]:
    root = state_root / "transferability" / run_id
    plan = json.loads((root / "execution_plan.json").read_text(encoding="utf-8"))
    if plan["run_id"] != run_id or not plan["identity_hash"].startswith(run_id.removeprefix("d4_8_")):
        raise ValueError("D4.8 run hash mismatch")
    preflight = _validate_frozen(plan, root, cache_root)
    workers = max(1, min(15, workers))
    preflight.update({"workers": workers, "run_hash": plan["identity_hash"], "backtest_execution": "LOCAL_DETERMINISTIC_CLI", "llm_calls_inside_backtest": 0})
    print(json.dumps({"pre_run": preflight}, sort_keys=True), flush=True)
    if preflight["candle_data"] != "COMPLETE" or preflight["funding"] != "COMPLETE":
        raise RuntimeError("Stage-A data preflight failed")

    results_path, checkpoint_path = root / "stage_a_results.jsonl", root / "checkpoint.json"
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()] if results_path.exists() else []
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    if checkpoint.get("identity_hash") not in {None, plan["identity_hash"]}:
        raise ValueError("checkpoint identity mismatch")
    completed = {(row["strategy"], row["symbol"]) for row in rows}
    early_rejected = dict(checkpoint.get("early_rejected", {}))
    strategies = harvested_mechanisms()
    universe = plan["universe"]
    started = time.monotonic()

    for strategy_name in plan["mechanisms"]:
        if strategy_name in early_rejected:
            continue
        pending = [item for item in universe if (strategy_name, item["symbol"]) not in completed]
        done_for_strategy = len({symbol for name, symbol in completed if name == strategy_name})
        while pending:
            required_before_gate = max(0, 12 - done_for_strategy)
            batch_size = required_before_gate or len(pending)
            batch = pending[:batch_size]
            with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
                futures = {pool.submit(_evaluate_market, strategies[strategy_name], strategy_name, item, plan, cache_root): item for item in batch}
                for future in as_completed(futures):
                    item = futures[future]
                    market_rows = future.result()
                    rows.extend(market_rows)
                    completed.add((strategy_name, str(item["symbol"])))
                    done_for_strategy += 1
                    rows.sort(key=lambda row: (plan["mechanisms"].index(row["strategy"]), next(index for index, value in enumerate(universe) if value["symbol"] == row["symbol"]), int(row["fold"])))
                    _atomic_jsonl(results_path, rows)
                    atomic_json(checkpoint_path, {"identity_hash": plan["identity_hash"], "status": "RUNNING", "completed_symbols": sorted([list(value) for value in completed]), "completed_jobs": len(completed) * 8, "early_rejected": early_rejected})
                    atomic_json(root / "stage_a_progress.json", {"status": "RUNNING", "strategy": strategy_name, "completed_jobs": len(completed) * 8, "planned_jobs": 960, "completed_symbols": len(completed), "updated_at": datetime.now(UTC).isoformat()})
            strategy_rows = [row for row in rows if row["strategy"] == strategy_name]
            if done_for_strategy >= 12:
                interim = _strategy_summary(strategy_name, strategy_rows, done_for_strategy)
                if interim["positive_market_ratio"] < .25 and interim["median_market_expectancy_pct"] < -.15 and interim["median_market_profit_factor"] < .85:
                    evidence = {key: interim[key] for key in ("valid_symbols", "positive_market_ratio", "median_market_expectancy", "median_market_expectancy_pct", "median_market_profit_factor")}
                    early_rejected[strategy_name] = evidence
                    atomic_json(root / f"early_rejection_{strategy_name}.json", {"strategy": strategy_name, "decision": "EARLY_REJECTED", "minimum_symbols_satisfied": True, "evidence": evidence})
                    break
            pending = [item for item in universe if (strategy_name, item["symbol"]) not in completed]

    summaries = []
    regimes = {}
    for strategy_name in plan["mechanisms"]:
        strategy_rows = [row for row in rows if row["strategy"] == strategy_name]
        valid = len({row["symbol"] for row in strategy_rows})
        summaries.append(_strategy_summary(strategy_name, strategy_rows, valid, strategy_name in early_rejected))
        regimes[strategy_name] = _combined_regimes(strategy_rows)
    ranking = sorted(summaries, key=lambda value: (-value["transferability_score"], value["strategy"]))
    survivors = [value["strategy"] for value in summaries if value["verdict"] == "STAGE_A_SURVIVOR"]
    result_hash = stable_digest(rows)
    final = {"run_id": run_id, "status": "COMPLETED", "planned_jobs": 960, "completed_jobs": len(completed) * 8, "workers": workers, "strategies_completed": len(summaries), "strategies_early_rejected": list(early_rejected), "symbols": 24, "folds": 4, "stage_a_survivors": survivors, "stage_b_eligible": survivors, "stage_b_executed": False, "result_hash": result_hash, "elapsed_seconds": round(time.monotonic() - started, 3)}
    atomic_json(root / "stage_a_summary.json", {"strategies": summaries})
    atomic_json(root / "regime_attribution.json", regimes)
    atomic_json(root / "transferability_ranking.json", {"ranking": ranking})
    atomic_json(root / "stage_a_final_report.json", final)
    atomic_json(root / "stage_a_result_hash.json", {"sha256": result_hash})
    atomic_json(checkpoint_path, {"identity_hash": plan["identity_hash"], "status": "COMPLETED", "completed_symbols": sorted([list(value) for value in completed]), "completed_jobs": len(completed) * 8, "early_rejected": early_rejected, "result_hash": result_hash})
    atomic_json(root / "stage_a_progress.json", {"status": "COMPLETED", "completed_jobs": len(completed) * 8, "planned_jobs": 960, "updated_at": datetime.now(UTC).isoformat()})
    return final


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="D4.8 cross-market strategy transferability study")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--workers", type=int, default=8)
    plan.add_argument("--state-root", default="state")
    plan.add_argument("--cache-root", default="data/market")
    run = commands.add_parser("execute")
    run.add_argument("--run-id", required=True)
    run.add_argument("--state-root", default="state")
    run.add_argument("--cache-root", default="data/market")
    stage_a = commands.add_parser("stage-a")
    stage_a.add_argument("--run-id", required=True)
    stage_a.add_argument("--workers", type=int, default=3)
    stage_a.add_argument("--state-root", default="state")
    stage_a.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "plan":
            plan = build_plan(Path(args.cache_root), Path(args.state_root), args.workers)
            artifact = save_plan(plan, Path(args.state_root))
            print(json.dumps({**plan, "artifact": str(artifact.resolve())}, sort_keys=True))
        elif args.command == "execute":
            print(json.dumps(execute(args.run_id, Path(args.state_root), Path(args.cache_root)), sort_keys=True))
        else:
            print(json.dumps(run_stage_a(args.run_id, Path(args.state_root), Path(args.cache_root), args.workers), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
