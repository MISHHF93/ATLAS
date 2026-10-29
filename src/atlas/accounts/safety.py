"""Hard safety rules for what a user may connect. Not configurable.

* Paper / practice only: live trading endpoints, live account ids and live key prefixes are refused before anything is stored.
* A key that reports withdraw / transfer / live-trading permission is refused (``check_permissions``).
* Outbound calls from the server (connection tests) only go to fixed vendor hosts, or to a user-supplied host that passes
  ``assert_public_https`` (https, no private / loopback / link-local addresses, no redirects): this is the SSRF guard.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse

from atlas.risk.safety import LiveTradingForbidden

FORBIDDEN_PERMISSIONS = frozenset({
    "withdraw", "withdrawal", "withdrawals", "withdraw_funds", "transfer", "transfers", "internal_transfer", "universal_transfer",
    "live_trading", "trade_live", "live", "margin", "futures_live", "enable_withdrawals",
})
LIVE_HOST_FRAGMENTS = ("api.alpaca.markets", "api-fxtrade.oanda.com", "stream-fxtrade.oanda.com", "fxtrade")


class SafetyRefusal(LiveTradingForbidden):
    """Subclass of the platform-wide LiveTradingForbidden so callers that already catch it keep working."""


def check_permissions(perms: Iterable[str] | None) -> None:
    have = {str(p).strip().lower() for p in (perms or [])}
    bad = sorted((have & FORBIDDEN_PERMISSIONS) | {p for p in have if "withdraw" in p or "transfer" in p})
    if bad:
        raise SafetyRefusal(f"refused: this key has {', '.join(bad)} permission. ATLAS only accepts read-only / paper-only keys")


def refuse_live_strings(values: dict[str, str]) -> None:
    for k, v in values.items():
        low = (v or "").lower()
        if any(f in low for f in LIVE_HOST_FRAGMENTS):
            raise SafetyRefusal(f"refused: field {k!r} points at a live trading endpoint. Paper / practice only")
        if k.lower().endswith("env") and low in ("live", "production", "prod"):
            raise SafetyRefusal(f"refused: field {k!r} selects a live environment")


def _ip_ok(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_global and not (a.is_multicast or a.is_reserved or a.is_loopback or a.is_link_local or a.is_private)


def assert_public_https(url: str, resolve=socket.getaddrinfo) -> str:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise SafetyRefusal("refused: only plain https:// URLs without credentials are allowed")
    host = u.hostname
    try:
        if not _ip_ok(host):
            raise SafetyRefusal("refused: that address is private or reserved")
        return url
    except ValueError:
        pass  # a hostname, not an IP literal
    try:
        infos = resolve(host, u.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as ex:
        raise SafetyRefusal("refused: host does not resolve") from ex
    if not infos or not all(_ip_ok(i[4][0]) for i in infos):
        raise SafetyRefusal("refused: host resolves to a private or reserved address")
    return url


def is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"
