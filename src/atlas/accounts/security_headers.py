"""Security response headers for the FastAPI side (the Next side sets the same set in ``frontend/server.mjs``).

* API responses are data, never documents: ``default-src 'none'; frame-ancestors 'none'`` plus ``nosniff``, ``no-referrer``,
  ``X-Frame-Options: DENY`` and a locked-down Permissions-Policy.
* ``/docs`` and ``/redoc`` (Swagger / ReDoc pull assets from a CDN) get only ``frame-ancestors 'none'``.
* ``Strict-Transport-Security`` is sent only when the request really was https (``ATLAS_PUBLIC_URL`` is https, the ASGI scheme is https,
  or a TRUSTED proxy says so via ``X-Forwarded-Proto``). Sending HSTS over plain http is ignored by browsers and would be a lie.
"""
from __future__ import annotations

from . import netinfo

HSTS = b"max-age=31536000; includeSubDomains"
API_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOC_PATHS = ("/docs", "/redoc")
DOC_CSP = b"frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
PERMISSIONS = b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def _hdr(scope, name: bytes) -> str:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin1")
    return ""


def is_https(scope) -> bool:
    if netinfo.public_https() or scope.get("scheme") in ("https", "wss"):
        return True
    if _hdr(scope, b"x-forwarded-proto").split(",")[0].strip().lower() == "https":
        peer = (scope.get("client") or ("", 0))[0]
        bridged = _hdr(scope, b"x-atlas-client-ip")
        hop = bridged if bridged and netinfo.is_loopback(peer) else peer
        nets = netinfo.trusted_proxies()
        return bool(nets) and netinfo._in(hop, nets)
    return False


def headers_for(scope, path: str) -> list[tuple[bytes, bytes]]:
    csp = DOC_CSP if path.startswith(DOC_PATHS) else API_CSP
    out = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
           (b"content-security-policy", csp), (b"permissions-policy", PERMISSIONS), (b"cross-origin-opener-policy", b"same-origin")]
    if is_https(scope):
        out.append((b"strict-transport-security", HSTS))
    return out


class SecurityHeadersMiddleware:
    """Outermost pure-ASGI layer: adds the headers to every HTTP response unless the app already set that header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                hs = list(message.get("headers", []))
                have = {k.lower() for k, _ in hs}
                for k, v in headers_for(scope, path):
                    if k not in have:
                        hs.append((k, v))
                message = {**message, "headers": hs}
            await send(message)

        await self.app(scope, receive, send_wrapped)
