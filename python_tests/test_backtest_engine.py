from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from backtest_engine.cli import eligible_symbols, replay_artifact, running_dashboard_job
from backtest_engine.data import DAY_MS, HistoricalDataStore, atomic_json, gap_count
from backtest_engine.engine import calculate_net, closed_at, funding_cost, reprice_trade, resample_closed, resolve_ambiguous, stable_digest
from backtest_engine.model import Candle, CostModel, FundingEvent, Trade


def candle(open_time: int, open_price: float = 100, close: float = 101, high: float = 102, low: float = 99, interval: int = 300_000) -> Candle:
    return Candle(open_time, open_price, high, low, close, 10, open_time + interval - 1)


def trade(side: str = "LONG", exit_reason: str = "INTRABAR_AMBIGUOUS") -> Trade:
    return Trade("t1", "r1", "BTCUSDT", side, "ENGINE_REFERENCE_INTRADAY", "V1", 0, 300_000, 599_999, 100, 97, 97 if side == "LONG" else 103, (105 if side == "LONG" else 95,), 1000, -0.03, -30, .4, .4, 0, (), .2, .1, -.0307, -30.7, -1, -.04, .06, exit_reason, 299_999, "ds", CostModel().version, "next-open-market-v1", "FAST_WORST_CASE")


class FakeBridge:
    def __init__(self) -> None: self.calls = 0
    def candles(self, symbol: str, interval: str, start: int, end: int, limit: int = 1500):
        self.calls += 1
        step = 60_000 if interval == "1m" else 300_000
        return [[at, "100", "102", "99", "101", "10", at + step - 1] for at in range(start, end, step)]
    def funding(self, symbol: str, start: int, end: int): return []


class EngineTests(unittest.TestCase):
    def test_incomplete_higher_timeframes_never_become_visible(self):
        rows = [candle(index * 300_000) for index in range(12)]
        hourly = resample_closed(rows, 3_600_000)
        self.assertEqual(len(hourly), 1)
        self.assertEqual(closed_at(hourly, 3_599_998), [])
        self.assertEqual(len(closed_at(hourly, 3_599_999)), 1)

    def test_universe_t_excludes_symbols_before_onboard_date(self):
        eligible, excluded = eligible_symbols({"symbols": [{"symbol": "OLDUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "onboardDate": 0}, {"symbol": "NEWUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "onboardDate": 20}]}, 0, 10)
        self.assertEqual([item["symbol"] for item in eligible], ["OLDUSDT"])
        self.assertEqual(excluded[0]["reason"], "NOT_LISTED_YET")

    def test_cost_accounting_is_itemized(self):
        self.assertAlmostEqual(calculate_net(25, 1, 1, -2, .5, .25), 24.25)

    def test_funding_only_applies_inside_position_window(self):
        value, events = funding_cost("LONG", 1000, 100, 300, [FundingEvent(100, .01), FundingEvent(200, .001), FundingEvent(400, .01)])
        self.assertEqual(value, 1)
        self.assertEqual(len(events), 1)
        short, _ = funding_cost("SHORT", 1000, 100, 300, [FundingEvent(200, .001)])
        self.assertEqual(short, -1)

    def test_long_and_short_pnl_signs(self):
        long = reprice_trade(trade("LONG"), 105, 600_000, "TAKE_PROFIT", "ACCURATE_1M", CostModel(), [])
        short = reprice_trade(trade("SHORT"), 95, 600_000, "TAKE_PROFIT", "ACCURATE_1M", CostModel(), [])
        self.assertGreater(long.net_pnl, 0)
        self.assertGreater(short.net_pnl, 0)
        self.assertAlmostEqual(long.gross_pnl, short.gross_pnl)

    def test_intrabar_ambiguity_never_assumes_favorable_order(self):
        resolved = resolve_ambiguous(trade(), [candle(300_000, high=106, low=96, interval=60_000)])
        self.assertEqual(resolved.exit_price, 97)
        self.assertEqual(resolved.intrabar_resolution_method, "ACCURATE_1M_WORST_CASE")

    def test_determinism_and_worker_order_independence(self):
        inputs = ["SOLUSDT", "BTCUSDT", "DOGEUSDT"]
        serial = sorted((value, stable_digest(value)) for value in inputs)
        with ThreadPoolExecutor(max_workers=3) as pool:
            parallel = sorted((value, digest) for value, digest in zip(inputs, pool.map(stable_digest, inputs)))
        self.assertEqual(serial, parallel)
        self.assertEqual(stable_digest(serial), stable_digest(parallel))

    def test_cache_reuses_existing_partition(self):
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as folder:
            store = HistoricalDataStore(Path(folder), bridge)
            first, _ = store.candles("BTCUSDT", "5m", 0, 600_000)
            second, _ = store.candles("BTCUSDT", "5m", 0, 600_000)
            self.assertEqual(first, second)
            self.assertEqual(bridge.calls, 1)
            self.assertEqual(store.cache_hits, 1)

    def test_gap_detection(self):
        self.assertEqual(gap_count([candle(0), candle(300_000), candle(900_000)], 300_000), 1)

    def test_checkpoint_is_atomic_and_resume_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            atomic_json(path, {"completed": {"BTCUSDT": {"trades": 2}}, "failed": {}})
            self.assertEqual(json.loads(path.read_text())["completed"]["BTCUSDT"]["trades"], 2)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_running_job_progress_is_authoritative(self):
        job = running_dashboard_job("r1", ["BTCUSDT", "SOLUSDT"], {"BTCUSDT": {"trades": []}}, {}, "SOLUSDT", datetime.now(UTC), 2)
        self.assertEqual(job["status"], "RUNNING_FAST")
        self.assertEqual(job["universeProgress"]["processed"], 1)
        self.assertEqual(job["universeProgress"]["total"], 2)
        self.assertEqual(job["currentEvaluation"]["symbol"], "SOLUSDT")

    def test_replay_artifact_uses_real_backtest_contract(self):
        five = [candle(at).as_dict() for at in range(0, 4 * DAY_MS, 300_000)]
        hourly = [item.as_dict() for item in resample_closed([Candle(**row) for row in five], 3_600_000)]
        daily = [item.as_dict() for item in resample_closed([Candle(**row) for row in five], DAY_MS)]
        value = trade(exit_reason="TAKE_PROFIT").as_dict()
        value.update({"signal_time": 3 * DAY_MS, "entry_time": 3 * DAY_MS + 300_000, "exit_time": 3 * DAY_MS + 600_000})
        result = {"symbol": "BTCUSDT", "trades": [value], "events": [], "candles": five, "hourly": hourly, "daily": daily}
        replay = replay_artifact("r1", result)
        self.assertIsNotNone(replay)
        self.assertEqual(replay["source"], "BACKTEST")
        self.assertEqual([item["timeframe"] for item in replay["series"]], ["1D", "1H", "5M"])


if __name__ == "__main__": unittest.main()
