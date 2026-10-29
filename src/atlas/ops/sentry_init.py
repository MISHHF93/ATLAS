"""Sentry error reporting (Python side). A NO-OP unless ``SENTRY_DSN`` is set AND ``sentry-sdk`` is installed.

``pip install 'sentry-sdk'`` (or the ``atlas[sentry]`` extra). Defaults are conservative: no PII, no request bodies, no performance
tracing (``SENTRY_TRACES_SAMPLE_RATE`` opts in), and ``before_send`` strips cookies, auth headers, CSRF tokens and anything that looks
like a credential from every event so a session cookie or API key can never leave the box in an error report.
Only the Python processes (API + runner) report; the Next.js frontend is not instrumented.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping

_SENSITIVE = re.compile(r"(key|token|secret|password|passwd|dsn|cookie|authorization|csrf|session|webhook|signature|chat_id|topic|ping_url|invite|reset|verify)", re.I)
_REDACTED = "[redacted]"
_state: dict[str, Any] = {"initialised": False}


def scrub(obj: Any, depth: int = 0) -> Any:
    if depth > 8:
        return _REDACTED
    if isinstance(obj, dict):
        return {k: (_REDACTED if isinstance(k, str) and _SENSITIVE.search(k) else scrub(v, depth + 1)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, depth + 1) for v in obj]
    return obj


def before_send(event: dict, hint: dict | None = None) -> dict | None:
    req = event.get("request")
    if isinstance(req, dict):
        req.pop("cookies", None)
        req.pop("data", None)
        req.pop("query_string", None)  # reset / verify / invite tokens travel in URLs
        if isinstance(req.get("url"), str):
            req["url"] = req["url"].split("?", 1)[0]
        req["headers"] = scrub(req.get("headers") or {})
    event.pop("user", None)
    for k in ("extra", "contexts", "breadcrumbs", "tags"):
        if k in event:
            event[k] = scrub(event[k])
    return event


def init(env: Mapping[str, str] | None = None, transport: Any = None) -> dict[str, Any]:
    e = env if env is not None else os.environ
    dsn = (e.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return {"enabled": False, "reason": "SENTRY_DSN not set"}
    try:
        import sentry_sdk
    except ImportError:
        return {"enabled": False, "reason": "sentry-sdk not installed"}
    try:
        rate = min(1.0, max(0.0, float(e.get("SENTRY_TRACES_SAMPLE_RATE") or 0)))
    except ValueError:
        rate = 0.0
    kw: dict[str, Any] = dict(dsn=dsn, environment=(e.get("ATLAS_ENV") or "local").strip() or "local", max_request_body_size="never", traces_sample_rate=rate, before_send=before_send, server_name="atlas")
    if transport is not None:
        kw["transport"] = transport
    try:
        sentry_sdk.init(**kw)
    except Exception as ex:  # noqa: BLE001 - a bad DSN must not stop ATLAS from starting
        return {"enabled": False, "reason": f"init failed: {type(ex).__name__}"}
    _state["initialised"] = True
    return {"enabled": True, "traces_sample_rate": rate, "environment": kw["environment"]}


def init_from_env() -> dict[str, Any]:
    """Process entry points call this once; under pytest it refuses so a stray SENTRY_DSN can never report test noise."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return {"enabled": False, "reason": "disabled under pytest"}
    if _state["initialised"]:
        return {"enabled": True, "reason": "already initialised"}
    return init()
