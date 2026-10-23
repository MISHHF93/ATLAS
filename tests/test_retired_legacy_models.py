"""Retired heuristic HTTP routes cannot train, construct models, or submit orders."""

from __future__ import annotations

from importlib import import_module

from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/ml/perfect-trader/state?symbol=BTC-USD&force_submit=true", None),
        ("POST", "/api/ml/perfect-trader/train", {"symbol": "NVDA"}),
        ("POST", "/api/ml/perfect-trader/auto-submit", {"action": "toggle_armed", "armed": True}),
        ("POST", "/api/ml/perfect-trader/auto-submit", {"action": "scan_multi_asset"}),
        ("POST", "/api/ml/perfect-trader/auto-submit", {"action": "auto_submit_symbol"}),
        ("GET", "/api/automation/visual-scan?symbol=NVDA", None),
        ("POST", "/api/automation/visual-scan", {"symbol": "BTC-USD", "trigger_dispatch": True}),
    ],
)
def test_retired_route_refuses_before_legacy_or_order_activity(monkeypatch, method, path, payload):
    api = import_module("atlas.api.app")

    class ForbiddenLegacyEngine:
        def __getattribute__(self, name):
            pytest.fail(f"Retired route accessed the legacy engine: {name}")

    def forbidden_activity(*args, **kwargs):
        pytest.fail("Retired route attempted model training, data access, or financial activity")

    monkeypatch.setattr(api, "_PERFECT_TRADER_WHALE_ENGINE", ForbiddenLegacyEngine(), raising=False)
    monkeypatch.setattr(api, "PerfectTraderWhaleEngine", forbidden_activity, raising=False)
    for method_name in ("submit_order", "process_strategy_signal", "ingest_whale_policy_signal", "record_training_run"):
        monkeypatch.setattr(api.control_engine, method_name, forbidden_activity)
    monkeypatch.setattr(api.live_market_gateway, "fetch_live_market_candles_and_ingest", forbidden_activity)
    monkeypatch.setattr(api._WHALE_POLICY_TRAINER, "train", forbidden_activity, raising=False)
    before = api.control_engine.get_state().model_dump(mode="json")

    response = TestClient(api.app).request(method, path, json=payload)

    assert response.status_code == 410
    assert response.json() == {
        "detail": {
            "status": "retired",
            "replacement": "/api/research/vertical-slice",
            "reason": "Legacy heuristic outputs are not validated model evidence.",
            "execution_permission": "none",
        }
    }
    after = api.control_engine.get_state().model_dump(mode="json")
    for field in ("order_history", "open_positions", "training_runs_completed", "audit_log"):
        assert after[field] == before[field]
