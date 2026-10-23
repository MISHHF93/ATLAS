"""Tiny stdlib HTTP layer: routing, JSON, security headers, session/CSRF/step-up enforcement.

Every /api route requires a logged-in session unless marked public. Every non-GET request needs:
Host in the loopback allowlist, same-origin Origin (when sent), Sec-Fetch-Site not cross-site,
JSON content type (or text/csv for uploads) and a valid X-CSRF-Token. Routes marked with a
step-up domain additionally need {"stepup": {"passphrase", "code"}} verified by that domain."""
from __future__ import annotations

import json
import math
import re
import traceback
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from importlib import resources
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from atlas.console.auth import ABSOLUTE_S, AuthError, Session, Sessions, Users, csrf_ok

COOKIE = "tbc_session"          # staff / owner console
PORTAL_COOKIE = "tbi_session"   # investor portal (separate role, separate session store)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
SPA_PAGES = ("trading", "strategies", "risk", "payments", "wallet", "fund", "tax", "reports", "audit", "profile", "settings", "money", "compliance", "overview", "home")
PORTAL_ROUTE = re.compile(r"^/portal(?:/[A-Za-z0-9_.:-]+)*/?$")
SPA_ROUTE = re.compile(r"^/(?:(?:" + "|".join(SPA_PAGES) + r")(?:/[A-Za-z0-9_.:-]+)*)?/?$")


class HTTPError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    params: dict[str, str]
    headers: Any
    body: Any = None
    raw: bytes = b""
    session: Session | None = None
    stepup_user: str | None = None


