from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_engine.replication import load_source_signals
from research_engine.replication import file_sha256
from research_engine.replication_b import PARENT_RUN, _parent_contract, execute, oos_guard, signal_b_stage_decision


STATE_ROOT = Path("state")


def test_d46b_preserves_source_hashes_and_parent_artifacts() -> None:
    parent = _parent_contract(STATE_ROOT)
    source = load_source_signals(STATE_ROOT)
    assert parent["run_id"] == PARENT_RUN
    assert parent["source_signal_hashes"] == [item["definition_hash"] for item in source["definitions"]]
    assert parent["artifact_hashes"] == _parent_contract(STATE_ROOT)["artifact_hashes"]


def test_signal_a_cannot_veto_signal_b_progression() -> None:
    assert signal_b_stage_decision("B", "WEAK_REPLICATION") == ("CONTINUE_STAGE_C", "C")
    assert signal_b_stage_decision("B", "REPLICATED") == ("CONTINUE_STAGE_C", "C")
    assert signal_b_stage_decision("B", "NOT_REPLICATED") == ("STOP_SIGNAL_B_NOT_REPLICATED", None)


def test_parent_contract_has_no_threshold_or_oos_mutation() -> None:
    manifest = json.loads((STATE_ROOT / "signal-replication" / PARENT_RUN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["thresholds_changed"] is False
    assert manifest["oos_access"] == "OOS_NOT_ACCESSED"
    with pytest.raises(PermissionError, match="outside D4.6B"):
        oos_guard()


def test_completed_d46b_artifacts_are_deterministic_and_guarded() -> None:
    root = STATE_ROOT / "signal-replication" / "d4_6b_d9380c7ff0781bac"
    required = ["manifest.json", "parent-run.json", "source-signal-hashes.json", "resource-plan.json", "backfill-summary.json", "signal-a.json", "signal-b.json", "temporal-stability.json", "symbol-breadth.json", "replication-gate.json", "replication-report.md"]
    tracked = [root / name for name in required]
    assert all(path.exists() for path in tracked)
    before = [file_sha256(path) for path in tracked]
    result = execute(root.name, "C", STATE_ROOT, Path("data/market"), "http://127.0.0.1:1")
    assert result["status"] == "ALREADY_COMPLETED"
    assert before == [file_sha256(path) for path in tracked]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    gate = json.loads((root / "replication-gate.json").read_text(encoding="utf-8"))
    assert manifest["oos_access"] == "OOS_NOT_ACCESSED"
    assert manifest["thresholds_changed"] is False
    assert manifest["current_ticker_used_for_selection_or_features"] is False
    assert gate["primary_signal"] == "B"
    assert gate["signal_a_cannot_veto_signal_b"] is True


def test_parent_artifacts_still_match_recorded_hashes() -> None:
    root = STATE_ROOT / "signal-replication" / "d4_6b_d9380c7ff0781bac"
    recorded = json.loads((root / "parent-run.json").read_text(encoding="utf-8"))["artifact_hashes"]
    parent = STATE_ROOT / "signal-replication" / PARENT_RUN
    assert recorded == {
        str(path.relative_to(parent)).replace("\\", "/"): file_sha256(path)
        for path in sorted(parent.rglob("*"))
        if path.is_file() and "work" not in path.parts
    }
