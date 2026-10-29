"""Public-launch onboarding: invite-gated registration, email verification, password reset. Policy lives here; ``auth.register`` stays the
trusted low-level creator.

Anti-enumeration contract (what an unauthenticated caller can and cannot learn):

* ``register_public`` returns nothing and the API answers identically whether the email is new or already registered. A new address
  gets a verification email; an existing one gets an "already registered" notice. No session is created at sign-up, so the response
  cannot differ by a Set-Cookie either. Mail is sent after the decision and failures are swallowed.
* ``forgot_password`` and ``resend_verification`` answer identically for unknown, unverified and verified addresses, and their rate-limit
  buckets are charged on every call, so a 429 depends on the caller's behaviour and never on whether the address exists.
* Invite errors never depend on whether an account exists. ``email_not_verified`` is only returned after the correct password.
* Tokens and invite codes are 24+ random bytes, stored only as sha256, single-use and time-boxed. Verify/reset links are consumed by a
  POST (a link prefetcher or mail scanner issuing GET cannot burn them).
"""
from __future__ import annotations

import os
import secrets
import time
import uuid
from typing import Any, Mapping

from . import audit, mailer
from .auth import (REGISTER_MAX_PER_IP, REGISTER_WINDOW, AuthError, User, _h, _record, _throttle, normalize_email, register, registration_mode,
                   revoke_all)
from .db import tx
from .passwords import PasswordPolicyError, check_policy, hash_password

VERIFY_TTL = 48 * 3600
RESET_TTL = 60 * 60
INVITE_TTL_DEFAULT = 7 * 86400
INVITE_TTL_MAX = 30 * 86400
MAIL_WINDOW = 3600
MAIL_MAX_PER_EMAIL = 3
MAIL_MAX_PER_IP = 10
RESET_ATTEMPT_MAX_PER_IP = 20


def new_code() -> str:
    return "inv_" + secrets.token_urlsafe(24)


def code_hash(code: str) -> str:
    return _h((code or "").strip())


# ------------------------------------------------------------------ invites
def check_invite(conn, code: str | None, email: str | None, now: float | None = None, kind: str | None = None):
    """The invite row if ``code`` is usable by ``email`` (not revoked / expired / used up; email-bound invites need that exact email)."""
    if not code or len(code) > 200:
        return None
    now = int(time.time() if now is None else now)
    r = conn.execute("SELECT * FROM invites WHERE code_hash=?", (code_hash(code),)).fetchone()
    if not r or r["revoked_at"] or r["uses"] >= r["max_uses"] or r["expires_at"] <= now:
        return None
    if kind and r["kind"] != kind:
        return None
    if r["email"] and (email or "").strip().lower() != r["email"]:
        return None
    return r


def redeem_invite(conn, inv, user_id: str, now: float | None = None) -> None:
    """Consume one use (inside the caller's transaction). The conditional UPDATE makes two racing redemptions of a single-use code safe."""
    now = int(time.time() if now is None else now)
    n = conn.execute("UPDATE invites SET uses=uses+1, used_by=?, used_at=? WHERE id=? AND uses<max_uses AND revoked_at IS NULL AND expires_at>?",
                     (user_id, now, inv["id"], now)).rowcount
    if n != 1:
        raise AuthError("invite_invalid", 403, message="That invite is not valid for this email.")
    audit.log(conn, user_id, "invite.redeem", "invite", inv["id"], detail={"kind": inv["kind"]}, now=now)


def create_invite(conn, actor: User, email: str | None = None, ttl_days: float = 7, note: str = "", max_uses: int = 1,
                  now: float | None = None, env: Mapping[str, str] | None = None, send: bool = True) -> dict[str, Any]:
    """Admin / owner: mint a registration invite. The code is returned ONCE (only its hash is stored)."""
    if not actor.is_admin:
        raise AuthError("forbidden", 403)
    now = time.time() if now is None else now
    e = normalize_email(email) if email else None
    ttl = max(3600, min(int(float(ttl_days) * 86400), INVITE_TTL_MAX))
    uses = 1 if e else max(1, min(int(max_uses), 100))
    code, iid = new_code(), uuid.uuid4().hex
    with tx(conn):
        conn.execute("INSERT INTO invites (id,code_hash,kind,email,created_by,note,created_at,expires_at,max_uses) VALUES (?,?,?,?,?,?,?,?,?)",
                     (iid, code_hash(code), "registration", e, actor.id, (note or "")[:120], int(now), int(now) + ttl, uses))
        audit.log(conn, actor.id, "admin.invite_create", "invite", iid, detail={"bound": bool(e), "max_uses": uses}, now=now)
    mailed = bool(e and send and mailer.send_safe(mailer.invite(e, code, actor.display_name or "An ATLAS admin", "registration", env), env))
    return {"id": iid, "code": code, "email": e, "expires_at": int(now) + ttl, "max_uses": uses, "emailed": mailed}