def _finite(obj):
    """Browsers reject NaN/Infinity in JSON; send them as null (e.g. gate values on empty shadow)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


@dataclass
class Response:
    code: int = 200
    body: bytes = b""
    ctype: str = "application/json"
    headers: dict = field(default_factory=dict)

    @staticmethod
    def json(obj, code: int = 200) -> "Response":
        return Response(code, json.dumps(_finite(obj), default=str, allow_nan=False).encode())

    @staticmethod
    def download(data: bytes | str, ctype: str, filename: str) -> "Response":
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)[:100]
        b = data.encode() if isinstance(data, str) else data
        return Response(200, b, ctype, {"Content-Disposition": f'attachment; filename="{safe}"'})


@dataclass
class Route:
    method: str
    pattern: re.Pattern
    fn: Callable[[Request], Any]
    public: bool = False
    stepup: str | None = None          # "trading" | "payments"
    max_body: int = 16_384
    body_types: tuple = ("application/json",)
    role: str = "owner"                # "owner" (staff console session) | "investor" (portal session)


class Router:
    def __init__(self):
        self.routes: list[Route] = []

    def add(self, method: str, path: str, fn, **kw) -> None:
        rx = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[A-Za-z0-9_.:-]+)", path) + "$")
        if path.startswith("/api/i/") != (kw.get("role", "owner") == "investor"):
            raise ValueError(f"{path}: /api/i/* routes are exactly the investor-role routes")
        self.routes.append(Route(method, rx, fn, **kw))

    def match(self, method: str, path: str) -> tuple[Route | None, dict, bool]:
        path_exists = False
        for r in self.routes:
            m = r.pattern.match(path)
            if m:
                path_exists = True
                if r.method == method:
                    return r, m.groupdict(), True
        return None, {}, path_exists


@dataclass
class App:
    router: Router
    users: Users
    sessions: Sessions
    port: int
    stepup: dict[str, Callable[[Session, str, str], bool]]
    audit: Callable[[str, dict, str], None]
    info: Callable[[], dict]
    static_pkg: str = "atlas.console"
    portal_sessions: Sessions | None = None
    portal_login: Callable[[str, str], int] | None = None      # (username, passphrase) -> investor id

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "atlas-console"
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # ---------------------------------------------------------------- output
        def _send(self, resp: Response, cookies: list[str] | None = None) -> None:
            self.send_response(resp.code)
            h = {"Content-Type": resp.ctype, "Content-Length": str(len(resp.body)), "Cache-Control": "no-store",
                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                 "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin",
                 "Permissions-Policy": "camera=(), microphone=(), geolocation=()", "Content-Security-Policy": CSP}
            h.update(resp.headers)
            for k, v in h.items():
                self.send_header(k, v)
            for c in cookies or []:
                self.send_header("Set-Cookie", c)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(resp.body)

        def _err(self, code: int, msg: str) -> None:
            self._send(Response.json({"error": msg}, code))

        def _token(self, name: str = COOKIE) -> str | None:
            c = SimpleCookie()
            try:
                c.load(self.headers.get("Cookie", ""))
            except Exception:
                return None
            return c[name].value if name in c else None

        def _same_origin(self) -> bool:
            o = self.headers.get("Origin")
            if o is not None and o.removeprefix("http://") not in app.allowed_hosts:
                return False
            return self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")

        # ---------------------------------------------------------------- dispatch
        def _handle(self, method: str) -> None:
            if self.headers.get("Host", "") not in app.allowed_hosts:
                return self._err(421, "bad host")
            u = urlsplit(self.path)
            path = u.path
            if method in ("GET", "HEAD") and not path.startswith("/api/"):
                return self._static(path)
            if path == "/healthz":
                return self._send(Response.json({"ok": True}))
            route, params, exists = app.router.match(method, path)
            if path in ("/api/login", "/api/logout", "/api/session"):
                return self._session_routes(method, path)
            if path in ("/api/portal/login", "/api/portal/logout", "/api/portal/session"):
                return self._session_routes(method, path.replace("/portal", ""), portal=True)
            if not route:
                return self._err(405 if exists else 404, "method not allowed" if exists else "not found")
            if route.role == "investor":       # investor routes only ever see the portal cookie/store, and vice versa
                if not app.portal_sessions:
                    return self._err(404, "not found")
                sess = app.portal_sessions.get(self._token(PORTAL_COOKIE))
            else:
                sess = app.sessions.get(self._token(COOKIE))
            if not route.public and not sess:
                return self._err(401, "login required")
            req = Request(method, path, {k: v[-1] for k, v in parse_qs(u.query).items()}, params, self.headers, session=sess)
            if method != "GET":
                if not self._same_origin():
                    app.audit("console.csrf_blocked", {"path": path, "reason": "cross-origin"}, sess.user if sess else "anonymous")
                    return self._err(403, "cross-origin request blocked")
                if not csrf_ok(sess, self.headers.get("X-CSRF-Token")):
                    app.audit("console.csrf_blocked", {"path": path, "reason": "bad csrf token"}, sess.user if sess else "anonymous")
                    return self._err(403, "CSRF token missing or invalid")
                try:
                    self._read_body(req, route)
                except HTTPError as e:
                    return self._err(e.code, e.msg)
                if route.stepup:
                    su = req.body.get("stepup") if isinstance(req.body, dict) else None
                    if not isinstance(su, dict) or not su.get("passphrase") or not su.get("code"):
                        return self._send(Response.json({"error": "step-up required", "stepup": route.stepup}, 401))
                    ok = False
                    try:
                        ok = bool(app.stepup[route.stepup](sess, str(su["passphrase"]), str(su["code"])))
                    except Exception:  # noqa: BLE001  fail closed
                        ok = False
                    app.audit("console.step_up", {"ok": ok, "domain": route.stepup, "path": path}, sess.user)
                    if not ok:
                        return self._send(Response.json({"error": "step-up failed", "stepup": route.stepup}, 403))
                    req.stepup_user = sess.user
                    req.body.pop("stepup", None)
            try:
                out = route.fn(req)
            except HTTPError as e:
                return self._err(e.code, e.msg)
            except (PermissionError, AuthError) as e:
                return self._err(409 if type(e).__name__ in ("ControlError", "GateError", "PromotionDenied", "WalletError") else 403, str(e)[:300])
            except RuntimeError as e:
                if type(e).__name__ in ("VaultUnavailable", "PartnerDisabled"):
                    return self._err(503, str(e)[:300])
                traceback.print_exc()
                return self._err(500, "internal error")
            except KeyError as e:
                return self._err(404, f"not found: {str(e)[:100]}")
            except (ValueError, TypeError) as e:
                return self._err(400, str(e)[:300])
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return self._err(500, "internal error")
            self._send(out if isinstance(out, Response) else Response.json(out))

        def _read_body(self, req: Request, route: Route) -> None:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise HTTPError(400, "bad length")
            if n < 0 or n > route.max_body:
                raise HTTPError(413, "body too large")
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in route.body_types:
                raise HTTPError(415, "unsupported content type")
            req.raw = self.rfile.read(n) if n else b""
            if ctype == "application/json":
                try:
                    req.body = json.loads(req.raw or b"{}")
                except Exception:
                    raise HTTPError(400, "bad json")
                if not isinstance(req.body, dict):
                    raise HTTPError(400, "json object expected")
            else:
                req.body = {}

        def _session_routes(self, method: str, path: str, portal: bool = False) -> None:
            cname = PORTAL_COOKIE if portal else COOKIE
            store = app.portal_sessions if portal else app.sessions
            if store is None:
                return self._err(404, "not found")
            token = self._token(cname)
            sess = store.get(token)
            if path == "/api/session" and method == "GET":
                body = {"authenticated": bool(sess), **app.info(), "role": "investor" if portal else "owner"}
                if sess:
                    body |= {"user": sess.user, "csrf": sess.csrf, "session_id": sess.sid}
                    if portal:
                        body["investor_id"] = sess.meta.get("investor_id")
                return self._send(Response.json(body))
            if method != "POST":
                return self._err(405, "method not allowed")
            if not self._same_origin():
                return self._err(403, "cross-origin request blocked")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._err(415, "unsupported content type")
            if path == "/api/logout":
                if not csrf_ok(sess, self.headers.get("X-CSRF-Token")):
                    return self._err(403, "CSRF token missing or invalid")
                store.destroy(token)
                app.audit("portal.logout" if portal else "console.logout", {}, sess.user)
                return self._send(Response.json({"ok": True}), [f"{cname}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"])
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 4096:
                    raise ValueError
                b = json.loads(self.rfile.read(n) or b"{}")
                user, pw = str(b.get("username", ""))[:64], str(b.get("passphrase", ""))[:256]
            except Exception:
                return self._err(400, "bad request")
            pfx = "portal" if portal else "console"
            try:
                iid = app.portal_login(user, pw) if portal else app.users.check(user, pw)
            except (AuthError, PermissionError) as e:
                app.audit(f"{pfx}.login_failed", {"user": user, "reason": str(e)}, "anonymous")
                return self._err(401, str(e))
            if sess:
                store.destroy(token)  # rotate on login (no session fixation)
            tok, s = store.create(user, self.headers.get("User-Agent", ""))
            if portal:
                s.meta["investor_id"] = int(iid)
            app.audit(f"{pfx}.login", {"session": s.sid}, user)
            cookie = f"{cname}={tok}; Path=/; Max-Age={ABSOLUTE_S}; HttpOnly; SameSite=Strict"
            body = {"ok": True, "user": user, "csrf": s.csrf, "session_id": s.sid}
            if portal:
                body["investor_id"] = int(iid)
            return self._send(Response.json(body), [cookie])

        def _static(self, path: str) -> None:
            root = resources.files(app.static_pkg).joinpath("static")
            if path.startswith("/static/"):
                rel = path.removeprefix("/static/")
                if ".." in rel or rel.startswith("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", rel):
                    return self._err(404, "not found")
                f = root.joinpath(*rel.split("/"))
                ext = "." + rel.rsplit(".", 1)[-1] if "." in rel else ""
                if ext not in STATIC_TYPES or not f.is_file():
                    return self._err(404, "not found")
                return self._send(Response(200, f.read_bytes(), STATIC_TYPES[ext], {"Cache-Control": "no-cache"}))
            if SPA_ROUTE.match(path):  # client-side routes all serve the shell
                return self._send(Response(200, root.joinpath("index.html").read_bytes(), STATIC_TYPES[".html"]))
            if PORTAL_ROUTE.match(path) and app.portal_sessions is not None:
                return self._send(Response(200, root.joinpath("portal.html").read_bytes(), STATIC_TYPES[".html"]))
            if (not path.startswith("/api/") and "text/html" in (self.headers.get("Accept") or "")
                    and re.fullmatch(r"/[A-Za-z0-9_./:-]{0,200}", path) and ".." not in path):
                # a browser navigation to an unknown page: keep HTTP 404 but render the shell's friendly "Page not found"
                return self._send(Response(404, root.joinpath("index.html").read_bytes(), STATIC_TYPES[".html"]))
            return self._err(404, "not found")

        def do_GET(self):
            self._handle("GET")

        def do_HEAD(self):
            self._handle("HEAD")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

        do_PATCH = do_PUT

    return H
