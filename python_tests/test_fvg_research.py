from __future__ import annotations

import unittest

from backtest_engine.engine import metrics
from backtest_engine.model import Candle
from research_engine.fvg import (
    FVG_EXPIRY_MS,
    confirms_structure,
    detect_fvgs,
    fill_percentage,
    fixed_r_target,
    fvg_events,
    fvg_invalidated,
    hourly_bias,
    local_sweep,
    next_open,
    oos_guard,
    structural_stop,
    triage_decision,
    PROFILE,
)


def candle(index: int, open_: float, high: float, low: float, close: float, interval: int = 900_000) -> Candle:
    start = index * interval
    return Candle(start, open_, high, low, close, 100, start + interval - 1)


class FvgResearchTests(unittest.TestCase):
    def test_bullish_fvg_is_canonical_and_available_after_third_close(self):
        rows = [candle(0, 9, 10, 8, 9.5), candle(1, 10, 12, 9, 11.5), candle(2, 11.5, 13, 11, 12)]
        self.assertEqual(detect_fvgs(rows, rows[2].close_time - 1), [])
        gap = detect_fvgs(rows, rows[2].close_time)[0]
        self.assertEqual(gap["direction"], "BULLISH")
        self.assertEqual((gap["price_low"], gap["price_high"]), (10, 11))
        self.assertEqual(gap["available_at"], rows[2].close_time)

    def test_bearish_fvg_is_canonical(self):
        rows = [candle(0, 12, 13, 11, 12), candle(1, 11, 12, 9, 9.5), candle(2, 9.5, 10, 8, 9)]
        gap = detect_fvgs(rows, rows[2].close_time)[0]
        self.assertEqual(gap["direction"], "BEARISH")
        self.assertEqual((gap["price_low"], gap["price_high"]), (10, 11))

    def test_hourly_bias_uses_only_closed_hourly_bars(self):
        rows = [candle(0, 10, 11, 9, 10, 3_600_000), candle(1, 11, 12, 10, 11, 3_600_000)]
        self.assertEqual(hourly_bias(rows[1].close_time - 1, rows)["direction"], "NEUTRAL")
        before = hourly_bias(rows[1].close_time, rows)
        future = candle(2, 11, 50, 1, 5, 3_600_000)
        self.assertEqual(before["direction"], "BULLISH")
        self.assertEqual(before, hourly_bias(rows[1].close_time, rows + [future]))

    def test_closed_5m_sweep_then_later_mss_and_next_open(self):
        rows = [candle(0, 10, 11, 9, 10, 300_000), candle(1, 10, 11, 9.2, 10, 300_000), candle(2, 10, 11, 9.1, 10, 300_000), candle(3, 10, 10.5, 8.8, 9.5, 300_000), candle(4, 9.5, 11.2, 9.4, 11.1, 300_000), candle(5, 11.1, 11.5, 11, 11.3, 300_000)]
        self.assertTrue(local_sweep("LONG", rows[3], rows[:3]))
        self.assertTrue(confirms_structure("LONG", rows[4], rows[3]))
        entry_time, entry = next_open(rows, 4)
        self.assertEqual(entry_time, rows[5].open_time)
        self.assertEqual(entry, rows[5].open)
        self.assertGreater(entry_time, rows[4].close_time)

    def test_fvg_invalidation_expiry_stop_and_target_are_deterministic(self):
        gap = {"direction": "BULLISH", "price_low": 10.0, "price_high": 11.0, "size": 1.0}
        touched = candle(4, 12, 12, 10.5, 11)
        filled = candle(5, 11, 11, 9.9, 10)
        self.assertEqual(fill_percentage(gap, touched), .5)
        self.assertFalse(fvg_invalidated(gap, touched))
        self.assertTrue(fvg_invalidated(gap, filled))
        self.assertEqual(FVG_EXPIRY_MS, 4 * 3_600_000)
        sweep = candle(3, 10, 10.5, 9, 10, 300_000)
        self.assertEqual(structural_stop("LONG", sweep), 9)
        self.assertEqual(fixed_r_target("LONG", 10, 9), 11.5)
        self.assertEqual(fixed_r_target("SHORT", 10, 11), 8.5)

    def test_long_short_accounting_remains_separate(self):
        base = {"gross_return": .01, "entry_fee": .4, "exit_fee": .4, "funding_cost": 0, "spread_cost": .2, "slippage_cost": .1, "normalized_notional": 1000, "r_multiple": 1, "mae": -.01, "mfe": .02, "exit_reason": "TAKE_PROFIT"}
        rows = [{**base, "side": "LONG", "net_return": .009, "net_pnl": 9}, {**base, "side": "SHORT", "net_return": -.011, "net_pnl": -11}]
        value = metrics(rows)
        self.assertEqual(value["LONG"]["trade_count"], 1)
        self.assertEqual(value["SHORT"]["trade_count"], 1)
        self.assertGreater(value["LONG"]["expectancy"], 0)
        self.assertLess(value["SHORT"]["expectancy"], 0)

    def test_replay_annotations_follow_fvg_trade_lifecycle(self):
        trade = {"trade_id": "t1", "symbol": "TESTUSDT", "side": "LONG", "signal_time": 2_000_000, "entry_time": 2_000_001, "exit_time": 3_000_000, "entry_price": 11.0, "stop_loss": 10.0, "take_profits": [12.5], "exit_price": 12.5, "exit_reason": "TAKE_PROFIT", "fvg_setup": {"fvg_id": "f1", "formed_at": 1_000_000, "expires_at": 9_000_000, "price_low": 10, "price_high": 11, "normalized_size": .5, "touched_at": 1_200_000, "penetration_pct": 40, "sweep_at": 1_500_000, "sweep_price": 9.8, "bias_observed_through": 900_000, "net_expected_rr": 1.2}}
        events = fvg_events(trade)
        for kind in ["BIAS_LOCKED", "FVG", "POI", "LIQUIDITY_SWEEP", "MSS", "ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT", "TRADE_OPEN", "TRADE_CLOSED"]:
            self.assertTrue(any(item["type"] == kind for item in events), kind)
        self.assertTrue(all(item["timestamp"] <= item["availableAt"] for item in events))

    def test_oos_is_guarded_and_triage_is_deterministic(self):
        with self.assertRaises(PermissionError):
            oos_guard()
        values = (1.0, -.1, 100, .2, "BROADLY_DISTRIBUTED")
        self.assertEqual(triage_decision(*values), "KILL_COST_DESTROYED")
        self.assertEqual(triage_decision(*values), triage_decision(*values))
        self.assertNotIn("1M", [item["timeframe"] for item in PROFILE["timeframes"]])


if __name__ == "__main__":
    unittest.main()
