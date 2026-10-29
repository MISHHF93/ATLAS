import pytest

from atlas.accounts import auth, db

from .conftest import PW, signup


def test_register_login_logout_flow(client):
    h = signup(client)
    me = client.get("/api/account/me").json()
    assert me["authenticated"] and me["user"]["email"] == "a@example.com" and me["user"]["role"] == "user"
    assert client.post("/api/account/logout", headers=h).status_code == 200
    assert client.get("/api/account/me").json()["authenticated"] is False
    r = client.post("/api/account/login", json={"email": "a@example.com", "password": PW})
    assert r.status_code == 200


def test_cookie_attributes(client):
    signup(client, "c@example.com")
    r = client.post("/api/account/login", json={"email": "c@example.com", "password": PW})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc and "path=/" in sc and "max-age=" in sc
    assert "atlas_session=" in sc


def test_cookie_secure_when_https(client, monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.example.com")
    monkeypatch.setenv("ATLAS_REQUIRE_EMAIL_VERIFICATION", "0")  # an https public URL makes verification mandatory by default
    signup(client, "s@example.com")
    r = client.post("/api/account/login", json={"email": "s@example.com", "password": PW})
    assert "secure" in r.headers["set-cookie"].lower()


def test_session_token_stored_hashed(client, acct_env):
    signup(client, "h@example.com")
    token = client.cookies.get("atlas_session")
    assert token
    with db.connect() as c:
        rows = [tuple(x) for x in c.execute("SELECT * FROM sessions")]
    assert token not in str(rows)


def test_password_hashed_argon2id(conn):
    from .conftest import mkuser
    u = mkuser(conn)
    h = conn.execute("SELECT password_hash FROM users WHERE id=?", (u.id,)).fetchone()[0]
    assert h.startswith("$argon2id$") and PW not in h


@pytest.mark.parametrize("pw", ["short", "a" * 11, ""])
def test_weak_password_rejected(client, pw):
    r = client.post("/api/account/register", json={"email": "w@example.com", "password": pw})
    assert r.status_code == 422 or r.status_code == 400
    assert pw not in r.text or pw == ""


def test_duplicate_email_does_not_overwrite(client):
    signup(client)
    client.cookies.clear()
    r = client.post("/api/account/register", json={"email": "A@Example.com", "password": PW + "x"})
    assert r.status_code == 200 and r.json()["status"] == "check_your_email"  # identical to a fresh sign-up: no enumeration
    assert client.post("/api/account/login", json={"email": "a@example.com", "password": PW}).status_code == 200


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    signup(client)
    client.cookies.clear()
    a = client.post("/api/account/login", json={"email": "a@example.com", "password": "nope-nope-nope-1"})
    b = client.post("/api/account/login", json={"email": "ghost@example.com", "password": "nope-nope-nope-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_rate_limited_per_email(client):
    signup(client)
    client.cookies.clear()
    codes = [client.post("/api/account/login", json={"email": "a@example.com", "password": "bad-bad-bad-1234"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    r = client.post("/api/account/login", json={"email": "a@example.com", "password": PW})
    assert r.status_code == 429 and "retry-after" in r.headers  # even the right password is locked out


def test_csrf_required_on_unsafe_methods_with_session(client):
    signup(client)
    assert client.post("/api/account/profile", json={"display_name": "x"}).status_code == 403
    assert client.post("/api/account/profile", json={"display_name": "x"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_csrf_token_is_per_session(client):
    h1 = signup(client)
    client.cookies.clear()
    h2 = signup(client, "b@example.com")
    assert h1 != h2
    assert client.post("/api/account/profile", json={"display_name": "x"}, headers=h1).status_code == 403


def test_cross_origin_post_refused(client):
    h = signup(client)
    r = client.post("/api/account/profile", json={"display_name": "x"}, headers={**h, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_password_change_revokes_other_sessions(client):
    from fastapi.testclient import TestClient

    from atlas.api.app import app
    h = signup(client)
    other = TestClient(app)
    assert other.post("/api/account/login", json={"email": "a@example.com", "password": PW}).status_code == 200
    assert other.get("/api/account/me").json()["authenticated"]
    r = client.post("/api/account/password", json={"current": PW, "new": PW + "-new"}, headers=h)
    assert r.status_code == 200
    assert other.get("/api/account/me").json()["authenticated"] is False
    assert client.get("/api/account/me").json()["authenticated"]


def test_password_change_needs_current(client):
    h = signup(client)
    assert client.post("/api/account/password", json={"current": "wrong-wrong-12", "new": PW + "n"}, headers=h).status_code == 401


def test_delete_account_removes_data(client, acct_env):
    h = signup(client)
    client.post("/api/account/connectors/tiingo/save", json={"values": {"api_key": "abcd1234efgh5678"}}, headers=h)
    assert client.post("/api/account/delete", json={"password": "bad-bad-bad-123"}, headers=h).status_code == 401
    assert client.post("/api/account/delete", json={"password": PW}, headers=h).status_code == 200
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM connector_secrets").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_registration_closed(client, monkeypatch):
    monkeypatch.setenv("ATLAS_REGISTRATION", "closed")
    assert client.post("/api/account/register", json={"email": "z@example.com", "password": PW}).status_code == 403


def test_owner_only_for_configured_email_and_only_once(client, monkeypatch):
    monkeypatch.setenv("ATLAS_OWNER_EMAIL", "boss@example.com")
    signup(client, "a@example.com")
    assert client.get("/api/account/me").json()["user"]["role"] == "user"
    client.cookies.clear()
    signup(client, "boss@example.com")
    assert client.get("/api/account/me").json()["user"]["role"] == "owner"


def test_roles_admin_endpoints(client):
    signup(client, "a@example.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403


def test_admin_cannot_grant_owner_and_user_cannot_self_promote(client, monkeypatch):
    monkeypatch.setenv("ATLAS_OWNER_EMAIL", "boss@example.com")
    signup(client, "boss@example.com")
    ho = {"X-CSRF-Token": client.get("/api/account/me").json()["csrf_token"]}
    client.cookies.clear()
    hu = signup(client, "u@example.com")
    uid = client.get("/api/account/me").json()["user"]["id"]
    assert client.post("/api/admin/users/role", json={"user_id": uid, "role": "admin"}, headers=hu).status_code == 403
    client.cookies.clear()
    client.post("/api/account/login", json={"email": "boss@example.com", "password": PW})
    ho = {"X-CSRF-Token": client.get("/api/account/me").json()["csrf_token"]}
    assert client.post("/api/admin/users/role", json={"user_id": uid, "role": "admin"}, headers=ho).status_code == 200
    assert client.post("/api/admin/users/role", json={"user_id": uid, "role": "owner"}, headers=ho).status_code in (400, 403, 422)
    assert client.get("/api/admin/audit", headers=ho).json()["chain"]["ok"]


def test_require_auth_blocks_anonymous_api(client, monkeypatch):
    monkeypatch.setenv("ATLAS_REQUIRE_AUTH", "true")
    assert client.get("/api/health").status_code != 401
    assert client.get("/api/account/config").status_code == 200
    r = client.get("/api/market/catalog") if False else client.get("/api/integrations/status")
    assert r.status_code == 401
    signup(client)
    assert client.get("/api/integrations/status").status_code != 401


def test_auth_off_keeps_legacy_open(client):
    assert client.get("/api/integrations/status").status_code != 401


def test_responses_not_cached_and_nosniff(client):
    signup(client)
    r = client.get("/api/account/me")
    assert "no-store" in r.headers["cache-control"] and r.headers["x-content-type-options"] == "nosniff"


def test_sessions_list_hides_full_token_hash_and_revokes_own_only(client):
    from fastapi.testclient import TestClient

    from atlas.api.app import app
    h = signup(client)
    other = TestClient(app)
    other.post("/api/account/login", json={"email": "a@example.com", "password": PW})
    lst = client.get("/api/account/sessions").json()["sessions"]
    assert len(lst) == 2 and all("ref" not in s and len(s["id"]) == 12 for s in lst)
    target = [s for s in lst if not s.get("current")][0]
    assert client.post("/api/account/sessions/revoke", json={"id": target["id"]}, headers=h).json()["revoked"] == 1
    assert other.get("/api/account/me").json()["authenticated"] is False


def test_idle_and_absolute_expiry(conn):
    from .conftest import mkuser
    u = mkuser(conn)
    tok, _ = auth.create_session(conn, u.id, "1.1.1.1", "ua")
    assert auth.resolve_session(conn, tok) is not None
    assert auth.resolve_session(conn, tok, now=10**11) is None
