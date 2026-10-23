"""One Safe stop for all of ATLAS.

The persisted, fail-closed :class:`atlas.risk.killswitch.KillSwitch` (shared via SQLite with the separate
``atlas-watchdog`` process) is the single source of truth. The prop-desk control plane, the founder API and
the UI Safe stop button all read and engage this same switch.

``ATLAS_STATE_DB`` / ``ATLAS_AUDIT_DB`` (names only) point at the shared files; unset means in-memory.
Engaging is always allowed. Resetting from the founder surface requires the owner CLI with step-up; the
prop-desk operator reset (role-checked ``/api/control/kill-switch``) is recorded as ``kill_switch.operator_reset``.
"""
from __future__ import annotations

import os
import threading

from atlas.governance.audit import AuditLog
from atlas.risk.killswitch import KEY, KillSwitch
from atlas.risk.state_store import StateStore

_LOCK = threading.Lock()
_SHARED: KillSwitch | None = None


def new_safe_stop(state_db: str = ":memory:", audit_db: str = ":memory:") -> KillSwitch:
    return KillSwitch(AuditLog(audit_db), store=StateStore(state_db))


def shared_safe_stop() -> KillSwitch:
    """Process-wide Safe stop used by the API process (control plane + founder routes)."""
    global _SHARED
    with _LOCK:
        if _SHARED is None:
            _SHARED = new_safe_stop(os.environ.get("ATLAS_STATE_DB", ":memory:"), os.environ.get("ATLAS_AUDIT_DB", ":memory:"))
        return _SHARED


def operator_reset(ks: KillSwitch, reason: str, actor: str = "control_plane_operator") -> None:
    """Prop-desk operator reset (role-checked upstream). Audited; never reachable from AI/MCP tools."""
    ks._store.set(KEY, {"engaged": False})  # noqa: SLF001
    ks._audit.append("kill_switch.operator_reset", {"reason": reason}, actor=actor)  # noqa: SLF001


__all__ = ["new_safe_stop", "operator_reset", "shared_safe_stop"]
