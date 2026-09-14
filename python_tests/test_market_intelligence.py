from __future__ import annotations

import unittest

from backtest_engine.model import Candle, FundingEvent
from research_engine.market_intelligence import DAY_MS, RegimeInputs, classify_regime, derive_inputs


def inputs(**changes: object) -> RegimeInputs:
    values = {
        "as_of": 1,
        "daily_direction": 1,
        "hourly_direction": 1,
        "hourly_efficiency": 0.55,
        "volume_expansion": 1.4,
        "funding_level": 0.0001,
        "funding_change": 0.0,
        "open_interest_change": 0.03,
        "basis_rate": 0.0002,
        "taker_imbalance": 0.2,
        "missing_features": (),
    }
    values.update(changes)
    return RegimeInputs(**values)  # type: ignore[arg-type]


class MarketIntelligenceTests(unittest.TestCase):
    def test_routes_confirmed_bull_and_bear_trends(self) -> None:
        self.assertEqual(classify_regime(inputs())["route"], "TREND_LONG")
        bearish = inputs(daily_direction=-1, hourly_direction=-1, taker_imbalance=-0.2)
        self.assertEqual(classify_regime(bearish)["route"], "TREND_SHORT")

    def test_routes_quiet_neutral_market_to_range(self) -> None:
        neutral = inputs(daily_direction=0, hourly_direction=0, hourly_efficiency=0.1, volume_expansion=0.8)
        self.assertEqual(classify_regime(neutral)["route"], "RANGE_MEAN_REVERSION")

    def test_waits_without_participant_confirmation(self) -> None:
        result = classify_regime(inputs(open_interest_change=None, taker_imbalance=None))
        self.assertEqual(result["regime"], "AMBIGUOUS")
        self.assertEqual(result["route"], "WAIT")

    def test_waits_when_positioning_is_crowded(self) -> None:
        result = classify_regime(inputs(funding_level=0.001))
        self.assertEqual(result["route"], "WAIT")
        self.assertIn("POSITIONING_CROWDED", result["reasons"])

    def test_waits_when_funding_accelerates_with_the_crowd(self) -> None:
        result = classify_regime(inputs(funding_change=0.0003))
        self.assertEqual(result["route"], "WAIT")
        self.assertIn("POSITIONING_CROWDED", result["reasons"])

    def test_never_authorizes_entry(self) -> None:
        self.assertFalse(classify_regime(inputs())["entry_authorized"])

    def test_future_market_data_cannot_change_current_inputs(self) -> None:
        interval = 300_000
        end = 28 * DAY_MS
        candles = [
            Candle(timestamp, 100 + index * 0.001, 100.06 + index * 0.001, 99.99 + index * 0.001, 100.05 + index * 0.001, 10, timestamp + interval - 1)
            for index, timestamp in enumerate(range(0, end, interval))
        ]
        base = derive_inputs(candles, [FundingEvent(end - 1, 0.0001)], [], [], [], end - 1)
        future = Candle(end, 1, 10_000, 1, 10_000, 1_000_000, end + interval - 1)
        with_future = derive_inputs(candles + [future], [FundingEvent(end - 1, 0.0001), FundingEvent(end + 1, 0.5)], [], [], [], end - 1)
        self.assertEqual(base, with_future)


if __name__ == "__main__":
    unittest.main()
