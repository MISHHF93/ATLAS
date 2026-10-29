"""evo-12 public-launch hardening: registration modes, invites, email verification, password reset, anti-enumeration, trusted-proxy
client IP, require-auth defaults, security headers, Team seats, Postgres schema path."""
from __future__ import annotations

import re
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from atlas.accounts import auth, billing, db, dialect, mailer, netinfo, onboarding, stripe_client, teams
from atlas.accounts.entitlements import EntitlementDenied

from .conftest import PW, mkuser, signup
from .test_billing import _event

PUBLIC_IP = ("203.0.113.9", 50000)


@pytest.fixture()
def outbox(acct_env):
    m = mailer.MemoryMailer()
    mailer.set_mailer(m)
    yield m.outbox
    mailer.set_mailer(None)


def token_from(msg, key):
    return re.search(key + r"=([\w\-]+)", msg.text).group(1)


def last(outbox, kind):
    return [m for m in outbox if m.kind == kind][-1]


@pytest.fixture()
def pub(acct_env):
    from atlas.api.app import app
    return TestClient(app, client=PUBLIC_IP)


def as_admin(client, email="boss@example.com"):
    h = signup(client, email)
    with db.connect() as c:
        c.execute("UPDATE users SET role='admin' WHERE email=?", (email,))
    return h


# ------------------------------------------------------------------ netinfo
def hdr(**kw):
    kw = {k.replace("_", "-"): v for k, v in kw.items()}
    return lambda name: kw.get(name, "")


def test_xff_ignored_without_trusted_proxy():
    assert netinfo.resolve_client_ip("198.51.100.7", hdr(x_forwarded_for="1.2.3.4"), {}) == "198.51.100.7"


def test_xff_walked_from_the_right_through_trusted_proxies():
    env = {"ATLAS_TRUSTED_PROXIES": "10.0.0.0/8, 192.0.2.1"}
    # attacker prepends 6.6.6.6; the proxy appended the real client; our own proxy hop is trusted
    assert netinfo.resolve_client_ip("10.0.0.5", hdr(x_forwarded_for="6.6.6.6, 198.51.100.7, 10.0.0.9"), env) == "198.51.100.7"
    assert netinfo.resolve_client_ip("10.0.0.5", hdr(x_forwarded_for="198.51.100.7"), env) == "198.51.100.7"


def test_xff_not_honoured_from_an_untrusted_peer_even_when_proxies_configured():
    env = {"ATLAS_TRUSTED_PROXIES": "10.0.0.0/8"}
    assert netinfo.resolve_client_ip("198.51.100.7", hdr(x_forwarded_for="1.2.3.4"), env) == "198.51.100.7"


def test_malformed_xff_entry_falls_back_to_last_trusted_hop():
    env = {"ATLAS_TRUSTED_PROXIES": "10.0.0.0/8"}
    assert netinfo.resolve_client_ip("10.0.0.5", hdr(x_forwarded_for="evil, 10.0.0.9"), env) == "10.0.0.9"
    assert netinfo.resolve_client_ip("10.0.0.5", hdr(x_forwarded_for="not-an-ip"), env) == "10.0.0.5"


def test_loopback_bridge_header_trusted_only_from_loopback():
    assert netinfo.resolve_client_ip("127.0.0.1", hdr(x_atlas_client_ip="198.51.100.7"), {}) == "198.51.100.7"
    assert netinfo.resolve_client_ip("198.51.100.8", hdr(x_atlas_client_ip="1.1.1.1"), {}) == "198.51.100.8"


def test_trusted_proxy_chain_with_bridge():
    env = {"ATLAS_TRUSTED_PROXIES": "172.16.0.0/12"}
    assert netinfo.resolve_client_ip("127.0.0.1", hdr(x_atlas_client_ip="172.16.0.3", x_forwarded_for="198.51.100.7"), env) == "198.51.100.7"


def test_parse_networks_ignores_garbage():
    assert len(netinfo.parse_networks("10.0.0.0/8, nonsense, ::1, 192.0.2.4/33")) == 2


