"""/api/account, /api/account/connectors, /api/billing, /api/admin. Every handler derives the user from the SESSION, never from the request
body or path, and every data access is scoped by that user id. Bodies are parsed by hand so a validation error can never echo a
secret back. All mutations are POST (the CSRF middleware covers them)."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from atlas.accounts import audit, auth, billing, connectors, crypto, entitlements, stripe_client
from atlas.accounts.catalog import CATEGORIES, TestContext
from atlas.accounts.db import connect
from atlas.accounts.http import fetch
from atlas.accounts.middleware import COOKIE, AccountsMiddleware, require_auth

router = APIRouter()
MAX_BODY = 32_768


def cookie_secure() -> bool:
    return os.environ.get("ATLAS_COOKIE_SECURE", "").lower() in ("1", "true", "on") or os.environ.get("ATLAS_PUBLIC_URL", "").startswith("https://")


def db():
    with connect() as conn:
        yield conn


async def body_of(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "body too large")
    if not raw:
        return {}
    try:
        import json
        v = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "bad_json") from None
    if not isinstance(v, dict):
        raise HTTPException(400, "bad_json")
    return v


async def raw_body(request: Request) -> bytes:
    raw = await request.body()
    if len(raw) > 262_144:
        raise HTTPException(413, "too large")
    return raw


def session_of(request: Request):
    return getattr(request.state, "atlas_session", None)


def need_session(request: Request):
    s = session_of(request)
    if s is None:
        raise auth.AuthError("login_required", 401)
    return s


def need_admin(request: Request):
    s = need_session(request)
    if not s.user.is_admin:
        raise auth.AuthError("forbidden", 403)
    return s


def _ip(request: Request) -> str:
    return getattr(request.state, "client_ip", "") or ""


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=auth.SESSION_ABS_SECONDS, httponly=True, samesite="lax", secure=cookie_secure(), path="/")


def _clear_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure())


def _s(v: Any, n: int = 200) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


# ---------------- account ----------------
@router.get("/api/account/config")
def account_config() -> dict[str, Any]:
    st = stripe_client.configured()
    return {"registration": auth.registration_mode(), "require_auth": require_auth(), "master_key_configured": crypto.master_key_configured(),
            "password_min_length": 12, "stripe_test_mode": {"checkout": st["secret_key"], "webhook": st["webhook_secret"]},
            "oauth_providers": [], "execution_permission": "none"}


@router.get("/api/account/me")
def me(request: Request) -> dict[str, Any]:
    s = session_of(request)
    if s is None:
        return {"authenticated": False, "require_auth": require_auth(), "registration": auth.registration_mode()}
    return {"authenticated": True, "user": s.user.public(), "csrf_token": s.csrf_token, "require_auth": require_auth()}


@router.post("/api/account/register")
def register(request: Request, b: dict = Depends(body_of), conn=Depends(db)):
    user = auth.register(conn, _s(b.get("email"), 254), b.get("password") if isinstance(b.get("password"), str) else "", _s(b.get("display_name"), 80),
                         ip=_ip(request), ref=_s(b.get("ref"), 16) or None)
    token, csrf = auth.create_session(conn, user.id, _ip(request), request.headers.get("user-agent", ""))
    resp = JSONResponse({"user": user.public(), "csrf_token": csrf})
    _set_cookie(resp, token)
    return resp


@router.post("/api/account/login")
def login(request: Request, b: dict = Depends(body_of), conn=Depends(db)):
    user = auth.authenticate(conn, _s(b.get("email"), 254), b.get("password") if isinstance(b.get("password"), str) else "", ip=_ip(request))
    token, csrf = auth.create_session(conn, user.id, _ip(request), request.headers.get("user-agent", ""))
    resp = JSONResponse({"user": user.public(), "csrf_token": csrf})
    _set_cookie(resp, token)
    return resp


@router.post("/api/account/logout")
def logout(request: Request, conn=Depends(db)):
    s = session_of(request)
    if s is not None:
        auth.revoke_session(conn, s.id, s.user.id)
    resp = JSONResponse({"ok": True})
    _clear_cookie(resp)
    return resp


@router.get("/api/account/sessions")
def sessions(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {"sessions": [{k: v for k, v in x.items() if k != "ref"} for x in auth.list_sessions(conn, s.user.id, s.id)]}


@router.post("/api/account/sessions/revoke")
def revoke_session(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    if b.get("all_others"):
        return {"revoked": auth.revoke_all(conn, s.user.id, except_id=s.id)}
    sid = _s(b.get("id"), 12)
    full = [x["ref"] for x in auth.list_sessions(conn, s.user.id, s.id) if len(sid) >= 8 and x["ref"].startswith(sid)]
    if len(full) != 1 or full[0] == s.id:
        raise auth.AuthError("not_found", 404)
    return {"revoked": int(auth.revoke_session(conn, full[0], s.user.id))}


@router.post("/api/account/profile")
def profile(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    u = auth.update_profile(conn, s.user.id, display_name=b.get("display_name") if isinstance(b.get("display_name"), str) else None,
                            timezone=b.get("timezone") if isinstance(b.get("timezone"), str) else None)
    return {"user": u.public()}


@router.post("/api/account/password")
def password(request: Request, b: dict = Depends(body_of), conn=Depends(db)):
    s = need_session(request)
    auth.change_password(conn, s.user.id, b.get("current") if isinstance(b.get("current"), str) else "", b.get("new") if isinstance(b.get("new"), str) else "", keep_session_id=s.id)
    return {"ok": True, "other_sessions_revoked": True}


@router.post("/api/account/delete")
def delete_me(request: Request, b: dict = Depends(body_of), conn=Depends(db)):
    s = need_session(request)
    auth.delete_account(conn, s.user.id, b.get("password") if isinstance(b.get("password"), str) else "")
    resp = JSONResponse({"ok": True})
    _clear_cookie(resp)
    return resp


@router.get("/api/account/audit")
def my_audit(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {"events": audit.recent(conn, s.user.id, 50)}


@router.get("/api/account/referrals")
def my_referrals(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM partner_referrals WHERE referrer_user_id=? GROUP BY status", (s.user.id,)).fetchall()
    return {"code": s.user.referral_code, "counts": {r["status"]: r["n"] for r in rows},
            "note": "Referral tracking only. No payouts are made and no rate is decided (see docs/atlas/monetization.md)."}


# ---------------- connectors ----------------
def _counts(conn, uid: str) -> dict[str, int]:
    return {"connectors.max": connectors.count_for(conn, uid), "alerts.channels.max": connectors.count_for(conn, uid, "alerts")}


@router.get("/api/account/connectors")
def connectors_library(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {"categories": [{"id": c[0], "title": c[1], "stage": c[2]} for c in CATEGORIES], "connectors": connectors.library(conn, s.user.id),
            "master_key_configured": crypto.master_key_configured(), "entitlements": entitlements.summary(conn, s.user.id, s.user.role, _counts(conn, s.user.id)),
            "paper_only": True, "execution_permission": "none"}


@router.post("/api/account/connectors/{connector_id}/save")
def connector_save(connector_id: str, request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    values = b.get("values") if isinstance(b.get("values"), dict) else {}
    from atlas.accounts.catalog import BY_ID
    spec = BY_ID.get(connector_id)
    if spec is None:
        raise connectors.ConnectorError("unknown_connector", 404)
    if not conn.execute("SELECT 1 FROM connectors WHERE user_id=? AND connector_id=?", (s.user.id, connector_id)).fetchone():
        entitlements.enforce(conn, s.user.id, s.user.role, "connectors.max", current=connectors.count_for(conn, s.user.id))
        if spec.category == "alerts":
            entitlements.enforce(conn, s.user.id, s.user.role, "alerts.channels.max", current=connectors.count_for(conn, s.user.id, "alerts"))
    st = connectors.save(conn, s.user.id, connector_id, values)
    return {"connector": connector_id, "state": st}


@router.post("/api/account/connectors/{connector_id}/rotate")
def connector_rotate(connector_id: str, request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    st = connectors.rotate(conn, s.user.id, connector_id, _s(b.get("field"), 40), b.get("value") if isinstance(b.get("value"), str) else "")
    return {"connector": connector_id, "state": st}


@router.post("/api/account/connectors/{connector_id}/delete")
def connector_delete(connector_id: str, request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {"connector": connector_id, "deleted": connectors.delete(conn, s.user.id, connector_id)}


@router.post("/api/account/connectors/{connector_id}/test")
def connector_test(connector_id: str, request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    from atlas.accounts.catalog import BY_ID
    if connector_id not in BY_ID:
        raise connectors.ConnectorError("unknown_connector", 404)
    if not conn.execute("SELECT 1 FROM connectors WHERE user_id=? AND connector_id=?", (s.user.id, connector_id)).fetchone():
        raise connectors.ConnectorError("not_saved", 404, "Save this connector first")
    entitlements.enforce(conn, s.user.id, s.user.role, "connector_tests.daily", record=True)
    st = connectors.run_test(conn, s.user.id, connector_id, TestContext(http=fetch, is_owner=s.user.is_owner))
    return {"connector": connector_id, "state": st}


# ---------------- billing (Stripe TEST MODE only; NO per-trade commissions) ----------------
@router.get("/api/billing/plans")
def plans(conn=Depends(db)) -> dict[str, Any]:
    return {"plans": billing.plans_public(conn), "placeholder": True, "per_trade_commission": False,
            "note": "Plans and prices are placeholders. ATLAS takes no commission on any trade."}


@router.get("/api/billing/subscription")
def subscription(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {**billing.subscription_public(conn, s.user.id), "entitlements": entitlements.summary(conn, s.user.id, s.user.role, _counts(conn, s.user.id)),
            "stripe_test_mode": stripe_client.configured()}


@router.post("/api/billing/checkout")
def checkout(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    plan = conn.execute("SELECT * FROM plans WHERE code=? AND active=1", (_s(b.get("plan"), 20),)).fetchone()
    if plan is None:
        raise stripe_client.StripeError("unknown_plan", 404)
    out = stripe_client.create_checkout_session(s.user.public(), plan)
    audit.log(conn, s.user.id, "billing.checkout_started", "plan", plan["code"])
    return {"url": out["url"], "test_mode": True}


@router.post("/api/billing/webhook")
def webhook(request: Request, raw: bytes = Depends(raw_body), conn=Depends(db)) -> dict[str, Any]:
    return {"received": True, "result": stripe_client.process_webhook(conn, raw, request.headers.get("stripe-signature"))}


# ---------------- admin ----------------
@router.get("/api/admin/users")
def admin_users(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    return {"users": auth.list_users(conn, s.user)}


@router.post("/api/admin/users/role")
def admin_role(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    return {"user": auth.set_role(conn, s.user, _s(b.get("user_id"), 64), _s(b.get("role"), 10)).public()}


@router.post("/api/admin/users/status")
def admin_status(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    return {"user": auth.set_status(conn, s.user, _s(b.get("user_id"), 64), _s(b.get("status"), 10)).public()}


@router.get("/api/admin/audit")
def admin_audit(request: Request, conn=Depends(db)) -> dict[str, Any]:
    need_admin(request)
    return {"events": audit.recent(conn, None, 200), "chain": audit.verify_chain(conn)}


# ---------------- install ----------------
def _err(status: int, code: str, message: str | None = None, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": code, **({"message": message} if message else {}), **extra}, status_code=status)


def install(app: FastAPI) -> None:
    app.include_router(router)

    @app.exception_handler(auth.AuthError)
    async def _auth(_: Request, ex: auth.AuthError):
        r = _err(ex.status, ex.code, str(ex) if str(ex) != ex.code else None)
        if ex.retry_after:
            r.headers["Retry-After"] = str(ex.retry_after)
        return r

    @app.exception_handler(connectors.ConnectorError)
    async def _conn(_: Request, ex: connectors.ConnectorError):
        return _err(ex.status, ex.code, str(ex) if str(ex) != ex.code else None)

    @app.exception_handler(entitlements.EntitlementDenied)
    async def _ent(_: Request, ex: entitlements.EntitlementDenied):
        return JSONResponse(ex.public(), status_code=402)

    @app.exception_handler(stripe_client.StripeError)
    async def _stripe(_: Request, ex: stripe_client.StripeError):
        return _err(ex.status, ex.code)

    @app.exception_handler(crypto.MasterKeyError)
    async def _mk(_: Request, ex: crypto.MasterKeyError):
        return _err(503, "master_key_unavailable", "ATLAS_MASTER_KEY is missing or invalid, so secrets cannot be stored or read (fail closed).")

    @app.exception_handler(crypto.TamperError)
    async def _tamper(_: Request, ex: crypto.TamperError):
        return _err(500, "secret_integrity_failure", "A stored secret failed authentication.")

    app.add_middleware(AccountsMiddleware)  # added last = outermost: runs before every other middleware
