from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Side = Literal["LONG", "SHORT"]
Decision = Literal["LONG", "SHORT", "WAIT", "REJECTED"]


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int

    @classmethod
    def from_row(cls, row: list[object]) -> "Candle":
        candle = cls(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), int(row[6]))
        if candle.high < candle.low or min(candle.open, candle.high, candle.low, candle.close, candle.volume) < 0:
            raise ValueError("invalid candle")
        return candle

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FundingEvent:
    timestamp: int
    rate: float


@dataclass(frozen=True)
class CostModel:
    version: str = "configured-taker-4bps-modeled-spread-slippage-v1"
    taker_bps: float = 4.0
    spread_bps: float = 2.0
    slippage_bps: float = 1.0
    fee_source: str = "CONFIGURED"
    spread_source: str = "MODELED"
    slippage_source: str = "MODELED"


@dataclass(frozen=True)
class Trade:
    trade_id: str
    run_id: str
    symbol: str
    side: Side
    strategy_id: str
    strategy_version: str
    signal_time: int
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profits: tuple[float, ...]
    normalized_notional: float
    gross_return: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    funding_cost: float
    funding_events: tuple[dict[str, float | int], ...]
    spread_cost: float
    slippage_cost: float
    net_return: float
    net_pnl: float
    r_multiple: float
    mae: float
    mfe: float
    exit_reason: str
    duration_ms: int
    dataset_version: str
    cost_model_version: str
    execution_model_version: str
    intrabar_resolution_method: str

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["take_profits"] = list(self.take_profits)
        value["funding_events"] = list(self.funding_events)
        return value