def test_rate_limit_keys_on_forwarded_client_when_proxy_trusted(acct_env, monkeypatch):
    monkeypatch.setenv("ATLAS_TRUSTED_PROXIES", "203.0.113.9")
    from atlas.api.app import app
    c = TestClient(app, client=PUBLIC_IP)
    for i in range(30):
        assert c.post("/api/account/login", json={"email": f"u{i}@example.com", "password": "x" * 14}, headers={"x-forwarded-for": "198.51.100.1"}).status_code == 401
    assert c.post("/api/account/login", json={"email": "z@example.com", "password": "x" * 14}, headers={"x-forwarded-for": "198.51.100.1"}).status_code == 429
    # a different real client behind the same proxy is not throttled
    assert c.post("/api/account/login", json={"email": "z@example.com", "password": "x" * 14}, headers={"x-forwarded-for": "198.51.100.2"}).status_code == 401
    # a spoofed left-most value cannot dodge the limit
    assert c.post("/api/account/login", json={"email": "q@example.com", "password": "x" * 14}, headers={"x-forwarded-for": "9.9.9.9, 198.51.100.1"}).status_code == 429


# ------------------------------------------------------------------ require_auth defaults
def test_require_auth_defaults():
    assert netinfo.require_auth("127.0.0.1", hdr(), {}) is False
    assert netinfo.require_auth("testclient", hdr(), {}) is False
    assert netinfo.require_auth("198.51.100.7", hdr(), {}) is True
    assert netinfo.require_auth("127.0.0.1", hdr(x_forwarded_for="1.2.3.4"), {}) is True  # loopback peer but a reverse proxy in front
    assert netinfo.require_auth("127.0.0.1", hdr(), {"ATLAS_ENV": "production"}) is True
    assert netinfo.require_auth("127.0.0.1", hdr(), {"ATLAS_PUBLIC_URL": "https://atlas.example.com"}) is True
    assert netinfo.require_auth("127.0.0.1", hdr(), {"ATLAS_PUBLIC_URL": "http://localhost:3000"}) is False
    assert netinfo.require_auth("198.51.100.7", hdr(), {"ATLAS_REQUIRE_AUTH": "0"}) is False  # an explicit setting wins
    assert netinfo.require_auth("127.0.0.1", hdr(), {"ATLAS_REQUIRE_AUTH": "1"}) is True


def test_api_requires_session_for_remote_clients_by_default(pub, client):
    assert pub.get("/api/billing/plans").status_code in (401, 200)
    r = pub.get("/api/account/sessions")
    assert r.status_code == 401
    assert pub.get("/api/health").status_code == 200  # public
    assert pub.get("/api/account/config").json()["require_auth"] is True
    assert client.get("/api/account/config").json()["require_auth"] is False  # in-process localhost-style client: unchanged


def test_spoofed_proxy_headers_cannot_lower_requirement(client, monkeypatch):
    # a loopback caller sending X-Forwarded-For is treated as behind a proxy -> auth required
    assert client.get("/api/account/config", headers={"x-forwarded-for": "1.2.3.4"}).json()["require_auth"] is True


def test_public_env_makes_email_verification_mandatory():
    assert netinfo.require_email_verification({}) is False
    assert netinfo.require_email_verification({"ATLAS_ENV": "prod"}) is True
    assert netinfo.require_email_verification({"ATLAS_ENV": "prod", "ATLAS_REQUIRE_EMAIL_VERIFICATION": "0"}) is False


# ------------------------------------------------------------------ registration modes + invites
def reg(client, email="n@example.com", pw=PW, **kw):
    return client.post("/api/account/register", json={"email": email, "password": pw, **kw})


def test_default_registration_mode_is_invite(client, monkeypatch, outbox):
    monkeypatch.delenv("ATLAS_REGISTRATION")
    assert auth.registration_mode() == "invite"
    r = reg(client)
    assert r.status_code == 403 and r.json()["error"] == "invite_required"
    assert not outbox
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_closed_mode_refuses_even_with_a_valid_invite(client, monkeypatch, conn):
    adm = mkuser(conn, "adm@example.com")
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (adm.id,))
    code = onboarding.create_invite(conn, auth.get_user(conn, adm.id), send=False)["code"]
    monkeypatch.setenv("ATLAS_REGISTRATION", "closed")
    assert reg(client, invite=code).status_code == 403


