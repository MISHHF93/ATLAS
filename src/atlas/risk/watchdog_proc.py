"""Separate watchdog process (fail closed).

Core process writes `core_heartbeat` (wall clock) into the shared StateStore.
The watchdog process (`atlas-watchdog --state var/state.sqlite`) checks it;
stale/missing/unreadable => engages the persisted kill switch. It also writes
`watchdog_heartbeat`; the core treats a stale watchdog as unhealthy too
(see `watchdog_alive`), so killing the watchdog halts trading.
"""
from __future__ import annotations

import argparse
import time
from typing import Callable

from atlas.governance.audit import AuditLog
from atlas.risk.killswitch import KillSwitch
from atlas.risk.state_store import StateStore

CORE_HB = "core_heartbeat"
WD_HB = "watchdog_heartbeat"


def write_core_heartbeat(store: StateStore, now: float | None = None) -> None:
    store.set(CORE_HB, time.time() if now is None else now)


def watchdog_alive(store: StateStore, window_s: float, now: float | None = None) -> bool:
    try:
        hb = store.get(WD_HB)
        now = time.time() if now is None else now
        return hb is not None and 0 <= now - float(hb) <= window_s
    except Exception:
        return False


def check_once(store: StateStore, ks: KillSwitch, window_s: float, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        hb = store.get(CORE_HB)
        ok = hb is not None and 0 <= now - float(hb) <= window_s
    except Exception:
        ok = False
    try:
        store.set(WD_HB, now)
    except Exception:
        pass
    if not ok and not ks.engaged:
        ks.engage(f"external watchdog: core heartbeat stale (> {window_s}s)", channel="watchdog")
    return ok


def run(state_path: str, interval_s: float, missed: int, iterations: int | None = None,
        sleep: Callable[[float], None] = time.sleep) -> None:
    store = StateStore(state_path)
    ks = KillSwitch(AuditLog(), store=store)
    window = interval_s * missed
    i = 0
    while iterations is None or i < iterations:
        check_once(store, ks, window)
        sleep(interval_s)
        i += 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="tradingbot external watchdog (fail closed)")
    ap.add_argument("--state", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--missed", type=int, default=3)
    ap.add_argument("--iterations", type=int, default=None)
    a = ap.parse_args(argv)
    run(a.state, a.interval, a.missed, a.iterations)


if __name__ == "__main__":
    main()
