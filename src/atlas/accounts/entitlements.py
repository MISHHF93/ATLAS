"""Entitlement checks: feature flags and quotas per plan, with usage metering. Fail closed: an unknown key is denied.
Owner / admin roles bypass quotas (they run the platform); every other user is gated by the plan resolved from ``subscriptions``."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .billing import plan_for_user
from .db import tx

BYPASS_ROLES = ("owner", "admin")
NEVER_BYPASS = frozenset({"live_order_routing"})  # even the owner is gated: off until counsel signs off in writing


class EntitlementDenied(Exception):
    status = 402

    def __init__(self, key: str, reason: str, plan: str, limit: int | None = None):
        super().__init__(f"{reason}: {key}")
        self.key, self.reason, self.plan, self.limit = key, reason, plan, limit

    def public(self) -> dict[str, Any]:
        return {"error": "entitlement_denied", "key": self.key, "reason": self.reason, "plan": self.plan, "limit": self.limit, "upgrade": True}


def _window_start(period: str, now: float) -> int:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    if period == "day":
        return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    if period == "month":
        return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    return 0


def _ent(conn, plan_id: str, key: str):
    return conn.execute("SELECT * FROM plan_entitlements WHERE plan_id=? AND key=?", (plan_id, key)).fetchone()


def used(conn, user_id: str, key: str, period: str, now: float | None = None) -> int:
    now = time.time() if now is None else now
    r = conn.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM usage_events WHERE user_id=? AND key=? AND ts>=?", (user_id, key, _window_start(period, now))).fetchone()
    return int(r["n"])


def record_usage(conn, user_id: str, key: str, quantity: int = 1, meta: dict[str, Any] | None = None, now: float | None = None,
                 idempotency_key: str | None = None, unit_cost_micros: int = 0) -> bool:
    """Append a metering row. A repeated ``idempotency_key`` is a no-op (returns False). ``unit_cost_micros`` (USD micro-dollars per unit) feeds the Flooos cost export."""
    def _w(c) -> bool:
        return c.execute("INSERT OR IGNORE INTO usage_events (id,user_id,key,quantity,ts,meta_json,idempotency_key,unit_cost_micros) VALUES (?,?,?,?,?,?,?,?)",
                         (uuid.uuid4().hex, user_id, key, int(quantity), int(time.time() if now is None else now), json.dumps(meta or {}, sort_keys=True)[:500],
                          idempotency_key, max(0, int(unit_cost_micros)))).rowcount == 1
    if conn.in_transaction:
        return _w(conn)
    with tx(conn):
        return _w(conn)


def enforce(conn, user_id: str, role: str, key: str, *, current: int | None = None, cost: int = 1, record: bool = False, now: float | None = None) -> dict[str, Any]:
    """Raise EntitlementDenied unless the user's plan allows ``key``.

    flag  -> must be true.   quota with period none -> ``current + cost`` must stay <= limit (caller supplies ``current``).
    quota with period day / month -> metered from usage_events; ``record=True`` appends the usage after the check passes.
    """
    plan = plan_for_user(conn, user_id, now)
    if role in BYPASS_ROLES and key not in NEVER_BYPASS:
        return {"plan": plan["code"], "bypass": True}
    e = _ent(conn, plan["id"], key)
    if not e:
        raise EntitlementDenied(key, "not_in_plan", plan["code"])
    if e["kind"] == "flag":
        if not e["bool_value"]:
            raise EntitlementDenied(key, "feature_not_in_plan", plan["code"])
        return {"plan": plan["code"], "allowed": True}
    limit = e["int_value"]
    if limit is not None:
        base = current if (e["period"] == "none" and current is not None) else used(conn, user_id, key, e["period"], now)
        if e["period"] == "none" and current is None:
            raise EntitlementDenied(key, "quota_check_needs_current", plan["code"], limit)
        if base + cost > limit:
            raise EntitlementDenied(key, "quota_exceeded", plan["code"], limit)
    if record and e["period"] != "none":
        record_usage(conn, user_id, key, cost, now=now)
    return {"plan": plan["code"], "limit": limit, "remaining": None if limit is None else max(0, limit - (base + cost))}


def summary(conn, user_id: str, role: str, current_counts: dict[str, int] | None = None, now: float | None = None) -> dict[str, Any]:
    plan = plan_for_user(conn, user_id, now)
    out: dict[str, Any] = {}
    for e in conn.execute("SELECT * FROM plan_entitlements WHERE plan_id=?", (plan["id"],)):
        if e["kind"] == "flag":
            out[e["key"]] = {"kind": "flag", "allowed": bool(e["bool_value"]) or (role in BYPASS_ROLES and e["key"] not in NEVER_BYPASS)}
        else:
            u = (current_counts or {}).get(e["key"]) if e["period"] == "none" else used(conn, user_id, e["key"], e["period"], now)
            out[e["key"]] = {"kind": "quota", "limit": e["int_value"], "period": e["period"], "used": u, "unlimited": role in BYPASS_ROLES}
    return {"plan": plan["code"], "plan_name": plan["name"], "entitlements": out}
