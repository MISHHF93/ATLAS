import pytest

from atlas.accounts import crypto, db


@pytest.fixture()
def acct_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(tmp_path / "accounts.sqlite"))
    monkeypatch.setenv("ATLAS_MASTER_KEY", crypto.generate_master_key())
    for k in ("ATLAS_MASTER_KEY_PREVIOUS", "ATLAS_OWNER_EMAIL", "ATLAS_REQUIRE_AUTH", "ATLAS_REGISTRATION", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
              "ATLAS_COOKIE_SECURE", "ATLAS_PUBLIC_URL", "ATLAS_ENV", "ATLAS_TRUSTED_PROXIES", "ATLAS_REQUIRE_EMAIL_VERIFICATION", "ATLAS_MAIL_BACKEND",
              "ATLAS_MAIL_OUTBOX", "ATLAS_SMTP_HOST", "ATLAS_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ATLAS_REGISTRATION", "open")  # the shipped default is invite-only; the legacy suites exercise open sign-up
    db.reset_for_tests()
    yield tmp_path
    db.reset_for_tests()


@pytest.fixture()
def conn(acct_env):
    with db.connect() as c:
        yield c


PW = "correct horse battery staple 9"


def mkuser(conn, email="a@example.com", pw=PW, **kw):
    from atlas.accounts import auth
    return auth.register(conn, email, pw, ip=kw.pop("ip", "10.0.0.1"), **kw)


@pytest.fixture()
def client(acct_env):
    from fastapi.testclient import TestClient

    from atlas.api.app import app
    yield TestClient(app)


def signup(client, email="a@example.com", pw=PW):
    r = client.post("/api/account/register", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    assert "set-cookie" not in r.headers  # sign-up never opens a session (anti-enumeration)
    r = client.post("/api/account/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}