def test_invite_registration_single_use_and_email_bound(client, monkeypatch, conn, outbox):
    monkeypatch.setenv("ATLAS_REGISTRATION", "invite")
    adm = mkuser(conn, "adm@example.com")
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (adm.id,))
    admin = auth.get_user(conn, adm.id)
    bound = onboarding.create_invite(conn, admin, "friend@example.com", send=False)
    open_ = onboarding.create_invite(conn, admin, None, send=False)
    assert reg(client, "wrong@example.com", invite=bound["code"]).json()["error"] == "invite_invalid"  # bound to another address
    assert reg(client, "friend@example.com", invite="inv_nonsense").status_code == 403
    assert reg(client, "friend@example.com", invite=bound["code"]).status_code == 200
    assert reg(client, "friend@example.com", invite=bound["code"]).status_code == 403  # consumed: refused whether or not the account exists
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email='friend@example.com'").fetchone()[0] == 1
    assert conn.execute("SELECT uses FROM invites WHERE id=?", (bound["id"],)).fetchone()[0] == 1
    assert reg(client, "second@example.com", invite=bound["code"]).status_code == 403
    assert reg(client, "open1@example.com", invite=open_["code"]).status_code == 200
    assert reg(client, "open2@example.com", invite=open_["code"]).status_code == 403  # single use
    # an email-bound invite proves control of the address: no verification mail, account is verified
    assert conn.execute("SELECT email_verified FROM users WHERE email='friend@example.com'").fetchone()[0] == 1
    assert conn.execute("SELECT email_verified FROM users WHERE email='open1@example.com'").fetchone()[0] == 0


def test_invite_expiry_revocation_and_hashing(client, monkeypatch, conn):
    monkeypatch.setenv("ATLAS_REGISTRATION", "invite")
    adm = mkuser(conn, "adm@example.com")
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (adm.id,))
    admin = auth.get_user(conn, adm.id)
    a = onboarding.create_invite(conn, admin, None, ttl_days=1, send=False)
    b = onboarding.create_invite(conn, admin, None, send=False)
    stored = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM invites"))
    assert a["code"] not in stored and b["code"] not in stored
    conn.execute("UPDATE invites SET expires_at=? WHERE id=?", (int(time.time()) - 5, a["id"]))
    assert reg(client, "e1@example.com", invite=a["code"]).status_code == 403
    onboarding.revoke_invite(conn, admin, b["id"])
    assert reg(client, "e2@example.com", invite=b["code"]).status_code == 403
    states = {i["id"]: i["state"] for i in onboarding.list_invites(conn, admin)}
    assert states == {a["id"]: "expired", b["id"]: "revoked"}
    assert all("code" not in i for i in onboarding.list_invites(conn, admin))


def test_invite_admin_only(conn):
    u = mkuser(conn)
    with pytest.raises(auth.AuthError):
        onboarding.create_invite(conn, u)


def test_admin_invite_endpoints(client):
    h = as_admin(client)
    r = client.post("/api/admin/invites/create", json={"email": "who@example.com", "note": "beta"}, headers=h)
    assert r.status_code == 200 and r.json()["code"].startswith("inv_")
    iid = r.json()["id"]
    lst = client.get("/api/admin/invites").json()["invites"]
    assert lst[0]["id"] == iid and lst[0]["state"] == "open" and "code" not in lst[0]
    assert client.post("/api/admin/invites/revoke", json={"id": iid}, headers=h).status_code == 200
    assert client.get("/api/admin/invites").json()["invites"][0]["state"] == "revoked"
    assert client.post("/api/admin/invites/create", json={"ttl_days": "x"}, headers=h).status_code == 400
    # a normal user gets 403
    c2 = TestClient(client.app)
    h2 = signup(c2, "user@example.com")
    assert c2.get("/api/admin/invites").status_code == 403
    assert c2.post("/api/admin/invites/create", json={}, headers=h2).status_code == 403


def test_invite_email_is_sent_when_bound(conn, outbox):
    adm = mkuser(conn, "adm@example.com")
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (adm.id,))
    r = onboarding.create_invite(conn, auth.get_user(conn, adm.id), "x@example.com")
    assert r["emailed"] and outbox[-1].to == "x@example.com" and r["code"] in outbox[-1].text


