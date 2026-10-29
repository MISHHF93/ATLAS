"""Deployment posture and client-address resolution, derived ONLY from server-side configuration (never from the Host header, which
an attacker controls).

* ``public_deployment()``: True when ``ATLAS_PUBLIC_URL`` is a non-loopback URL, ``ATLAS_TRUSTED_PROXIES`` is set (ATLAS sits behind a
  proxy) or ``ATLAS_ENV=production``. Drives the safe defaults: auth required, email verification required.
* ``ATLAS_REQUIRE_AUTH``: an explicit value always wins. Unset means "on for anything that is not plain localhost": a public deployment,
  a non-loopback client address, or a request that carries proxy headers (``X-Forwarded-For`` / ``Forwarded`` / ``X-Real-IP``) which
  betray a reverse proxy even when nobody configured one. A bare local install keeps working with no sign-in.
* ``client_ip``: the address the rate limiter keys on. ``X-Forwarded-For`` is honoured only when the connecting hop is in
  ``ATLAS_TRUSTED_PROXIES`` (comma separated IPs / CIDRs), walking the chain from the right and skipping trusted hops, so a client cannot
  mint fresh rate-limit buckets by forging the header.
"""
from __future__ import annotations

import ipaddress
import os
from typing import Callable, Mapping
from urllib.parse import urlsplit

_TRUE = ("1", "true", "on", "yes")
_FALSE = ("0", "false", "off", "no")
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host")


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def env_flag(name: str, env: Mapping[str, str] | None = None) -> bool | None:
    v = _env(env).get(name, "").strip().lower()
    return True if v in _TRUE else False if v in _FALSE else None


def is_loopback(ip: str) -> bool:
    if ip in ("localhost", ""):
        return ip == "localhost"
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return False


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.split("%")[0])
        return True
    except ValueError:
        return False


def parse_networks(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    out: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue  # a typo must not widen trust; the entry is ignored
    return out


def trusted_proxies(env: Mapping[str, str] | None = None) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return parse_networks(_env(env).get("ATLAS_TRUSTED_PROXIES", ""))


def _in(ip: str, nets) -> bool:
    try:
        a = ipaddress.ip_address(ip.strip().split("%")[0])
    except ValueError:
        return False
    return any(a in n for n in nets)


def public_deployment(env: Mapping[str, str] | None = None) -> bool:
    e = _env(env)
    if e.get("ATLAS_ENV", "").strip().lower() in ("prod", "production"):
        return True
    if e.get("ATLAS_TRUSTED_PROXIES", "").strip():
        return True
    url = e.get("ATLAS_PUBLIC_URL", "").strip()
    if url:
        host = (urlsplit(url if "://" in url else "//" + url).hostname or "").lower()
        if host and not is_loopback(host):
            return True
    return False


def public_https(env: Mapping[str, str] | None = None) -> bool:
    return _env(env).get("ATLAS_PUBLIC_URL", "").strip().lower().startswith("https://")


def resolve_client_ip(peer: str, get_header: Callable[[str], str], env: Mapping[str, str] | None = None) -> str:
    """``peer`` is the TCP peer ATLAS sees; ``get_header`` returns a lowercase header's value or ''."""
    nets = trusted_proxies(env)
    hop = peer
    bridged = get_header("x-atlas-client-ip")  # set by frontend/server.mjs from the real socket; trusted only from the loopback bridge
    if bridged and is_loopback(peer):
        hop = bridged[:64]
    if not nets or not _in(hop, nets):
        return hop
    xff = [p.strip() for p in get_header("x-forwarded-for").split(",") if p.strip()]
    for entry in reversed(xff):
        try:
            ipaddress.ip_address(entry.split("%")[0])
        except ValueError:
            return hop  # malformed hop: stop trusting the chain, key on the last trusted hop
        if not _in(entry, nets):
            return entry[:64]
        hop = entry
    return hop


def has_proxy_headers(get_header: Callable[[str], str]) -> bool:
    return any(get_header(h) for h in PROXY_HEADERS)


def require_auth(client: str = "", get_header: Callable[[str], str] | None = None, env: Mapping[str, str] | None = None) -> bool:
    """Is a valid session required for /api routes?  Explicit ATLAS_REQUIRE_AUTH wins; otherwise on for anything but plain localhost."""
    flag = env_flag("ATLAS_REQUIRE_AUTH", env)
    if flag is not None:
        return flag
    if public_deployment(env):
        return True
    if client and is_ip(client) and not is_loopback(client):  # a non-IP peer (unix socket, in-process test client) is not a network client
        return True
    return bool(get_header and has_proxy_headers(get_header))


def require_email_verification(env: Mapping[str, str] | None = None) -> bool:
    flag = env_flag("ATLAS_REQUIRE_EMAIL_VERIFICATION", env)
    return public_deployment(env) if flag is None else flag
