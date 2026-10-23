"""Weekly kill-switch drill (paper). Runs against an ISOLATED in-memory paper service built
from the same config, so the live paper service's kill switch is never touched. Verifies:
engage latency, open orders cancelled, new intents rejected, MCP cannot reset, reset needs
owner + step-up, audit chain verifies. Result recorded in the real audit log."""
from __future__ import annotations

import time

from atlas.risk.models import OrderIntent


def run_drill(cfg_dir, audit=None, verify_signature: bool = True) -> dict:
    from atlas.mcp.trading.service import build_service
    svc = build_service(cfg_dir, verify_signature=verify_signature)
    svc.heartbeat()
    checks = {}
    i = OrderIntent(symbol="SPY", side="buy", qty=1, order_type="limit", limit_price=99.0, reference_price=100.0,
                    sleeve="core", asset_class="index_etf", broker="alpaca", source="owner", quote_age_s=0.1)
    d = svc.engine.evaluate(i, svc.broker.snapshot())
    if d.approved:
        svc.broker.submit(i, d)  # rests (limit far below market)
    checks["resting_order_placed"] = len(svc.broker.open_orders) == 1
    if not d.approved:
        checks["resting_order_reject_reasons"] = d.reasons or ["?"]  # makes the drill fail visibly
    t0 = time.perf_counter()
    svc.kill_switch("weekly drill")
    checks["engage_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    checks["engaged"] = svc.ks.engaged
    checks["open_orders_cancelled"] = len(svc.broker.open_orders) == 0
    r = svc.engine.evaluate(i.model_copy(update={"intent_id": "drill-2"}), svc.broker.snapshot())
    checks["new_orders_rejected"] = not r.approved
    checks["mcp_has_no_reset"] = not hasattr(svc, "reset_kill_switch")
    try:
        svc.ks.reset("ai", True, svc.cfg.risk.owner); checks["non_owner_reset_denied"] = False
    except PermissionError:
        checks["non_owner_reset_denied"] = True
    try:
        svc.ks.reset(svc.cfg.risk.owner, False, svc.cfg.risk.owner); checks["reset_without_stepup_denied"] = False
    except PermissionError:
        checks["reset_without_stepup_denied"] = True
    svc.ks.reset(svc.cfg.risk.owner, True, svc.cfg.risk.owner)
    checks["owner_reset_ok"] = not svc.ks.engaged
    checks["audit_chain_ok"] = svc.audit.verify() > 0
    passed = all(v for k, v in checks.items() if k != "engage_ms") and checks["engage_ms"] < 1000
    res = {"passed": passed, "checks": checks}
    if audit is not None:
        audit.append("ops.drill", res)
    return res


def main(argv=None) -> None:
    import argparse
    import json
    import sys
    from atlas.governance.audit import AuditLog
    ap = argparse.ArgumentParser(prog="atlas-drill")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--audit", default="var/audit.sqlite")
    a = ap.parse_args(argv)
    r = run_drill(a.config, AuditLog(a.audit))
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["passed"] else 1)
