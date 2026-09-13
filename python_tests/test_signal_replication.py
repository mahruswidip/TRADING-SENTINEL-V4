from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest_engine.engine import stable_digest
from research_engine.discovery import MINIMUM_ROUND_TRIP_COST_BPS, effective_sample
from research_engine.replication import (
    SOURCE_RUN,
    deterministic_selection,
    execute,
    file_sha256,
    load_source_signals,
    oos_guard,
    replication_status,
    stage_decision,
)
from research_engine.discovery import universe_eligible


STATE_ROOT = Path("state")


def _contract(symbol: str, onboard: int = 0) -> dict[str, object]:
    return {
        "symbol": symbol,
        "onboardDate": onboard,
        "deliveryDate": 10**15,
        "contractType": "PERPETUAL",
        "quoteAsset": "USDT",
        "marginAsset": "USDT",
    }


def test_replication_loads_exactly_two_frozen_d45_definitions() -> None:
    source = load_source_signals(STATE_ROOT)
    definitions = source["definitions"]
    assert source["source_run"] == SOURCE_RUN
    assert len(definitions) == 2
    assert [item["expected_direction"] for item in definitions] == ["POSITIVE", "NEGATIVE"]
    assert [item["horizon"] for item in definitions] == ["4h", "4h"]
    assert definitions[0]["condition_bucket"] == "NORMAL \u00d7 BTC_BEARISH"
    assert definitions[1]["condition_bucket"] == "LOW \u00d7 BTC_BULLISH"
    assert all(item["feature"] == "RELATIVE_STRENGTH_X_BTC_REGIME" for item in definitions)


def test_source_definition_hashes_are_stable_and_self_verifying() -> None:
    left = load_source_signals(STATE_ROOT)
    right = load_source_signals(STATE_ROOT)
    assert left["source_artifact_hashes"] == right["source_artifact_hashes"]
    assert [item["definition_hash"] for item in left["definitions"]] == [
        stable_digest({key: value for key, value in item.items() if key != "definition_hash"})
        for item in left["definitions"]
    ]


def test_replication_contract_does_not_mutate_thresholds() -> None:
    source = load_source_signals(STATE_ROOT)
    catalog = json.loads((STATE_ROOT / "signal-discovery" / SOURCE_RUN / "feature-catalog.json").read_text(encoding="utf-8"))
    catalog_by_id = {item["id"]: item for item in catalog["catalog"]}
    for definition in source["definitions"]:
        for component in definition["component_catalog"]:
            assert component == catalog_by_id[component["id"]]
    assert MINIMUM_ROUND_TRIP_COST_BPS == 11.0


def test_symbol_selection_is_deterministic_and_preserves_source_cohort() -> None:
    universe = [_contract(f"S{index:03d}USDT", onboard=index * 1_000) for index in range(80)]
    source = ["S003USDT", "S020USDT", "S071USDT"]
    left = deterministic_selection(universe, source, 50, 100_000_000)
    right = deterministic_selection(list(reversed(universe)), list(reversed(source)), 50, 100_000_000)
    assert left == right
    symbols = {item["symbol"] for item in left}
    assert set(source) <= symbols
    assert len(symbols) == 50


def test_selection_uses_historical_contract_fields_not_ticker_values() -> None:
    clean = [_contract(f"S{index:03d}USDT", onboard=index * 1_000) for index in range(60)]
    contaminated = [{**item, "currentTickerVolume": 10**12 - index} for index, item in enumerate(clean)]
    assert deterministic_selection(clean, [], 50, 100_000_000) == [
        {key: value for key, value in item.items() if key != "currentTickerVolume"}
        for item in deterministic_selection(contaminated, [], 50, 100_000_000)
    ]


def test_replication_observation_respects_onboard_and_delivery_time() -> None:
    metadata = {"onboardDate": 100, "deliveryDate": 200}
    assert not universe_eligible(metadata, 99)
    assert universe_eligible(metadata, 100)
    assert universe_eligible(metadata, 199)
    assert not universe_eligible(metadata, 200)


