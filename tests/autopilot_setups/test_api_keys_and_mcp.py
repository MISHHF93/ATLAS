"""API keys (hashed/scoped/revocable/rate-limited) and the localhost MCP endpoint. Synthetic fixtures only."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from atlas.api import agent
from atlas.api.app import app
from atlas.autopilot.setups import SetupAutopilot, Stream
from atlas.control.setup_autopilot_approval import approve_request
from atlas.keys.api_keys import ApiKeyStore, KeyError_
from tests.autopilot_setups.test_setup_autopilot import BARS, _approve


def test_keys_hashed_scoped_revocable_rate_limited(tmp_path):
    t = [0.0]
    st = ApiKeyStore(tmp_path / "k.json", clock=lambda: t[0])
    key, rec = st.create("claude", "read", rate_per_min=2)
    raw = (tmp_path / "k.json").read_text()
    assert key.split("_", 2)[2] not in raw and "digest" in raw and "digest" not in rec
    assert st.verify(key, "read")["key_id"] == rec["key_id"]
    with pytest.raises(KeyError_) as e:
        st.verify(key, "research")
    assert e.value.status == 403
    st.verify(key, "read")
    with pytest.raises(KeyError_) as e:
        st.verify(key, "read")
    assert e.value.code == "rate_limited" and e.value.status == 429
    t[0] += 30.0
    st.verify(key, "read")                                         # bucket refilled
    with pytest.raises(KeyError_):
        st.verify(key[:-2] + "xx", "read")
    assert st.revoke(rec["key_id"]) and not st.revoke(rec["key_id"])
    with pytest.raises(KeyError_) as e:
        st.verify(key, "read")
    assert e.value.code == "revoked_key"
    k2, _ = st.create("pa", "paper-trade")
    assert st.verify(k2, "research") and st.verify(k2, "read")
    with pytest.raises(ValueError):
        st.create("x", "admin")


@pytest.fixture
def env(tmp_path, monkeypatch):
    st = ApiKeyStore(tmp_path / "k.json")
    monkeypatch.setattr(agent, "_KEYS", st)
    ap = SetupAutopilot(lambda s, tf: list(BARS), [Stream("SPY", 3600, "us_equity_rth")])
    monkeypatch.setattr(agent, "_AP", ap)
    return st, ap, TestClient(app, base_url="http://127.0.0.1")


def _rpc(c, key, method, params=None, id_=1, **kw):
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
               headers={"Authorization": f"Bearer {key}", **kw.pop("headers", {})}, **kw)
    return r


def test_mcp_requires_key_and_localhost(env):
    st, _, c = env
    key, _ = st.create("claude", "read")
    assert c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert _rpc(c, key, "ping", headers={"Host": "evil.example"}).status_code == 403
    assert _rpc(c, key, "ping", headers={"Origin": "https://evil.example"}).status_code == 403
    r = _rpc(c, key, "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert r["result"]["serverInfo"]["name"] == "atlas-readonly"
    names = {t["name"] for t in _rpc(c, key, "tools/list").json()["result"]["tools"]}
    assert names == {"zones", "setups", "predict", "safe_stop_status"}          # read scope hides research tools
    assert _rpc(c, key, "tools/call", {"name": "replay", "arguments": {"symbol": "SPY"}}).status_code == 403
    rk, _ = st.create("grok", "research")
    names = {t["name"] for t in _rpc(c, rk, "tools/list").json()["result"]["tools"]}
    assert {"replay", "evidence"} <= names
    ev = _rpc(c, rk, "tools/call", {"name": "evidence", "arguments": {}}).json()["result"]
    assert "price-action-setups-2026-10-23.json" in json.loads(ev["content"][0]["text"])["files"]
    ss = _rpc(c, key, "tools/call", {"name": "safe_stop_status", "arguments": {}}).json()["result"]
    assert ss["structuredContent"]["execution_permission"] == "none" and not ss["isError"]
    assert _rpc(c, key, "tools/call", {"name": "place_order", "arguments": {}}).json()["error"]["code"] == -32602
    assert _rpc(c, key, "nope").json()["error"]["code"] == -32601


def test_autopilot_api_needs_paper_scope_and_owner_approval(env):
    st, ap, c = env
    rk, _ = st.create("ro", "read"); pk, _ = st.create("pt", "paper-trade")
    h = lambda k: {"Authorization": f"Bearer {k}"}
    assert c.get("/api/quant/autopilot").status_code == 401
    s = c.get("/api/quant/autopilot", headers=h(rk)).json()
    assert s["on"] is False and s["live_trading"] == "disabled"
    assert c.post("/api/quant/autopilot/request-on", json={}, headers=h(rk)).status_code == 403
    req = c.post("/api/quant/autopilot/request-on", json={"note": "t"}, headers=h(pk)).json()
    assert req["status"] == "pending_owner_approval" and "setup-autopilot-approve" in req["approve_with"]
    assert c.post("/api/quant/autopilot/tick", headers=h(pk)).json()["state"] == "off"   # not approved yet
    _approve(ap, req["id"], "owner", True)          # owner CLI path (step-up) in production
    ap.start_background = lambda *a, **k: None                      # no thread in tests
    out = c.post("/api/quant/autopilot/tick", headers=h(pk)).json()
    assert out["state"] == "on" and all(d["decision"] == "abstain" for d in out["decisions"])
    assert c.post("/api/quant/autopilot/off", json={"reason": "done"}, headers=h(rk)).json()["on"] is False
