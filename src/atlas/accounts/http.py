"""One tiny outbound HTTP helper for connection tests: no redirects, short timeout, bounded body, injectable for tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx


@dataclass
class HttpResult:
    status: int
    json: Any = None
    text: str = ""


HttpFn = Callable[..., HttpResult]


def fetch(method: str, url: str, *, headers: dict[str, str] | None = None, params: dict[str, str] | None = None,
          json_body: Any = None, timeout: float = 10.0) -> HttpResult:
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "ATLAS-connection-test/1.0"}) as c:
        r = c.request(method, url, headers=headers, params=params, json=json_body)
    body = r.content[:200_000]
    try:
        js = httpx.Response(r.status_code, content=body).json()
    except Exception:  # noqa: BLE001
        js = None
    return HttpResult(r.status_code, js, body[:2000].decode("utf-8", "replace"))
