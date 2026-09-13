from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from backtest_engine.cli import jsonl
from backtest_engine.data import BridgeClient, HistoricalDataStore, atomic_json, iso_ms
from backtest_engine.engine import calculate_net, closed_at, funding_cost, metrics, resample_closed, stable_digest
from backtest_engine.model import Candle, CostModel, FundingEvent, Side, Trade
from forensics_engine.accounting_audit import reference_equity, temporal_slice
from forensics_engine.analysis import DAY_MS, atomic_text, feature_row, grouped, read_jsonl
from forensics_engine.expansion import expanded_breadth, stratified_universe
from research_engine.research import cost_stress, dashboard_metrics


ENGINE_VERSION = "d4.4-triage-fvg-v2"
STRATEGY_ID = "FVG_PULLBACK"
STRATEGY_VERSION = "V1"
VERSION_ID = f"{STRATEGY_ID}_{STRATEGY_VERSION}"
SOURCE_RESEARCH_RUN = "d4_dynamic_stratified_v3_20260911"
TRIAGE_FAMILIES = (
    "LIQUIDITY_SWEEP_REVERSAL_V1",
    "PULLBACK_CONTINUATION_V1",
    "COMPRESSION_EXPANSION_V1",
    "MOMENTUM_BREAK_V1",
)
FVG_EXPIRY_MS = 4 * 3_600_000
TARGET_R = 1.5
MIN_NET_EXPECTED_RR = 1.1
STARTING_EQUITY = 10_000.0
PROFILE = {
    "id": "INTRADAY_FVG",
    "label": "Intraday FVG",
    "timeframes": [
        {"timeframe": "1H", "responsibility": "Direction / Bias"},
        {"timeframe": "15M", "responsibility": "FVG / Setup Area"},
        {"timeframe": "5M", "responsibility": "Confirmation / Entry"},
    ],
}


def oos_guard() -> None:
    raise PermissionError("locked OOS is outside D4.4")


def triage_decision(gross_expectancy: float, net_expectancy: float, trade_count: int, top_share: float, temporal_flag: str) -> str:
    if gross_expectancy <= 0:
        return "KILL_NEGATIVE_RAW_EDGE"
    if net_expectancy <= 0:
        return "KILL_COST_DESTROYED"
    if trade_count < 20:
        return "KILL_INSUFFICIENT_EVIDENCE"
    if top_share > .60 or temporal_flag == "TEMPORAL_CONCENTRATION":
        return "KILL_UNSTABLE"
    return "KEEP_FOR_FUTURE_HYPOTHESIS"


def hourly_bias(now: int, hourly: list[Candle]) -> dict[str, Any]:
    """Two fully closed 1H bars confirm higher-high/higher-low or lower-low/lower-high structure."""
    known = closed_at(hourly, now)
    if len(known) < 2:
        return {"direction": "NEUTRAL", "observed_through": None}
    previous, latest = known[-2:]
    if latest.high > previous.high and latest.low > previous.low:
        direction = "BULLISH"
    elif latest.high < previous.high and latest.low < previous.low:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    return {"direction": direction, "observed_through": latest.close_time}


def detect_fvgs(candles: list[Candle], now: int, symbol: str = "TEST") -> list[dict[str, Any]]:
    known = closed_at(candles, now)
    result = []
    for index in range(2, len(known)):
        first, middle, third = known[index - 2:index + 1]
        direction, low, high = None, 0.0, 0.0
        if first.high < third.low:
            direction, low, high = "BULLISH", first.high, third.low
        elif first.low > third.high:
            direction, low, high = "BEARISH", third.high, first.low
        if direction is None:
            continue
        size = high - low
        typical = median(max(item.high - item.low, 1e-12) for item in known[max(0, index - 20):index + 1])
        identity = f"{symbol}:{direction}:{third.close_time}:{low:.12f}:{high:.12f}"
        result.append({
            "fvg_id": hashlib.sha256(identity.encode()).hexdigest()[:20],
            "direction": direction,
            "formed_at": third.close_time,
            "available_at": third.close_time,
            "price_low": low,
            "price_high": high,
            "size": size,
            "normalized_size": size / typical if typical else 0.0,
            "expires_at": third.close_time + FVG_EXPIRY_MS,
            "originating_displacement": {
                "open_time": middle.open_time,
                "close_time": middle.close_time,
                "body": abs(middle.close - middle.open),
                "body_to_range": abs(middle.close - middle.open) / max(middle.high - middle.low, 1e-12),
            },
        })
    return result


def fill_percentage(gap: dict[str, Any], candle: Candle) -> float:
    size = max(float(gap["size"]), 1e-12)
    if gap["direction"] == "BULLISH":
        return min(1.0, max(0.0, (float(gap["price_high"]) - candle.low) / size))
    return min(1.0, max(0.0, (candle.high - float(gap["price_low"])) / size))


def fvg_touched(gap: dict[str, Any], candle: Candle) -> bool:
    return candle.high >= float(gap["price_low"]) and candle.low <= float(gap["price_high"])


