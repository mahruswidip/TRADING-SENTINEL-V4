from __future__ import annotations

import unittest

from research_engine.transferability import (
    VERDICTS,
    harvested_mechanisms,
    stage_gate,
    transferability_score,
)


class TransferabilityTests(unittest.TestCase):
    def test_harvest_is_frozen_and_excludes_incomplete_signals(self) -> None:
        self.assertEqual(
            set(harvested_mechanisms()),
            {
                "BREAKOUT_RETEST_V1",
                "RANGE_REVERSION_V1",
                "MOMENTUM_BREAK_V1",
                "BREAKOUT_RETEST_V2",
                "RANGE_REVERSION_V2",
            },
        )

    def test_stage_a_gate_requires_every_threshold(self) -> None:
        passing = {
            "valid_symbols": 20,
            "positive_market_ratio": .55,
            "aggregate_trades": 100,
            "median_market_expectancy": .01,
            "median_market_profit_factor": 1.051,
            "aggregate_oos_expectancy": .01,
            "positive_oos_fold_ratio": .50,
            "aggregate_expectancy": .01,
        }
        self.assertTrue(stage_gate("A", passing))
        for key in ("valid_symbols", "positive_market_ratio", "aggregate_trades", "median_market_expectancy", "median_market_profit_factor", "aggregate_oos_expectancy", "positive_oos_fold_ratio"):
            failed = dict(passing)
            failed[key] = 0
            self.assertFalse(stage_gate("A", failed), key)

    def test_stage_b_adds_aggregate_expectancy_gate(self) -> None:
        value = {
            "valid_symbols": 100,
            "positive_market_ratio": .60,
            "aggregate_trades": 500,
            "median_market_expectancy": .1,
            "median_market_profit_factor": 1.2,
            "aggregate_oos_expectancy": .1,
            "positive_oos_fold_ratio": .75,
            "aggregate_expectancy": 0,
        }
        self.assertFalse(stage_gate("B", value))

    def test_score_is_bounded_and_has_declared_verdicts(self) -> None:
        self.assertEqual(transferability_score(0, -100, 0, 0, 0, 0), 0)
        self.assertEqual(transferability_score(1, 100, 100, 1, 1, 1), 100)
        self.assertIn("TRANSFERABILITY_CANDIDATE", VERDICTS)
        self.assertNotIn("SHADOW_READY", VERDICTS)


if __name__ == "__main__":
    unittest.main()