# ------------------------------------------------------------------ anti-enumeration
def test_register_response_identical_for_new_and_existing_address(client, outbox):
    a = reg(client, "fresh@example.com")
    b = reg(client, "fresh@example.com")
    c = reg(client, "FRESH@example.com", pw=PW + "different")
    assert a.status_code == b.status_code == c.status_code == 200
    assert a.json() == b.json() == c.json() and not a.headers.get("set-cookie") and not b.headers.get("set-cookie")
    assert [m.kind for m in outbox] == ["verify", "already_registered", "already_registered"]
    # the existing account's password is untouched
    assert client.post("/api/account/login", json={"email": "fresh@example.com", "password": PW}).status_code == 200


def test_forgot_and_resend_identical_for_unknown_and_known(client, outbox):
    signup(client, "known@example.com")
    client.cookies.clear()
    outbox.clear()
    a = client.post("/api/account/forgot-password", json={"email": "known@example.com"})
    b = client.post("/api/account/forgot-password", json={"email": "ghost@example.com"})
    c = client.post("/api/account/forgot-password", json={"email": "not an email"})
    assert a.status_code == b.status_code == c.status_code == 200 and a.json() == b.json() == c.json()
    assert [m.to for m in outbox] == ["known@example.com"]
    x = client.post("/api/account/resend-verification", json={"email": "known@example.com"})
    y = client.post("/api/account/resend-verification", json={"email": "ghost@example.com"})
    assert x.status_code == y.status_code == 200 and x.json() == y.json()


def test_forgot_throttle_does_not_depend_on_account_existence(client):
    codes_known, codes_ghost = [], []
    signup(client, "known@example.com")
    client.cookies.clear()
    for _ in range(5):
        codes_known.append(client.post("/api/account/forgot-password", json={"email": "known@example.com"}).status_code)
        codes_ghost.append(client.post("/api/account/forgot-password", json={"email": "ghost@example.com"}).status_code)
    assert codes_known == codes_ghost == [200, 200, 200, 429, 429]


def test_login_requires_correct_password_before_revealing_unverified(client, monkeypatch, outbox):
    monkeypatch.setenv("ATLAS_REQUIRE_EMAIL_VERIFICATION", "1")
    reg(client, "u@example.com")
    bad = client.post("/api/account/login", json={"email": "u@example.com", "password": "wrong-wrong-wrong-1"})
    ghost = client.post("/api/account/login", json={"email": "ghost@example.com", "password": "wrong-wrong-wrong-1"})
    assert bad.status_code == ghost.status_code == 401 and bad.json() == ghost.json()
    r = client.post("/api/account/login", json={"email": "u@example.com", "password": PW})
    assert r.status_code == 403 and r.json()["error"] == "email_not_verified" and "set-cookie" not in r.headers


# ------------------------------------------------------------------ email verification
def test_verify_email_flow(client, monkeypatch, outbox):
    monkeypatch.setenv("ATLAS_REQUIRE_EMAIL_VERIFICATION", "1")
    reg(client, "v@example.com")
    tok = token_from(last(outbox, "verify"), "verify")
    assert client.get("/api/account/verify-email", params={"token": tok}).status_code == 405  # a link prefetcher cannot consume it
    assert client.post("/api/account/login", json={"email": "v@example.com", "password": PW}).status_code == 403
    r = client.post("/api/account/verify-email", json={"token": tok})
    assert r.status_code == 200 and r.json()["email"] == "v@example.com"
    assert client.post("/api/account/verify-email", json={"token": tok}).status_code == 400  # single use
    assert client.post("/api/account/login", json={"email": "v@example.com", "password": PW}).status_code == 200
    assert client.get("/api/account/me").json()["user"]["email_verified"] is True


def test_verify_token_bad_expired_and_hashed(client, conn, outbox):
    reg(client, "t@example.com")
    tok = token_from(last(outbox, "verify"), "verify")
    assert tok not in " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM email_tokens"))
    assert client.post("/api/account/verify-email", json={"token": "nope"}).status_code == 400
    assert client.post("/api/account/verify-email", json={}).status_code == 400
    conn.execute("UPDATE email_tokens SET expires_at=?", (int(time.time()) - 1,))
    r = client.post("/api/account/verify-email", json={"token": tok})
    assert r.status_code == 400 and r.json()["error"] == "invalid_token"


