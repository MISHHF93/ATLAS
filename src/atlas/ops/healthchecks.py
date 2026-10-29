"""Healthchecks.io dead-man ping. A NO-OP unless ``HEALTHCHECKS_PING_URL`` is set (environment or the local .env).

The core loop calls ``beat()`` after every successful safety step and ``fail()`` when the safety step is blocked. Healthchecks.io alerts
you when the pings STOP (process dead, host asleep, loop wedged) or when ``/fail`` arrives, which is the silent-stall case nothing
else notices.

Safety properties:
* Never blocks the safety loop: the HTTP call runs on a daemon thread with a short timeout and at most one ping is in flight.
* Never raises, never logs the ping URL (it contains the check's secret UUID).
* Throttled (``HEALTHCHECKS_INTERVAL_S``, default 60 s, minimum 10 s) so a fast loop does not hammer the service.
* Only http(s) URLs are accepted; nothing is sent under pytest unless a ``post`` callable is injected.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

TIMEOUT_S = 4.0
_lock = threading.Lock()
_last: dict[str, float] = {}
_inflight = False


def _ping_url(env: Mapping[str, str] | None = None, env_file: str | Path = ".env") -> str:
    e = env if env is not None else os.environ
    url = (e.get("HEALTHCHECKS_PING_URL") or "").strip()
    if not url and env is None:
        try:
            from atlas.control.policy.loader import parse_env_file
            url = (parse_env_file(Path(env_file)).get("HEALTHCHECKS_PING_URL") or "").strip()
        except Exception:  # noqa: BLE001
            url = ""
    parts = urlsplit(url)
    return url.rstrip("/") if parts.scheme in ("http", "https") and parts.netloc else ""


def configured(env: Mapping[str, str] | None = None) -> bool:
    return bool(_ping_url(env))


def _get(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-healthcheck"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - owner-configured URL
        return r.status


def ping(kind: str = "", env: Mapping[str, str] | None = None, post: Callable[[str], int] | None = None, sync: bool = False,
         now: float | None = None, force: bool = False) -> dict:
    """``kind``: '' (success heartbeat), 'start' or 'fail'. Returns what happened (never the URL)."""
    global _inflight
    if kind not in ("", "start", "fail"):
        return {"sent": False, "reason": "unknown kind"}
    base = _ping_url(env)
    if not base:
        return {"sent": False, "reason": "not configured"}
    if post is None and "PYTEST_CURRENT_TEST" in os.environ:
        return {"sent": False, "reason": "never sends under pytest"}
    t = time.monotonic() if now is None else now
    e = env if env is not None else os.environ
    try:
        gap = max(10.0, float(e.get("HEALTHCHECKS_INTERVAL_S") or 60))
    except ValueError:
        gap = 60.0
    url = base + (f"/{kind}" if kind else "")
    with _lock:
        if not force and kind != "fail" and t - _last.get(kind, -1e12) < gap:
            return {"sent": False, "reason": "throttled"}
        if _inflight and not sync:
            return {"sent": False, "reason": "ping in flight"}
        _last[kind] = t
        _inflight = not sync

    def run() -> int | None:
        global _inflight
        try:
            return (post or _get)(url)
        except Exception:  # noqa: BLE001 - monitoring must never hurt the loop
            return None
        finally:
            with _lock:
                _inflight = False

    if sync:
        code = run()
        return {"sent": code is not None and 200 <= code < 300, "http_status": code}
    threading.Thread(target=run, name="healthchecks-ping", daemon=True).start()
    return {"sent": True, "async": True}


def beat(**kw) -> dict:
    return ping("", **kw)


def fail(**kw) -> dict:
    return ping("fail", **kw)


def reset_for_tests() -> None:
    global _inflight
    with _lock:
        _last.clear()
        _inflight = False
