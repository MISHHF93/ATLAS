import json

import pytest

from atlas.accounts import audit, connectors, credentials, db

from .conftest import mkuser, signup

KEY = "abcd1234efgh5678"


def _two(client):
    ha = signup(client, "a@example.com")
    client.post("/api/account/connectors/tiingo/save", json={"values": {"api_key": KEY}}, headers=ha)
    client.cookies.clear()
    hb = signup(client, "b@example.com")
    return ha, hb


def test_user_b_cannot_see_user_a_connectors(client):
    _two(client)
    lib = client.get("/api/account/connectors").json()["connectors"]
    tiingo = [c for c in lib if c["id"] == "tiingo"][0]
    assert tiingo["state"] is None and tiingo["light"] == "gray"
    assert KEY not in client.get("/api/account/connectors").text


def test_user_b_cannot_test_rotate_delete_users_a_connector(client):
    _, hb = _two(client)
    assert client.post("/api/account/connectors/tiingo/test", headers=hb).status_code == 404
    assert client.post("/api/account/connectors/tiingo/rotate", json={"field": "api_key", "value": "zzzz1111yyyy2222"}, headers=hb).status_code in (404, 422)
    assert client.post("/api/account/connectors/tiingo/delete", headers=hb).json()["deleted"] is False
    client.cookies.clear()
    client.post("/api/account/login", json={"email": "a@example.com", "password": "correct horse battery staple 9"})
    st = [c for c in client.get("/api/account/connectors").json()["connectors"] if c["id"] == "tiingo"][0]["state"]
    assert st["secrets"]["api_key"]["last4"] == "5678" and st["secrets"]["api_key"]["version"] == 1


def test_connector_endpoints_require_login(client):
    assert client.get("/api/account/connectors").status_code == 401
    assert client.post("/api/account/connectors/tiingo/save", json={"values": {"api_key": KEY}}).status_code == 401
    assert client.get("/api/account/audit").status_code == 401


def test_audit_view_only_own_events(client):
    _two(client)
    ev = client.get("/api/account/audit").json()["events"]
    assert all("connector" not in e["action"] for e in ev)


def test_secrets_are_write_only_in_every_response(client):
    h = signup(client)
    secret = "WRITEONLY-secret-9999aaaa"
    r1 = client.post("/api/account/connectors/finnhub/save", json={"values": {"api_key": secret}}, headers=h)
    r2 = client.get("/api/account/connectors")
    r3 = client.post("/api/account/connectors/finnhub/rotate", json={"field": "api_key", "value": secret + "R"}, headers=h)
    r4 = client.get("/api/account/audit")
    r5 = client.get("/api/billing/subscription")
    for r in (r1, r2, r3, r4, r5):
        assert secret not in r.text and (secret + "R") not in r.text
    st = r3.json()["state"]["secrets"]["api_key"]
    assert st == {**st, "set": True, "last4": "aaaR"} and st["version"] == 2


def test_validation_error_does_not_echo_secret(client):
    h = signup(client)
    secret = "NOT-A-VALID-KEY-SHAPE-!!!-leak"
    r = client.post("/api/account/connectors/fred/save", json={"values": {"api_key": secret}}, headers=h)
    assert r.status_code in (400, 422) and secret not in r.text
    r = client.post("/api/account/connectors/tiingo/save", data="{" + secret, headers={**h, "content-type": "application/json"})
    assert r.status_code == 400 and secret not in r.text


def test_save_fails_closed_without_master_key(client, monkeypatch):
    h = signup(client)
    monkeypatch.delenv("ATLAS_MASTER_KEY")
    r = client.post("/api/account/connectors/tiingo/save", json={"values": {"api_key": KEY}}, headers=h)
    assert r.status_code == 503 and r.json()["error"] == "master_key_unavailable"
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM connectors").fetchone()[0] == 0
    assert KEY not in r.text


def test_unknown_connector_404(client):
    h = signup(client)
    assert client.post("/api/account/connectors/nope/save", json={"values": {}}, headers=h).status_code == 404


