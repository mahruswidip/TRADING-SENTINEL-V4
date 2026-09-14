from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtest_engine.data import HistoricalDataStore
from research_engine.funding_backfill import contract_status, missing_for_plan, validate_rows


class NeverDownload:
    def funding(self, *_: object) -> list[dict[str, object]]:
        raise AssertionError("cache round-trip attempted a download")


class FundingBackfillTests(unittest.TestCase):
    def test_contract_validation(self) -> None:
        valid = {"contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "onboardDate": 1, "deliveryDate": 999}
        self.assertEqual(contract_status(valid, 10, 100), "VALID_PERPETUAL")
        self.assertEqual(contract_status({**valid, "onboardDate": 11}, 10, 100), "NOT_LISTED_DURING_PERIOD")
        self.assertEqual(contract_status({**valid, "contractType": "CURRENT_QUARTER"}, 10, 100), "NOT_PERPETUAL")

    def test_parser_preserves_sign_and_detects_duplicates(self) -> None:
        rows = [
            {"fundingTime": 10, "fundingRate": "-0.00010", "markPrice": "100"},
            {"fundingTime": 10, "fundingRate": "0.99"},
            {"fundingTime": 20, "fundingRate": "0.00020"},
        ]
        result = validate_rows("BTCUSDT", rows, 10, 20)
        self.assertEqual(result["duplicate_timestamps"], 1)
        self.assertEqual(result["rows"][0]["fundingRate"], "-0.00010")

    def test_existing_cache_loader_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            start, end = 10, 30
            path = root / "binance-usdm-v1" / "BTCUSDT" / "funding" / f"{start}-{end}.json"
            path.parent.mkdir(parents=True)
            source = [{"fundingTime": 20, "fundingRate": "-0.00010", "source": "BINANCE"}]
            path.write_text(json.dumps(source), encoding="utf-8")
            events = HistoricalDataStore(root, NeverDownload()).funding("BTCUSDT", start, end)  # type: ignore[arg-type]
            self.assertEqual([(event.timestamp, event.rate) for event in events], [(20, -0.0001)])

    def test_preflight_distinguishes_empty_from_real_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = {"history": {"start": 10, "end": 30}, "universe": [{"symbol": "BTCUSDT"}]}
            path = root / "binance-usdm-v1" / "BTCUSDT" / "funding" / "10-30.json"
            path.parent.mkdir(parents=True)
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(missing_for_plan(plan, root), ["BTCUSDT"])
            path.write_text(json.dumps([{"fundingTime": 20, "fundingRate": "0.0"}]), encoding="utf-8")
            self.assertEqual(missing_for_plan(plan, root), [])


if __name__ == "__main__":
    unittest.main()
