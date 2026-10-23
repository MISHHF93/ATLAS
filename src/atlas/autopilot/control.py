"""Autopilot switch, shared by the core loop, the console, the owner CLI and the MCP server (state DB keys only;
no heavy imports). Start requires the caller to have verified owner step-up; stop never requires anything."""
from __future__ import annotations

import secrets
import time
from typing import Any

CONTROL = "autopilot.control"         # written by owner/console/MCP: {"desired": "on"|"off", ...}
STATE = "autopilot.state"             # written by the core loop only
REQUESTS = "autopilot.start_requests"  # MCP-originated start requests awaiting owner step-up
REQUEST_TTL_S = 900


class StepUpRequired(PermissionError):
    pass


def request_start(store, audit, actor: str, step_up_verified: bool, channel: str = "console") -> dict[str, Any]:
    if not step_up_verified:
        audit.append("autopilot.start_refused", {"actor": actor, "channel": channel, "reason": "step-up required"}, actor=actor)
        raise StepUpRequired("starting the autopilot requires owner step-up (passphrase + authenticator code)")
    c = {"desired": "on", "by": actor, "channel": channel, "at": time.time()}
    store.set(CONTROL, c)
    audit.append("autopilot.start_requested", {"channel": channel}, actor=actor)
    return {"desired": "on", "note": "the core loop starts the autopilot on its next heartbeat"}


def request_stop(store, audit, actor: str, reason: str = "", channel: str = "console") -> dict[str, Any]:
    """Instant: the core checks this flag every safety tick and before routing each order."""
    store.set(CONTROL, {"desired": "off", "by": actor, "channel": channel, "at": time.time(), "reason": (reason or "stopped")[:200]})
    audit.append("autopilot.stop_requested", {"channel": channel, "reason": (reason or "")[:200]}, actor=actor)
    return {"desired": "off", "stopped": True}


def desired(store) -> str:
    return (store.get(CONTROL) or {}).get("desired", "off")


def mcp_start_request(store, audit, client: str, note: str = "") -> dict[str, Any]:
    """MCP cannot start the autopilot: it files a request the owner approves in the console with step-up."""
    now = time.time()
    rid = "apr-" + secrets.token_hex(4)
    req = {"id": rid, "client": client[:60], "note": note[:200], "at": now, "expires": now + REQUEST_TTL_S}
    store.update(REQUESTS, lambda old: [r for r in (old or []) if r["expires"] > now][-9:] + [req], [])
    audit.append("autopilot.mcp_start_request", {"id": rid, "client": client[:60]}, actor="mcp")
    return req


def pending_requests(store) -> list[dict]:
    now = time.time()
    return [r for r in (store.get(REQUESTS) or []) if r["expires"] > now]


def resolve_request(store, rid: str) -> dict | None:
    hit: list = []
    store.update(REQUESTS, lambda old: [r for r in (old or []) if not (r["id"] == rid and not hit.append(r))], [])
    return hit[0] if hit else None


def status_view(store) -> dict[str, Any]:
    """What the console/MCP show: the core's state, overridden by a newer stop so 'Stop' is visibly instant."""
    st = dict(store.get(STATE) or {"state": "off"})
    c = store.get(CONTROL) or {"desired": "off"}
    st["desired"] = c.get("desired", "off")
    if c.get("desired") == "off" and st.get("state") not in ("off", None):
        st["state"] = "stopping"
    if c.get("desired") == "on" and st.get("state") in ("off", None):
        st["state"] = "starting"
    st["control"] = {k: c.get(k) for k in ("by", "channel", "at", "reason")}
    st["pending_start_requests"] = pending_requests(store)
    if st.get("started_at") and st.get("state") in ("running", "paused", "waiting"):
        st["uptime_s"] = max(0.0, time.time() - float(st["started_at"]))
    return st