def test_resend_invalidates_previous_link(client, outbox):
    reg(client, "r@example.com")
    first = token_from(last(outbox, "verify"), "verify")
    client.post("/api/account/resend-verification", json={"email": "r@example.com"})
    second = token_from(last(outbox, "verify"), "verify")
    assert first != second
    assert client.post("/api/account/verify-email", json={"token": first}).status_code == 400
    assert client.post("/api/account/verify-email", json={"token": second}).status_code == 200


def test_unverified_login_allowed_on_plain_local_install(client, outbox):
    reg(client, "l@example.com")
    assert client.post("/api/account/login", json={"email": "l@example.com", "password": PW}).status_code == 200
    me = client.get("/api/account/me").json()
    assert me["user"]["email_verified"] is False


# ------------------------------------------------------------------ password reset
def test_password_reset_flow(client, outbox):
    h = signup(client, "p@example.com")
    other = TestClient(client.app)
    other.post("/api/account/login", json={"email": "p@example.com", "password": PW})
    assert other.get("/api/account/me").json()["authenticated"]
    client.post("/api/account/forgot-password", json={"email": "p@example.com"})
    tok = token_from(last(outbox, "reset"), "reset")
    assert client.post("/api/account/reset-password", json={"token": tok, "new": "short"}).status_code == 400  # weak: token not burned
    r = client.post("/api/account/reset-password", json={"token": tok, "new": "a brand new long passphrase 7"})
    assert r.status_code == 200
    assert client.post("/api/account/reset-password", json={"token": tok, "new": "another long passphrase 99"}).status_code == 400  # single use
    assert other.get("/api/account/me").json()["authenticated"] is False  # every session revoked
    c3 = TestClient(client.app)
    assert c3.post("/api/account/login", json={"email": "p@example.com", "password": PW}).status_code == 401
    assert c3.post("/api/account/login", json={"email": "p@example.com", "password": "a brand new long passphrase 7"}).status_code == 200
    assert h  # signup helper used


def test_reset_token_expiry_and_garbage(client, conn, outbox):
    signup(client, "x@example.com")
    client.post("/api/account/forgot-password", json={"email": "x@example.com"})
    tok = token_from(last(outbox, "reset"), "reset")
    conn.execute("UPDATE email_tokens SET expires_at=?", (int(time.time()) - 1,))
    assert client.post("/api/account/reset-password", json={"token": tok, "new": "a brand new long passphrase 7"}).status_code == 400
    assert client.post("/api/account/reset-password", json={"token": "x" * 500, "new": "a brand new long passphrase 7"}).status_code == 400


def test_reset_and_verify_tokens_are_not_interchangeable(client, outbox):
    reg(client, "i@example.com")
    vt = token_from(last(outbox, "verify"), "verify")
    assert client.post("/api/account/reset-password", json={"token": vt, "new": "a brand new long passphrase 7"}).status_code == 400
    client.post("/api/account/forgot-password", json={"email": "i@example.com"})
    rt = token_from(last(outbox, "reset"), "reset")
    assert client.post("/api/account/verify-email", json={"token": rt}).status_code == 400


def test_reset_blocked_for_disabled_account(client, conn, outbox):
    signup(client, "d@example.com")
    client.cookies.clear()
    outbox.clear()
    conn.execute("UPDATE users SET status='disabled' WHERE email='d@example.com'")
    assert client.post("/api/account/forgot-password", json={"email": "d@example.com"}).status_code == 200
    assert not outbox


# ------------------------------------------------------------------ mailer
def test_default_backend_is_console_and_sends_nothing(acct_env, caplog):
    mailer.set_mailer(None)
    assert mailer.backend_name() == "console"
    with caplog.at_level("INFO", logger="atlas.mail"):
        assert mailer.send_safe(mailer.verify_email("a@example.com", "TOKEN123", 48)) is True
    assert "TOKEN123" in caplog.text  # local dev: the link is readable in the log
    caplog.clear()
    with caplog.at_level("INFO", logger="atlas.mail"):
        mailer.send_safe(mailer.verify_email("a@example.com", "TOKEN123", 48), {"ATLAS_ENV": "production"})
    assert "TOKEN123" not in caplog.text  # a public deployment never writes live tokens to logs


