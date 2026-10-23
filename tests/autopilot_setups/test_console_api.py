"""Console endpoints: localhost + header guarded, only read or risk-reducing writes. Synthetic fixtures only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas.api import agent
from atlas.api.app import app
from atlas.autopilot.setups import SetupAutopilot, Stream
from atlas.keys.api_keys import ApiKeyStore
from tests.autopilot_setups.test_setup_autopilot import BARS

H = {"X-Atlas-Console": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    st = ApiKeyStore(tmp_path / "k.json")
    monkeypatch.setattr(agent, "_KEYS", st)
    ap = SetupAutopilot(lambda s, tf: list(BARS), [Stream("SPY", 3600, "us_equity_rth")])
    monkeypatch.setattr(agent, "_AP", ap)
    return st, ap, TestClient(app, base_url="http://127.0.0.1")


def test_autopilot_request_needs_owner_approval(env):
    _, ap, c = env
    r = c.post("/api/console/autopilot/request-on", json={"note": "ui"}, headers=H).json()
    assert r["status"] == "pending_owner_approval" and r["id"] in r["approve_with"]
    assert not ap.is_on()                                   # filing a request never switches it on
    s = c.get("/api/console/autopilot").json()
    assert s["on"] is False and s["pending_requests"][0]["id"] == r["id"] and s["approve_with"]
    assert c.post("/api/console/autopilot/off", json={}, headers=H).json()["on"] is False


def test_writes_need_header_and_localhost(env):
    _, _, c = env
    assert c.post("/api/console/autopilot/request-on", json={}).status_code == 403
    assert c.post("/api/console/keys", json={"name": "x"}, headers={**H, "Origin": "http://evil.example"}).status_code == 403
    remote = TestClient(app, base_url="http://atlas.example.com")
    assert remote.get("/api/console/keys").status_code == 403


def test_keys_create_once_list_revoke_and_no_paper_trade(env):
    st, _, c = env
    r = c.post("/api/console/keys", json={"name": "claude", "scope": "research"}, headers=H).json()
    assert r["key"].startswith("atk_") and r["shown_once"]
    listed = c.get("/api/console/keys").json()["keys"]
    assert listed[0]["key_id"] == r["record"]["key_id"] and r["key"] not in str(listed)
    assert c.post("/api/console/keys", json={"name": "p", "scope": "paper-trade"}, headers=H).status_code == 403
    kid = r["record"]["key_id"]
    assert c.post(f"/api/console/keys/{kid}/revoke", headers=H).status_code == 200
    assert c.post(f"/api/console/keys/{kid}/revoke", headers=H).status_code == 404


def test_approve_is_cli_only_and_unknown_reject_404(env):
    _, _, c = env
    r = c.post("/api/console/approvals/abc/approve", headers=H)
    assert r.status_code == 403 and "atlas-owner approve abc" in r.json()["detail"]
    assert c.post("/api/console/approvals/nope/reject", headers=H).status_code == 404


def test_shadow_read_only(env):
    _, _, c = env
    r = c.get("/api/console/shadow").json()
    assert r["execution_permission"] == "none" and isinstance(r["weeks"], list)


def test_models_and_evidence(env):
    _, _, c = env
    assert isinstance(c.get("/api/console/models").json()["versions"], list)
    files = c.get("/api/console/evidence").json()["files"]
    assert files and c.get("/api/console/evidence", params={"name": files[0]}).json()["name"] == files[0]
    assert c.get("/api/console/evidence", params={"name": "../x.json"}).status_code == 404
