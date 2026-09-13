from __future__ import annotations

from dataclasses import dataclass

from backtest_engine.engine import closed_at
from backtest_engine.model import Candle, Decision, Side
from research_engine.strategies import ResearchStrategy, STRATEGIES

BASE = {strategy.family: strategy for strategy in STRATEGIES}


@dataclass(frozen=True)
class DevelopmentVariant:
    base: ResearchStrategy
    version: str
    allowed_side: Side
    require_daily_uptrend: bool = False

    @property
    def strategy_id(self) -> str: return self.base.strategy_id

    @property
    def strategy_version(self) -> str: return self.version

    def prepare(self, candles: list[Candle]) -> None: self.base.prepare(candles)
    def evaluate_bias(self, now: int, daily: list[Candle]) -> Decision: return self.base.evaluate_bias(now, daily)
    def evaluate_structure(self, now: int, hourly: list[Candle], bias: Decision) -> Decision: return self.base.evaluate_structure(now, hourly, bias)
    def evaluate_entry(self, signal_bar: Candle, structure: Decision) -> Decision: return self.base.evaluate_entry(signal_bar, structure)
    def build_trade_plan(self, side: Side, entry: float, recent: list[Candle]) -> tuple[float, float]: return self.base.build_trade_plan(side, entry, recent)
    def invalidate(self, side: Side, price: float, stop: float) -> bool: return self.base.invalidate(side, price, stop)

    def signal(self, now: int, bar: Candle, hourly: list[Candle], daily: list[Candle]) -> Decision:
        side = self.base.signal(now, bar, hourly, daily)
        if side != self.allowed_side: return "WAIT"
        known = closed_at(daily, now)
        if self.require_daily_uptrend and (len(known) < 2 or known[-1].close <= known[-2].close or known[-1].close <= known[-1].open): return "WAIT"
        return side


VARIANTS = (
    DevelopmentVariant(BASE["BREAKOUT_RETEST"], "V2", "LONG", True),
    DevelopmentVariant(BASE["RANGE_REVERSION"], "V2", "LONG"),
)

HYPOTHESES = {
    "BREAKOUT_RETEST_V2": {
        "observed_problem": "V1 loses outside closed-1D uptrends and SHORT evidence is negative.",
        "evidence": "TRENDING_UP Dev subset: 12 trades, +1.02 net expectancy; V1 SHORT: 14 trades, -0.76 expectancy. Sample remains insufficient.",
        "change": "Allow LONG only and require the latest closed 1D candle to be bullish and close above the previous closed 1D candle.",
        "why": "Specializes the breakout continuation hypothesis to the only prospectively observable regime with positive V1 Dev expectancy.",
        "falsification": "Reject if Development net expectancy <= 0, PF < 1.1, trades < 20, breadth/concentration fails, or any cost stress expectancy <= 0.",
    },
    "RANGE_REVERSION_V2": {
        "observed_problem": "V1 direction is asymmetric; SHORT overwhelms a mildly positive LONG slice.",
        "evidence": "V1 LONG: 39 trades, +0.245 net expectancy and PF 1.057; SHORT: 41 trades, -1.337 expectancy and PF 0.677.",
        "change": "Keep the immutable V1 entry/stop/target logic and permit LONG signals only.",
        "why": "Tests observed direction asymmetry without changing a numeric parameter or consulting OOS.",
        "falsification": "Reject if the unchanged D4 Development gates fail, including PF >= 1.1 and cost survival.",
    },
}
