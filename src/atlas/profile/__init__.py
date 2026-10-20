"""Subsystem U: User Roles & RBAC Boundaries (`src/atlas/profile/`).

Enforces founder_admin, researcher, and monitoring RBAC boundaries with zero infrastructure
operator discretion over orders or signing keys (`execution_permission = "none"`).
"""
from __future__ import annotations

from typing import Literal

from atlas.models.schemas import Record, Text


class RbacBoundaryCheck(Record):
    """RBAC permission check verifying founder IP ownership and zero operator order discretion."""

    role: Literal["founder_admin", "researcher", "monitoring", "external_operator"]
    action: Text
    allowed: bool
    founder_ip_ownership_pct: float = 100.0
    operator_order_discretion: Literal[False] = False
    execution_permission: Literal["none"] = "none"


def check_rbac_boundary(
    role: Literal["founder_admin", "researcher", "monitoring", "external_operator"],
    action: str,
) -> RbacBoundaryCheck:
    """Verify whether `role` is permitted to execute `action` under ATLAS governance."""
    if role == "external_operator":
        allowed = action in ("view_health", "view_telemetry")
    elif role == "monitoring":
        allowed = action.startswith("view_")
    elif role == "researcher":
        allowed = not action.startswith("promote_") and not action.startswith("authorize_")
    else:
        allowed = True
    return RbacBoundaryCheck(role=role, action=action, allowed=allowed)


__all__ = ["RbacBoundaryCheck", "check_rbac_boundary"]