def fvg_invalidated(gap: dict[str, Any], candle: Candle) -> bool:
    return candle.low <= float(gap["price_low"]) if gap["direction"] == "BULLISH" else candle.high >= float(gap["price_high"])


def local_sweep(side: Side, candle: Candle, prior: list[Candle]) -> bool:
    if len(prior) < 3:
        return False
    recent = prior[-3:]
    if side == "LONG":
        level = min(item.low for item in recent)
        return candle.low < level and candle.close > level
    level = max(item.high for item in recent)
    return candle.high > level and candle.close < level


def confirms_structure(side: Side, candle: Candle, sweep: Candle) -> bool:
    return candle.close > sweep.high if side == "LONG" else candle.close < sweep.low


def next_open(candles: list[Candle], confirmation_index: int) -> tuple[int, float]:
    entry = candles[confirmation_index + 1]
    if entry.open_time <= candles[confirmation_index].close_time:
        raise ValueError("entry must occur after the confirmation candle closes")
    return entry.open_time, entry.open


def structural_stop(side: Side, sweep: Candle) -> float:
    return sweep.low if side == "LONG" else sweep.high


def fixed_r_target(side: Side, entry: float, stop: float) -> float:
    risk = abs(entry - stop)
    return entry + TARGET_R * risk if side == "LONG" else entry - TARGET_R * risk


def expected_net_rr(side: Side, entry: float, stop: float, target: float, cost: CostModel) -> float:
    direction = 1 if side == "LONG" else -1
    gross_reward = direction * (target - entry) / entry * 1_000
    gross_risk = abs(entry - stop) / entry * 1_000
    costs = 1_000 * (2 * cost.taker_bps + cost.spread_bps + cost.slippage_bps) / 10_000
    return (gross_reward - costs) / gross_risk if gross_risk else 0.0


def simulate_trade(
    run_id: str,
    symbol: str,
    side: Side,
    candles: list[Candle],
    entry_index: int,
    confirmation: Candle,
    sweep: Candle,
    target: float,
    funding: list[FundingEvent],
    dataset_version: str,
    cost: CostModel,
) -> tuple[dict[str, Any], int]:
    entry_bar, entry = candles[entry_index], candles[entry_index].open
    stop = structural_stop(side, sweep)
    observed = candles[entry_index:min(len(candles), entry_index + 24)]
    exit_price, exit_time, reason, resolution, exit_index = entry, entry_bar.close_time, "END_OF_DATA", "FAST_CLOSE", entry_index
    for offset, bar in enumerate(observed):
        stop_hit = bar.low <= stop if side == "LONG" else bar.high >= stop
        target_hit = bar.high >= target if side == "LONG" else bar.low <= target
        if stop_hit and target_hit:
            exit_price, exit_time, reason, resolution, exit_index = stop, bar.close_time, "INTRABAR_AMBIGUOUS", "FAST_WORST_CASE", entry_index + offset
            break
        if stop_hit:
            exit_price, exit_time, reason, resolution, exit_index = stop, bar.close_time, "STOP_LOSS", "FAST_OHLC", entry_index + offset
            break
        if target_hit:
            exit_price, exit_time, reason, resolution, exit_index = target, bar.close_time, "TAKE_PROFIT", "FAST_OHLC", entry_index + offset
            break
        exit_price, exit_time, exit_index = bar.close, bar.close_time, entry_index + offset
    direction = 1 if side == "LONG" else -1
    notional = 1_000.0
    gross_return = direction * (exit_price - entry) / entry
    gross_pnl = notional * gross_return
    entry_fee = exit_fee = notional * cost.taker_bps / 10_000
    funding_value, funding_rows = funding_cost(side, notional, entry_bar.open_time, exit_time, funding)
    spread_cost = notional * cost.spread_bps / 10_000
    slippage_cost = notional * cost.slippage_bps / 10_000
    net_pnl = calculate_net(gross_pnl, entry_fee, exit_fee, funding_value, spread_cost, slippage_cost)
    evaluated = observed[:exit_index - entry_index + 1]
    favorable = max((bar.high - entry) / entry if side == "LONG" else (entry - bar.low) / entry for bar in evaluated)
    adverse = min((bar.low - entry) / entry if side == "LONG" else (entry - bar.high) / entry for bar in evaluated)
    risk = abs(entry - stop)
    trade_id = hashlib.sha256(f"{run_id}:{VERSION_ID}:{symbol}:{entry_bar.open_time}:{side}".encode()).hexdigest()[:20]
    trade = Trade(trade_id, run_id, symbol, side, STRATEGY_ID, STRATEGY_VERSION, confirmation.close_time, entry_bar.open_time, exit_time, entry, exit_price, stop, (target,), notional, gross_return, gross_pnl, entry_fee, exit_fee, funding_value, funding_rows, spread_cost, slippage_cost, net_pnl / notional, net_pnl, gross_pnl / (notional * risk / entry), adverse, favorable, reason, exit_time - entry_bar.open_time, dataset_version, cost.version, "next-5m-open-market-v1", resolution)
    return trade.as_dict(), exit_index


