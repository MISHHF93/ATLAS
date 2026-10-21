"""Role-Based Access Control (RBAC) & Client Segment Segregation (`src/atlas/api/rbac.py`).

Defines the three primary institutional client segments for ATLAS:
1. `prop_firm_admin` (B2B Enterprise Operator):
   - Focus: Multi-account surveillance, real-time liquidation engine, Sybil/latency-arbitrage
     detection, B-Book to A-Book smart dealing desk copier.
   - Access: Full control plane, kill switch, risk rulebook configuration.
2. `quant_researcher` (Institutional Quant / Fund):
   - Focus: Purged & embargoed walk-forward evaluation (`EXP-001`), Kyle's Lambda & VPIN
     feature stores, model training lifecycle.
   - Access: Research workbench, model registry, lakehouse SQL console.
   - Invariant: `execution_permission: "none"`.
3. `funded_trader` (Challenge & Funded Trader):
   - Focus: Live execution cockpit, Depth of Market (DOM) ladder, Dynamic Remaining-Room HUD
     (cushion to 4% daily loss and 8% trailing DD), pre-trade bracket order desk.
   - Access: `/`, `/listings`, `/market`, `/trade/*`. Cannot modify risk parameters or
     trigger global kill switches.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ClientRoleId = Literal["prop_firm_admin", "quant_researcher", "funded_trader"]


@dataclass(frozen=True)
class RoleProfile:
    role_id: ClientRoleId
    title: str
    segment: str
    focus_summary: str
    allowed_routes: tuple[str, ...]
    can_modify_risk_parameters: bool
    can_trigger_kill_switch: bool
    can_execute_trader_orders: bool
    can_access_surveillance_and_dealing_desk: bool
    can_run_walk_forward_and_sql: bool
    execution_permission: Literal["none", "control_plane_gated"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ROLE_PROFILES: dict[ClientRoleId, RoleProfile] = {
    "prop_firm_admin": RoleProfile(
        role_id="prop_firm_admin",
        title="B2B Enterprise Prop Operator",
        segment="B2B Prop Firm & Risk Desk",
        focus_summary=(
            "Multi-account surveillance, real-time liquidation engine, Sybil/latency-arbitrage "
            "detection, and B-Book to A-Book smart dealing desk copier."
        ),
        allowed_routes=(
            "/",
            "/listings",
            "/market",
            "/trade",
            "/trade/cockpit",
            "/trade/depth-dom",
            "/trade/blotter",
            "/trade/journal",
            "/control",
            "/control/risk-hud",
            "/control/rulebook",
            "/control/surveillance",
            "/control/proctoring",
            "/control/dealing-desk",
            "/research",
            "/research/central-node",
            "/research/walk-forward",
            "/research/microstructure",
            "/research/registry",
            "/data",
            "/data/lakehouse",
            "/data/pipelines",
            "/data/governance",
            "/data/features-100",
        ),
        can_modify_risk_parameters=True,
        can_trigger_kill_switch=True,
        can_execute_trader_orders=True,
        can_access_surveillance_and_dealing_desk=True,
        can_run_walk_forward_and_sql=True,
        execution_permission="control_plane_gated",
    ),
    "quant_researcher": RoleProfile(
        role_id="quant_researcher",
        title="Institutional Quant Researcher",
        segment="Institutional Quant / Hedge Fund",
        focus_summary=(
            "Purged & embargoed walk-forward evaluation (EXP-001), Kyle's Lambda & VPIN feature "
            "stores, and causal model training lifecycle (execution_permission: none)."
        ),
        allowed_routes=(
            "/",
            "/listings",
            "/market",
            "/research",
            "/research/central-node",
            "/research/walk-forward",
            "/research/microstructure",
            "/research/registry",
            "/models",
            "/experiments",
            "/matrix",
            "/data",
            "/data/lakehouse",
            "/data/pipelines",
            "/data/governance",
            "/data/features-100",
            "/warehouse",
        ),
        can_modify_risk_parameters=False,
        can_trigger_kill_switch=False,
        can_execute_trader_orders=False,
        can_access_surveillance_and_dealing_desk=False,
        can_run_walk_forward_and_sql=True,
        execution_permission="none",
    ),
    "funded_trader": RoleProfile(
        role_id="funded_trader",
        title="Challenge & Funded Trader",
        segment="Prop Challenge & Open-Market Trader",
        focus_summary=(
            "Live execution cockpit, Depth of Market (DOM) ladder, Dynamic Remaining-Room HUD "
            "(cushion to 4% daily loss and 8% trailing DD), and pre-trade bracket order desk."
        ),
        allowed_routes=(
            "/",
            "/listings",
            "/market",
            "/trade",
            "/trade/cockpit",
            "/trade/depth-dom",
            "/trade/blotter",
            "/trade/journal",
        ),
        can_modify_risk_parameters=False,
        can_trigger_kill_switch=False,
        can_execute_trader_orders=True,
        can_access_surveillance_and_dealing_desk=False,
        can_run_walk_forward_and_sql=False,
        execution_permission="control_plane_gated",
    ),
}


def get_role_profile(role_id: str) -> RoleProfile:
    key = role_id.strip().lower()
    if key not in ROLE_PROFILES:
        raise ValueError(f"Unknown RBAC role: {role_id}. Expected one of {tuple(ROLE_PROFILES.keys())}")
    return ROLE_PROFILES[key]  # type: ignore[index]


def verify_role_action(
    role_id: str,
    action: Literal[
        "modify_risk_parameters",
        "trigger_kill_switch",
        "submit_bracket_order",
        "run_walk_forward_experiment",
        "query_lakehouse_sql",
        "access_surveillance",
        "view_market_stream",
    ],
    *,
    route: str | None = None,
) -> dict[str, Any]:
    """Deterministically evaluate whether a given client role is authorized for an action or route."""
    profile = get_role_profile(role_id)

    route_allowed = True
    if route is not None:
        clean_route = route.strip() or "/"
        route_allowed = any(
            clean_route == allowed or (allowed != "/" and clean_route.startswith(allowed))
            for allowed in profile.allowed_routes
        )

    action_map: dict[str, bool] = {
        "modify_risk_parameters": profile.can_modify_risk_parameters,
        "trigger_kill_switch": profile.can_trigger_kill_switch,
        "submit_bracket_order": profile.can_execute_trader_orders and profile.execution_permission != "none",
        "run_walk_forward_experiment": profile.can_run_walk_forward_and_sql,
        "query_lakehouse_sql": profile.can_run_walk_forward_and_sql,
        "access_surveillance": profile.can_access_surveillance_and_dealing_desk,
        "view_market_stream": True,
    }
    action_allowed = bool(action_map.get(action, False))
    authorized = bool(route_allowed and action_allowed)

    reason = "authorized"
    if not route_allowed:
        reason = f"role '{profile.role_id}' is not permitted to access route '{route}'"
    elif not action_allowed:
        reason = f"role '{profile.role_id}' is forbidden from action '{action}'"

    return {
        "role_id": profile.role_id,
        "action": action,
        "route": route,
        "authorized": authorized,
        "route_allowed": route_allowed,
        "action_allowed": action_allowed,
        "execution_permission": profile.execution_permission,
        "reason": reason,
    }

