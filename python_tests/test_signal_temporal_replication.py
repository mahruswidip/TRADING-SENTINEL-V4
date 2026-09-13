from __future__ import annotations

from pathlib import Path

import pytest

from research_engine.replication import load_source_signals
from research_engine.temporal_replication import INDEPENDENT_END, INDEPENDENT_START, _decision, oos_guard


STATE_ROOT = Path("state")


def test_d47_uses_exact_signal_b_and_pre_july_independent_period() -> None:
    definitions = load_source_signals(STATE_ROOT)["definitions"]
    signal_b = next(item for item in definitions if item["expected_direction"] == "NEGATIVE")
    assert signal_b["definition_hash"] == "79f6169b3289d82c1e7e6b654b93bf7440d14cb1f42b00ad858a3d64f26d49af"
    assert signal_b["condition_bucket"] == "LOW × BTC_BULLISH"
    assert signal_b["horizon"] == "4h"
    assert INDEPENDENT_START < INDEPENDENT_END < "2026-07-01T00:00:00Z"


def test_d47_decision_requires_confidence_and_does_not_filter_tail_rows() -> None:
    replication = {"mean_forward_return": -.002, "median_forward_return": -.001, "block_bootstrap_95_ci": [-.004, -.0001], "temporal_classification": "TEMPORALLY_STABLE", "breadth": {"active_symbol_count": 20, "profitable_direction_symbol_count": 16, "top_symbol_contribution": .2}}
    assert _decision(replication, {"mean_after_removing_largest_negative_observations": -.001})[0] == "INDEPENDENTLY_REPLICATED"
    replication["block_bootstrap_95_ci"] = [-.004, .0001]
    assert _decision(replication, {"mean_after_removing_largest_negative_observations": -.001})[0] == "WEAK"


def test_d47_oos_guard() -> None:
    with pytest.raises(PermissionError, match="outside D4.7"):
        oos_guard()
