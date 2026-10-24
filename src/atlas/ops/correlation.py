"""Correlation IDs + structured (JSON-line) request logs. No secrets, query strings or bodies are logged."""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("atlas_correlation_id", default="-")
log = logging.getLogger("atlas.request")
HEADER = "x-correlation-id"


def current() -> str:
    return correlation_id.get()


def log_event(event: str, **fields) -> None:
    log.info(json.dumps({"event": event, "correlation_id": current(), "ts": time.time(), **fields}, default=str))


def install(app) -> None:
    @app.middleware("http")
    async def _cid(request, call_next):
        raw = request.headers.get(HEADER, "")
        cid = raw if 0 < len(raw) <= 64 and raw.replace("-", "").isalnum() else uuid.uuid4().hex
        tok = correlation_id.set(cid)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
            resp.headers[HEADER] = cid
            log_event("http_request", method=request.method, path=request.url.path, status=resp.status_code,
                      ms=round((time.perf_counter() - t0) * 1000, 2))
            return resp
        finally:
            correlation_id.reset(tok)


from contextlib import contextmanager as _cm


@_cm
def bind(cid: str | None = None):
    """Bind a correlation id for a non-HTTP flow (replay journey, autopilot tick). Yields the id."""
    cid = cid or uuid.uuid4().hex[:16]
    tok = correlation_id.set(cid)
    try:
        yield cid
    finally:
        correlation_id.reset(tok)
