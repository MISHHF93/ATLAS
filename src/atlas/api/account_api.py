"""/api/account, /api/account/connectors, /api/billing, /api/admin. Every handler derives the user from the SESSION, never from the request
body or path, and every data access is scoped by that user id. Bodies are parsed by hand so a validation error can never echo a
secret back. All mutations are POST (the CSRF middleware covers them)."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from atlas.accounts import audit, auth, billing, brokers, connectors, crypto, entitlements, flooos, ledger, stripe_client
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
    return {"plans": billing.plans_public(conn), "addons": list(billing.ADDONS), "placeholder": True, "per_trade_commission": False, "fees": billing.FEES,
            "prices_exclude_tax": True, "currencies": list(billing.CURRENCIES), "intervals": list(billing.INTERVALS),
            "note": "Plans and prices are placeholders, tax is added at checkout. ATLAS charges $0 per trade and takes no performance fee."}


@router.get("/api/billing/subscription")
def subscription(request: Request, conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return {**billing.subscription_public(conn, s.user.id), "entitlements": entitlements.summary(conn, s.user.id, s.user.role, _counts(conn, s.user.id)),
            "stripe_test_mode": stripe_client.configured(), "stripe_tax": stripe_client.tax_enabled()}


@router.post("/api/billing/checkout")
def checkout(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    plan = billing.resolve_plan(conn, _s(b.get("plan"), 30), _s(b.get("interval"), 8) or None, _s(b.get("currency"), 4) or None)
    if plan is None:
        raise stripe_client.StripeError("unknown_plan", 404)
    seats = b.get("seats")
    if seats is not None and (not isinstance(seats, int) or isinstance(seats, bool)):
        raise stripe_client.StripeError("bad_seats", 400)
    out = stripe_client.create_checkout_session(s.user.public(), plan, seats=seats)
    audit.log(conn, s.user.id, "billing.checkout_started", "plan", plan["code"], detail={"seats": seats})
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


# ---------------- broker referrals (OFF until counsel approves a partner) ----------------
@router.get("/api/account/brokers")
def broker_list(request: Request, conn=Depends(db)) -> dict[str, Any]:
    need_session(request)
    return brokers.public_partners(conn)


@router.post("/api/account/brokers/{code}/refer")
def broker_refer(code: str, request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_session(request)
    return brokers.start_referral(conn, s.user.id, _s(code, 30), b.get("disclosure_shown") is True)


# ---------------- admin: plans, brokers, ledger, Flooos export ----------------
@router.post("/api/admin/plans/update")
def admin_plan_update(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    p = conn.execute("SELECT * FROM plans WHERE code=?", (_s(b.get("code"), 30),)).fetchone()
    if p is None:
        raise HTTPException(404, "unknown_plan")
    sets, args = [], []
    for col, hi in (("price_cents", 10_000_000), ("extra_seat_cents", 1_000_000), ("seats_included", 1000), ("trial_days", 365)):
        if col in b:
            v = b[col]
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= hi or (col == "seats_included" and v < 1):
                raise HTTPException(400, f"bad_{col}")
            sets.append(f"{col}=?"); args.append(v)
    for col in ("is_placeholder", "active"):
        if col in b:
            if not isinstance(b[col], bool):
                raise HTTPException(400, f"bad_{col}")
            sets.append(f"{col}=?"); args.append(int(b[col]))
    if "tax_behavior" in b:
        if b["tax_behavior"] not in ("exclusive", "inclusive"):
            raise HTTPException(400, "bad_tax_behavior")
        sets.append("tax_behavior=?"); args.append(b["tax_behavior"])
    for col in ("stripe_price_id", "stripe_product_id"):
        if col in b:
            v = b[col]
            if v is not None and (not isinstance(v, str) or not v.startswith(("price_", "prod_")) or len(v) > 80):
                raise HTTPException(400, f"bad_{col}")
            sets.append(f"{col}=?"); args.append(v)
    if not sets:
        raise HTTPException(400, "nothing_to_update")
    from atlas.accounts.db import tx
    with tx(conn):
        conn.execute(f"UPDATE plans SET {', '.join(sets)} WHERE id=?", (*args, p["id"]))
        audit.log(conn, s.user.id, "admin.plan_update", "plan", p["code"], detail={"fields": [x.split("=")[0] for x in sets]})
    return {"plan": next(x for x in billing.plans_public(conn) if x["code"] == p["code"])}


@router.get("/api/admin/brokers")
def admin_brokers(request: Request, conn=Depends(db)) -> dict[str, Any]:
    need_admin(request)
    return {"partners": [dict(r) for r in conn.execute("SELECT code,name,program_type,legal_status,terms_url,active FROM broker_partners ORDER BY name")],
            "referrals": [dict(r) for r in conn.execute("SELECT r.id, p.code AS partner, r.status, r.cpa_cents, r.currency, r.created_at FROM broker_referrals r JOIN broker_partners p ON p.id=r.partner_id ORDER BY r.created_at DESC LIMIT 200")]}


@router.post("/api/admin/brokers/update")
def admin_broker_update(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    act = b.get("active")
    if act is not None and not isinstance(act, bool):
        raise HTTPException(400, "bad_active")
    return brokers.set_partner(conn, s.user.id, _s(b.get("code"), 30), b.get("legal_status") if isinstance(b.get("legal_status"), str) else None, act)


@router.post("/api/admin/brokers/referral")
def admin_broker_referral(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    cents = b.get("cpa_cents")
    if cents is not None and (not isinstance(cents, int) or isinstance(cents, bool)):
        raise HTTPException(400, "bad_cpa")
    return brokers.update_referral(conn, s.user.id, _s(b.get("id"), 64), _s(b.get("status"), 20), cents, _s(b.get("currency"), 3) or "usd", _s(b.get("bank_ref"), 60) or None)


@router.post("/api/admin/ledger/append")
def admin_ledger_append(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    """Manual entries only for kinds the webhooks cannot see (tax_remittance, stripe_fee reconciliation, adjustment, user_credit)."""
    s = need_admin(request)
    kind = _s(b.get("kind"), 20)
    if kind not in ("tax_remittance", "stripe_fee", "adjustment", "user_credit"):
        raise HTTPException(400, "kind_not_manual")
    amt = b.get("amount_cents")
    if not isinstance(amt, int) or isinstance(amt, bool):
        raise HTTPException(400, "bad_amount")
    from atlas.accounts.db import tx
    with tx(conn):
        rid = ledger.append(conn, kind, _s(b.get("direction"), 3), amt, _s(b.get("currency"), 3), _s(b.get("counterparty"), 60), bank_ref=_s(b.get("bank_ref"), 60) or None,
                            memo=_s(b.get("memo"), 200), dedupe_key=_s(b.get("dedupe_key"), 80) or None)
        audit.log(conn, s.user.id, "admin.ledger_append", "payouts_ledger", rid or "", detail={"kind": kind, "amount_cents": amt})
    return {"id": rid, "chain": ledger.verify_chain(conn)}


def _range(request: Request) -> tuple[int, int | None]:
    try:
        a = int(request.query_params.get("from") or 0)
        z = request.query_params.get("to")
        return a, (int(z) if z else None)
    except ValueError:
        raise HTTPException(400, "bad_range") from None


@router.get("/api/admin/flooos/export")
def admin_flooos(request: Request, conn=Depends(db)):
    need_admin(request)
    start, end = _range(request)
    out = flooos.build(conn, start, end)
    if request.query_params.get("format") == "csv":
        return Response(flooos.to_csv(out["ledger"]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="atlas-ledger.csv"'})
    return out


@router.post("/api/admin/flooos/mark")
def admin_flooos_mark(request: Request, b: dict = Depends(body_of), conn=Depends(db)) -> dict[str, Any]:
    s = need_admin(request)
    a, z = b.get("from", 0), b.get("to")
    if not isinstance(a, int) or not isinstance(z, int):
        raise HTTPException(400, "bad_range")
    n = ledger.mark_exported(conn, _s(b.get("batch"), 40), a, z)
    audit.log(conn, s.user.id, "admin.flooos_mark", "payouts_ledger", _s(b.get("batch"), 40), detail={"rows": n})
    return {"marked": n}


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

    @app.exception_handler(brokers.BrokerError)
    async def _broker(_: Request, ex: brokers.BrokerError):
        return _err(ex.status, ex.code)

    @app.exception_handler(ledger.LedgerError)
    async def _ledger(_: Request, ex: ledger.LedgerError):
        return _err(ex.status, ex.code)

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
