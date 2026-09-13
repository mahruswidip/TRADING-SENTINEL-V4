from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtest_engine.engine import metrics
from research_engine.research import chronological_splits, cost_stress, rank_research, rejection_reasons, robustness, stability_score, symbol_breadth, verify_immutable_run
from research_engine.strategies import STRATEGIES


def trade(side: str, pnl: float) -> dict[str, float | str]:
    return {"side": side, "net_pnl": pnl, "gross_pnl": pnl + 1.1, "gross_return": (pnl + 1.1) / 1000, "net_return": pnl / 1000, "r_multiple": pnl / 10, "mae": -.01, "mfe": .02, "normalized_notional": 1000, "entry_fee": .4, "exit_fee": .4, "funding_cost": 0, "spread_cost": .2, "slippage_cost": .1, "exit_reason": "TAKE_PROFIT", "cost_model_version": "base"}


class ResearchEngineTests(unittest.TestCase):
    def test_seven_predeclared_families_and_narrow_variants(self):
        self.assertEqual(len(STRATEGIES), 7)
        self.assertEqual(len({item.family for item in STRATEGIES}), 7)
        self.assertEqual({item.version for item in STRATEGIES}, {"V1"})

    def test_chronological_oos_is_locked_and_non_overlapping(self):
        value = chronological_splits(10, 30, 30, 50)
        self.assertLessEqual(value["development"]["end"], value["oos"]["start"])
        self.assertTrue(value["oos"]["locked"])
        self.assertFalse(value["oos"]["tuning_allowed"])
        with self.assertRaises(ValueError): chronological_splits(10, 40, 30, 50)

    def test_walk_forward_boundaries_only_move_forward(self):
        folds = chronological_splits(0, 100, 100, 200)["walk_forward"]
        for fold in folds:
            self.assertLessEqual(fold["train_end"], fold["validation_start"])
            self.assertLess(fold["validation_start"], fold["validation_end"])

    def test_long_short_metrics_are_independent(self):
        value = metrics([trade("LONG", 10), trade("SHORT", -5)])
        self.assertGreater(value["LONG"]["expectancy"], 0)
        self.assertLess(value["SHORT"]["expectancy"], 0)
        self.assertEqual(value["trade_count"], 2)

    def test_cost_stress_increases_the_expected_cost_dimension(self):
        value = cost_stress([trade("LONG", 10)])
        self.assertGreater(value["HIGHER_FEE_50"]["metrics"]["fees_total"], value["BASE"]["metrics"]["fees_total"])
        self.assertGreater(value["HIGHER_SPREAD_50"]["metrics"]["spread_total"], value["BASE"]["metrics"]["spread_total"])
        self.assertGreater(value["HIGHER_SLIPPAGE_50"]["metrics"]["slippage_total"], value["BASE"]["metrics"]["slippage_total"])

    def test_parameter_stability_is_reproducible(self):
        values = [1.0, .95, 1.05]
        self.assertEqual(stability_score(values), stability_score(values))
        self.assertGreater(stability_score(values), stability_score([1, -1, 1]))

    def test_symbol_breadth_and_concentration(self):
        breadth = symbol_breadth([{"symbol": "A", "net_pnl": 90, "trade_count": 9}, {"symbol": "B", "net_pnl": 10, "trade_count": 1}, {"symbol": "C", "net_pnl": -5, "trade_count": 2}], .5)
        self.assertEqual(breadth["profitable_symbol_count"], 2)
        self.assertEqual(breadth["losing_symbol_count"], 1)
        self.assertAlmostEqual(breadth["top_symbol_pnl_share"], .9)
        self.assertEqual(breadth["trades_per_month"], 24)

    def test_rejection_reasons_include_sample_and_concentration(self):
        poor = metrics([trade("LONG", 1)])
        folds = [{"metrics": poor}, {"metrics": poor}]
        stress = {"BASE": {"metrics": poor}}
        reasons = rejection_reasons(poor, poor, folds, 100, {"top_symbol_pnl_share": .9}, stress)
        self.assertIn("INSUFFICIENT_TRADES", reasons)
        self.assertIn("SYMBOL_CONCENTRATION", reasons)

    def test_robustness_and_ranking_are_deterministic(self):
        good = metrics([trade("LONG", 10), trade("SHORT", 8)])
        folds = [{"metrics": good}, {"metrics": good}]
        stress = {"BASE": {"metrics": good}}
        breadth = {"profitable_symbol_count": 2, "losing_symbol_count": 0}
        first = robustness(good, good, folds, 90, breadth, stress)
        self.assertEqual(first, robustness(good, good, folds, 90, breadth, stress))
        rows = [{"strategy": "B", "score": 50}, {"strategy": "A", "score": 50}, {"strategy": "C", "score": 60}]
        self.assertEqual([row["strategy"] for row in rank_research(rows)], ["C", "A", "B"])

    def test_research_run_identity_is_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            path.write_text(json.dumps({"identity_hash": "same"}), encoding="utf-8")
            self.assertTrue(verify_immutable_run(path, "same"))
            with self.assertRaises(ValueError): verify_immutable_run(path, "different")


if __name__ == "__main__": unittest.main()
