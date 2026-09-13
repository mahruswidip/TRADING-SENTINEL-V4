from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Protocol

from . import ENGINE_VERSION, STRATEGY_ID, STRATEGY_LABEL, STRATEGY_VERSION
from .data import INTERVAL_MS, gap_count
from .model import Candle, CostModel, Decision, FundingEvent, Side, Trade


def resample_closed(candles: list[Candle], target_ms: int) -> list[Candle]:
    source_ms = INTERVAL_MS["5m"]
    required = target_ms // source_ms
    groups: dict[int, list[Candle]] = {}
    for candle in candles:
        groups.setdefault(candle.open_time - candle.open_time % target_ms, []).append(candle)
    result = []
    for start, rows in sorted(groups.items()):
        rows.sort(key=lambda item: item.open_time)
        end = start + target_ms - 1
        if len(rows) != required or rows[0].open_time != start or rows[-1].close_time < end or gap_count(rows, source_ms):
            continue
        result.append(Candle(start, rows[0].open, max(item.high for item in rows), min(item.low for item in rows), rows[-1].close, sum(item.volume for item in rows), end))
    return result


def closed_at(candles: list[Candle], timestamp: int) -> list[Candle]:
    return [candle for candle in candles if candle.close_time <= timestamp]


def funding_cost(side: Side, notional: float, entry_time: int, exit_time: int, events: list[FundingEvent]) -> tuple[float, tuple[dict[str, float | int], ...]]:
    applied = tuple({"timestamp": event.timestamp, "rate": event.rate, "cost": notional * event.rate * (1 if side == "LONG" else -1)} for event in events if entry_time < event.timestamp <= exit_time)
    return sum(float(item["cost"]) for item in applied), applied


def calculate_net(gross_pnl: float, entry_fee: float, exit_fee: float, funding: float, spread: float, slippage: float) -> float:
    return gross_pnl - entry_fee - exit_fee - funding - spread - slippage


class StrategyEngine(Protocol):
    strategy_id: str
    strategy_version: str
    def prepare(self, candles: list[Candle]) -> None: ...
    def evaluate_bias(self, now: int, daily: list[Candle]) -> Decision: ...
    def evaluate_structure(self, now: int, hourly: list[Candle], bias: Decision) -> Decision: ...
    def evaluate_entry(self, signal_bar: Candle, structure: Decision) -> Decision: ...
    def build_trade_plan(self, side: Side, entry: float, recent: list[Candle]) -> tuple[float, float]: ...
    def invalidate(self, side: Side, price: float, stop: float) -> bool: ...


class ReferenceIntradayStrategy:
    """Engineering-only deterministic rule set; not a validated trading strategy."""

    strategy_id = STRATEGY_ID
    strategy_version = STRATEGY_VERSION
    label = STRATEGY_LABEL

    def prepare(self, candles: list[Candle]) -> None:
        if not candles: raise ValueError("strategy requires candles")

    def evaluate_bias(self, now: int, daily: list[Candle]) -> Decision:
        known = closed_at(daily, now)
        return "WAIT" if not known or known[-1].close == known[-1].open else "LONG" if known[-1].close > known[-1].open else "SHORT"

    def evaluate_structure(self, now: int, hourly: list[Candle], bias: Decision) -> Decision:
        known = closed_at(hourly, now)
        if not known or bias not in {"LONG", "SHORT"}: return "WAIT"
        side = "LONG" if known[-1].close > known[-1].open else "SHORT"
        return side if side == bias else "WAIT"

    def evaluate_entry(self, signal_bar: Candle, structure: Decision) -> Decision:
        bar_side: Side = "LONG" if signal_bar.close > signal_bar.open else "SHORT"
        body_bps = abs(signal_bar.close - signal_bar.open) / signal_bar.open * 10_000 if signal_bar.open else 0
        return bar_side if structure == bar_side and body_bps >= 2 else "WAIT"

    def signal(self, now: int, signal_bar: Candle, hourly: list[Candle], daily: list[Candle]) -> Decision:
        return self.evaluate_entry(signal_bar, self.evaluate_structure(now, hourly, self.evaluate_bias(now, daily)))

    def build_trade_plan(self, side: Side, entry: float, recent: list[Candle]) -> tuple[float, float]:
        risk = max(sum(bar.high - bar.low for bar in recent) / len(recent), entry * 0.001)
        return (entry - risk, entry + 1.5 * risk) if side == "LONG" else (entry + risk, entry - 1.5 * risk)

    def invalidate(self, side: Side, price: float, stop: float) -> bool:
        return price <= stop if side == "LONG" else price >= stop