def test_backend_selection_and_smtp_needs_host(acct_env, tmp_path):
    assert mailer.backend_name({"ATLAS_MAIL_BACKEND": "smtp"}) == "console"  # no host -> safe fallback
    assert mailer.backend_name({"ATLAS_MAIL_BACKEND": "smtp", "ATLAS_SMTP_HOST": "smtp.example.com"}) == "smtp"
    assert mailer.backend_name({"ATLAS_MAIL_BACKEND": "file", "ATLAS_MAIL_OUTBOX": str(tmp_path)}) == "file"
    m = mailer.get_mailer({"ATLAS_MAIL_BACKEND": "file", "ATLAS_MAIL_OUTBOX": str(tmp_path)})
    m.send(mailer.invite("a@example.com", "inv_x", "Me", "registration"))
    assert len(list(tmp_path.iterdir())) == 1


def test_send_safe_swallows_backend_failure(acct_env):
    class Boom:
        name = "boom"

        def send(self, msg):
            raise RuntimeError("smtp down")

    mailer.set_mailer(Boom())
    try:
        assert mailer.send_safe(mailer.verify_email("a@example.com", "t", 1)) is False
    finally:
        mailer.set_mailer(None)


def test_registration_survives_mail_outage(client):
    class Boom:
        name = "boom"

        def send(self, msg):
            raise RuntimeError("smtp down")

    mailer.set_mailer(Boom())
    try:
        assert reg(client, "o@example.com").status_code == 200
    finally:
        mailer.set_mailer(None)


# ------------------------------------------------------------------ security headers (FastAPI)
def test_api_security_headers(client):
    r = client.get("/api/account/config")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "default-src 'none'" in h["content-security-policy"]
    assert "strict-transport-security" not in h  # plain http: HSTS would be meaningless


def test_security_headers_on_errors_and_unauthenticated_responses(pub):
    r = pub.get("/api/account/sessions")
    assert r.status_code == 401 and r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_hsts_only_when_https(acct_env, monkeypatch):
    from atlas.api.app import app
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.example.com")
    assert "max-age=31536000" in TestClient(app).get("/api/health").headers["strict-transport-security"]
    monkeypatch.delenv("ATLAS_PUBLIC_URL")
    assert "strict-transport-security" not in TestClient(app, client=PUBLIC_IP).get("/api/health", headers={"x-forwarded-proto": "https"}).headers  # untrusted proxy claim
    monkeypatch.setenv("ATLAS_TRUSTED_PROXIES", "203.0.113.9")
    assert "strict-transport-security" in TestClient(app, client=PUBLIC_IP).get("/api/health", headers={"x-forwarded-proto": "https"}).headers
    assert "strict-transport-security" in TestClient(app, base_url="https://testserver").get("/api/health").headers