def test_dependence_aware_effective_sample_is_reused_for_4h() -> None:
    rows = [{"symbol": "A", "timestamp": index, "labels": {"4h": 0.01}} for index in range(96)]
    assert len(effective_sample(rows, "4h")) == 2


def test_replication_status_enforces_breadth_temporal_and_cost_hurdles() -> None:
    definition = {"expected_direction": "POSITIVE"}
    summary = {
        "effective_observation_count": 200,
        "mean_forward_return": (MINIMUM_ROUND_TRIP_COST_BPS * 2.5) / 10_000,
        "median_forward_return": (MINIMUM_ROUND_TRIP_COST_BPS * 1.5) / 10_000,
        "block_bootstrap_95_ci": [0.001, 0.004],
        "temporal_classification": "STABLE",
        "breadth": {"active_symbol_count": 20, "profitable_direction_symbol_count": 16, "top_symbol_contribution": 0.2},
    }
    assert replication_status(summary, definition) == "REPLICATED_STRONG"
    summary["temporal_classification"] = "SIGN_FLIP"
    assert replication_status(summary, definition) != "REPLICATED_STRONG"
    summary["temporal_classification"] = "STABLE"
    summary["breadth"]["top_symbol_contribution"] = 0.8
    assert replication_status(summary, definition) != "REPLICATED_STRONG"


@pytest.mark.parametrize(
    ("stage", "statuses", "decision"),
    [
        ("A", ["REPLICATED", "REPLICATED_STRONG"], "CONTINUE_STAGE_B"),
        ("A", ["NOT_REPLICATED", "REPLICATED"], "STOP_NOT_REPLICATED"),
        ("B", ["WEAK_REPLICATION", "REPLICATED"], "STOP_WEAK_REPLICATION"),
        ("B", ["REPLICATED", "REPLICATED"], "CONTINUE_STAGE_C"),
        ("C", ["REPLICATED", "REPLICATED"], "STOP_STAGE_C_COMPLETE"),
    ],
)
def test_stage_early_stop_rules(stage: str, statuses: list[str], decision: str) -> None:
    assert stage_decision(stage, statuses) == decision


def test_locked_oos_guard() -> None:
    with pytest.raises(PermissionError, match="outside D4.6"):
        oos_guard()


def test_completed_replication_artifacts_cover_breadth_temporal_and_oos() -> None:
    root = STATE_ROOT / "signal-replication" / "d4_6_8733a768a0dd3dd4"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    gate = json.loads((root / "replication-gate.json").read_text(encoding="utf-8"))
    assert manifest["thresholds_changed"] is False
    assert manifest["current_ticker_used_for_selection_or_features"] is False
    assert manifest["oos_access"] == "OOS_NOT_ACCESSED"
    assert manifest["locked_oos_resolved_or_read"] is False
    assert gate["decision"] == "STOP_NOT_REPLICATED"
    assert gate["next_stage"] is None
    for name in ("a", "b"):
        signal = json.loads((root / f"signal-{name}-replication.json").read_text(encoding="utf-8"))
        assert signal["replication"]["effective_observation_count"] < signal["replication"]["observation_count"]
        assert signal["replication"]["date_count"] > 1
        assert signal["replication"]["breadth"]["active_symbol_count"] > 1
        assert set(signal["temporal_detail"]) == {"DEV_A", "DEV_B", "DEV_C"}
        assert signal["neutral_or_insufficient_symbol_count"] >= 0


def test_completed_run_resume_is_network_free_and_deterministic() -> None:
    root = STATE_ROOT / "signal-replication" / "d4_6_8733a768a0dd3dd4"
    tracked = [root / name for name in ("manifest.json", "signal-a-replication.json", "signal-b-replication.json", "replication-gate.json")]
    before_hashes = [file_sha256(path) for path in tracked]
    before_checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    result = execute(root.name, "A", STATE_ROOT, Path("data/market"), "http://127.0.0.1:1")
    after_checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
    assert result["status"] == "ALREADY_COMPLETED"
    assert before_checkpoint == after_checkpoint
    assert before_hashes == [file_sha256(path) for path in tracked]
