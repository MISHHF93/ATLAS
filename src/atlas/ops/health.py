"""Healthcheck: config, audit chain, watchdog, kill switch, state DB, heartbeat age.
`atlas-health` exits 0 when healthy, 1 otherwise (used by Docker HEALTHCHECK)."""
from __future__ import annotations

import argparse
import json
import sys
import time


def health(svc=None, state_path: str | None = None, config_dir: str = "config/founder", max_hb_age_s: float = 30) -> dict:
    checks = {}
    try:
        from atlas.control.policy import load_all
        load_all(config_dir)
        checks["config_valid"] = True
    except Exception as e:  # noqa: BLE001
        checks["config_valid"] = f"error: {str(e)[:200]}"
    try:
        from atlas.risk.safety import assert_paper_only
        assert_paper_only(); checks["paper_only"] = True
    except Exception as e:  # noqa: BLE001
        checks["paper_only"] = f"error: {e}"
    if svc is not None:
        checks["audit_chain"] = _try(lambda: svc.audit.verify() >= 0)
        checks["watchdog_healthy"] = bool(svc.watchdog.healthy())
        checks["kill_switch_engaged"] = svc.ks.engaged  # informational
    if state_path:
        from atlas.risk.state_store import StateStore
        from atlas.risk.watchdog_proc import CORE_HB
        st = StateStore(state_path)
        checks["state_db_writable"] = _try(lambda: st.set("health_probe", time.time()) is None)
        hb = st.get(CORE_HB)
        checks["core_heartbeat_fresh"] = hb is not None and time.time() - float(hb) <= max_hb_age_s
        from atlas.risk.killswitch import KEY
        checks["kill_switch_engaged"] = bool((st.get(KEY) or {}).get("engaged"))
    required = [k for k in checks if k not in ("kill_switch_engaged",)]
    ok = all(checks[k] is True for k in required)
    return {"ok": ok, "checks": checks}


def _try(fn):
    try:
        return bool(fn())
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="atlas-health")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--state", default=None)
    ap.add_argument("--max-heartbeat-age", type=float, default=30)
    a = ap.parse_args(argv)
    r = health(None, a.state, a.config, a.max_heartbeat_age)
    print(json.dumps(r))
    sys.exit(0 if r["ok"] else 1)
