"""MCP-style tool registry (list_tools / list_resources / call_tool) over the /api/ext read-only surfaces.

Exposed over HTTP at /api/ext/mcp/* and over stdio JSON-RPC 2.0 by scripts/atlas_mcp_stdio.py (methods initialize,
tools/list, tools/call, resources/list). Only research tools are registered; there is no order tool here: paper orders
go through /api/ext/alpaca/orders and the control plane."""
from __future__ import annotations

from typing import Any, Callable


def _api():
    from atlas.api import ext_api
    return ext_api


def _s(desc, **props):
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "description": desc}


TOOLS: dict[str, tuple[str, dict, Callable[..., Any]]] = {
    "options_greeks": ("Black-Scholes price + greeks", _s("", spot="number", strike="number", tte_years="number", vol="number", r="number", right="string"),
                       lambda **a: _api().greeks(**a)),
    "implied_vol": ("Implied volatility from an option price", _s("", price="number", spot="number", strike="number", tte_years="number", right="string"),
                    lambda **a: _api().iv(**a)),
    "value_at_risk": ("Historical + parametric VaR/CVaR from ATLAS bars", _s("", symbol="string", tf="string"), lambda **a: _api().var_ep(**a)),
    "fundamentals": ("SEC EDGAR companyfacts, point-in-time normalised", _s("", ticker="string", as_of="string"), lambda **a: _api().fundamentals_ep(**a)),
    "volume_profile": ("Session/anchored VWAP + POC/value area", _s("", symbol="string", tf="string"), lambda **a: _api().vwap_ep(**a)),
    "sr_zones": ("Support/resistance zones from swing touches", _s("", symbol="string", tf="string"), lambda **a: _api().sr_ep(**a)),
    "watchlist_scan": ("Pivot/fib/zone breach scan", _s("", symbols="string", tf="string"), lambda **a: _api().scan_ep(**a)),
    "pine_export": ("Pine v5 export + ATLAS backtest stats", _s("", sid="string", symbol="string", tf="string"), lambda **a: _api().pine_gen(**a)),
    "dossier": ("Deterministic dossier + conviction 1–100", _s("", symbol="string", tf="string"), lambda **a: _api().dossier_ep(**a)),
    "agent_pipeline": ("Analysts → debate → trader → control-plane dry run", _s("", symbol="string", tf="string"), lambda **a: _api().pipeline_ep(**a)),
    "broker_status": ("Alpaca paper configuration status", _s(""), lambda **a: _api().alpaca_status()),
}

RESOURCES = [
    {"uri": "atlas://ext/pine", "name": "Pine v5 strategies", "mimeType": "application/json"},
    {"uri": "atlas://ext/alerts/status", "name": "Alert dispatcher status", "mimeType": "application/json"},
    {"uri": "atlas://ext/alpaca/status", "name": "Alpaca paper status", "mimeType": "application/json"},
]
_READ = {"atlas://ext/pine": lambda: _api().pine_list(), "atlas://ext/alerts/status": lambda: _api().alerts_status(),
         "atlas://ext/alpaca/status": lambda: _api().alpaca_status()}


def list_tools() -> list[dict[str, Any]]:
    return [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()]


def list_resources() -> list[dict[str, Any]]:
    return RESOURCES


def read_resource(uri: str) -> dict[str, Any]:
    if uri not in _READ:
        return {"isError": True, "error": "unknown resource"}
    return {"uri": uri, "contents": _READ[uri]()}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        return {"isError": True, "error": f"unknown tool {name}"}
    allowed = set(TOOLS[name][1]["properties"])
    bad = set(arguments) - allowed
    if bad:
        return {"isError": True, "error": f"unexpected arguments {sorted(bad)}"}
    try:
        return {"isError": False, "content": TOOLS[name][2](**arguments)}
    except Exception as e:  # HTTPException / ValueError
        return {"isError": True, "error": getattr(e, "detail", None) or str(e)}


def handle(req: dict[str, Any]) -> dict[str, Any] | None:
    """JSON-RPC 2.0 dispatch for the stdio server."""
    m, p, rid = req.get("method"), req.get("params") or {}, req.get("id")
    if m == "initialize":
        r = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "atlas-ext", "version": "1"}, "capabilities": {"tools": {}, "resources": {}}}
    elif m == "tools/list":
        r = {"tools": list_tools()}
    elif m == "tools/call":
        out = call_tool(p.get("name", ""), p.get("arguments") or {})
        import json
        r = {"content": [{"type": "text", "text": json.dumps(out.get("content", out.get("error")), default=str)}], "isError": out["isError"]}
    elif m == "resources/list":
        r = {"resources": list_resources()}
    elif m == "resources/read":
        import json
        r = {"contents": [{"uri": p.get("uri"), "mimeType": "application/json", "text": json.dumps(read_resource(p.get("uri", "")), default=str)}]}
    elif rid is None:
        return None
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}
    return None if rid is None else {"jsonrpc": "2.0", "id": rid, "result": r}
