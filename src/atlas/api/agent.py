"""Key-protected agent surfaces: paper setup autopilot controls and a localhost MCP (JSON-RPC over HTTP) endpoint.

Every route here needs an ATLAS API key (``Authorization: Bearer atk_...`` or ``X-Atlas-Key``); see
docs/api-and-mcp.md. MCP tools are read-only (``execution_permission: none``). Nothing here can place a live
order, approve the autopilot (owner CLI with step-up only), reset the Safe stop, or move money.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from atlas.keys.api_keys import ApiKeyStore, KeyError_, bearer

agent_router = APIRouter(tags=["agent"])
EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "docs" / "spec" / "evidence"
_KEYS: ApiKeyStore | None = None
_AP: Any = None
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def keys() -> ApiKeyStore:
    global _KEYS
    if _KEYS is None:
        _KEYS = ApiKeyStore()
    return _KEYS


def _auth(request: Request, scope: str) -> dict[str, Any]:
    try:
        return keys().verify(bearer(request.headers), scope)
    except KeyError_ as e:
        raise HTTPException(status_code=e.status, detail=e.code) from e


def _local(request: Request) -> None:
    host = (request.headers.get("host") or "").rsplit(":", 1)[0] if "]" not in (request.headers.get("host") or "") \
        else (request.headers.get("host") or "").split("]")[0] + "]"
    origin = request.headers.get("origin")
    client = request.client.host if request.client else "127.0.0.1"
    ok_origin = origin is None or any(origin.startswith(f"http://{h}") for h in LOCAL_HOSTS)
    if host not in LOCAL_HOSTS or not ok_origin or client not in LOCAL_HOSTS | {"testclient"}:
        raise HTTPException(status_code=403, detail="localhost_only")


# ---- paper setup autopilot ------------------------------------------------------------------------------
def autopilot():
    global _AP
    if _AP is None:
        from atlas.autopilot.setups import SetupAutopilot, Stream
        from atlas.control.founder_track import founder_policy_dir
        from atlas.features.price_action import bars_from_rows
        from atlas.models.shadow import ShadowCollector
        from atlas.risk.safe_stop import shared_safe_stop
        from atlas.api.quant import _visible

        def feed(sym: str, tf: int):
            return bars_from_rows(_visible(sym, str(tf // 60))[0], tf)

        streams = []
        for part in os.environ.get("ATLAS_SETUP_AUTOPILOT_STREAMS", "SPY:60:us_equity_rth").split(","):
            bits = part.strip().split(":")
            if bits and bits[0]:
                streams.append(Stream(bits[0].upper(), int(bits[1] if len(bits) > 1 else 60) * 60, bits[2] if len(bits) > 2 else None))
        try:
            from atlas.control.policy import load_all
            owner = load_all(founder_policy_dir()).risk.owner
        except Exception:  # noqa: BLE001
            owner = "owner"
        state = os.environ.get("ATLAS_STATE_DB", "var/state.sqlite")
        audit = os.environ.get("ATLAS_AUDIT_DB", "var/audit.sqlite")
        for p in (state, audit):
            if p != ":memory:":
                Path(p).parent.mkdir(parents=True, exist_ok=True)
        _AP = SetupAutopilot(feed, streams, state_db=state, audit_db=audit, safe_stop=shared_safe_stop(),
                             shadow=ShadowCollector(), expected_owner=owner)
    return _AP


def _kick(ap) -> None:
    if ap.is_on():
        ap.start_background(float(os.environ.get("ATLAS_SETUP_AUTOPILOT_INTERVAL_S", "60")))


class OnRequest(BaseModel):
    note: str = Field(default="", max_length=200)


class OffRequest(BaseModel):
    reason: str = Field(default="switched_off", max_length=200)


@agent_router.get("/api/quant/autopilot")
def autopilot_status(request: Request) -> dict[str, Any]:
    _auth(request, "read")
    ap = autopilot(); _kick(ap)
    return ap.status()


@agent_router.post("/api/quant/autopilot/request-on")
def autopilot_request_on(body: OnRequest, request: Request) -> dict[str, Any]:
    k = _auth(request, "paper-trade")
    req = autopilot().request_on(f"key:{k['key_id']}", body.note, channel="api")
    return {**req, "approve_with": f"atlas-owner setup-autopilot-approve {req['id']}  (owner passphrase + TOTP)"}


@agent_router.post("/api/quant/autopilot/off")
def autopilot_off(body: OffRequest, request: Request) -> dict[str, Any]:
    k = _auth(request, "read")   # stopping must always be easy
    return autopilot().switch_off(f"key:{k['key_id']}", body.reason)


@agent_router.post("/api/quant/autopilot/tick")
def autopilot_tick(request: Request) -> dict[str, Any]:
    _auth(request, "paper-trade")
    ap = autopilot()
    out = ap.tick(); _kick(ap)
    return out


@agent_router.get("/api/quant/shadow")
def shadow_weeks(request: Request) -> dict[str, Any]:
    _auth(request, "read")
    from atlas.models.shadow import ShadowCollector
    return {"weeks": ShadowCollector().weekly(), "rule": "conservative_ohlc_v1", "execution_permission": "none"}


# ---- MCP ------------------------------------------------------------------------------------------------
def _sym_schema(extra: dict | None = None) -> dict[str, Any]:
    props = {"symbol": {"type": "string"}, "resolution": {"type": "string", "default": "60"},
             "session": {"type": ["string", "null"], "default": None}}
    return {"type": "object", "properties": {**props, **(extra or {})}, "required": ["symbol"]}


def _t_zones(a):
    from atlas.api.quant import quant_zones
    return quant_zones(a["symbol"], str(a.get("resolution", "60")), a.get("session"))


def _t_setups(a):
    from atlas.api.quant import _desk
    out = _desk(a["symbol"], str(a.get("resolution", "60")), a.get("session"))
    out.pop("bars", None)
    return out


def _t_predict(a):
    from atlas.api.quant import _desk
    out = _desk(a["symbol"], str(a.get("resolution", "60")), a.get("session"))
    return {"instrument": out.get("instrument"), "evaluations": out.get("evaluations", []), "proposals": out.get("proposals", []),
            "feed_origin": out.get("feed_origin"), "execution_permission": "none"}


def _t_replay(a):
    from atlas.api.quant import quant_replay
    out = quant_replay(a["symbol"], str(a.get("resolution", "60")), a.get("session"),
                       float(a.get("cost_per_unit", 0.0)), int(a.get("max_hold_bars", 8)))
    out["trades"] = out["trades"][-50:]
    return out


def _t_evidence(a):
    files = sorted(EVIDENCE_DIR.glob("*.json"))
    name = a.get("name")
    if not name:
        return {"files": [f.name for f in files], "execution_permission": "none"}
    f = next((f for f in files if f.name == name), None)
    if f is None:
        raise ValueError("unknown evidence file")
    d = json.loads(f.read_text())
    return {"name": f.name, "generated_at": d.get("generated_at"), "method": d.get("method"), "pbo": d.get("pbo"),
            "n_trials": d.get("n_trials"), "configs": d.get("configs"), "execution_permission": "none"}


def _t_safe_stop(a):
    from atlas.risk.safe_stop import shared_safe_stop
    ks = shared_safe_stop()
    out = {"engaged": ks.engaged, "reason": ks.reason, "engaged_at": ks.engaged_at, "execution_permission": "none"}
    try:
        out["paper_autopilot"] = {k: v for k, v in autopilot().status().items() if k in ("on", "risk", "mode")}
    except Exception:  # noqa: BLE001
        pass
    return out


TOOLS: dict[str, tuple[str, str, dict[str, Any], Callable[[dict], Any]]] = {
    "zones": ("read", "Price-action zones on confirmed bars for a symbol.", _sym_schema(), _t_zones),
    "setups": ("read", "Zones, setup candidates and their predict()/EV evaluation (abstains without a validated model).",
               _sym_schema(), _t_setups),
    "predict": ("read", "predict() + EV-gate evaluation for current candidates; abstention reasons included.",
                _sym_schema(), _t_predict),
    "replay": ("research", "Conservative OHLC paper replay (descriptive, not a performance estimate).",
               _sym_schema({"cost_per_unit": {"type": "number", "default": 0}, "max_hold_bars": {"type": "integer", "default": 8}}),
               _t_replay),
    "evidence": ("research", "List or read committed evidence reports (docs/spec/evidence).",
                 {"type": "object", "properties": {"name": {"type": "string"}}}, _t_evidence),
    "safe_stop_status": ("read", "Founder Safe stop state and paper-autopilot risk room.",
                         {"type": "object", "properties": {}}, _t_safe_stop),
}
PROTOCOL = "2025-06-18"


def _rpc(id_: Any, result: Any = None, error: tuple[int, str] | None = None) -> dict[str, Any]:
    if error:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": error[0], "message": error[1]}}
    return {"jsonrpc": "2.0", "id": id_, "result": result}


@agent_router.post("/api/mcp")
async def mcp(request: Request):
    _local(request)
    key = _auth(request, "read")
    try:
        msg = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_rpc(None, error=(-32700, "parse error")))
    if not isinstance(msg, dict):
        return JSONResponse(_rpc(None, error=(-32600, "batch requests are not supported")))
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:   # notification (e.g. notifications/initialized)
        return JSONResponse(None, status_code=202)
    if method == "initialize":
        return JSONResponse(_rpc(mid, {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                                       "capabilities": {"tools": {"listChanged": False}},
                                       "serverInfo": {"name": "atlas-readonly", "version": "1.0.0"},
                                       "instructions": "Read-only research tools. execution_permission: none."}))
    if method == "ping":
        return JSONResponse(_rpc(mid, {}))
    if method == "tools/list":
        from atlas.keys.api_keys import scope_allows
        return JSONResponse(_rpc(mid, {"tools": [
            {"name": n, "description": d, "inputSchema": s, "annotations": {"readOnlyHint": True}}
            for n, (sc, d, s, _) in TOOLS.items() if scope_allows(key["scope"], sc)]}))
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return JSONResponse(_rpc(mid, error=(-32602, f"unknown tool {name}")))
        scope, _, schema, fn = TOOLS[name]
        _auth(request, scope)
        if "symbol" in schema.get("required", []) and not isinstance(args.get("symbol"), str):
            return JSONResponse(_rpc(mid, error=(-32602, "symbol is required")))
        try:
            data = fn(args)
            err = False
        except HTTPException as e:
            data, err = {"error": e.detail}, True
        except (ValueError, KeyError, TypeError) as e:
            data, err = {"error": str(e)[:300]}, True
        text = json.dumps(data, default=str)
        return JSONResponse(_rpc(mid, {"content": [{"type": "text", "text": text}], "isError": err,
                                       "structuredContent": json.loads(text) if isinstance(data, dict) else {"value": data}}))
    return JSONResponse(_rpc(mid, error=(-32601, f"method not found: {method}")))


@agent_router.get("/api/mcp")
def mcp_get() -> JSONResponse:
    return JSONResponse({"detail": "POST JSON-RPC to this endpoint; server-initiated streams are not offered"}, status_code=405)