def list_invites(conn, actor: User, now: float | None = None) -> list[dict[str, Any]]:
    if not actor.is_admin:
        raise AuthError("forbidden", 403)
    now = int(time.time() if now is None else now)
    out = []
    for r in conn.execute("SELECT * FROM invites WHERE kind='registration' ORDER BY created_at DESC LIMIT 100"):
        state = "revoked" if r["revoked_at"] else "used" if r["uses"] >= r["max_uses"] else "expired" if r["expires_at"] <= now else "open"
        out.append({"id": r["id"], "email": r["email"], "note": r["note"], "created_at": r["created_at"], "expires_at": r["expires_at"],
                    "uses": r["uses"], "max_uses": r["max_uses"], "state": state})
    return out


def revoke_invite(conn, actor: User, invite_id: str, now: float | None = None) -> None:
    if not actor.is_admin:
        raise AuthError("forbidden", 403)
    now = time.time() if now is None else now
    with tx(conn):
        if not conn.execute("UPDATE invites SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (int(now), invite_id)).rowcount:
            raise AuthError("not_found", 404)
        audit.log(conn, actor.id, "admin.invite_revoke", "invite", invite_id, now=now)


# ------------------------------------------------------------------ tokens
def _issue_token(conn, user_id: str, purpose: str, email: str, ttl: int, now: float) -> str:
    raw = secrets.token_urlsafe(32)
    conn.execute("UPDATE email_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (int(now), user_id, purpose))  # newest link only
    conn.execute("INSERT INTO email_tokens (id,user_id,purpose,token_hash,email,created_at,expires_at) VALUES (?,?,?,?,?,?,?)",
                 (uuid.uuid4().hex, user_id, purpose, _h(raw), email, int(now), int(now) + ttl))
    conn.execute("DELETE FROM email_tokens WHERE expires_at < ?", (int(now) - 7 * 86400,))
    return raw


def _consume(conn, raw: str, purpose: str, now: float):
    if not raw or len(raw) > 200:
        return None
    r = conn.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose=?", (_h(raw), purpose)).fetchone()
    if not r or r["used_at"] or r["expires_at"] <= now:
        return None
    if conn.execute("UPDATE email_tokens SET used_at=? WHERE id=? AND used_at IS NULL", (int(now), r["id"])).rowcount != 1:
        return None
    return r


def send_verification(conn, user_id: str, email: str, now: float, env=None) -> None:
    with tx(conn):
        raw = _issue_token(conn, user_id, "verify", email, VERIFY_TTL, now)
    mailer.send_safe(mailer.verify_email(email, raw, VERIFY_TTL // 3600, env), env)


# ------------------------------------------------------------------ registration
def register_public(conn, email: str, password: str, display_name: str = "", ip: str = "", ref: str | None = None,
                    invite_code: str | None = None, now: float | None = None, env: Mapping[str, str] | None = None) -> None:
    """Self-service sign-up. Returns None on every accepted request (new or existing address alike)."""
    now = time.time() if now is None else now
    environ = dict(env) if env is not None else None
    mode = registration_mode(environ)
    if mode == "closed":
        raise AuthError("registration_closed", 403, message="Registration is closed on this server.")
    e = normalize_email(email)
    _throttle(conn, [(f"register:ip:{ip}", REGISTER_MAX_PER_IP, REGISTER_WINDOW)], now)
    try:
        check_policy(password, e)
    except PasswordPolicyError as ex:
        raise AuthError("weak_password", 400, message=str(ex)) from ex
    owner_email = ((environ if environ is not None else os.environ).get("ATLAS_OWNER_EMAIL") or "").strip().lower()
    bootstrap = bool(owner_email and e == owner_email and not conn.execute("SELECT 1 FROM users WHERE role='owner'").fetchone())
    inv = check_invite(conn, invite_code, e, now)
    if mode == "invite" and not bootstrap and inv is None:
        with tx(conn):
            _record(conn, f"register:ip:{ip}", False, now)
        raise AuthError("invite_invalid" if invite_code else "invite_required", 403,
                        message="Registration is by invitation. Use the invite link or code you were given, with the email it was sent to.")
    existing = conn.execute("SELECT id FROM users WHERE email=?", (e,)).fetchone()
    if existing:
        hash_password(password)  # same CPU cost as the new-account path, so response time does not reveal the address
        with tx(conn):
            _record(conn, f"register:ip:{ip}", False, now)
            audit.log(conn, None, "user.register_duplicate", "user", existing["id"], outcome="denied", now=now)
        mailer.send_safe(mailer.already_registered(e, environ), environ)
        return

    def _hook(c, uid: str) -> None:
        if inv is not None:
            redeem_invite(c, inv, uid, now)
            if inv["kind"] == "team":
                from . import teams
                teams.join(c, inv["team_owner_id"], uid, now)

    try:
        u = register(conn, e, password, display_name, ip, ref, now, environ or None, verified=bool(inv is not None and inv["email"]), in_tx=_hook)
    except AuthError as ex:
        if ex.code != "email_unavailable":
            raise
        mailer.send_safe(mailer.already_registered(e, environ), environ)  # lost a race with a concurrent sign-up: same outward behaviour
        return
    if not u.email_verified:
        send_verification(conn, u.id, u.email, now, environ)


def verify_email(conn, token: str, now: float | None = None) -> User:
    now = time.time() if now is None else now
    with tx(conn):
        r = _consume(conn, token, "verify", now)
        if r is None:
            raise AuthError("invalid_token", 400, message="This link is invalid or has expired. Request a new one.")
        n = conn.execute("UPDATE users SET email_verified=1, email_verified_at=?, updated_at=? WHERE id=? AND email=?", (int(now), int(now), r["user_id"], r["email"])).rowcount
        if not n:
            raise AuthError("invalid_token", 400, message="This link is invalid or has expired. Request a new one.")
        audit.log(conn, r["user_id"], "user.verify_email", "user", r["user_id"], now=now)
    from .auth import get_user
    return get_user(conn, r["user_id"])  # type: ignore[return-value]


def _mail_throttle(conn, kind: str, e: str, ip: str, now: float) -> None:
    eb, ib = f"{kind}:email:{_h(e)[:24]}", f"{kind}:ip:{ip}"
    _throttle(conn, [(eb, MAIL_MAX_PER_EMAIL, MAIL_WINDOW), (ib, MAIL_MAX_PER_IP, MAIL_WINDOW)], now)
    with tx(conn):  # charged on EVERY call, whether or not the address exists
        _record(conn, eb, False, now)
        _record(conn, ib, False, now)


def resend_verification(conn, email: str, ip: str = "", now: float | None = None, env: Mapping[str, str] | None = None) -> None:
    now = time.time() if now is None else now
    try:
        e = normalize_email(email)
    except AuthError:
        return  # malformed: same silent answer as an unknown address
    _mail_throttle(conn, "resend", e, ip, now)
    row = conn.execute("SELECT id, email, status, email_verified FROM users WHERE email=?", (e,)).fetchone()
    if row and row["status"] == "active" and not row["email_verified"]:
        send_verification(conn, row["id"], row["email"], now, env)


def forgot_password(conn, email: str, ip: str = "", now: float | None = None, env: Mapping[str, str] | None = None) -> None:
    now = time.time() if now is None else now
    try:
        e = normalize_email(email)
    except AuthError:
        return
    _mail_throttle(conn, "forgot", e, ip, now)
    row = conn.execute("SELECT id, email, status FROM users WHERE email=?", (e,)).fetchone()
    if row and row["status"] == "active":
        with tx(conn):
            raw = _issue_token(conn, row["id"], "reset", row["email"], RESET_TTL, now)
            audit.log(conn, row["id"], "auth.reset_requested", "user", row["id"], now=now)
        mailer.send_safe(mailer.reset_password(row["email"], raw, RESET_TTL // 60, env), env)


def reset_password(conn, token: str, new_password: str, ip: str = "", now: float | None = None) -> User:
    now = time.time() if now is None else now
    _throttle(conn, [(f"reset:ip:{ip}", RESET_ATTEMPT_MAX_PER_IP, MAIL_WINDOW)], now)
    r = conn.execute("SELECT t.*, u.email AS user_email, u.status AS user_status FROM email_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.purpose='reset'",
                     (_h(token or ""),)).fetchone() if token and len(token) <= 200 else None
    if r is None or r["used_at"] or r["expires_at"] <= now or r["user_status"] != "active" or r["user_email"] != r["email"]:
        with tx(conn):
            _record(conn, f"reset:ip:{ip}", False, now)
        raise AuthError("invalid_token", 400, message="This link is invalid or has expired. Request a new one.")
    try:
        check_policy(new_password, r["user_email"])
    except PasswordPolicyError as ex:  # the token stays valid: a weak password does not burn the link
        raise AuthError("weak_password", 400, message=str(ex)) from ex
    ph = hash_password(new_password)
    with tx(conn):
        if conn.execute("UPDATE email_tokens SET used_at=? WHERE id=? AND used_at IS NULL", (int(now), r["id"])).rowcount != 1:
            raise AuthError("invalid_token", 400, message="This link is invalid or has expired. Request a new one.")
        conn.execute("UPDATE users SET password_hash=?, password_changed_at=?, updated_at=?, email_verified=1, email_verified_at=COALESCE(email_verified_at,?) WHERE id=?",
                     (ph, int(now), int(now), int(now), r["user_id"]))
        conn.execute("UPDATE email_tokens SET used_at=? WHERE user_id=? AND purpose='reset' AND used_at IS NULL", (int(now), r["user_id"]))
        n = revoke_all(conn, r["user_id"], now=now)
        audit.log(conn, r["user_id"], "auth.password_reset", "user", r["user_id"], detail={"sessions_revoked": n}, now=now)
    from .auth import get_user
    return get_user(conn, r["user_id"])  # type: ignore[return-value]
