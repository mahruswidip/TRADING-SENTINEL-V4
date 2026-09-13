from __future__ import annotations

import unittest
from pathlib import Path

from backtest_engine.model import Candle
from forensics_engine.accounting_audit import hypothesis_decision, reference_equity
from forensics_engine.analysis import regime_at
from forensics_engine.expansion import oos_guard


def trade(identifier: str, timestamp: int, pnl: float, normalized_return: float) -> dict:
    return {"trade_id": identifier, "exit_time": timestamp, "net_pnl": pnl, "net_return": normalized_return, "normalized_notional": 1_000}


class AccountingAuditTests(unittest.TestCase):
    def test_positive_and_negative_equity_paths_are_peak_to_trough(self):
        value = reference_equity([trade("a", 1, 100, .1), trade("b", 2, -550, -.55), trade("c", 3, 50, .05)], 1_000)
        self.assertEqual(value["ending_equity"], 600)
        self.assertAlmostEqual(value["portfolio_equity_return_pct"], -40)
        self.assertAlmostEqual(value["portfolio_max_drawdown_pct"], 50)
        self.assertEqual(value["drawdown_trough_timestamp"], 2)

    def test_bankruptcy_floors_equity_and_stops_later_trades(self):
        value = reference_equity([trade("a", 1, -1_500, -1.5), trade("b", 2, 5_000, 5)], 1_000)
        self.assertEqual(value["ending_equity"], 0)
        self.assertEqual(value["portfolio_max_drawdown_pct"], 100)
        self.assertTrue(value["bankrupt"])
        self.assertEqual(value["skipped_after_bankruptcy"], 1)

    def test_aggregate_return_can_exceed_minus_100_without_equity_dd_exceeding_100(self):
        value = reference_equity([trade("a", 1, -800, -.8), trade("b", 2, -800, -.8)], 10_000)
        self.assertEqual(value["aggregate_normalized_net_return_pct"], -160)
        self.assertGreaterEqual(value["portfolio_equity_return_pct"], -100)
        self.assertLessEqual(value["portfolio_max_drawdown_pct"], 100)
        self.assertEqual(value["return_metric_type"], "REFERENCE_PORTFOLIO_EQUITY_RETURN")

    def test_equity_simulation_is_deterministic_and_ordered_by_exit(self):
        rows = [trade("b", 2, -20, -.02), trade("a", 1, 10, .01)]
        self.assertEqual(reference_equity(rows), reference_equity(list(reversed(rows))))

    def test_regime_is_ex_ante_and_future_candles_cannot_change_past_classification(self):
        hourly = [Candle(index * 3_600_000, 10, 11, 10, 10.5, 1, (index + 1) * 3_600_000 - 1) for index in range(24)]
        hourly.append(Candle(24 * 3_600_000, 10, 13, 10, 12, 1, 25 * 3_600_000 - 1))
        timestamp = hourly[-1].close_time
        before = regime_at(timestamp, hourly)
        future = Candle(25 * 3_600_000, 10, 100, 1, 50, 1, 26 * 3_600_000 - 1)
        self.assertEqual(before, regime_at(timestamp, hourly + [future]))
        self.assertEqual(before["volatility_regime"], "HIGH_VOLATILITY")
        self.assertLessEqual(before["observed_through"], timestamp)

    def test_hypothesis_gate_rejects_concentration_without_parameter_search(self):
        evidence = {"metrics": {"expectancy": 1, "profit_factor": 1.2, "trade_count": 100}, "symbol_breadth": {"profitable_symbol_count": 1, "top_symbol_pnl_share": 1}, "temporal_stability": {"positive_segment_count": 1, "max_positive_pnl_segment_share": 1}, "cost_stress": {"BASE": {"metrics": {"expectancy": 1}}}, "ex_ante_proof": {"all_observations_available_by_signal": True}}
        decision = hypothesis_decision(evidence)
        self.assertEqual(decision["decision"], "REGIME_HYPOTHESIS_NOT_JUSTIFIED")
        self.assertFalse(decision["v3_created"])
        self.assertNotEqual(decision["decision"], "BREAKOUT_RETEST_V3_JUSTIFIED")
        self.assertTrue(decision["gates"]["NO_PARAMETER_SEARCH"])

    def test_locked_oos_guard_remains_closed(self):
        with self.assertRaises(PermissionError): oos_guard("REJECT_DEVELOPMENT_EXPANSION")
        with self.assertRaises(PermissionError): oos_guard("OOS_ELIGIBLE")

    def test_rejected_regime_did_not_create_a_v3_artifact(self):
        self.assertFalse((Path("state") / "research" / "BREAKOUT_RETEST_V3").exists())


if __name__ == "__main__": unittest.main()
