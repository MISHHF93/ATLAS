"""Team workspace seats (Team tier). A team is one owner (the paying account) plus members who hold a seat.

* The seat limit is the owner's ``billing.team_seat_limit`` (seats bought, at least the plan's ``seats_included``; the owner uses one).
  Pending invites count against the limit so the owner cannot over-invite.
* Members get the owner's plan entitlements while their seat is covered (``billing.team_plan_for_member``); the benefit follows the
  owner's subscription, so a cancellation or seat reduction takes effect without any bookkeeping here.
* Staff accounts (owner / admin roles) run the platform and bypass plan gates; for team management they get the Team seat allowance.
* A user can hold a seat in one team only, and a member cannot run their own team.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from . import audit, billing, mailer, onboarding
from .auth import AuthError, User, normalize_email
from .db import tx
from .entitlements import BYPASS_ROLES, EntitlementDenied

STAFF_SEATS = billing.TEAM_SEATS


def _limit(conn, owner: User, now: float | None) -> tuple[int, str]:
    plan = billing.own_plan(conn, owner.id, now)
    lim = billing.team_seat_limit(conn, owner.id, now)
    if not lim and owner.role in BYPASS_ROLES:
        return STAFF_SEATS, plan["code"]
    return lim, plan["code"]


def pending_invites(conn, owner_id: str, now: float | None = None):
    now = int(time.time() if now is None else now)
    return conn.execute("SELECT * FROM invites WHERE kind='team' AND team_owner_id=? AND revoked_at IS NULL AND uses<max_uses AND expires_at>? ORDER BY created_at DESC",
                        (owner_id, now)).fetchall()


def seats_used(conn, owner_id: str, now: float | None = None) -> dict[str, int]:
    members = conn.execute("SELECT COUNT(*) FROM team_members WHERE owner_id=?", (owner_id,)).fetchone()[0]
    return {"owner": 1, "members": members, "pending": len(pending_invites(conn, owner_id, now))}


def _require_manager(conn, owner: User, now: float | None) -> int:
    if conn.execute("SELECT 1 FROM team_members WHERE user_id=?", (owner.id,)).fetchone():
        raise AuthError("member_cannot_manage", 403, message="Team members cannot manage a team. Ask the team owner.")
    lim, plan = _limit(conn, owner, now)
    if lim <= 1 and owner.role not in BYPASS_ROLES:
        raise EntitlementDenied("feature.team_workspace", "feature_not_in_plan", plan)
    return lim


def check_capacity(conn, owner_id: str, limit: int, plan: str, extra: int = 1, now: float | None = None) -> None:
    u = seats_used(conn, owner_id, now)
    if u["owner"] + u["members"] + u["pending"] + extra > limit:
        raise EntitlementDenied("seats", "quota_exceeded", plan, limit)


def state(conn, user: User, now: float | None = None) -> dict[str, Any]:
    m = conn.execute("SELECT t.owner_id, t.joined_at, o.email AS owner_email FROM team_members t JOIN users o ON o.id=t.owner_id WHERE t.user_id=?", (user.id,)).fetchone()
    if m:
        covered = billing.team_plan_for_member(conn, user.id, now) is not None
        return {"role": "member", "owner_email": m["owner_email"], "joined_at": m["joined_at"], "seat_active": covered, "can_manage": False}
    lim, plan = _limit(conn, user, now)
    u = seats_used(conn, user.id, now)
    members = [{"id": r["user_id"], "email": r["email"], "joined_at": r["joined_at"]} for r in conn.execute(
        "SELECT t.user_id, u.email, t.joined_at FROM team_members t JOIN users u ON u.id=t.user_id WHERE t.owner_id=? ORDER BY t.joined_at", (user.id,))]
    invs = [{"id": r["id"], "email": r["email"], "created_at": r["created_at"], "expires_at": r["expires_at"]} for r in pending_invites(conn, user.id, now)]
    can = lim > 1 or user.role in BYPASS_ROLES
    return {"role": "owner" if (members or invs or can) else "none", "can_manage": can, "plan": plan,
            "seats": {"limit": lim, "used": u["owner"] + u["members"], "pending": u["pending"]}, "members": members, "invites": invs}


def invite_member(conn, owner: User, email: str, now: float | None = None, env=None) -> dict[str, Any]:
    now = time.time() if now is None else now
    e = normalize_email(email)
    lim = _require_manager(conn, owner, now)
    _, plan = _limit(conn, owner, now)
    if conn.execute("SELECT 1 FROM users WHERE email=? AND id=?", (e, owner.id)).fetchone():
        raise AuthError("invalid_invite", 400, message="You already hold the owner seat.")
    code = onboarding.new_code()
    iid = uuid.uuid4().hex
    with tx(conn):
        check_capacity(conn, owner.id, lim, plan, 1, now)
        conn.execute("INSERT INTO invites (id,code_hash,kind,email,team_owner_id,created_by,created_at,expires_at,max_uses) VALUES (?,?,?,?,?,?,?,?,1)",
                     (iid, onboarding.code_hash(code), "team", e, owner.id, owner.id, int(now), int(now) + onboarding.INVITE_TTL_DEFAULT))
        audit.log(conn, owner.id, "team.invite", "invite", iid, detail={"seats_limit": lim}, now=now)
    mailer.send_safe(mailer.invite(e, code, owner.display_name or owner.email, "team", env), env)
    return {"id": iid, "email": e, "code": code, "expires_at": int(now) + onboarding.INVITE_TTL_DEFAULT}


def join(conn, owner_id: str, user_id: str, now: float | None = None) -> None:
    """Seat the user in the owner's team (inside the caller's transaction). Raises EntitlementDenied when no seat is free."""
    now = time.time() if now is None else now
    owner = conn.execute("SELECT * FROM users WHERE id=?", (owner_id,)).fetchone()
    if not owner or owner["status"] != "active" or owner_id == user_id:
        raise AuthError("invalid_invite", 400)
    if conn.execute("SELECT 1 FROM team_members WHERE user_id=?", (user_id,)).fetchone():
        raise AuthError("already_in_team", 409, message="This account already holds a team seat.")
    lim = billing.team_seat_limit(conn, owner_id, now)
    if not lim and owner["role"] in BYPASS_ROLES:
        lim = STAFF_SEATS
    used = conn.execute("SELECT COUNT(*) FROM team_members WHERE owner_id=?", (owner_id,)).fetchone()[0] + 1
    if used + 1 > lim:  # owner + seated members + this new member must fit (the redeemed invite is no longer pending)
        raise EntitlementDenied("seats", "quota_exceeded", billing.own_plan(conn, owner_id, now)["code"], lim)
    conn.execute("INSERT INTO team_members (user_id, owner_id, joined_at) VALUES (?,?,?)", (user_id, owner_id, int(now)))
    audit.log(conn, user_id, "team.join", "user", owner_id, now=now)


def accept_invite(conn, user: User, code: str, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    inv = onboarding.check_invite(conn, code, user.email, now, kind="team")
    if inv is None:
        raise AuthError("invite_invalid", 403, message="That invite is not valid for this account.")
    with tx(conn):
        onboarding.redeem_invite(conn, inv, user.id, now)
        join(conn, inv["team_owner_id"], user.id, now)
    return state(conn, user, now)


def remove_member(conn, owner: User, member_id: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with tx(conn):
        n = conn.execute("DELETE FROM team_members WHERE user_id=? AND owner_id=?", (member_id, owner.id)).rowcount
        if not n:
            raise AuthError("not_found", 404)
        audit.log(conn, owner.id, "team.remove", "user", member_id, now=now)


def leave(conn, user: User, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with tx(conn):
        if not conn.execute("DELETE FROM team_members WHERE user_id=?", (user.id,)).rowcount:
            raise AuthError("not_found", 404)
        audit.log(conn, user.id, "team.leave", "user", user.id, now=now)


def revoke_invite(conn, owner: User, invite_id: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with tx(conn):
        n = conn.execute("UPDATE invites SET revoked_at=? WHERE id=? AND kind='team' AND team_owner_id=? AND revoked_at IS NULL", (int(now), invite_id, owner.id)).rowcount
        if not n:
            raise AuthError("not_found", 404)
        audit.log(conn, owner.id, "team.invite_revoke", "invite", invite_id, now=now)
