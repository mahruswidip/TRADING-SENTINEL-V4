from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from backtest_engine.engine import stable_digest
from forensics_engine.expansion import chronological_segments, execute, expanded_breadth, next_stage, oos_guard, stratified_universe, temporal_stability
from research_engine.refinements import VARIANTS


def universe(count: int = 12) -> dict:
    symbols = [{"symbol": f"S{index}USDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "onboardDate": index * 1_000} for index in range(count)]
    tickers = [{"symbol": item["symbol"], "quoteVolume": (count - index) * 100} for index, item in enumerate(symbols)]
    return {"symbols": symbols, "tickers": tickers, "source": "TEST"}


class DevelopmentExpansionTests(unittest.TestCase):
    def test_locked_oos_needs_eligibility_and_explicit_authorization(self):
        with self.assertRaises(PermissionError): oos_guard("REJECT_DEVELOPMENT_EXPANSION")
        with self.assertRaises(PermissionError): oos_guard("OOS_ELIGIBLE")
        self.assertIsNone(oos_guard("OOS_ELIGIBLE", True))

    def test_v2_rules_are_not_mutated(self):
        before = stable_digest([asdict(item) for item in VARIANTS])
        stratified_universe(universe(), 10 * 86_400_000, 50 * 86_400_000, "A")
        self.assertEqual(before, stable_digest([asdict(item) for item in VARIANTS]))
        self.assertEqual([f"{item.strategy_id}_{item.strategy_version}" for item in VARIANTS], ["BREAKOUT_RETEST_V2", "RANGE_REVERSION_V2"])

    def test_dynamic_stratified_selection_has_all_tiers_without_whitelist(self):
        snapshot, provenance = stratified_universe(universe(), 10 * 86_400_000, 50 * 86_400_000, "A")
        self.assertEqual({item["tier"] for item in snapshot}, {"TIER_A", "TIER_B", "TIER_C"})
        self.assertFalse(provenance["static_whitelist"])
        self.assertNotIn("BTCUSDT", {item["symbol"] for item in snapshot})

    def test_concentration_metrics_include_top_three_and_median(self):
        rows = [{"symbol": "A", "net_pnl": 70, "trade_count": 7, "expectancy": 10}, {"symbol": "B", "net_pnl": 20, "trade_count": 4, "expectancy": 5}, {"symbol": "C", "net_pnl": 10, "trade_count": 2, "expectancy": 5}, {"symbol": "D", "net_pnl": -5, "trade_count": 1, "expectancy": -5}]
        value = expanded_breadth(rows, 2)
        self.assertAlmostEqual(value["top_symbol_pnl_share"], .7)
        self.assertAlmostEqual(value["top_3_symbol_pnl_share"], 1)
        self.assertEqual(value["median_symbol_expectancy"], 5)
        self.assertEqual(value["trades_per_week"], 7)

    def test_temporal_periods_are_chronological_and_flag_concentration(self):
        self.assertEqual([(item["start"], item["end"]) for item in chronological_segments(0, 300)], [(0, 100), (100, 200), (200, 300)])
        values = iter([{"metrics": {"net_pnl": 100, "expectancy": 2}}, {"metrics": {"net_pnl": 0, "expectancy": 0}}, {"metrics": {"net_pnl": -10, "expectancy": -1}}])
        with patch("forensics_engine.expansion.evaluate", side_effect=lambda *args: next(values)):
            result = temporal_stability(object(), "TEST_V2", [], {}, 0, 300)
        self.assertEqual(result["flag"], "TEMPORAL_CONCENTRATION")
        self.assertTrue(result["decaying_expectancy"])

    def test_failed_stage_stops_early(self):
        self.assertIsNone(next_stage("A", False))
        self.assertEqual(next_stage("A", True), "B")
        self.assertEqual(next_stage("B", True), "C")

    def test_checkpoint_resume_skips_completed_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder); root = state / "research-runs" / "run"
            root.mkdir(parents=True)
            plan = {"identity_hash": "identity", "development_window": {"start": 0, "end": 1}, "symbols": [], "warmup_start": 0, "worker_count": 1, "stage": "A", "symbol_count": 0, "universe_snapshot": []}
            (root / "resource-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            done = {"strategy": "BREAKOUT_RETEST_V2", "passed": False}
            (root / "checkpoint.json").write_text(json.dumps({"identity_hash": "identity", "completed": {"BREAKOUT_RETEST_V2": done}}), encoding="utf-8")
            with patch("forensics_engine.expansion.load_datasets", return_value={}), patch("forensics_engine.expansion.run_candidate", return_value={"strategy": "RANGE_REVERSION_V2", "passed": False}) as run:
                result = execute("run", state, state / "cache", "http://unused")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(result["candidates"]), 2)

    def test_completed_rerun_is_byte_stable_and_does_not_evaluate(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder); root = state / "research-runs" / "run"
            root.mkdir(parents=True)
            (root / "resource-plan.json").write_text(json.dumps({"identity_hash": "same"}), encoding="utf-8")
            expected = {"runId": "run", "status": "COMPLETED"}
            (root / "expansion-run.json").write_text(json.dumps(expected), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({"identity_hash": "same"}), encoding="utf-8")
            with patch("forensics_engine.expansion.load_datasets") as load:
                self.assertEqual(execute("run", state, state, "http://unused"), expected)
            load.assert_not_called()


if __name__ == "__main__": unittest.main()
