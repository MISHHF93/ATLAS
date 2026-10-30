"""Needs verification -> Verify -> verified / failed, for every third-party key ATLAS can use.

No provider key is ever set by ATLAS. Until the owner (or a signed-in user) enters one and presses Verify, a service is
``needs_verification``. Verify makes ONE read-only call with the key (no order, no alert, no message), records the outcome in
``var/integrations_verify.json`` and nothing else. The record holds a salted fingerprint of the key so that changing the key
puts the service back to ``needs_verification``; it never stores or returns the key, a last-4, or a response body.

States: needs_verification (no key, or a key that was not verified yet / was changed) | verified | failed | format_only
(well-formed, cannot be checked live: Sentry DSN, Slack webhook) | keyless (public source, nothing to verify)
Verify reuses the per-user connector tests (accounts/catalog.py) so the owner Setup tab and the user Connectors tab agree.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from atlas.accounts.catalog import BY_ID, TestContext, TestResult, _guard, _http_status, _scrub
from atlas.accounts.http import HttpResult, fetch

STORE = Path(os.environ.get("ATLAS_VERIFY_STORE", "var/integrations_verify.json"))
MIN_GAP_S = 8.0                      # protects free quotas (Alpha Vantage: 25/day): one verify per service per 8 s
_LOCK = threading.Lock()
_LAST: dict[tuple[str, str], float] = {}

# registry service id -> per-user connector id whose test is reused
CONNECTOR_FOR = {"alpaca": "alpaca", "oanda": "oanda", "ibkr": "ibkr", "tiingo": "tiingo", "finnhub": "finnhub", "twelvedata": "twelvedata",
                 "alphavantage": "alphavantage", "fmp": "fmp", "polygon": "massive", "fred": "fred", "sec_edgar": "sec_edgar",
                 "alerts_telegram": "telegram", "alerts_discord": "discord", "alerts_ntfy": "ntfy", "healthchecks": "healthchecks", "sentry": "sentry"}
KEYLESS = {"public_crypto", "yahoo", "solana_rpc"}


# ---------- extra tests for services with no per-user connector ----------
def _t_stripe(v, ctx):
    k = v["STRIPE_SECRET_KEY"]
    if not k.startswith(("sk_test_", "rk_test_")):
        return TestResult(False, "Stripe: only TEST-mode keys (sk_test_…) are accepted; live keys are refused and not contacted")
    r = ctx.http("GET", "https://api.stripe.com/v1/balance", headers={"Authorization": "Bearer " + k})
    bad = _http_status(r, what="Stripe test-mode balance")
    if bad:
        return bad
    if (r.json or {}).get("livemode") is True:
        return TestResult(False, "Stripe: this key is live-mode; refused")
    return TestResult(True, "test-mode key accepted (read-only balance call)")



def _t_questrade(v, ctx):
    from atlas.feeds.providers.questrade import QuestradeAdapter
    a = QuestradeAdapter(env=v)
    cur = a._session(time.time())   # consumes the single-use token once; the rotated one stays in memory only
    return TestResult(True, "refresh token accepted; the rotated token is held in memory only (a restart needs a new token from Questrade)") if cur else TestResult(False, "Questrade: no token")


def _t_gemini(v, ctx):
    r = ctx.http("GET", "https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": v["GEMINI_API_KEY"]}, params={"pageSize": "1"})
    return _http_status(r, what="Gemini models list") or TestResult(True, "key accepted (read-only model list)")


def _t_eodhd(v, ctx):
    r = ctx.http("GET", "https://eodhd.com/api/user", params={"api_token": v["EODHD_API_KEY"], "fmt": "json"})
    return _http_status(r, what="EODHD account") or TestResult(True, "key accepted (read-only account call)")


def _t_slack(v, ctx):
    u = v["SLACK_WEBHOOK_URL"]
    ok = u.startswith("https://hooks.slack.com/services/") and u.count("/") >= 6
    return TestResult(ok, "webhook URL format is valid. Slack has no read-only probe, so nothing was sent" if ok else "not a Slack incoming-webhook URL", state="format_only" if ok else "")


EXTRA: dict[str, tuple[tuple[str, ...], Callable]] = {
    "stripe": (("STRIPE_SECRET_KEY",), _guard(_t_stripe)),
    "questrade": (("QUESTRADE_REFRESH_TOKEN",), _guard(_t_questrade)),
    "gemini": (("GEMINI_API_KEY",), _guard(_t_gemini)),
    "eodhd": (("EODHD_API_KEY",), _guard(_t_eodhd)),
    "alerts_slack": (("SLACK_WEBHOOK_URL",), _guard(_t_slack)),
}
NO_VERIFIER = {"databento": "Databento is paid and has no free read-only probe; ATLAS never calls it unless ATLAS_ALLOW_PAID_DATA is on",
               "external_mcp": "External MCP servers are checked by their own client, not here", "llm_other": "Optional assistant keys are not probed"}


def _required(service) -> tuple[str, ...]:
    return tuple(k for k in service.required if k not in ("ATLAS_ALERTS_ENABLED", "ATLAS_EXTERNAL_MCP"))


def _val(env, k: str) -> str:
    v = (env.get(k) or "").strip()
    if k == "POLYGON_API_KEY" and not v:
        v = (env.get("MASSIVE_API_KEY") or "").strip()
    return "" if v.startswith("<") else v


# ---------- fingerprint + persistence ----------
def _salt() -> str:
    try:
        return json.loads(STORE.read_text()).get("_salt") or ""
    except Exception:  # noqa: BLE001
        return ""


def fingerprint(service, env) -> str:
    vals = [f"{k}={_val(env, k)}" for k in (*_required(service), *[o for o in service.optional if o in ("ALPACA_BASE_URL",)])]
    return hashlib.sha256((_salt() + "|".join(vals)).encode()).hexdigest()[:16]


def _scope() -> str:
    from atlas.accounts.credentials import current_identity
    i = current_identity()
    return "owner" if i is None or i.role == "owner" else f"user:{i.user_id}"


def _load() -> dict[str, Any]:
    try:
        return json.loads(STORE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(doc: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    doc.setdefault("_salt", hashlib.sha256(os.urandom(32)).hexdigest())
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True))
    os.replace(tmp, STORE)


def state_for(service, env, scope: str | None = None, doc: dict | None = None) -> dict[str, Any]:
    """Verification state for one service given the env the caller sees. Never contains a secret."""
    if service.id in KEYLESS or (not _required(service) and service.category != "ai"):
        return {"state": "keyless", "detail": "public source, nothing to verify", "verified_at": None, "key_present": False}
    missing = [k for k in _required(service) if not _val(env, k)]
    if missing:
        return {"state": "needs_verification", "detail": "No key entered yet: " + ", ".join(missing) + ". Enter it, then press Verify.", "verified_at": None,
                "key_present": False, "missing": missing}
    doc = _load() if doc is None else doc
    rec = (doc.get(scope or _scope()) or {}).get(service.id)
    if not rec:
        return {"state": "needs_verification", "detail": "Key entered but not verified yet. Press Verify.", "verified_at": None, "key_present": True}
    if rec.get("fp") != fingerprint(service, env):
        return {"state": "needs_verification", "detail": "Key changed since it was last checked. Press Verify.", "verified_at": None, "key_present": True}
    return {"state": rec["state"], "detail": rec.get("detail", ""), "verified_at": rec.get("at"), "key_present": True}


def verify(service_id: str, env, http=fetch, now: float | None = None, throttle: bool = True) -> dict[str, Any]:
    """Run one read-only verification and record it. Returns the new state (secret-free)."""
    from atlas.integrations.registry import SERVICES, mode_for
    svc = next((s for s in SERVICES if s.id == service_id), None)
    if svc is None:
        return {"service": service_id, "state": "unknown_service", "ok": None, "detail": "not a known service"}
    now = time.time() if now is None else now
    scope = _scope()
    cur = state_for(svc, env, scope)
    out = {"service": service_id, "scope": "owner" if scope == "owner" else "user"}
    if cur["state"] == "keyless":
        return {**out, **cur, "ok": None}
    if not cur["key_present"]:
        return {**out, **cur, "ok": None}
    if service_id in NO_VERIFIER:
        return {**out, "state": "needs_verification", "ok": None, "detail": NO_VERIFIER[service_id], "verified_at": None, "key_present": True}
    if mode_for(svc, dict(env)) == "live_refused":
        return {**out, "state": "failed", "ok": False, "detail": "live endpoint refused; not contacted (paper / practice / test mode only)", "verified_at": now, "key_present": True}
    with _LOCK:
        last = _LAST.get((scope, service_id), 0.0)
        if throttle and now - last < MIN_GAP_S:
            return {**out, **cur, "ok": None, "throttled": True, "detail": f"Verified a moment ago; wait {int(MIN_GAP_S - (now - last)) + 1}s (protects your free quota)"}
        _LAST[(scope, service_id)] = now
    ctx = TestContext(http=http, is_owner=scope == "owner")
    values: dict[str, str] = {}
    if service_id in CONNECTOR_FOR:
        spec = BY_ID[CONNECTOR_FOR[service_id]]
        for f in spec.fields:
            v = _val(env, f.env) or f.default
            if v:
                values[f.name] = v
        test = spec.test
    else:
        names, test = EXTRA[service_id]
        values = {k: _val(env, k) for k in dict.fromkeys((*names, *svc.optional))}
        values = {k: v for k, v in values.items() if v}
    try:
        res = test(values, ctx)
    except Exception as ex:  # noqa: BLE001
        res = TestResult(False, _scrub(f"{type(ex).__name__}: {ex}", values))
    st = "format_only" if res.state == "format_only" else ("verified" if res.ok else "failed")
    detail = _scrub(res.detail, values)
    with _LOCK:
        doc = _load()
        if not doc.get("_salt"):   # the salt must exist before the fingerprint is taken, or the first record never matches
            _save(doc)
            doc = _load()
        doc.setdefault(scope, {})[service_id] = {"state": st, "detail": detail, "at": int(now), "fp": fingerprint(svc, env)}
        _save(doc)
    return {**out, "state": st, "ok": res.ok if st != "format_only" else None, "detail": detail, "verified_at": int(now), "key_present": True}


def all_states(env, services=None) -> dict[str, dict[str, Any]]:
    from atlas.integrations.registry import SERVICES
    doc, scope = _load(), _scope()
    return {s.id: state_for(s, env, scope, doc) for s in (services or SERVICES)}