def fvg_events(trade: dict[str, Any]) -> list[dict[str, Any]]:
    setup = trade["fvg_setup"]
    base = {"symbol": trade["symbol"], "strategyId": STRATEGY_ID, "strategyVersion": STRATEGY_VERSION}
    direction = "BULLISH" if trade["side"] == "LONG" else "BEARISH"
    def event(identifier: str, kind: str, timestamp: int, timeframe: str, category: str, label: str, reason: str, **extra: object) -> dict[str, Any]:
        return {**base, "id": f"{trade['trade_id']}-{identifier}", "type": kind, "timestamp": timestamp // 1000, "availableAt": timestamp // 1000, "timeframe": timeframe, "category": category, "label": label, "reason": reason, **extra}
    def transition(identifier: str, timestamp: int, from_state: str, to_state: str, label: str) -> dict[str, Any]:
        return event(identifier, "STATE_TRANSITION", timestamp, "5M", "TRADE", label, label, fromState=from_state, toState=to_state)
    formed, touch, sweep, signal = setup["formed_at"], setup["touched_at"], setup["sweep_at"], trade["signal_time"]
    return [
        transition("context-transition", setup["bias_observed_through"], "SCANNING", "HTF_CONTEXT_FOUND", "Closed 1H structure found"),
        event("bias", "BIAS_LOCKED", setup["bias_observed_through"], "1H", "CONTEXT", f"{direction} 1H bias", "Two fully closed 1H bars confirmed directional structure.", direction=direction),
        transition("bias-transition", setup["bias_observed_through"], "HTF_CONTEXT_FOUND", "BIAS_LOCKED", "1H bias locked"),
        transition("wait-fvg", setup["bias_observed_through"], "BIAS_LOCKED", "WAITING_MTF_STRUCTURE", "Waiting for 15M FVG"),
        event("fvg", "FVG", formed, "15M", "STRUCTURE", "15M FVG zone", "Canonical three-candle FVG became available after candle three closed.", direction=direction, priceRange={"timeStart": formed // 1000, "timeEnd": setup["expires_at"] // 1000, "priceLow": setup["price_low"], "priceHigh": setup["price_high"]}, metadata={"fvgId": setup["fvg_id"], "normalizedSize": setup["normalized_size"]}),
        event("touch", "POI", touch, "15M", "STRUCTURE", "FVG touch", "Price retraced into the confirmed FVG zone.", direction=direction, priceRange={"timeStart": touch // 1000, "timeEnd": touch // 1000, "priceLow": setup["price_low"], "priceHigh": setup["price_high"]}, metadata={"penetrationPct": setup["penetration_pct"]}),
        transition("fvg-transition", touch, "WAITING_MTF_STRUCTURE", "MTF_CONFIRMED", "15M FVG touched"),
        transition("wait-entry", touch, "MTF_CONFIRMED", "WAITING_LTF_ENTRY", "Waiting for closed 5M confirmation"),
        event("sweep", "LIQUIDITY_SWEEP", sweep, "5M", "STRUCTURE", "5M liquidity sweep", "Closed 5M candle swept and reclaimed the prior three-bar local extreme.", direction="SELL_SIDE" if trade["side"] == "LONG" else "BUY_SIDE", price=setup["sweep_price"]),
        event("mss", "MSS", signal, "5M", "STRUCTURE", "5M MSS confirmed", "A later closed 5M candle broke the sweep candle structural extreme.", direction=direction, price=trade["entry_price"]),
        event("trigger", "ENTRY_TRIGGERED", signal, "5M", "ENTRY", f"{trade['side']} entry triggered", "Confirmation was complete; execution waits for the next 5M open.", direction=trade["side"], price=trade["entry_price"]),
        transition("entry-transition", signal, "WAITING_LTF_ENTRY", "ENTRY_TRIGGERED", "Closed 5M confirmation"),
        event("risk", "RISK_VALIDATION", signal, "5M", "RISK", "Risk validation passed", "Structural stop, fixed 1.5R target, and modeled-cost R:R passed.", decision="PASSED"),
        transition("risk-transition", signal, "ENTRY_TRIGGERED", "RISK_VALIDATION", "Risk checks passed"),
        event("plan", "ENTRY_PLAN", signal, "5M", "ENTRY", "FVG pullback plan", "Entry, structural stop, and target were fixed before the next bar opened.", direction=trade["side"], priceRange={"timeStart": signal // 1000, "timeEnd": trade["entry_time"] // 1000, "priceLow": min(trade["entry_price"], trade["stop_loss"]), "priceHigh": max(trade["entry_price"], trade["stop_loss"])}, price=trade["entry_price"], riskDistance=abs(trade["entry_price"] - trade["stop_loss"]), expectedRiskReward=setup["net_expected_rr"]),
        event("stop", "STOP_LOSS", trade["entry_time"], "5M", "RISK", "Structural stop", "Stop is the known 5M sweep extreme.", direction=trade["side"], price=trade["stop_loss"]),
        event("target", "TAKE_PROFIT", trade["entry_time"], "5M", "TRADE", "Fixed 1.5R target", "V1 uses one frozen target model known at entry.", direction=trade["side"], price=trade["take_profits"][0]),
        event("open", "TRADE_OPEN", trade["entry_time"], "5M", "TRADE", "Trade opened", "Entry filled at the next 5M open.", direction=trade["side"], price=trade["entry_price"]),
        transition("open-transition", trade["entry_time"], "RISK_VALIDATION", "TRADE_OPEN", "Position opened"),
        event("close", "TRADE_CLOSED", trade["exit_time"], "5M", "TRADE", "Trade closed", trade["exit_reason"], direction=trade["side"], price=trade["exit_price"]),
        transition("close-transition", trade["exit_time"], "TRADE_OPEN", "TRADE_CLOSED", f"Position closed: {trade['exit_reason']}"),
    ]


def run_fvg_symbol(run_id: str, symbol: str, data: dict[str, Any], start: int, end: int, cost: CostModel | None = None) -> dict[str, Any]:
    candles: list[Candle] = data["candles"]
    funding: list[FundingEvent] = data["funding"]
    hourly, quarter_hourly = resample_closed(candles, 3_600_000), resample_closed(candles, 900_000)
    gaps = [dict(item) for item in detect_fvgs(quarter_hourly, end - 1, symbol) if start <= int(item["formed_at"]) < end]
    states = {item["fvg_id"]: {**item, "status": "FORMED", "touched_at": None, "penetration_pct": 0.0, "age_at_touch_ms": None, "sweep_at": None, "confirmation_at": None} for item in gaps}
    trades, events = [], []
    funnel = {"fvgs_formed": len(gaps), "fvgs_touched": 0, "fvgs_expired": 0, "fvgs_invalidated": 0, "confirmations": 0, "entries": 0, "rejected_entries": 0, "long_entries": 0, "short_entries": 0}
    active: dict[str, Any] | None = None
    sweep_bar: Candle | None = None
    index = 0
    while index < len(candles) - 1:
        bar = candles[index]
        if bar.close_time < start or bar.close_time >= end:
            index += 1
            continue
        bias = hourly_bias(bar.close_time, hourly)
        if active is None and bias["direction"] in {"BULLISH", "BEARISH"}:
            candidates = [item for item in states.values() if item["status"] == "FORMED" and item["direction"] == bias["direction"] and item["available_at"] <= bar.close_time <= item["expires_at"]]
            if candidates:
                active = max(candidates, key=lambda item: (item["formed_at"], item["fvg_id"]))
                active["bias_observed_through"] = bias["observed_through"]
        if active is None:
            index += 1
            continue
        if bar.close_time > active["expires_at"]:
            active["status"] = "EXPIRED"; funnel["fvgs_expired"] += 1; active = None; sweep_bar = None; index += 1; continue
        if active["status"] == "TOUCHED" and bias["direction"] != active["direction"]:
            active["status"] = "INVALIDATED_BIAS"; funnel["fvgs_invalidated"] += 1; funnel["rejected_entries"] += 1; active = None; sweep_bar = None; index += 1; continue
        if active["status"] == "FORMED" and bar.open_time > active["formed_at"] and fvg_touched(active, bar):
            active["touched_at"] = bar.close_time
            active["penetration_pct"] = fill_percentage(active, bar) * 100
            active["age_at_touch_ms"] = bar.close_time - active["formed_at"]
            active["status"] = "TOUCHED"
            funnel["fvgs_touched"] += 1
        if active["status"] == "TOUCHED" and fvg_invalidated(active, bar):
            active["status"] = "INVALIDATED_FULL_FILL"; funnel["fvgs_invalidated"] += 1; funnel["rejected_entries"] += 1; active = None; sweep_bar = None; index += 1; continue
        if active and active["status"] == "TOUCHED":
            side: Side = "LONG" if active["direction"] == "BULLISH" else "SHORT"
            if sweep_bar is None and local_sweep(side, bar, candles[max(0, index - 3):index]):
                sweep_bar = bar
                active["sweep_at"] = bar.close_time
                active["sweep_price"] = bar.low if side == "LONG" else bar.high
            elif sweep_bar is not None and bar.open_time > sweep_bar.close_time and confirms_structure(side, bar, sweep_bar):
                active["confirmation_at"] = bar.close_time
                funnel["confirmations"] += 1
                entry_time, entry = next_open(candles, index)
                stop = structural_stop(side, sweep_bar)
                target = fixed_r_target(side, entry, stop)
                net_rr = expected_net_rr(side, entry, stop, target, cost or CostModel())
                valid = (stop < entry < target if side == "LONG" else target < entry < stop) and net_rr >= MIN_NET_EXPECTED_RR and entry_time < end
                if not valid:
                    active["status"] = "REJECTED_RISK"; active["net_expected_rr"] = net_rr; funnel["rejected_entries"] += 1; active = None; sweep_bar = None; index += 1; continue
                trade, exit_index = simulate_trade(run_id, symbol, side, candles, index + 1, bar, sweep_bar, target, funding, data["dataset_version"], cost or CostModel())
                active["status"] = "TRADED"
                active["net_expected_rr"] = net_rr
                active["time_touch_to_confirmation_ms"] = bar.close_time - active["touched_at"]
                active["room_to_target"] = abs(target - entry)
                trade["fvg_setup"] = {key: value for key, value in active.items() if key != "originating_displacement"}
                active["trade_id"] = trade["trade_id"]
                active["mae"] = trade["mae"]; active["mfe"] = trade["mfe"]; active["exit_reason"] = trade["exit_reason"]
                trades.append(trade); events.extend(fvg_events(trade))
                funnel["entries"] += 1; funnel["long_entries" if side == "LONG" else "short_entries"] += 1
                active = None; sweep_bar = None; index = exit_index + 1; continue
        index += 1
    for value in states.values():
        if value["status"] == "FORMED" and value["expires_at"] < end:
            value["status"] = "EXPIRED"; funnel["fvgs_expired"] += 1
    return {"symbol": symbol, "trades": trades, "events": events, "funnel": funnel, "fvg_records": list(states.values()), "candles": candles, "hourly": hourly, "quarter_hourly": quarter_hourly}


def replay_artifact(run_id: str, result: dict[str, Any], evaluation_start: int) -> dict[str, Any] | None:
    if not result["trades"]:
        return None
    trade = result["trades"][0]
    start, end = trade["fvg_setup"]["formed_at"] - 3_600_000, trade["exit_time"] + 3_600_000
    series_rows = {
        "1H": [bar for bar in result["hourly"] if bar.close_time <= end][-48:],
        "15M": [bar for bar in result["quarter_hourly"] if start <= bar.open_time <= end],
        "5M": [bar for bar in result["candles"] if start <= bar.open_time <= end],
    }
    if any(not rows for rows in series_rows.values()):
        return None
    def series(timeframe: str, rows: list[Candle]) -> dict[str, Any]:
        return {"symbol": result["symbol"], "timeframe": timeframe, "candles": [{"timestamp": row.close_time // 1000, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume} for row in rows]}
    available = list(series_rows.values())
    events = [event for event in result["events"] if event["id"].startswith(f"{trade['trade_id']}-")]
    return {"id": f"replay-{trade['trade_id']}", "runId": run_id, "symbol": result["symbol"], "strategyId": STRATEGY_ID, "strategyVersion": STRATEGY_VERSION, "profile": PROFILE, "source": "BACKTEST", "evaluationStartTimestamp": evaluation_start // 1000, "startTimestamp": min(rows[0].close_time for rows in available) // 1000, "endTimestamp": max(rows[-1].close_time for rows in available) // 1000, "series": [series(key, rows) for key, rows in series_rows.items()], "events": events}


def triage_family(version_id: str, source_run: str, state_root: Path, datasets: dict[str, dict[str, Any]], start: int, end: int, tiers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = state_root / "research" / version_id / source_run
    trades = read_jsonl(root / "trades" / "dev.jsonl")
    summary = metrics(trades)
    symbols = sorted(datasets)
    symbol_rows = [{"symbol": symbol, **metrics([trade for trade in trades if trade["symbol"] == symbol])} for symbol in symbols]
    breadth = expanded_breadth(symbol_rows, (end - start) / (7 * DAY_MS))
    features = []
    for trade in trades:
        candles = datasets[trade["symbol"]]["candles"]
        features.append(feature_row(trade, candles, resample_closed(candles, 3_600_000), resample_closed(candles, DAY_MS), tiers[trade["symbol"]], start))
    temporal = temporal_slice(trades, start, end)
    gross_expectancy = sum(float(trade["gross_pnl"]) for trade in trades) / len(trades) if trades else 0.0
    decision = triage_decision(gross_expectancy, summary["expectancy"], summary["trade_count"], breadth["top_symbol_pnl_share"], temporal["flag"])
    return {
        "family": version_id.removesuffix("_V1"), "source_version": version_id, "source_run": source_run,
        "decision": decision, "gross_expectancy": gross_expectancy, "net_expectancy": summary["expectancy"],
        "cost_burden": {"fees": summary["fees_total"], "spread": summary["spread_total"], "slippage": summary["slippage_total"], "funding": summary["funding_total"]},
        "long_short": {"LONG": summary["LONG"], "SHORT": summary["SHORT"]}, "mae": summary["MAE"], "mfe": summary["MFE"],
        "exit_distribution": dict(sorted(Counter(str(trade["exit_reason"]) for trade in trades).items())),
        "regime_performance": {"market": grouped(features, "regime"), "volatility": grouped(features, "volatility_regime"), "range_phase": grouped(features, "range_phase")},
        "symbol_breadth": breadth, "symbol_metrics": symbol_rows, "temporal_concentration": temporal,
        "oos_access": "OOS_NOT_ACCESSED", "source_oos_artifacts_ignored": True,
    }


def resource_plan(start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str, source_run: str = SOURCE_RESEARCH_RUN) -> dict[str, Any]:
    snapshot, provenance = stratified_universe(BridgeClient(bridge_url).universe(), start, end, "A")
    symbols = [item["symbol"] for item in snapshot]
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, end, DAY_MS))
    candle_parts = [(symbol, day) for symbol in symbols for day in days]
    cached_candles = sum((cache_root / "binance-usdm-v1" / symbol / "5m" / f"{datetime.fromtimestamp(day / 1000, UTC):%Y-%m-%d}.jsonl.gz").exists() for symbol, day in candle_parts)
    cached_funding = sum((cache_root / "binance-usdm-v1" / symbol / "funding" / f"{start}-{end}.json").exists() for symbol in symbols)
    total_requests = len(candle_parts) + len(symbols)
    identity = {"engine": ENGINE_VERSION, "strategy": VERSION_ID, "development": {"start": start, "end": end}, "universe_snapshot": snapshot, "source_triage_run": source_run, "cost": asdict(CostModel()), "rules": {"expiry_ms": FVG_EXPIRY_MS, "target_r": TARGET_R, "minimum_net_rr": MIN_NET_EXPECTED_RR}}
    run_id = f"d4_4_{stable_digest(identity)[:16]}"
    return {"run_id": run_id, "identity_hash": stable_digest(identity), "engine_version": ENGINE_VERSION, "strategy": VERSION_ID, "stage": "A", "development_window": {"start": start, "end": end}, "warmup_start": start - 3 * DAY_MS, "symbol_count": len(symbols), "symbols": symbols, "universe_snapshot": snapshot, "universe_provenance": provenance, "approximate_5m_candles": len(symbols) * ((end - start) // 300_000), "expected_jobs": len(symbols) + len(TRIAGE_FAMILIES), "cache": {"cached_partitions": cached_candles + cached_funding, "total_partitions": total_requests, "hit_rate": (cached_candles + cached_funding) / total_requests if total_requests else 1.0}, "estimated_network_requests": total_requests - cached_candles - cached_funding, "worker_count": max(1, min(8, workers)), "source_triage_run": source_run, "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False}


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = state_root / "research-runs" / plan["run_id"]
    path = root / "resource-plan.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8"))["identity_hash"] != plan["identity_hash"]:
            raise ValueError("immutable D4.4 plan collision")
    else:
        atomic_json(path, plan)
    return root


class PacedBridgeClient(BridgeClient):
    def get(self, path: str, **params: object) -> dict[str, Any]:
        time.sleep(.25)
        return super().get(path, **params)


def load_datasets_paced(symbols: list[str], start: int, end: int, cache_root: Path, bridge_url: str) -> dict[str, dict[str, Any]]:
    values = {}
    for symbol in symbols:
        store = HistoricalDataStore(cache_root, PacedBridgeClient(bridge_url))
        candles, manifests = store.candles(symbol, "5m", start - 3 * DAY_MS, end)
        values[symbol] = {"candles": candles, "funding": store.funding(symbol, start, end), "dataset_version": stable_digest([item["dataset_id"] for item in manifests])}
    return values


def execute(run_id: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    run_root = state_root / "research-runs" / run_id
    plan = json.loads((run_root / "resource-plan.json").read_text(encoding="utf-8"))
    complete_path = run_root / "d4.4-run.json"
    if complete_path.exists():
        result = json.loads(complete_path.read_text(encoding="utf-8"))
        if result["identity_hash"] != plan["identity_hash"]:
            raise ValueError("immutable D4.4 run collision")
        return {"run_id": run_id, "status": "ALREADY_COMPLETED", "artifact": str(run_root.resolve()), "gate_status": result["fvg_gate_status"]}

    start, end = plan["development_window"]["start"], plan["development_window"]["end"]
    datasets = load_datasets_paced(plan["symbols"], start, end, cache_root, bridge_url)
    source_manifest = json.loads((state_root / "research-runs" / plan["source_triage_run"] / "manifest.json").read_text(encoding="utf-8"))
    triage_start, triage_end = source_manifest["dev_window"]["start"], source_manifest["dev_window"]["end"]
    triage_symbols = source_manifest["universe_snapshot"]
    triage_data = load_datasets_paced(triage_symbols, triage_start, triage_end, cache_root, bridge_url)
    tier_lookup = {item["symbol"]: {"tier": item["tier"], "onboard_date": item["onboard_date"]} for item in plan["universe_snapshot"]}
    triage_tiers = {symbol: {"tier": "SOURCE_UNIVERSE", "onboard_date": 0} for symbol in triage_symbols}
    triage = [triage_family(family, plan["source_triage_run"], state_root, triage_data, triage_start, triage_end, triage_tiers) for family in TRIAGE_FAMILIES]
    triage_identity = {"engine": ENGINE_VERSION, "source_run": plan["source_triage_run"], "source_dev_hashes": {family: stable_digest(read_jsonl(state_root / "research" / family / plan["source_triage_run"] / "trades" / "dev.jsonl")) for family in TRIAGE_FAMILIES}}
    triage_id = f"d4_4_{stable_digest(triage_identity)[:16]}"
    triage_root = state_root / "triage" / triage_id
    triage_root.mkdir(parents=True, exist_ok=True)
    triage_artifact = {"triage_id": triage_id, "identity_hash": stable_digest(triage_identity), "status": "COMPLETED", "method": "IMMUTABLE_V1_DEVELOPMENT_TRADE_FORENSICS", "families": triage, "oos_access": "OOS_NOT_ACCESSED", "source_oos_artifacts_ignored": True}
    atomic_json(triage_root / "remaining-families.json", triage_artifact)
    report = ["# D4.4 Remaining Family Triage", "", "Only immutable V1 Development trades were read. OOS artifacts were ignored.", ""]
    report.extend(f"- `{item['family']}`: **{item['decision']}** — gross expectancy {item['gross_expectancy']:.4f}, net expectancy {item['net_expectancy']:.4f}." for item in triage)
    atomic_text(triage_root / "triage-report.md", "\n".join(report) + "\n")

    results = [run_fvg_symbol(f"{run_id}:{VERSION_ID}:DEV", symbol, datasets[symbol], start, end) for symbol in plan["symbols"]]
    trades = [trade for result in results for trade in result["trades"]]
    summary = metrics(trades)
    stress = cost_stress(trades)
    symbol_rows = [{"symbol": result["symbol"], **metrics(result["trades"])} for result in results]
    breadth = expanded_breadth(symbol_rows, (end - start) / (7 * DAY_MS))
    temporal = temporal_slice(trades, start, end)
    features = []
    for trade in trades:
        candles = datasets[trade["symbol"]]["candles"]
        features.append(feature_row(trade, candles, resample_closed(candles, 3_600_000), resample_closed(candles, DAY_MS), tier_lookup[trade["symbol"]], start))
    regimes = {"by_tier": grouped(features, "market_tier"), "by_market_regime": grouped(features, "regime"), "by_volatility_regime": grouped(features, "volatility_regime"), "by_range_phase": grouped(features, "range_phase")}
    equity = reference_equity(trades, STARTING_EQUITY)
    funnel = {key: sum(int(result["funnel"][key]) for result in results) for key in results[0]["funnel"]} if results else {}
    for result in results:
        for record in result["fvg_records"]:
            record["age_ms"] = min(end, int(record["expires_at"])) - int(record["formed_at"])
    gates = {"POSITIVE_NET_EXPECTANCY": summary["expectancy"] > 0, "PF_AT_LEAST_1_1": summary["profit_factor"] >= 1.1, "REFERENCE_DD_AT_MOST_25": equity["portfolio_max_drawdown_pct"] <= 25, "AT_LEAST_20_TRADES": summary["trade_count"] >= 20, "REASONABLE_BREADTH": breadth["profitable_symbol_count"] >= 2, "NO_EXTREME_CONCENTRATION": breadth["top_symbol_pnl_share"] <= .60, "TEMPORAL_STABILITY": temporal["positive_segment_count"] > 1 and temporal["max_positive_pnl_segment_share"] <= .60, "COST_SURVIVAL": all(value["metrics"]["expectancy"] > 0 for value in stress.values())}
    passed = all(gates.values())
    status = "DEVELOPMENT_PROMISING" if passed else "RESEARCH_REJECTED"
    artifact_id = run_id
    output = state_root / "research" / VERSION_ID / artifact_id
    replay = next((value for result in results if (value := replay_artifact(run_id, result, start)) is not None), None)
    manifest = {"identity_hash": plan["identity_hash"], "research_run_id": run_id, "strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION, "label": "NEW RESEARCH HYPOTHESIS", "validation": "NOT VALIDATED", "phase": "DEVELOPMENT ONLY", "profile": PROFILE, "hypothesis": "Trade a same-direction retracement into a canonical closed-15M FVG after closed-1H structure bias and closed-5M sweep-plus-MSS confirmation.", "rules": {"hourly_bias": "two fully closed 1H bars: HH+HL bullish, LH+LL bearish, otherwise neutral", "fvg": "canonical three closed 15M candles", "expiry_ms": FVG_EXPIRY_MS, "confirmation": "closed 5M local three-bar sweep/reclaim then later closed 5M break of sweep-candle structural extreme", "entry": "next 5M open", "stop": "5M sweep extreme", "target": f"fixed {TARGET_R}R", "minimum_net_expected_rr": MIN_NET_EXPECTED_RR, "m1_execution": "DEFERRED_NOT_IMPLEMENTED"}, "config_hash": stable_digest({"profile": PROFILE, "expiry": FVG_EXPIRY_MS, "target_r": TARGET_R, "minimum_net_rr": MIN_NET_EXPECTED_RR}), "dataset_version": stable_digest(sorted(item["dataset_version"] for item in datasets.values())), "cost_model": asdict(CostModel()), "execution_model_version": "next-5m-open-market-v1", "development_window": plan["development_window"], "universe_snapshot": plan["universe_snapshot"], "status": status, "gates": gates, "return_metric_type": "AGGREGATE_NORMALIZED_TRADE_RETURN_AND_SEPARATE_REFERENCE_PORTFOLIO_EQUITY_RETURN", "drawdown_metric_type": "AGGREGATE_FIXED_NOTIONAL_DECLINE_AND_SEPARATE_PEAK_TO_TROUGH_EQUITY_DRAWDOWN", "capital_model": equity["capital_model"], "starting_equity": STARTING_EQUITY, "position_notional_model": equity["position_notional_model"], "compounding": False, "bankruptcy_behavior": equity["bankruptcy_behavior"], "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False}
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "manifest.json", manifest)
    atomic_json(output / "dev-summary.json", {**summary, "reference_equity": {key: value for key, value in equity.items() if key != "equity_curve"}})
    atomic_json(output / "fvg-funnel.json", funnel)
    atomic_json(output / "fvg-records.json", [record for result in results for record in result["fvg_records"]])
    atomic_json(output / "long-short.json", {"LONG": summary["LONG"], "SHORT": summary["SHORT"]})
    atomic_json(output / "symbol-breadth.json", {**breadth, "symbol_metrics": symbol_rows})
    atomic_json(output / "temporal-stability.json", temporal)
    atomic_json(output / "regime-analysis.json", regimes)
    atomic_json(output / "cost-stress.json", stress)
    atomic_json(output / "gate-result.json", {"gates": gates, "passed": passed, "status": status, "oos_access": "OOS_NOT_ACCESSED"})
    jsonl(output / "trades" / "dev.jsonl", trades)
    if replay:
        atomic_json(output / "replay.json", replay)
    atomic_json(output / "replay-links.json", {"available": replay is not None, "run_id": replay["runId"] if replay else None, "route": f"/backtest/replay/{replay['runId']}" if replay else None})
    strategy = {"source": "RESEARCH_CANDIDATE" if passed else "RESEARCH_REJECTED", "researchRunId": run_id, "strategyId": STRATEGY_ID, "strategyVersion": STRATEGY_VERSION, "name": "FVG Pullback", "family": STRATEGY_ID, "configHash": manifest["config_hash"][:12], "codeCommit": "WORKSPACE_NO_GIT", "datasetVersion": manifest["dataset_version"][:16], "feeModelVersion": CostModel().version, "profile": PROFILE, "directionSupport": "BOTH", "directionValidity": "BOTH_VALID" if summary["LONG"]["expectancy"] > 0 and summary["SHORT"]["expectancy"] > 0 else "LONG_ONLY_VALID" if summary["LONG"]["expectancy"] > 0 else "SHORT_ONLY_VALID" if summary["SHORT"]["expectancy"] > 0 else "NOT_VALID", "lifecycle": {"stage": "RESEARCH_READY" if passed else "RESEARCH_REJECTED", "backtest": "PASSED" if summary["expectancy"] > 0 else "FAILED", "oos": "NOT_STARTED", "walkForward": "NOT_STARTED", "shadow": "NOT_STARTED", "canary": "NOT_STARTED", "real": "NOT_STARTED"}, "metrics": dashboard_metrics(summary), "robustnessScore": round(100 * sum(gates.values()) / len(gates), 2), "devExpectancy": summary["expectancy"], "rejectionReasons": [key for key, value in gates.items() if not value], "replayRunId": replay["runId"] if replay else None}
    atomic_json(output / "strategy.json", strategy)
    result = {"identity_hash": plan["identity_hash"], "runId": run_id, "status": "COMPLETED", "triageId": triage_id, "fvgArtifact": str(output.resolve()), "fvgGateStatus": status, "fvg_gate_status": status, "oosAccess": "OOS_NOT_ACCESSED", "lockedOosResolvedOrRead": False}
    atomic_json(complete_path, result)
    atomic_json(run_root / "manifest.json", {"identity_hash": plan["identity_hash"], "run_id": run_id, "status": "COMPLETED", "triage_id": triage_id, "strategy_artifact": str(output.resolve()), "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False})
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.4 triage and FVG Development research")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--dev-start", required=True); plan.add_argument("--dev-end", required=True)
    plan.add_argument("--workers", type=int, default=3); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market"); plan.add_argument("--source-run", default=SOURCE_RESEARCH_RUN)
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
            value = resource_plan(start, end, args.workers, state_root, cache_root, bridge_url, args.source_run)
            save_plan(value, state_root)
        else:
            value = execute(args.run_id, state_root, cache_root, bridge_url)
        print(json.dumps(value, sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
