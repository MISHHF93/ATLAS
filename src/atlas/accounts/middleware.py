"""Pure ASGI middleware: session -> identity, CSRF, optional auth requirement, plan gating, response hygiene.

* The session cookie (``atlas_session``) is resolved to a user once per request; the identity is placed in a ContextVar so feeds and
  integrations resolve THAT user's credentials (owner .env is the owner's fallback only).
* Auth is required for every /api route except the public ones (401 without a valid session) unless this is plain localhost:
  ``ATLAS_REQUIRE_AUTH`` decides when set, otherwise it is ON for a public deployment, a non-loopback client, or any request that
  carries proxy headers (see ``netinfo.require_auth``). A bare local install keeps working without signing in.
* Unsafe methods carrying a session cookie must present the per-session ``X-CSRF-Token`` and a same-host Origin (when sent).
* ``/api/account|connectors|billing|admin`` responses are ``Cache-Control: no-store``.
"""
from __future__ import annotations

import json
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

import anyio

from . import auth, entitlements
from .netinfo import require_auth as netinfo_require_auth
from .netinfo import resolve_client_ip
from .credentials import reset_identity, set_identity
from .db import connect

COOKIE = "atlas_session"
SAFE = ("GET", "HEAD", "OPTIONS")
PRE_AUTH = ("/api/account/register", "/api/account/login", "/api/account/verify-email", "/api/account/resend-verification",
            "/api/account/forgot-password", "/api/account/reset-password")  # callable with no session
PUBLIC = ("/api/account/config", "/api/billing/webhook", "/api/health", *PRE_AUTH)
CSRF_EXEMPT = ("/api/billing/webhook", *PRE_AUTH)  # no session yet / signature-authenticated
NO_STORE = ("/api/account", "/api/billing", "/api/admin", "/api/team")
# route prefix -> entitlement flag required (users on a plan without it get 402; owner/admin bypass). Authenticated users only.
ROUTE_FEATURES: tuple[tuple[str, str], ...] = (("/api/intel/lab", "feature.research_lab"),)


def _hdr(scope, name: bytes) -> str:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin1")
    return ""


def _getter(scope):
    return lambda name: _hdr(scope, name.encode("latin1"))


def client_ip(scope) -> str:
    """The address the rate limiter keys on: the real socket (via the loopback bridge header), and ``X-Forwarded-For`` only from a trusted proxy."""
    peer = (scope.get("client") or ("", 0))[0]
    return resolve_client_ip(peer, _getter(scope))


def require_auth(scope=None) -> bool:
    """Is a session required? With no ``scope`` only the environment is consulted (``ATLAS_REQUIRE_AUTH`` / public deployment)."""
    if scope is None:
        return netinfo_require_auth()
    return netinfo_require_auth(client_ip(scope), _getter(scope))


def _cookie(scope) -> str | None:
    raw = _hdr(scope, b"cookie")
    if not raw:
        return None
    c = SimpleCookie()
    try:
        c.load(raw)
    except Exception:  # noqa: BLE001
        return None
    m = c.get(COOKIE)
    return m.value if m else None


def _origin_ok(scope) -> bool:
    origin = _hdr(scope, b"origin")
    if not origin:
        return True
    host = (_hdr(scope, b"host") or "").lower()
    return (urlsplit(origin).netloc or "").lower() == host


async def _json(send, status: int, body: dict, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    raw = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), (b"cache-control", b"no-store"), *(extra or [])]})
    await send({"type": "http.response.body", "body": raw})


def _resolve(token: str | None):
    with connect() as conn:
        return auth.resolve_session(conn, token)


def _gate(user_id: str, role: str, feature: str) -> dict | None:
    with connect() as conn:
        try:
            entitlements.enforce(conn, user_id, role, feature)
        except entitlements.EntitlementDenied as ex:
            return ex.public()
    return None


class AccountsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not (scope.get("path") or "").startswith("/api") and scope["type"] == "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        scope.setdefault("state", {})
        scope["state"]["client_ip"] = client_ip(scope)
        token = _cookie(scope)
        sess = await anyio.to_thread.run_sync(_resolve, token) if token else None
        scope["state"]["atlas_session"] = sess
        is_http = scope["type"] == "http"
        method = scope.get("method", "GET")
        if sess is None and require_auth(scope) and not (is_http and path in PUBLIC):
            if is_http:
                await _json(send, 401, {"error": "auth_required"})
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        if sess is not None and is_http:
            if method not in SAFE and path not in CSRF_EXEMPT:
                if not _origin_ok(scope) or not auth.csrf_ok(sess, _hdr(scope, b"x-csrf-token")):
                    await _json(send, 403, {"error": "csrf_failed"})
                    return
            for prefix, feature in ROUTE_FEATURES:
                if path.startswith(prefix):
                    denied = await anyio.to_thread.run_sync(_gate, sess.user.id, sess.user.role, feature)
                    if denied:
                        await _json(send, 402, denied)
                        return
        tok = set_identity(sess.user.id, sess.user.role) if sess is not None else None

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                hs = list(message.get("headers", []))
                hs.append((b"x-content-type-options", b"nosniff"))
                if path.startswith(NO_STORE) and not any(k == b"cache-control" for k, _ in hs):
                    hs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hs}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapped)
        finally:
            if tok is not None:
                reset_identity(tok)
