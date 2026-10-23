"""Provider plumbing. Network is OFF by default: adapters use OfflineTransport
(raises) unless an explicit transport is injected. Tests inject fixtures."""
from __future__ import annotations

import json
from typing import Any, Protocol


class ProviderDisabled(RuntimeError):
    pass


class Transport(Protocol):
    def get_json(self, url: str, params: dict[str, Any]) -> Any: ...


class OfflineTransport:
    def get_json(self, url: str, params: dict[str, Any]) -> Any:
        raise ProviderDisabled(f"network disabled (offline transport): {url}")


class FixtureTransport:
    """Maps URL path suffix -> JSON payload (for tests/offline replay)."""

    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, url: str, params: dict[str, Any]) -> Any:
        self.calls.append((url, dict(params)))
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return json.loads(payload) if isinstance(payload, str) else payload
        raise KeyError(f"no fixture for {url}")


class UrllibTransport:  # pragma: no cover - never used in tests; data APIs only, never brokers
    def __init__(self, allow_network: bool = False, timeout_s: float = 10):
        if not allow_network:
            raise ProviderDisabled("UrllibTransport requires allow_network=True (explicit opt-in)")
        self.timeout_s = timeout_s

    def get_json(self, url: str, params: dict[str, Any]) -> Any:
        import urllib.parse
        import urllib.request
        with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=self.timeout_s) as r:
            return json.loads(r.read())


def require_real_key(key: str | None, name: str) -> str:
    if not key or key.startswith("<") or "placeholder" in key.lower():
        raise ProviderDisabled(f"{name}: API key missing or placeholder")
    return key