def test_rotate_bumps_version_and_old_ciphertext_gone(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "tiingo", {"api_key": KEY})
    before = conn.execute("SELECT ciphertext FROM connector_secrets").fetchone()[0]
    connectors.rotate(conn, u.id, "tiingo", "api_key", "newkey11112222")
    after = conn.execute("SELECT ciphertext, version FROM connector_secrets").fetchone()
    assert after[0] != before and after[1] == 2
    assert connectors.load_values(conn, u.id, "tiingo")["api_key"] == "newkey11112222"


def test_delete_removes_secrets_and_is_audited(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "tiingo", {"api_key": KEY})
    assert connectors.delete(conn, u.id, "tiingo") is True
    assert conn.execute("SELECT COUNT(*) FROM connector_secrets").fetchone()[0] == 0
    assert any(e["action"] == "connector.delete" for e in audit.recent(conn, u.id, 20))


def test_partial_update_keeps_existing_secret(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "oanda", {"account_id": "101-001-1234567-001", "api_token": "tok-aaaaaaaaaaaaaaaaaaaa"})
    connectors.save(conn, u.id, "oanda", {"account_id": "101-001-1234567-002"})
    v = connectors.load_values(conn, u.id, "oanda")
    assert v["api_token"] == "tok-aaaaaaaaaaaaaaaaaaaa" and v["account_id"].endswith("002")


# ---- credential resolution ----
def test_owner_falls_back_to_env_and_db_wins(conn, monkeypatch):
    owner = mkuser(conn, "boss@example.com", env={"ATLAS_OWNER_EMAIL": "boss@example.com"})
    assert owner.role == "owner"
    monkeypatch.setenv("TIINGO_API_KEY", "ENVKEY0000000000")
    t = credentials.set_identity(owner.id, "owner")
    try:
        assert credentials.effective_environ()["TIINGO_API_KEY"] == "ENVKEY0000000000"
    finally:
        credentials.reset_identity(t)
    connectors.save(conn, owner.id, "tiingo", {"api_key": "DBKEY11111111111"})
    t = credentials.set_identity(owner.id, "owner")
    try:
        assert credentials.effective_environ()["TIINGO_API_KEY"] == "DBKEY11111111111"
    finally:
        credentials.reset_identity(t)


def test_other_users_never_see_owner_env_or_other_users(conn, monkeypatch):
    a, b = mkuser(conn, "a@example.com"), mkuser(conn, "b@example.com")
    monkeypatch.setenv("TIINGO_API_KEY", "OWNER-ENV-KEY-0001")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PKOWNERENV")
    monkeypatch.setenv("ATLAS_MASTER_KEY_PREVIOUS", __import__("atlas.accounts.crypto", fromlist=["x"]).generate_master_key())
    connectors.save(conn, a.id, "tiingo", {"api_key": "A-USERS-KEY-111111"})
    t = credentials.set_identity(b.id, "user")
    try:
        env = credentials.effective_environ()
        assert "TIINGO_API_KEY" not in env and "ALPACA_API_KEY_ID" not in env and "ATLAS_MASTER_KEY" not in env and "ATLAS_MASTER_KEY_PREVIOUS" not in env
        assert "OWNER-ENV-KEY-0001" not in json.dumps(dict(env))
    finally:
        credentials.reset_identity(t)
    t = credentials.set_identity(a.id, "user")
    try:
        assert credentials.effective_environ()["TIINGO_API_KEY"] == "A-USERS-KEY-111111"
    finally:
        credentials.reset_identity(t)


def test_no_identity_is_plain_process_env(monkeypatch):
    import os
    monkeypatch.setenv("TIINGO_API_KEY", "PLAIN")
    assert credentials.effective_environ() is os.environ


def test_adapter_resolves_per_user_via_http_context(conn, monkeypatch):
    from atlas.integrations.registry import load_env
    a = mkuser(conn, "a@example.com")
    monkeypatch.setenv("TIINGO_API_KEY", "OWNER-ENV")
    connectors.save(conn, a.id, "tiingo", {"api_key": "A-USERS-KEY-111111"})
    t = credentials.set_identity(a.id, "user")
    try:
        assert load_env().get("TIINGO_API_KEY") == "A-USERS-KEY-111111"
    finally:
        credentials.reset_identity(t)
