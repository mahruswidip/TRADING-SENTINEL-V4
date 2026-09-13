from __future__ import annotations

import unittest

from backtest_engine.cli import eligible_symbols
from forensics_engine.analysis import distribution, tier_snapshot
from forensics_engine.validation import development_gates
from research_engine.refinements import VARIANTS


class ForensicsTests(unittest.TestCase):
    def test_distribution_is_deterministic_and_exposes_quantiles(self):
        expected = distribution([4, 1, 3, 2])
        self.assertEqual(expected, distribution([2, 4, 1, 3]))
        self.assertEqual(expected["median"], 2.5)
        self.assertEqual(expected["count"], 4)

    def test_universe_enriches_separate_bridge_tickers_before_ranking(self):
        universe = {"symbols": [{"symbol": "AUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "onboardDate": 0}], "tickers": [{"symbol": "AUSDT", "quoteVolume": "123"}], "books": [{"symbol": "AUSDT", "bidPrice": "9", "askPrice": "10"}]}
        eligible, _ = eligible_symbols(universe, 10, 20)
        self.assertEqual(eligible[0]["quoteVolume24h"], "123")
        self.assertEqual(eligible[0]["bidPrice"], "9")

    def test_tiers_use_volume_not_symbol_order(self):
        symbols = [{"symbol": name, "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "onboardDate": 0} for name in ("LOW", "HIGH", "MID")]
        tickers = [{"symbol": "LOW", "quoteVolume": 1}, {"symbol": "HIGH", "quoteVolume": 100}, {"symbol": "MID", "quoteVolume": 10}]
        tiers, _ = tier_snapshot({"symbols": symbols, "tickers": tickers}, 10, 20)
        self.assertEqual(tiers["HIGH"]["tier"], "TIER_A")
        self.assertEqual(tiers["MID"]["tier"], "TIER_B")
        self.assertEqual(tiers["LOW"]["tier"], "TIER_C")

    def test_development_gates_keep_d4_thresholds(self):
        summary = {"expectancy": .01, "profit_factor": 1.09, "max_drawdown": 1, "trade_count": 50}
        stress = {"BASE": {"metrics": {"expectancy": .01}}}
        gates = development_gates(summary, stress, {"top_symbol_pnl_share": .5})
        self.assertFalse(gates["PF_AT_LEAST_1_1"])
        self.assertTrue(gates["POSITIVE_NET_EXPECTANCY"])

    def test_refinements_are_new_versions_and_stay_small(self):
        self.assertLessEqual(len(VARIANTS), 3 * 3)
        self.assertEqual({variant.strategy_version for variant in VARIANTS}, {"V2"})
        self.assertEqual({variant.base.strategy_version for variant in VARIANTS}, {"V1"})


if __name__ == "__main__": unittest.main()
