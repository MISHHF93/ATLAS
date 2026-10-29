"""Users, sessions, CSRF tokens and login throttling. Every function takes an open connection; none reads a request."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from . import audit, netinfo
from .db import tx
from .passwords import PasswordPolicyError, check_policy, hash_password, needs_rehash, verify_password

ROLES = ("owner", "admin", "user")
SESSION_ABS_SECONDS = int(os.environ.get("ATLAS_SESSION_ABS_SECONDS", 7 * 86400))
SESSION_IDLE_SECONDS = int(os.environ.get("ATLAS_SESSION_IDLE_SECONDS", 12 * 3600))
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_PER_EMAIL = 5
LOGIN_MAX_PER_IP = 30
REGISTER_WINDOW = 3600
REGISTER_MAX_PER_IP = 10
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


class AuthError(Exception):
    def __init__(self, code: str, status: int = 400, retry_after: int | None = None, message: str | None = None):
        super().__init__(message or code)
        self.code, self.status, self.retry_after = code, status, retry_after


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: str
    status: str
    display_name: str
    timezone: str
    created_at: int
    last_login_at: int | None
    referral_code: str | None = None
    email_verified: bool = False

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "role": self.role, "display_name": self.display_name, "timezone": self.timezone,
                "created_at": self.created_at, "last_login_at": self.last_login_at, "referral_code": self.referral_code,
                "email_verified": self.email_verified}


def _user(r: sqlite3.Row) -> User:
    return User(r["id"], r["email"], r["role"], r["status"], r["display_name"], r["timezone"], r["created_at"], r["last_login_at"], r["referral_code"], bool(r["email_verified"]))


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if len(e) > 254 or not _EMAIL_RE.match(e):
        raise AuthError("invalid_email", 400)
    return e


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------- throttling ----------------
def _bucket_fail_count(conn, bucket: str, window: int, now: float) -> tuple[int, int | None]:
    rows = [r[0] for r in conn.execute("SELECT ts FROM login_attempts WHERE bucket=? AND success=0 AND ts>? ORDER BY ts", (bucket, int(now) - window))]
    return len(rows), (rows[0] + window - int(now) if rows else None)


def _record(conn, bucket: str, success: bool, now: float) -> None:
    conn.execute("INSERT INTO login_attempts (id,bucket,ts,success) VALUES (?,?,?,?)", (uuid.uuid4().hex, bucket, int(now), 1 if success else 0))
    conn.execute("DELETE FROM login_attempts WHERE ts < ?", (int(now) - 86400,))


def _throttle(conn, buckets: list[tuple[str, int, int]], now: float) -> None:
    for bucket, limit, window in buckets:
        n, retry = _bucket_fail_count(conn, bucket, window, now)
        if n >= limit:
            raise AuthError("rate_limited", 429, retry_after=max(1, retry or window), message="Too many attempts. Try again later.")


# ---------------- users ----------------
def user_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_user(conn, user_id: str) -> User | None:
    r = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _user(r) if r else None


REGISTRATION_MODES = ("open", "invite", "closed")


def registration_mode(env: dict[str, str] | None = None) -> str:
    """``open`` (anyone), ``invite`` (a valid invite code, the DEFAULT) or ``closed``. An unknown value fails to ``invite``, never ``open``."""
    v = (os.environ if env is None else env).get("ATLAS_REGISTRATION", "invite").strip().lower() or "invite"
    return v if v in REGISTRATION_MODES else "invite"


def new_referral_code() -> str:
    return secrets.token_urlsafe(6).replace("_", "x").replace("-", "y")[:8].upper()


def register(conn, email: str, password: str, display_name: str = "", ip: str = "", ref: str | None = None,
             now: float | None = None, env: dict[str, str] | None = None, verified: bool = False, in_tx=None) -> User:
    """Create an account. This is the TRUSTED creator (CLI, tests, and ``onboarding.register_public`` after its policy checks): it does not
    look at ``ATLAS_REGISTRATION``. ``in_tx(conn, user_id)`` runs inside the same transaction (invite redemption, team join); if it
    raises, the account is not created."""
    now = time.time() if now is None else now
    env = os.environ if env is None else env
    e = normalize_email(email)
    _throttle(conn, [(f"register:ip:{ip}", REGISTER_MAX_PER_IP, REGISTER_WINDOW)], now)
    try:
        check_policy(password, e)
    except PasswordPolicyError as ex:
        raise AuthError("weak_password", 400, message=str(ex)) from ex
    # The owner role is only ever granted to ATLAS_OWNER_EMAIL (or by the CLI). First-come-first-owner would hand a public
    # deployment to whoever registers first.
    owner_email = (env.get("ATLAS_OWNER_EMAIL") or "").strip().lower()
    role = "owner" if owner_email and e == owner_email else "user"
    if role == "owner" and conn.execute("SELECT 1 FROM users WHERE role='owner'").fetchone():
        role = "user"
    uid = uuid.uuid4().hex
    ph = hash_password(password)  # slow; outside the write lock
    code = ref.strip().upper()[:16] if ref else None
    try:
        with tx(conn):
            conn.execute("INSERT INTO users (id,email,password_hash,role,display_name,referral_code,referred_by_code,created_at,updated_at,password_changed_at,"
                         "email_verified,email_verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (uid, e, ph, role, (display_name or "").strip()[:80], new_referral_code(), code, int(now), int(now), int(now),
                          1 if verified else 0, int(now) if verified else None))
            if code:
                ref_row = conn.execute("SELECT id FROM users WHERE referral_code=?", (code,)).fetchone()
                if ref_row and ref_row["id"] != uid:
                    conn.execute("INSERT INTO partner_referrals (id,referrer_user_id,referred_user_id,code,status,created_at) VALUES (?,?,?,?,?,?)",
                                 (uuid.uuid4().hex, ref_row["id"], uid, code, "pending", int(now)))
            audit.log(conn, uid, "user.register", "user", uid, detail={"role": role, "referred": bool(code), "verified": bool(verified)}, now=now)
            _record(conn, f"register:ip:{ip}", False, now)  # counts every attempt
            if in_tx is not None:
                in_tx(conn, uid)
    except sqlite3.IntegrityError as ex:
        raise AuthError("email_unavailable", 409, message="That email can't be registered.") from ex
    return get_user(conn, uid)  # type: ignore[return-value]


def authenticate(conn, email: str, password: str, ip: str = "", now: float | None = None) -> User:
    now = time.time() if now is None else now
    try:
        e = normalize_email(email)
    except AuthError:
        e = ""
    eb, ib = f"login:email:{_h(e)[:24]}", f"login:ip:{ip}"
    _throttle(conn, [(eb, LOGIN_MAX_PER_EMAIL, LOGIN_WINDOW), (ib, LOGIN_MAX_PER_IP, LOGIN_WINDOW)], now)
    row = conn.execute("SELECT * FROM users WHERE email=?", (e,)).fetchone() if e else None
    ok = verify_password(row["password_hash"] if row else None, password if isinstance(password, str) else "")
    if not (ok and row and row["status"] == "active"):
        with tx(conn):
            _record(conn, eb, False, now)
            _record(conn, ib, False, now)
            audit.log(conn, row["id"] if row else None, "auth.login", "user", row["id"] if row else "", outcome="denied",
                      detail={"reason": "bad_credentials_or_disabled"}, now=now)
        raise AuthError("invalid_credentials", 401, message="Email or password is incorrect.")
    if not row["email_verified"] and netinfo.require_email_verification():
        # only reachable with the right password, so it reveals nothing to someone who does not already control the account
        raise AuthError("email_not_verified", 403, message="Confirm your email address first. Check your inbox, or request a new link.")
    with tx(conn):
        conn.execute("DELETE FROM login_attempts WHERE bucket=?", (eb,))
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (int(now), row["id"]))
        if needs_rehash(row["password_hash"]):
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row["id"]))
        audit.log(conn, row["id"], "auth.login", "user", row["id"], now=now)
    return get_user(conn, row["id"])  # type: ignore[return-value]


# ---------------- sessions ----------------
def create_session(conn, user_id: str, ip: str = "", user_agent: str = "", now: float | None = None) -> tuple[str, str]:
    """Returns (cookie token, csrf token). A fresh id on every login prevents session fixation."""
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with tx(conn):
        conn.execute("INSERT INTO sessions (id,user_id,csrf_token,created_at,last_seen_at,expires_at,idle_expires_at,ip_hash,user_agent) VALUES (?,?,?,?,?,?,?,?,?)",
                     (_h(token), user_id, csrf, int(now), int(now), int(now) + SESSION_ABS_SECONDS, int(now) + SESSION_IDLE_SECONDS,
                      _h(ip)[:16], (user_agent or "")[:160]))
    return token, csrf


@dataclass(frozen=True)
class Session:
    id: str
    user: User
    csrf_token: str
    expires_at: int


def resolve_session(conn, token: str | None, now: float | None = None) -> Session | None:
    if not token or len(token) > 200:
        return None
    now = time.time() if now is None else now
    r = conn.execute("SELECT * FROM sessions WHERE id=?", (_h(token),)).fetchone()
    if not r or r["revoked_at"] or r["expires_at"] <= now or r["idle_expires_at"] <= now:
        return None
    u = get_user(conn, r["user_id"])
    if not u or u.status != "active":
        return None
    if now - r["last_seen_at"] > 60:  # slide the idle window at most once a minute
        conn.execute("UPDATE sessions SET last_seen_at=?, idle_expires_at=? WHERE id=?",
                     (int(now), min(int(now) + SESSION_IDLE_SECONDS, r["expires_at"]), r["id"]))
    return Session(r["id"], u, r["csrf_token"], r["expires_at"])


def csrf_ok(session: Session, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(session.csrf_token, presented or "")


def revoke_session(conn, session_id: str, user_id: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    with tx(conn):
        cur = conn.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL", (int(now), session_id, user_id))
        if cur.rowcount:
            audit.log(conn, user_id, "auth.logout", "session", session_id[:8], now=now)
    return bool(cur.rowcount)


def list_sessions(conn, user_id: str, current_id: str | None = None, now: float | None = None) -> list[dict[str, Any]]:
    now = time.time() if now is None else now
    rows = conn.execute("SELECT id,created_at,last_seen_at,expires_at,user_agent FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC", (user_id, int(now)))
    return [{"id": r["id"][:12], "ref": r["id"], "created_at": r["created_at"], "last_seen_at": r["last_seen_at"], "user_agent": r["user_agent"],
             "current": r["id"] == current_id} for r in rows]


def revoke_all(conn, user_id: str, except_id: str | None = None, now: float | None = None) -> int:
    now = time.time() if now is None else now
    cur = conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND id<>?", (int(now), user_id, except_id or ""))
    return cur.rowcount


# ---------------- account changes ----------------
def change_password(conn, user_id: str, current: str, new: str, keep_session_id: str | None = None, now: float | None = None) -> None:
    now = time.time() if now is None else now
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise AuthError("not_found", 404)
    _throttle(conn, [(f"pwchange:{user_id}", 5, LOGIN_WINDOW)], now)
    if not verify_password(row["password_hash"], current if isinstance(current, str) else ""):
        with tx(conn):
            _record(conn, f"pwchange:{user_id}", False, now)
            audit.log(conn, user_id, "auth.password_change", "user", user_id, outcome="denied", now=now)
        raise AuthError("invalid_credentials", 401, message="Current password is incorrect.")
    try:
        check_policy(new, row["email"])
    except PasswordPolicyError as ex:
        raise AuthError("weak_password", 400, message=str(ex)) from ex
    ph = hash_password(new)
    with tx(conn):
        conn.execute("UPDATE users SET password_hash=?, password_changed_at=?, updated_at=? WHERE id=?", (ph, int(now), int(now), user_id))
        n = revoke_all(conn, user_id, except_id=keep_session_id, now=now)
        audit.log(conn, user_id, "auth.password_change", "user", user_id, detail={"other_sessions_revoked": n}, now=now)


def update_profile(conn, user_id: str, display_name: str | None = None, timezone: str | None = None, now: float | None = None) -> User:
    now = time.time() if now is None else now
    sets, args = [], []
    if display_name is not None:
        sets.append("display_name=?"); args.append(display_name.strip()[:80])
    if timezone is not None:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(timezone)
        except Exception as ex:  # noqa: BLE001
            raise AuthError("invalid_timezone", 400) from ex
        sets.append("timezone=?"); args.append(timezone)
    if sets:
        with tx(conn):
            conn.execute(f"UPDATE users SET {', '.join(sets)}, updated_at=? WHERE id=?", (*args, int(now), user_id))
            audit.log(conn, user_id, "user.profile_update", "user", user_id, detail={"fields": [s.split('=')[0] for s in sets]}, now=now)
    return get_user(conn, user_id)  # type: ignore[return-value]


def delete_account(conn, user_id: str, password: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not verify_password(row["password_hash"], password if isinstance(password, str) else ""):
        raise AuthError("invalid_credentials", 401, message="Password is incorrect.")
    if row["role"] == "owner":
        raise AuthError("owner_cannot_self_delete", 403, message="The owner account can only be removed from the CLI.")
    with tx(conn):
        # Financial records (tax_records, broker bounties, ledger-linked invoices) must be kept for statutory retention
        # (monetization_plan.md: 6 years), and they reference the user row. In that case the account is ANONYMISED: every personal
        # field, session, connector and secret is destroyed and the row stays only as an opaque, un-loginable id.
        retained = (conn.execute("SELECT 1 FROM tax_records WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
                    or conn.execute("SELECT 1 FROM broker_referrals WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
                    or conn.execute("SELECT 1 FROM payouts_ledger l JOIN invoices i ON i.id=l.invoice_id WHERE i.user_id=? LIMIT 1", (user_id,)).fetchone())
        if retained:
            for tbl, col in (("sessions", "user_id"), ("oauth_identities", "user_id"), ("connector_secrets", "user_id"), ("connectors", "user_id"),
                             ("subscriptions", "user_id"), ("usage_events", "user_id"), ("partner_referrals", "referrer_user_id"), ("partner_referrals", "referred_user_id"),
                             ("email_tokens", "user_id"), ("team_members", "user_id"), ("team_members", "owner_id"), ("invites", "team_owner_id")):
                conn.execute(f"DELETE FROM {tbl} WHERE {col}=?", (user_id,))
            conn.execute("UPDATE users SET email=?, password_hash=NULL, status='disabled', display_name='', referral_code=NULL, referred_by_code=NULL, updated_at=?, email_verified=0 WHERE id=?",
                         (f"deleted-{user_id}@deleted.invalid", int(now), user_id))
        else:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))  # cascades: sessions, connectors, secrets, subscriptions
        audit.log(conn, user_id, "user.delete", "user", user_id, detail={"anonymised_for_retention": bool(retained)}, now=now)


def set_role(conn, actor: User, target_id: str, role: str, now: float | None = None) -> User:
    now = time.time() if now is None else now
    if role not in ROLES:
        raise AuthError("invalid_role", 400)
    t = get_user(conn, target_id)
    if not t:
        raise AuthError("not_found", 404)
    if not actor.is_owner:  # only the owner changes roles; admins cannot create admins or touch the owner
        raise AuthError("forbidden", 403)
    if t.role == "owner" or role == "owner":
        raise AuthError("owner_role_is_cli_only", 403)
    with tx(conn):
        conn.execute("UPDATE users SET role=?, updated_at=? WHERE id=?", (role, int(now), target_id))
        audit.log(conn, actor.id, "admin.set_role", "user", target_id, detail={"role": role}, now=now)
    return get_user(conn, target_id)  # type: ignore[return-value]


def set_status(conn, actor: User, target_id: str, status: str, now: float | None = None) -> User:
    now = time.time() if now is None else now
    if status not in ("active", "disabled"):
        raise AuthError("invalid_status", 400)
    t = get_user(conn, target_id)
    if not t:
        raise AuthError("not_found", 404)
    if not actor.is_admin or t.role == "owner" or (t.role == "admin" and not actor.is_owner):
        raise AuthError("forbidden", 403)
    with tx(conn):
        conn.execute("UPDATE users SET status=?, updated_at=? WHERE id=?", (status, int(now), target_id))
        if status == "disabled":
            revoke_all(conn, target_id, now=now)
        audit.log(conn, actor.id, "admin.set_status", "user", target_id, detail={"status": status}, now=now)
    return get_user(conn, target_id)  # type: ignore[return-value]


def list_users(conn, actor: User) -> list[dict[str, Any]]:
    if not actor.is_admin:
        raise AuthError("forbidden", 403)
    return [{**_user(r).public(), "status": r["status"]} for r in conn.execute("SELECT * FROM users ORDER BY created_at")]