def run_symbol(run_id: str, symbol: str, candles: list[Candle], funding: list[FundingEvent], dataset_version: str, cost: CostModel, start: int, end: int, strategy: StrategyEngine | None = None) -> dict[str, Any]:
    hourly, daily = resample_closed(candles, 3_600_000), resample_closed(candles, 86_400_000)
    strategy = strategy or ReferenceIntradayStrategy()
    strategy.prepare(candles)
    trades: list[Trade] = []
    events: list[dict[str, Any]] = []
    funnel = {"htf_contexts_found": 0, "mtf_structures_confirmed": 0, "ltf_entry_setups": 0, "entry_triggers": 0, "risk_accepted": 0, "trades_opened": 0, "trades_closed": 0, "rejected": 0, "wait": 0}
    index = 0
    while index < len(candles) - 1:
        signal_bar = candles[index]
        if signal_bar.close_time < start or signal_bar.close_time >= end:
            index += 1
            continue
        known_days, known_hours = closed_at(daily, signal_bar.close_time), closed_at(hourly, signal_bar.close_time)
        if not known_days:
            funnel["wait"] += 1; index += 1; continue
        funnel["htf_contexts_found"] += 1
        if not known_hours:
            funnel["wait"] += 1; index += 1; continue
        funnel["mtf_structures_confirmed"] += 1
        side = strategy.signal(signal_bar.close_time, signal_bar, hourly, daily)
        if side not in {"LONG", "SHORT"}:
            funnel["wait"] += 1; index += 1; continue
        funnel["ltf_entry_setups"] += 1; funnel["entry_triggers"] += 1; funnel["risk_accepted"] += 1
        entry_index = index + 1
        entry_bar = candles[entry_index]
        entry = entry_bar.open
        stop, target = strategy.build_trade_plan(side, entry, candles[max(0, index - 11): index + 1])
        risk = abs(entry - stop)
        exit_price, exit_time, reason, resolution, exit_index = entry, entry_bar.close_time, "END_OF_DATA", "FAST_CLOSE", entry_index
        observed = candles[entry_index:min(len(candles), entry_index + 24)]
        for offset, bar in enumerate(observed):
            stop_hit = bar.low <= stop if side == "LONG" else bar.high >= stop
            target_hit = bar.high >= target if side == "LONG" else bar.low <= target
            if stop_hit and target_hit:
                exit_price, exit_time, reason, resolution, exit_index = stop, bar.close_time, "INTRABAR_AMBIGUOUS", "FAST_WORST_CASE", entry_index + offset; break
            if stop_hit:
                exit_price, exit_time, reason, resolution, exit_index = stop, bar.close_time, "STOP_LOSS", "FAST_OHLC", entry_index + offset; break
            if target_hit:
                exit_price, exit_time, reason, resolution, exit_index = target, bar.close_time, "TAKE_PROFIT", "FAST_OHLC", entry_index + offset; break
            exit_price, exit_time, exit_index = bar.close, bar.close_time, entry_index + offset
        notional = 1_000.0
        direction = 1 if side == "LONG" else -1
        gross_return = direction * (exit_price - entry) / entry
        gross_pnl = notional * gross_return
        entry_fee = exit_fee = notional * cost.taker_bps / 10_000
        funding_value, funding_rows = funding_cost(side, notional, entry_bar.open_time, exit_time, funding)
        spread_cost = notional * cost.spread_bps / 10_000
        slippage_cost = notional * cost.slippage_bps / 10_000
        net_pnl = calculate_net(gross_pnl, entry_fee, exit_fee, funding_value, spread_cost, slippage_cost)
        evaluated = observed[:exit_index - entry_index + 1]
        favorable = max(((bar.high - entry) / entry if side == "LONG" else (entry - bar.low) / entry) for bar in evaluated)
        adverse = min(((bar.low - entry) / entry if side == "LONG" else (entry - bar.high) / entry) for bar in evaluated)
        trade_id = hashlib.sha256(f"{run_id}:{strategy.strategy_id}:{strategy.strategy_version}:{symbol}:{entry_bar.open_time}:{side}".encode()).hexdigest()[:20]
        trade = Trade(trade_id, run_id, symbol, side, strategy.strategy_id, strategy.strategy_version, signal_bar.close_time, entry_bar.open_time, exit_time, entry, exit_price, stop, (target,), notional, gross_return, gross_pnl, entry_fee, exit_fee, funding_value, funding_rows, spread_cost, slippage_cost, net_pnl / notional, net_pnl, gross_pnl / (notional * risk / entry), adverse, favorable, reason, exit_time - entry_bar.open_time, dataset_version, cost.version, "next-open-market-v1", resolution)
        trades.append(trade); funnel["trades_opened"] += 1; funnel["trades_closed"] += 1
        events.extend(trade_events(trade))
        index = exit_index + 1
    return {"symbol": symbol, "trades": [trade.as_dict() for trade in trades], "events": events, "funnel": funnel, "hourly": hourly, "daily": daily, "candles": candles}