def test_docs_pages_keep_frame_ancestors_none(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "frame-ancestors 'none'" in r.headers["content-security-policy"] and "default-src 'none'" not in r.headers["content-security-policy"]


# ------------------------------------------------------------------ Team seats
def team_owner(conn, seats=3, email="owner@example.com"):
    u = mkuser(conn, email)
    ev = _event(u.id, plan="team_month_usd")
    ev["data"]["object"]["metadata"]["seats"] = str(seats)
    stripe_client.handle_event(conn, ev)
    return auth.get_user(conn, u.id)


def test_team_seat_limit_enforced_including_pending(conn, outbox):
    owner = team_owner(conn, seats=5)
    assert billing.team_seat_limit(conn, owner.id) == 5
    for i in range(4):
        teams.invite_member(conn, owner, f"m{i}@example.com")
    with pytest.raises(EntitlementDenied) as ex:
        teams.invite_member(conn, owner, "m4@example.com")
    assert ex.value.public()["key"] == "seats" and ex.value.public()["limit"] == 5
    assert teams.state(conn, owner)["seats"] == {"limit": 5, "used": 1, "pending": 4}


def test_team_member_gets_owner_entitlements_then_loses_them(conn, outbox):
    owner = team_owner(conn, seats=5)
    inv = teams.invite_member(conn, owner, "mem@example.com")
    mem = mkuser(conn, "mem@example.com")
    assert billing.plan_for_user(conn, mem.id)["tier"] == "free"
    teams.accept_invite(conn, auth.get_user(conn, mem.id), inv["code"])
    assert billing.plan_for_user(conn, mem.id)["tier"] == "team"
    assert teams.state(conn, auth.get_user(conn, mem.id))["role"] == "member"
    teams.remove_member(conn, owner, mem.id)
    assert billing.plan_for_user(conn, mem.id)["tier"] == "free"


def test_team_invite_cannot_be_accepted_by_another_account_or_twice(conn, outbox):
    owner = team_owner(conn, seats=5)
    inv = teams.invite_member(conn, owner, "mem@example.com")
    other = mkuser(conn, "other@example.com")
    with pytest.raises(auth.AuthError):
        teams.accept_invite(conn, auth.get_user(conn, other.id), inv["code"])
    mem = auth.get_user(conn, mkuser(conn, "mem@example.com").id)
    teams.accept_invite(conn, mem, inv["code"])
    with pytest.raises(auth.AuthError):
        teams.accept_invite(conn, mem, inv["code"])


def test_team_requires_team_plan_and_members_cannot_manage(conn, outbox):
    free = mkuser(conn, "free@example.com")
    with pytest.raises(EntitlementDenied):
        teams.invite_member(conn, auth.get_user(conn, free.id), "x@example.com")
    owner = team_owner(conn, seats=5)
    inv = teams.invite_member(conn, owner, "mem@example.com")
    mem = auth.get_user(conn, mkuser(conn, "mem@example.com").id)
    teams.accept_invite(conn, mem, inv["code"])
    with pytest.raises(auth.AuthError):
        teams.invite_member(conn, mem, "y@example.com")


def test_seat_reduction_demotes_newest_members_first(conn, outbox):
    owner = team_owner(conn, seats=5)
    ids = []
    for i, t in enumerate((1000, 2000, 3000)):
        inv = teams.invite_member(conn, owner, f"m{i}@example.com")
        u = auth.get_user(conn, mkuser(conn, f"m{i}@example.com").id)
        teams.accept_invite(conn, u, inv["code"], now=t + time.time())
        ids.append(u.id)
    conn.execute("UPDATE subscriptions SET seats=3 WHERE user_id=?", (owner.id,))
    plan = billing.team_seat_limit
    assert billing.team_seat_limit(conn, owner.id) == 5  # plan includes 5 seats, so still covered
    conn.execute("UPDATE plans SET seats_included=3")
    assert plan(conn, owner.id) == 3
    tiers = [billing.plan_for_user(conn, i)["tier"] for i in ids]
    assert tiers == ["team", "team", "free"]


def test_team_api_flow(client, outbox):
    owner_h = signup(client, "tm-owner@example.com")
    with db.connect() as c:
        uid = c.execute("SELECT id FROM users").fetchone()[0]
        ev = _event(uid, plan="team_month_usd")
        ev["data"]["object"]["metadata"]["seats"] = "5"
        stripe_client.handle_event(c, ev)
    assert client.get("/api/team").json()["seats"]["limit"] == 5
    r = client.post("/api/team/invite", json={"email": "tm-member@example.com"}, headers=owner_h)
    assert r.status_code == 200
    code = r.json()["code"]
    mc = TestClient(client.app)
    mh = signup(mc, "tm-member@example.com")
    assert mc.post("/api/team/accept", json={"code": code}, headers=mh).json()["role"] == "member"
    assert client.get("/api/team").json()["members"][0]["email"] == "tm-member@example.com"
    assert mc.post("/api/team/invite", json={"email": "z@example.com"}, headers=mh).status_code == 403
    for e in ("a", "b", "c"):
        assert client.post("/api/team/invite", json={"email": f"{e}@example.com"}, headers=owner_h).status_code == 200
    r = client.post("/api/team/invite", json={"email": "d@example.com"}, headers=owner_h)
    assert r.status_code == 402 and r.json()["key"] == "seats"


# ------------------------------------------------------------------ Postgres schema path
def test_pg_ledger_trigger_sql_is_generated_from_the_column_list():
    sql = dialect.postgres_ledger_triggers()
    assert "plpgsql" in sql.lower() and "TRUNCATE" in sql and dialect.LEDGER_APPEND_ONLY_MSG in sql
    for col in dialect.LEDGER_IMMUTABLE_COLUMNS:
        assert f"NEW.{col}" in sql and f"OLD.{col}" in sql
    assert "OLD.flooos_batch IS NOT NULL" in sql and "NEW.flooos_batch" not in sql  # the batch tag is the one column that may change, once


def test_every_ledger_column_is_covered_by_the_immutability_guard(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(payouts_ledger)")]
    assert sorted(set(cols) - {"flooos_batch"}) == sorted(dialect.LEDGER_IMMUTABLE_COLUMNS)


def test_postgres_migrations_swap_only_the_sqlite_triggers():
    sq, pg = dict((v, s) for v, _, s in dialect.migrations_for("sqlite")), dict((v, s) for v, _, s in dialect.migrations_for("postgresql"))
    assert sq.keys() == pg.keys() and len(sq) >= 6
    assert "BEGIN SELECT RAISE" not in " ".join(pg.values()) and "RAISE(ABORT" not in " ".join(pg.values())
    assert "RAISE(ABORT" in sq[5]
    assert all(sq[v] == pg[v] for v in sq if v != 5)
    assert "AUTOINCREMENT" not in "".join(pg.values()).upper()


def _pg_server(tmp_path):
    psycopg = pytest.importorskip("psycopg")
    try:
        pgs = pytest.importorskip("pixeltable_pgserver")
        srv = pgs.get_server(str(tmp_path / "pg"), cleanup_mode="stop")
        return psycopg, srv
    except Exception as e:  # noqa: BLE001 - no usable server on this machine
        pytest.skip(f"no postgres available: {e}")


def test_postgres_migration_applies_and_ledger_is_immutable(tmp_path):
    psycopg, srv = _pg_server(tmp_path)
    try:
        with psycopg.connect(srv.get_uri()) as c:
            assert dialect.apply_postgres(c) == [v for v, _, _ in dialect.migrations_for("postgresql")]
            assert dialect.apply_postgres(c) == []  # idempotent
            c.execute("INSERT INTO payouts_ledger (id,seq,ts,kind,direction,amount_cents,currency,counterparty,prev_hash,hash) VALUES ('a',1,1,'stripe_fee','out',5,'usd','x','0','h')")
            c.commit()
            for q in ("UPDATE payouts_ledger SET memo='z'", "UPDATE payouts_ledger SET amount_cents=1", "DELETE FROM payouts_ledger", "TRUNCATE payouts_ledger"):
                with pytest.raises(psycopg.Error, match="append-only"):
                    c.execute(q)
                c.rollback()
            c.execute("UPDATE payouts_ledger SET flooos_batch='b1'")  # the one allowed edit, once
            c.commit()
            with pytest.raises(psycopg.Error):
                c.execute("UPDATE payouts_ledger SET flooos_batch='b2'")
            c.rollback()
    finally:
        srv.cleanup()


def test_cli_pg_schema_prints_without_a_database(capsys):
    from atlas.accounts import cli
    assert cli.main(["print-pg-schema"]) == 0
    out = capsys.readouterr().out
    assert "CREATE TABLE" in out and "plpgsql" in out.lower() and "email_tokens" in out


def test_migration_6_verifies_existing_users(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "m.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    from atlas.accounts import migrations
    old = [m for m in migrations.MIGRATIONS if m[0] <= 5]
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at BIGINT NOT NULL)")
    for v, n, sql in old:
        c.executescript("BEGIN;\n" + sql + f"\nINSERT INTO schema_migrations VALUES ({v},'{n}',1);\nCOMMIT;")
    c.execute("INSERT INTO users (id,email,created_at,updated_at) VALUES ('u1','a@b.co',5,5)")
    assert db.migrate(c) == [6]
    r = c.execute("SELECT email_verified, email_verified_at FROM users").fetchone()
    assert (r[0], r[1]) == (1, 5)  # accounts that predate verification are grandfathered


def test_me_and_config_are_reachable_signed_out_when_auth_is_required(pub, monkeypatch):
    """The sign-in screen needs /me to learn that sign-in is required; it must answer 200 {authenticated:false}, not 401."""
    r = pub.get("/api/account/me")
    assert r.status_code == 200 and r.json()["authenticated"] is False and r.json()["require_auth"] is True
    assert pub.get("/api/account/config").status_code == 200
    assert pub.get("/api/connectors").status_code == 401
