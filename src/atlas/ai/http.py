"""HTTP boundary of the AI node: ``/api/ai/*`` router + one guard middleware."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from atlas.ai.node import AI_GUARDED_PREFIXES, AI_NAMESPACES, EXECUTION_PERMISSION, NODE, component, component_status, enforce_advisory, read_audit

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("")
@router.get("/status")
def ai_status() -> dict[str, Any]:
    return NODE.status()


@router.get("/components")
def ai_components() -> dict[str, Any]:
    return {"components": NODE.components(), "execution_permission": EXECUTION_PERMISSION}


@router.get("/components/{name}")
def ai_component(name: str) -> dict[str, Any]:
    try:
        return component_status(component(name))
    except KeyError:
        raise HTTPException(404, f"unknown AI component {name}") from None


@router.get("/helpers")
def ai_helpers(component: str | None = None, family: str | None = None) -> dict[str, Any]:
    """Same-named ML helper variants, what each does, and which components/pipelines use it."""
    from atlas.ai.helpers_registry import HELPERS, as_dict, families

    rows = [as_dict(h) for h in HELPERS
            if (component is None or component in h.used_by_components) and (family is None or h.family == family)]
    return {"helpers": rows, "families": families(), "execution_permission": EXECUTION_PERMISSION}


@router.get("/audit")
def ai_audit(limit: int = 100) -> dict[str, Any]:
    return {"events": read_audit(max(1, min(limit, 1000))), "execution_permission": EXECUTION_PERMISSION}


def _ns(path: str) -> str | None:
    for ns in AI_NAMESPACES:
        if path == f"/api/{ns}" or path.startswith(f"/api/{ns}/"):
            return ns
    for pre in AI_GUARDED_PREFIXES:
        if path == pre or path.startswith(pre + "/"):
            return "ext"
    return None


class AINodeMiddleware:
    """Aliases ``/api/ai/<ns>/...`` onto ``/api/<ns>/...`` and guards JSON output
    of every AI namespace (old and new paths) through :func:`enforce_advisory`."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        for ns in AI_NAMESPACES:
            pre = f"/api/ai/{ns}"
            if path == pre or path.startswith(pre + "/"):
                path = f"/api/{ns}" + path[len(pre):]
                scope = dict(scope, path=path, raw_path=path.encode())
                break
        ns = _ns(path)
        if ns is None:
            return await self.app(scope, receive, send)

        start: dict | None = None
        body = bytearray()
        passthrough = False

        async def wrapped(msg):
            nonlocal start, passthrough
            if msg["type"] == "http.response.start":
                ctype = dict((k.lower(), v) for k, v in msg.get("headers", [])).get(b"content-type", b"")
                if b"application/json" not in ctype:
                    passthrough = True
                    return await send(msg)
                start = msg
                return
            if passthrough:
                return await send(msg)
            body.extend(msg.get("body", b""))
            if msg.get("more_body"):
                return
            data = bytes(body)
            try:
                clean, n = enforce_advisory(json.loads(data), source=path)
                if n:
                    data = json.dumps(clean).encode()
            except ValueError:
                pass
            headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
            headers.append((b"content-length", str(len(data)).encode()))
            await send(dict(start, headers=headers))
            await send({"type": "http.response.body", "body": data})

        return await self.app(scope, receive, wrapped)
