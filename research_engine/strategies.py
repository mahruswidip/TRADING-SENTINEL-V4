from __future__ import annotations

from dataclasses import dataclass, replace

from backtest_engine.engine import closed_at
from backtest_engine.model import Candle, Decision, Side


@dataclass(frozen=True)
class ResearchStrategy:
    family: str
    version: str
    threshold: float
    hypothesis: str
    mandatory: tuple[str, ...]
    wait_condition: str
    rejected_condition: str = "Malformed or unavailable required market data"
    risk_multiplier: float = 1.0
    reward_risk: float = 1.5

    @property
    def strategy_id(self) -> str: return self.family

    @property
    def strategy_version(self) -> str: return self.version

    @property
    def label(self) -> str: return self.family.replace("_", " ").title()

    def neighbor(self, multiplier: float) -> "ResearchStrategy":
        return replace(self, threshold=self.threshold * multiplier)

    def prepare(self, candles: list[Candle]) -> None:
        if not candles: raise ValueError("strategy requires candles")

    @staticmethod
    def _side(candle: Candle) -> Side | None:
        if candle.close == candle.open: return None
        return "LONG" if candle.close > candle.open else "SHORT"

    def evaluate_bias(self, now: int, daily: list[Candle]) -> Decision:
        known = closed_at(daily, now)
        return self._side(known[-1]) or "WAIT" if known else "WAIT"

    def evaluate_structure(self, now: int, hourly: list[Candle], bias: Decision) -> Decision:
        known = closed_at(hourly, now)
        if not known or bias not in {"LONG", "SHORT"}: return "WAIT"
        side = self._side(known[-1])
        return side if side == bias else "WAIT"

    def evaluate_entry(self, signal_bar: Candle, structure: Decision) -> Decision:
        side = self._side(signal_bar)
        body_bps = abs(signal_bar.close - signal_bar.open) / signal_bar.open * 10_000
        return side if side == structure and body_bps >= self.threshold else "WAIT"

    def signal(self, now: int, bar: Candle, hourly: list[Candle], daily: list[Candle]) -> Decision:
        days, hours = closed_at(daily, now), closed_at(hourly, now)
        if not days or not hours: return "WAIT"
        bias, side = self._side(days[-1]), self._side(bar)
        if not bias or not side: return "WAIT"
        hour, prior_hours = hours[-1], hours[:-1]
        body = abs(bar.close - bar.open)
        body_bps = body / bar.open * 10_000
        hour_side = self._side(hour)
        if self.family == "TREND_CONTINUATION":
            return side if bias == hour_side == side and body_bps >= self.threshold else "WAIT"
        if self.family == "PULLBACK_CONTINUATION":
            lower_wick, upper_wick = min(bar.open, bar.close) - bar.low, bar.high - max(bar.open, bar.close)
            rejected = lower_wick >= body * self.threshold if bias == "LONG" else upper_wick >= body * self.threshold
            return side if hour_side == bias == side and rejected else "WAIT"
        if self.family == "BREAKOUT_RETEST":
            if not prior_hours: return "WAIT"
            broke = hour.close > prior_hours[-1].high if bias == "LONG" else hour.close < prior_hours[-1].low
            retest = bar.low <= prior_hours[-1].high if bias == "LONG" else bar.high >= prior_hours[-1].low
            return side if side == bias and broke and retest else "WAIT"
        if self.family == "LIQUIDITY_SWEEP_REVERSAL":
            swept = bar.low < hour.low and bar.close > hour.low if bias == "LONG" else bar.high > hour.high and bar.close < hour.high
            return side if side == bias and swept else "WAIT"
        if self.family == "RANGE_REVERSION":
            day_range = max(days[-1].high - days[-1].low, 1e-12)
            ranging = abs(days[-1].close - days[-1].open) / day_range <= self.threshold
            edge = bar.low <= hour.low * 1.001 if side == "LONG" else bar.high >= hour.high * .999
            return side if ranging and edge else "WAIT"
        if self.family == "COMPRESSION_EXPANSION":
            if len(prior_hours) < 6: return "WAIT"
            average = sum(item.high - item.low for item in prior_hours[-6:]) / 6
            compressed = hour.high - hour.low <= average * self.threshold
            expanded = bar.high - bar.low >= (hour.high - hour.low) / 12 * 1.5
            return side if compressed and expanded and side == bias else "WAIT"
        if self.family == "MOMENTUM_BREAK":
            return side if side == bias == hour_side and body_bps >= self.threshold else "WAIT"
        return "REJECTED"

    def build_trade_plan(self, side: Side, entry: float, recent: list[Candle]) -> tuple[float, float]:
        risk = max(sum(bar.high - bar.low for bar in recent) / len(recent) * self.risk_multiplier, entry * .001)
        return (entry - risk, entry + risk * self.reward_risk) if side == "LONG" else (entry + risk, entry - risk * self.reward_risk)

    def invalidate(self, side: Side, price: float, stop: float) -> bool:
        return price <= stop if side == "LONG" else price >= stop


STRATEGIES: tuple[ResearchStrategy, ...] = (
    ResearchStrategy("TREND_CONTINUATION", "V1", 2.0, "Aligned closed 1D/1H direction persists through a decisive 5M body.", ("Closed 1D bias", "Closed 1H alignment", "5M body >= 2 bps"), "Any alignment or body requirement is absent."),
    ResearchStrategy("PULLBACK_CONTINUATION", "V1", 1.0, "A directional 5M rejection wick resumes an aligned 1D/1H trend.", ("Closed 1D/1H alignment", "Directional rejection wick", "5M close resumes bias"), "No aligned rejection wick."),
    ResearchStrategy("BREAKOUT_RETEST", "V1", 1.0, "A closed 1H breakout followed by a directional 5M retest continues.", ("Closed 1D bias", "Closed 1H breakout", "5M retest and close"), "Breakout or retest is absent."),
    ResearchStrategy("LIQUIDITY_SWEEP_REVERSAL", "V1", 1.0, "A 5M sweep beyond the last closed 1H extreme that closes back inside reverses with 1D bias.", ("Closed 1D bias", "1H extreme sweep", "5M reclaim"), "Sweep does not reclaim the 1H extreme."),
    ResearchStrategy("RANGE_REVERSION", "V1", .35, "Small-body 1D ranges revert from the last closed 1H boundary.", ("Closed 1D body/range <= 0.35", "5M tests 1H edge", "Directional close inward"), "Daily market is not ranging or edge is untouched."),
    ResearchStrategy("COMPRESSION_EXPANSION", "V1", .70, "A compressed closed 1H range expands directionally on 5M with 1D bias.", ("Closed 1H range <= 70% six-hour average", "5M range expansion", "1D directional agreement"), "Compression or expansion is absent."),
    ResearchStrategy("MOMENTUM_BREAK", "V1", 5.0, "Strong 5M momentum continues when closed 1D and 1H direction agree.", ("Closed 1D/1H alignment", "5M body >= 5 bps"), "Momentum threshold or alignment is absent."),
)
