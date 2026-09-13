from __future__ import annotations

from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from backtest_engine.data import HistoricalDataStore
from backtest_engine.model import Candle, FundingEvent
from research_engine.discovery import (
    UNAVAILABLE,
    add_cross_sectional_features,
    align_past_value,
    build_symbol_rows,
    cross_sectional_rank,
    data_capabilities,
    effective_sample,
    feature_catalog,
    forward_return_labels,
    oos_guard,
    past_percentile,
    rank_findings,
    rolling_percentile,
    symbol_breadth,
    temporal_segment,
    universe_eligible,
)


STEP = 300_000


def candles(count: int = 120, start: int = 0) -> list[Candle]:
    result = []
    for index in range(count):
        price = 100 + index
        result.append(Candle(start + index * STEP, price - .5, price + 1, price - 1, price, 10 + index, start + (index + 1) * STEP - 1))
    return result


def metadata() -> dict[str, int | str]:
    return {"symbol": "TESTUSDT", "onboardDate": 0, "deliveryDate": 10**15, "contractType": "PERPETUAL"}


def test_forward_return_labels_use_closed_reference_and_future_close() -> None:
    rows = candles()
    labels = forward_return_labels(rows, 50)
    assert labels["5m"] == rows[51].close / rows[50].close - 1
    assert labels["4h"] == rows[98].close / rows[50].close - 1


def test_feature_values_do_not_change_when_only_future_changes() -> None:
    original = candles()
    changed = deepcopy(original)
    changed[108] = Candle(changed[108].open_time, 999, 1001, 998, 1000, 999, changed[108].close_time)
    start, end = original[60].close_time, original[61].close_time + 1
    left = build_symbol_rows("TESTUSDT", original, [], metadata(), start, end)[0]
    right = build_symbol_rows("TESTUSDT", changed, [], metadata(), start, end)[0]
    assert left["features"] == right["features"]
    assert left["labels"] != right["labels"]
    assert left["feature_observed_through"] == left["timestamp"]


def test_rolling_percentile_uses_past_only() -> None:
    values = [1.0, 2.0, 100.0]
    assert past_percentile([1.0, 2.0], 100.0) == 1.0
    assert rolling_percentile(values, 2, 10) == 1.0
    changed_future = values + [-1000.0]
    assert rolling_percentile(changed_future, 2, 10) == 1.0


def test_cross_sectional_rank_respects_universe_t() -> None:
    values = {"A": 1.0, "B": 2.0, "NOT_LISTED": 100.0}
    assert cross_sectional_rank(values, {"A", "B"}) == {"A": 0.0, "B": 1.0}


def test_onboard_and_delivery_enforcement() -> None:
    item = {"onboardDate": 100, "deliveryDate": 200}
    assert not universe_eligible(item, 99)
    assert universe_eligible(item, 100)
    assert not universe_eligible(item, 200)


def test_unavailable_features_and_current_snapshots_are_not_historical() -> None:
    capabilities = data_capabilities({"/api/v1/market/candles-window", "/api/v1/market/book", "/api/v1/market/open-interest"})
    assert capabilities["open_interest"]["historical"] == UNAVAILABLE
    assert capabilities["bbo_spread"]["historical"] == UNAVAILABLE
    assert capabilities["order_book_depth"]["historical"] == UNAVAILABLE
    catalog = {item["id"]: item for item in feature_catalog()}
    for feature in ("oi_change", "premium_basis", "historical_spread", "historical_depth"):
        assert catalog[feature]["availability"] == UNAVAILABLE


def test_oi_and_funding_alignment_never_take_future_event() -> None:
    events = [(100, 1.0), (200, 2.0)]
    assert align_past_value(events, 99) is None
    assert align_past_value(events, 150) == (100, 1.0)
    assert align_past_value(events, 200) == (200, 2.0)
    bars = candles(120, 1_000)
    rows = build_symbol_rows("TESTUSDT", bars, [FundingEvent(bars[55].close_time, .001), FundingEvent(bars[90].close_time, .002)], metadata(), bars[60].close_time, bars[70].close_time)
    assert rows and all(row["features"]["funding_level"] == .001 for row in rows)


