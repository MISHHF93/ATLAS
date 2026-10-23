"""atlas-owner: owner-only operations from a local terminal.

Commands needing step-up (passphrase + TOTP): approve, reset, kill --flatten, mcp-token create/revoke.
Engaging the kill switch (without flatten) never needs step-up: halting must always be easy.
State is shared with the core process through the SQLite state DB; the core
executes owner-approved orders / flatten requests on its next heartbeat."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime, timezone
from typing import Callable

from atlas.governance.audit import AuditLog
from atlas.control.policy import load_all
from atlas.risk.approvals import ApprovalQueue
from atlas.risk.killswitch import KillSwitch
from atlas.risk.state_store import StateStore
from atlas.risk.stepup import StepUp
from atlas.risk.safety import assert_paper_only


def _default_prompt() -> tuple[str, str]:
    return getpass.getpass("Owner passphrase: "), input("TOTP code: ").strip()


def run(argv: list[str], prompt: Callable[[], tuple[str, str]] = _default_prompt, out=print) -> int:
    assert_paper_only()
    ap = argparse.ArgumentParser(prog="atlas-owner")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--state", default="var/state.sqlite")
    ap.add_argument("--audit", default="var/audit.sqlite")
    ap.add_argument("--stepup", default="var/owner_stepup.json")
    ap.add_argument("--tokens", default="var/mcp_tokens.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-stepup")
    sub.add_parser("status")
    sub.add_parser("approvals")
    for c in ("approve", "reject"):
        sub.add_parser(c).add_argument("approval_id")
    k = sub.add_parser("kill"); k.add_argument("--reason", required=True); k.add_argument("--flatten", action="store_true")
    sub.add_parser("reset")
    t = sub.add_parser("mcp-token"); t.add_argument("action", choices=["create", "revoke"]); t.add_argument("client")
    t.add_argument("--scopes", default="read"); t.add_argument("--ttl-days", type=float, default=30)
    mp = sub.add_parser("model-promote"); mp.add_argument("model_id"); mp.add_argument("--registry", default="var/models")
    sap = sub.add_parser("setup-autopilot-approve"); sap.add_argument("request_id")
    mr = sub.add_parser("model-rollback"); mr.add_argument("--registry", default="var/models")
    a = ap.parse_args(argv)

    cfg = load_all(a.config)
    owner = cfg.risk.owner
    from pathlib import Path
    for p in (a.state, a.audit):
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
    store, audit = StateStore(a.state), AuditLog(a.audit)
    ks = KillSwitch(audit, store=store)
    q = ApprovalQueue(cfg.risk.autonomy.approval_ttl_seconds, owner, audit, store=store)
    su = StepUp(a.stepup)

    def step_up() -> bool:
        pw, code = prompt()
        ok = su.verify(owner, pw, code)
        audit.append("owner.step_up", {"ok": ok, "cmd": a.cmd}, actor=owner)
        if not ok:
            out("step-up FAILED")
        return ok

    if a.cmd == "init-stepup":
        pw, confirm = prompt()
        if pw != confirm:
            out("passphrases differ"); return 2
        secret = su.init(pw, owner)
        out(f"Step-up initialised in {a.stepup}. Add this TOTP secret to your authenticator (shown once): {secret}")
        return 0
    if a.cmd == "status":
        out(json.dumps({"kill_switch": ks.engaged, "reason": ks.reason, "pending_approvals": len(q.pending()),
                        "session": store.get("session_date"), "daily_halt": store.get("daily_halt_session")}, indent=2))
        return 0
    if a.cmd == "approvals":
        for p in q.pending():
            i = p.intent
            left = p.expires - datetime.now(timezone.utc).timestamp()
            out(f"{p.approval_id}  {i.side} {i.qty} {i.symbol} {i.order_type} ref={i.reference_price} sleeve={i.sleeve} "
                f"broker={i.broker}  expires_in={left:.0f}s")
        return 0
    if a.cmd == "reject":
        q.reject(a.approval_id, owner); out("rejected"); return 0
    if a.cmd == "kill":
        if a.flatten:
            if not step_up():
                ks.engage(a.reason + " (flatten denied: step-up failed)", channel="cli")
                return 3
            store.set("flatten_request", {"reason": a.reason, "channel": "cli"})
        r = ks.engage(a.reason, channel="cli")
        out(f"KILL SWITCH ENGAGED: {r['reason']}" + (" (flatten queued for core)" if a.flatten else ""))
        return 0
    if not step_up():
        return 3
    if a.cmd == "approve":
        q.mark_owner_approved(a.approval_id, owner, True)
        out("approved; the core will re-check risk and execute on its next heartbeat"); return 0
    if a.cmd == "setup-autopilot-approve":
        from atlas.control.setup_autopilot_approval import approve_request
        try:
            approve_request(store, audit, a.request_id, owner, True, owner, ks.engaged)
        except (LookupError, PermissionError) as e:
            out(f"DENIED: {e}"); return 4
        out("paper setup autopilot switched ON (paper only; stop any time)"); return 0
    if a.cmd == "reset":
        ks.reset(owner, True, owner); out("kill switch reset"); return 0
    if a.cmd in ("model-promote", "model-rollback"):
        from atlas.models.quant.registry import ModelRegistry, PromotionDenied
        reg = ModelRegistry(a.registry, audit=audit)
        try:
            if a.cmd == "model-promote":
                gates = reg.promote(a.model_id, cfg.risk.ai_controls.model_promotion, "owner", cfg.risk.autonomy.level, True)
                out("promoted to champion; gates: " + ", ".join(f"{g.name}={g.value}" for g in gates))
            else:
                out(f"rolled back to {reg.rollback('owner', True)}")
        except (PromotionDenied, ValueError) as e:
            out(f"DENIED: {e}"); return 4
        return 0
    if a.cmd == "mcp-token":
        from atlas.mcp.trading.tokens import TokenRegistry
        reg = TokenRegistry(a.tokens)
        if a.action == "create":
            tok = reg.create(a.client, set(a.scopes.split(",")), a.ttl_days)
            out(f"token for {a.client} (shown once): {tok}")
        else:
            reg.revoke(a.client); out("revoked")
        return 0
    return 1


def main() -> None:
    sys.exit(run(sys.argv[1:]))
