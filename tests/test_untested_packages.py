"""Smoke/contract tests for packages that previously had no tests (streamline pass 2)."""
from __future__ import annotations

import importlib

import pytest


def _no_execution_permission(obj) -> None:
    if isinstance(obj, dict):
        if "execution_permission" in obj:
            assert obj["execution_permission"] == "none"
        for v in obj.values():
            _no_execution_permission(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _no_execution_permission(v)


def test_experiments_reexports_resolve():
    exp = importlib.import_module("atlas.experiments")
    for name in exp.__all__:
        assert getattr(exp, name) is not None
    assert exp.SQLiteExperimentTracker is exp.ExperimentStore


def test_fundamentals_reexports_resolve():
    fund = importlib.import_module("atlas.fundamentals")
    from atlas.marketdata.sec_edgar import select_as_filed_sec_facts

    assert fund.select_as_filed_sec_facts is select_as_filed_sec_facts
    assert set(fund.__all__) == {"SECEdgarFilingFact", "select_as_filed_sec_facts"}


def test_main_module_imports_without_starting():
    main = importlib.import_module("atlas.main")
    assert hasattr(main, "AtlasSystem")


@pytest.mark.parametrize("phase,target", [(0, 8.0), (1, 5.0), (2, 4.0)])
def test_lifecycle_competition_phases(phase, target):
    from atlas.lifecycle import UserLifecycleEngine

    eng = UserLifecycleEngine()
    eng.phase_index = phase
    label, pct, _ = eng._phase_metadata("competition")
    assert pct == target and label


def test_lifecycle_open_market_and_state_is_advisory():
    from atlas.lifecycle import ChallengeProgressionState, UserLifecycleEngine

    assert UserLifecycleEngine()._phase_metadata("open_market")[1] == 10.0
    assert ChallengeProgressionState.__dataclass_fields__["execution_permission"].default == "none"


def test_backlog_tracker_reports_are_advisory():
    from atlas import backlog_tracker as bt

    for fn in (bt.compute_ai_usage_metering_and_zdr_status, bt.reconcile_cloud_training_and_foundation_gates):
        out = fn()
        assert out["execution_permission"] == "none"
        _no_execution_permission(out)