def trade_events(trade: Trade) -> list[dict[str, Any]]:
    base = {"symbol": trade.symbol, "strategyId": trade.strategy_id, "strategyVersion": trade.strategy_version}
    def event(identifier: str, kind: str, timestamp: int, timeframe: str, category: str, label: str, reason: str, **extra: object) -> dict[str, Any]:
        return {**base, "id": f"{trade.trade_id}-{identifier}", "type": kind, "timestamp": timestamp // 1000, "availableAt": timestamp // 1000, "timeframe": timeframe, "category": category, "label": label, "reason": reason, **extra}
    direction = "BULLISH" if trade.side == "LONG" else "BEARISH"
    def transition(identifier: str, timestamp: int, from_state: str, to_state: str, label: str) -> dict[str, Any]:
        return event(identifier, "STATE_TRANSITION", timestamp, "5M", "TRADE", label, label, fromState=from_state, toState=to_state)
    return [
        transition("context-transition", trade.signal_time, "SCANNING", "HTF_CONTEXT_FOUND", "Closed 1D context found"),
        event("bias", "BIAS_LOCKED", trade.signal_time, "1D", "CONTEXT", f"{trade.side} bias locked", "The strategy used only closed daily context.", direction=direction),
        transition("bias-transition", trade.signal_time, "HTF_CONTEXT_FOUND", "BIAS_LOCKED", "1D bias locked"),
        event("structure", "MSS", trade.signal_time, "1H", "STRUCTURE", f"{trade.side} structure confirmed", "The strategy family confirmed its deterministic closed-1H requirement.", direction=direction, price=trade.entry_price),
        transition("structure-transition", trade.signal_time, "BIAS_LOCKED", "MTF_CONFIRMED", "Closed 1H structure aligned"),
        event("trigger", "ENTRY_TRIGGERED", trade.signal_time, "5M", "ENTRY", f"{trade.side} entry triggered", "The closed 5M bar satisfied the strategy family's mandatory trigger.", direction=trade.side, price=trade.entry_price),
        transition("entry-transition", trade.signal_time, "MTF_CONFIRMED", "ENTRY_TRIGGERED", "5M entry triggered"),
        transition("risk-transition", trade.signal_time, "ENTRY_TRIGGERED", "RISK_VALIDATION", "Reference risk checks passed"),
        event("stop", "STOP_LOSS", trade.entry_time, "5M", "RISK", "Protective stop", "Deterministic volatility-distance stop.", direction=trade.side, price=trade.stop_loss),
        event("target", "TAKE_PROFIT", trade.entry_time, "5M", "TRADE", "Take profit", "Deterministic 1.5R target.", direction=trade.side, price=trade.take_profits[0]),
        event("open", "TRADE_OPEN", trade.entry_time, "5M", "TRADE", "Trade opened", "Next 5M open market execution assumption.", direction=trade.side, price=trade.entry_price),
        transition("open-transition", trade.entry_time, "RISK_VALIDATION", "TRADE_OPEN", "Position opened"),
        event("close", "TRADE_CLOSED", trade.exit_time, "5M", "TRADE", "Trade closed", trade.exit_reason, direction=trade.side, price=trade.exit_price),
        transition("close-transition", trade.exit_time, "TRADE_OPEN", "TRADE_CLOSED", f"Position closed: {trade.exit_reason}"),
    ]


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    def one(rows: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [float(row["net_pnl"]) for row in rows]
        wins, losses = [value for value in pnls if value > 0], [value for value in pnls if value < 0]
        cumulative = peak = drawdown = 0.0
        for pnl in pnls:
            cumulative += pnl; peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
        return {"trade_count": len(rows), "wins": len(wins), "losses": len(losses), "breakeven": len(rows) - len(wins) - len(losses), "win_rate": len(wins) / len(rows) * 100 if rows else 0.0, "gross_return": sum(float(row["gross_return"]) for row in rows) * 100, "net_return": sum(float(row["net_return"]) for row in rows) * 100, "expectancy": sum(pnls) / len(rows) if rows else 0.0, "expectancy_R": sum(float(row["r_multiple"]) for row in rows) / len(rows) if rows else 0.0, "profit_factor": sum(wins) / abs(sum(losses)) if losses else (999.0 if wins else 0.0), "max_drawdown": drawdown / 1_000 * 100, "average_R": sum(float(row["r_multiple"]) for row in rows) / len(rows) if rows else 0.0, "MAE": sum(float(row["mae"]) for row in rows) / len(rows) if rows else 0.0, "MFE": sum(float(row["mfe"]) for row in rows) / len(rows) if rows else 0.0, "net_pnl": sum(pnls)}
    result = one(trades)
    result.update({"fees_total": sum(float(row["entry_fee"]) + float(row["exit_fee"]) for row in trades), "funding_total": sum(float(row["funding_cost"]) for row in trades), "spread_total": sum(float(row["spread_cost"]) for row in trades), "slippage_total": sum(float(row["slippage_cost"]) for row in trades), "LONG": one([row for row in trades if row["side"] == "LONG"]), "SHORT": one([row for row in trades if row["side"] == "SHORT"]), "ambiguous_trades": sum(row["exit_reason"] == "INTRABAR_AMBIGUOUS" for row in trades)})
    return result


def reprice_trade(trade: Trade, exit_price: float, exit_time: int, exit_reason: str, resolution: str, cost: CostModel, funding: list[FundingEvent]) -> Trade:
    direction = 1 if trade.side == "LONG" else -1
    gross_return = direction * (exit_price - trade.entry_price) / trade.entry_price
    gross_pnl = trade.normalized_notional * gross_return
    funding_value, funding_rows = funding_cost(trade.side, trade.normalized_notional, trade.entry_time, exit_time, funding)
    net_pnl = calculate_net(gross_pnl, trade.entry_fee, trade.exit_fee, funding_value, trade.spread_cost, trade.slippage_cost)
    return replace(
        trade,
        exit_price=exit_price,
        exit_time=exit_time,
        gross_return=gross_return,
        gross_pnl=gross_pnl,
        funding_cost=funding_value,
        funding_events=funding_rows,
        net_return=net_pnl / trade.normalized_notional,
        net_pnl=net_pnl,
        r_multiple=gross_pnl / (trade.normalized_notional * abs(trade.entry_price - trade.stop_loss) / trade.entry_price),
        exit_reason=exit_reason,
        duration_ms=exit_time - trade.entry_time,
        cost_model_version=cost.version,
        intrabar_resolution_method=resolution,
    )


def resolve_ambiguous(trade: Trade, minute_bars: list[Candle], cost: CostModel | None = None, funding: list[FundingEvent] | None = None) -> Trade:
    if trade.exit_reason != "INTRABAR_AMBIGUOUS":
        return trade
    model, funding_rows = cost or CostModel(), funding or []
    for bar in minute_bars:
        stop_hit = bar.low <= trade.stop_loss if trade.side == "LONG" else bar.high >= trade.stop_loss
        target_hit = bar.high >= trade.take_profits[0] if trade.side == "LONG" else bar.low <= trade.take_profits[0]
        if stop_hit and target_hit:
            return reprice_trade(trade, trade.stop_loss, bar.close_time, "STOP_LOSS", "ACCURATE_1M_WORST_CASE", model, funding_rows)
        if stop_hit:
            return reprice_trade(trade, trade.stop_loss, bar.close_time, "STOP_LOSS", "ACCURATE_1M", model, funding_rows)
        if target_hit:
            return reprice_trade(trade, trade.take_profits[0], bar.close_time, "TAKE_PROFIT", "ACCURATE_1M", model, funding_rows)
    return trade


def stable_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
