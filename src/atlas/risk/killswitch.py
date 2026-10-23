from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from atlas.governance.audit import AuditLog
from atlas.risk.state_store import StateStore

KEY = "kill_switch"


class KillSwitch:
    """Once engaged, every intent is rejected until an owner reset.

    State is persisted in a StateStore (SQLite) so a restart stays halted and a
    separate watchdog process can engage it. If the store can't be read, the
    switch reports engaged (fail closed). Reset is NOT exposed via MCP."""

    def __init__(self, audit: AuditLog, on_engage: list[Callable[[str], int]] | None = None,
                 store: StateStore | None = None):
        self._audit = audit
        self._lock = threading.Lock()
        self._store = store or StateStore()
        self._on_engage = on_engage or []

    def _state(self) -> dict:
        try:
            return self._store.get(KEY, {"engaged": False}) or {"engaged": False}
        except Exception:
            return {"engaged": True, "reason": "state store unreadable (fail closed)"}

    @property
    def engaged(self) -> bool:
        return bool(self._state().get("engaged"))

    @property
    def reason(self) -> str | None:
        return self._state().get("reason")

    @property
    def engaged_at(self) -> str | None:
        return self._state().get("ts")

    def add_on_engage(self, cb: Callable[[str], int]) -> None:
        self._on_engage.append(cb)

    def add_on_flatten(self, cb: Callable[[str], int]) -> None:
        self._on_flatten = getattr(self, "_on_flatten", []) + [cb]

    def engage(self, reason: str, channel: str, flatten: bool = False) -> dict:
        new = {"engaged": True, "reason": reason, "channel": channel, "ts": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            try:  # atomic across processes: keep the first engage's reason/ts, never un-engage
                st = self._store.update(KEY, lambda old: old if (old or {}).get("engaged") else new, {"engaged": False})
            except Exception:
                st = new  # store unwritable: still report halted; _state() fails closed
        cancelled = 0
        for cb in self._on_engage:
            try:
                cancelled += int(cb(reason) or 0)
            except Exception:  # cancel-all failures must not un-halt
                pass
        flattened = 0
        if flatten:  # owner-chosen at engage time; reduces risk only (closing sells)
            for cb in getattr(self, "_on_flatten", []):
                try:
                    flattened += int(cb(reason) or 0)
                except Exception:
                    pass
        self._audit.append("kill_switch.engage", {"reason": reason, "channel": channel, "cancelled": cancelled,
                                                  "flatten": flatten, "flattened": flattened}, actor=channel)
        return {"halted": True, "cancelled_orders": cancelled, "flattened_positions": flattened,
                "ts": st.get("ts"), "reason": st.get("reason")}

    def reset(self, owner: str, step_up_verified: bool, expected_owner: str) -> None:
        if owner != expected_owner or not step_up_verified:
            self._audit.append("kill_switch.reset_denied", {"owner": owner}, actor=owner)
            raise PermissionError("kill switch reset requires owner + step-up auth")
        with self._lock:
            self._store.set(KEY, {"engaged": False})
        self._audit.append("kill_switch.reset", {"owner": owner}, actor=owner)
