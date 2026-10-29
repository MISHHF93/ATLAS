"""HTTP surface of the Setup checklist, go-live readiness and Massive live status. Read-only; no secrets in any body."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("xgboost")
from fastapi.testclient import TestClient  # noqa: E402

from atlas.api.app import app  # noqa: E402

SECRET = "api-test-secret-value-9876543210abcdef"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MASSIVE_API_KEY", SECRET)
    monkeypatch.setenv("ATLAS_ML_DIRECTIONAL", str(tmp_path / "ml"))
    return TestClient(app)


def test_checklist_endpoint(client):
    r = client.get("/api/integrations/checklist")
    assert r.status_code == 200
    b = r.json()
    assert [i["key"] for i in b["items"][:5]] == ["massive", "gemini", "edgar", "fred", "broker_paper"]
    assert SECRET not in json.dumps(b)
    assert b["execution_permission"] == "none"


def test_golive_endpoint_is_read_only_and_refuses_everything(client):
    r = client.get("/api/integrations/golive-readiness")
    assert r.status_code == 200
    b = r.json()
    assert b["read_only"] is True and b["execution_permission"] == "none" and b["live_endpoints"] == "refused"
    assert len(b["gates"]) == 5 and b["gates"][-1]["key"] == "owner_signoff" and b["gates"][-1]["state"] == "pending"
    for verb in (client.post, client.put, client.delete):
        assert verb("/api/integrations/golive-readiness").status_code in (404, 405)


def test_massive_live_and_predictions_endpoints(client):
    b = client.get("/api/integrations/massive-live?symbol=SPY").json()
    assert b["capability"]["mode"] == "eod_lag" and b["execution_permission"] == "none"
    p = client.get("/api/integrations/live-predictions?symbols=SPY,BTCUSDT").json()
    assert {r["symbol"] for r in p["rows"]} == {"SPY", "BTCUSDT"} and p["paper_only"] is True
    assert SECRET not in json.dumps([b, p])
