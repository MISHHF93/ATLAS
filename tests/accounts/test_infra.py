import sqlite3

import pytest

from atlas.accounts import audit, db, middleware
from atlas.accounts.migrations import MIGRATIONS

from .conftest import PW, mkuser, signup


def test_migrations_are_ordered_forward_only_and_idempotent(acct_env):
    versions = [m[0] for m in MIGRATIONS]
    assert versions == sorted(set(versions)) and versions[0] == 1
    with db.connect() as c:
        first = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        assert db.migrate(c) == []   # nothing left to apply
    assert first == versions


def test_foreign_keys_on_and_cascade(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sessions (id,user_id,csrf_token,created_at,last_seen_at,expires_at) VALUES ('x','nouser','c',1,1,2)")


def test_audit_chain_detects_edit_and_delete(conn):
    u = mkuser(conn)
    audit.log(conn, u.id, "x.one"); audit.log(conn, u.id, "x.two"); audit.log(conn, u.id, "x.three")
    assert audit.verify_chain(conn)["ok"]
    conn.execute("UPDATE audit_log SET action='x.edited' WHERE action='x.two'")
    assert not audit.verify_chain(conn)["ok"]


def test_audit_redacts_secret_shaped_keys(conn):
    audit.log(conn, None, "t", detail={"api_key": "SHH-secret", "password": "pw", "nested_token": "tok", "written_fields": ["api_key"], "key_last4": "1234"})
    d = str(audit.recent(conn, None, 5))
    assert "SHH-secret" not in d and "pw'" not in d and "tok'" not in d and "1234" in d and "written_fields" in d


def test_client_ip_only_trusted_from_loopback_peer():
    ok = {"client": ("127.0.0.1", 0), "headers": [(b"x-atlas-client-ip", b"9.9.9.9")]}
    bad = {"client": ("8.8.8.8", 5), "headers": [(b"x-atlas-client-ip", b"9.9.9.9")]}
    assert middleware.client_ip(ok) == "9.9.9.9"
    assert middleware.client_ip(bad) == "8.8.8.8"


def test_per_ip_login_limit(client):
    codes = [client.post("/api/account/login", json={"email": f"u{i}@example.com", "password": "x" * 14}).status_code for i in range(32)]
    assert codes[:30] == [401] * 30 and 429 in codes[30:]


def test_register_rate_limit(client):
    codes = [client.post("/api/account/register", json={"email": f"n{i}@example.com", "password": PW}).status_code for i in range(12)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_oversize_body_rejected(client):
    h = signup(client)
    r = client.post("/api/account/profile", content=b'{"display_name":"' + b"x" * 40000 + b'"}', headers={**h, "content-type": "application/json"})
    assert r.status_code == 413


def test_account_config_never_reveals_keys(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_SUPERSECRET")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_SUPERSECRET")
    t = client.get("/api/account/config").text
    assert "SUPERSECRET" not in t and client.get("/api/account/config").json()["execution_permission"] == "none"


def test_execution_permission_stays_none():
    from atlas import accounts
    assert accounts.EXECUTION_PERMISSION == "none"
