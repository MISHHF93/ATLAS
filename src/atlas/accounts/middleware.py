"""Pure ASGI middleware: session -> identity, CSRF, optional auth requirement, plan gating, response hygiene.

* The session cookie (``atlas_session``) is resolved to a user once per request; the identity is placed in a ContextVar so feeds and
  integrations resolve THAT user's credentials (owner .env is the owner's fallback only).
* ``ATLAS_REQUIRE_AUTH`` (default OFF so the existing single-user local install is unchanged) makes every /api route except the
  public ones answer 401 without a valid session. Turn it on before exposing ATLAS beyond localhost.
* Unsafe methods carrying a session cookie must present the per-session ``X-CSRF-Token`` and a same-host Origin (when sent).
* ``/api/account|connectors|billing|admin`` responses are ``Cache-Control: no-store``.
"""
from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

import anyio

from . import auth, entitlements
from .credentials import reset_identity, set_identity
from .db import connect

COOKIE = "atlas_session"
SAFE = ("GET", "HEAD", "OPTIONS")
PUBLIC = ("/api/account/register", "/api/account/login", "/api/account/config", "/api/billing/webhook", "/api/health")
CSRF_EXEMPT = ("/api/billing/webhook", "/api/account/login", "/api/account/register")  # no session yet / signature-authenticated
NO_STORE = ("/api/account", "/api/billing", "/api/admin")
# route prefix -> entitlement flag required (users on a plan without it get 402; owner/admin bypass). Authenticated users only.
ROUTE_FEATURES: tuple[tuple[str, str], ...] = (("/api/intel/lab", "feature.research_lab"),)


def require_auth() -> bool:
    return os.environ.get("ATLAS_REQUIRE_AUTH", "").strip().lower() in ("1", "true", "on", "yes")


def _truthy_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def _hdr(scope, name: bytes) -> str:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin1")
    return ""


def client_ip(scope) -> str:
    peer = (scope.get("client") or ("", 0))[0]
    fwd = _hdr(scope, b"x-atlas-client-ip")  # set by frontend/server.mjs from the real socket; only honoured from the loopback bridge
    return fwd[:64] if fwd and _truthy_loopback(peer) else peer


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
        if sess is None and require_auth() and not (is_http and path in PUBLIC):
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