def test_temporal_segments_are_deterministic() -> None:
    assert [temporal_segment(value, 0, 300) for value in (0, 99, 100, 199, 200, 299)] == ["DEV_A", "DEV_A", "DEV_B", "DEV_B", "DEV_C", "DEV_C"]


def test_symbol_concentration_is_transparent() -> None:
    rows = []
    for symbol, values in {"A": [.03, .03], "B": [.001, .001], "C": [-.001, -.001]}.items():
        rows.extend({"symbol": symbol, "labels": {"5m": value}} for value in values)
    breadth = symbol_breadth(rows, "5m", 1)
    assert breadth["active_symbol_count"] == 3
    assert breadth["profitable_direction_symbol_count"] == 2
    assert breadth["top_symbol_contribution"] > .9


def test_dependence_aware_sample_downsamples_overlapping_horizons() -> None:
    rows = [{"symbol": "A", "timestamp": index, "labels": {"4h": 0.0}} for index in range(100)]
    assert len(effective_sample(rows, "4h")) == 3
    assert len(effective_sample(rows, "5m")) == 100


def test_discovery_ranking_is_deterministic() -> None:
    rows = [
        {"finding_id": "b", "discovery_score": 10.0},
        {"finding_id": "a", "discovery_score": 10.0},
        {"finding_id": "c", "discovery_score": 20.0},
    ]
    assert [item["finding_id"] for item in rank_findings(rows)] == ["c", "a", "b"]


def test_cross_sectional_features_only_use_current_universe() -> None:
    rows = [
        {"symbol": "A", "timestamp": 100, "features": {"return_15m": 0.01, "return_1h": 0.01, "return_4h": 0.01}},
        {"symbol": "B", "timestamp": 100, "features": {"return_15m": 0.02, "return_1h": 0.02, "return_4h": 0.02}},
    ]
    meta = {"A": {"onboardDate": 0, "deliveryDate": 1_000}, "B": {"onboardDate": 101, "deliveryDate": 1_000}}
    add_cross_sectional_features(rows, meta, [])
    assert rows[0]["features"]["relative_strength_1h"] == .5
    assert rows[1]["features"]["relative_strength_1h"] is None


def test_locked_oos_guard() -> None:
    with pytest.raises(PermissionError, match="outside D4.5"):
        oos_guard()


def test_funding_cache_reuses_a_covering_window(tmp_path) -> None:
    folder = tmp_path / "binance-usdm-v1" / "TESTUSDT" / "funding"
    folder.mkdir(parents=True)
    (folder / "100-300.json").write_text('[{"fundingTime": "200", "fundingRate": "0.001"}]', encoding="utf-8")

    class NoNetwork:
        def funding(self, *_args):
            raise AssertionError("covering cache should prevent a bridge request")

    store = HistoricalDataStore(tmp_path, NoNetwork())
    assert store.funding("TESTUSDT", 150, 250) == [FundingEvent(200, .001)]
    assert store.cache_hits == 1


def test_completed_d45_artifact_is_evidence_only_and_oos_locked() -> None:
    root = Path("state/signal-discovery/d4_5_482ba89ea0075922")
    required = {
        "manifest.json", "data-capabilities.json", "universe.json", "feature-catalog.json",
        "single-feature-results.json", "interaction-results.json", "horizon-results.json",
        "long-short-asymmetry.json", "temporal-stability.json", "symbol-breadth.json",
        "new-listing-analysis.json", "discovery-ranking.json", "discovery-report.md",
    }
    assert all((root / name).exists() for name in required)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((root / "feature-catalog.json").read_text(encoding="utf-8"))
    ranking = json.loads((root / "discovery-ranking.json").read_text(encoding="utf-8"))
    assert manifest["oos_access"] == "OOS_NOT_ACCESSED"
    assert manifest["locked_oos_resolved_or_read"] is False
    assert manifest["current_snapshot_features_used"] is False
    assert catalog["frozen_before_evaluation"] is True
    assert ranking["status_counts"]["PROMISING_SIGNAL"] == 2
    assert not Path("state/research/D4_5_STRATEGY").exists()
    with gzip.open(root / "work/AIXBTUSDT.rows.json.gz", "rt", encoding="utf-8") as source:
        first = json.load(source)[0]
    assert not ({"historical_spread", "historical_depth", "oi_change"} & first["features"].keys())
