"""Deterministic control-plane rule definitions, execution engine, and readiness gates.

This package never imports `atlas.ai` or any LLM provider. All order, position,
kill-switch, and lifecycle actions are governed deterministically by the control plane.
"""
from typing import TYPE_CHECKING

from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableControlState,
    ActionableOrderDecision,
    ActionableOrderRequest,
    ActionablePositionRecord,
    BracketOrderIntakeReport,
)
from atlas.control.rules import (
    AccountRiskSnapshot,
    LimitProximity,
    MasterSpecGateInput,
    MasterSpecGateReport,
    ProposedTradeCheck,
    RemainingRoomReport,
    RuleEvaluationReport,
    TradingRuleBook,
    evaluate_master_spec_readiness,
    evaluate_trading_rules,
)

if TYPE_CHECKING:
    from atlas.control.gateway import ControlPlaneExecutionGateway


def __getattr__(name: str):
    if name == "ControlPlaneExecutionGateway":
        # Connectors import the engine. Loading the connector gateway while the
        # package initializes would re-enter a partially initialized connector.
        from atlas.control.gateway import ControlPlaneExecutionGateway

        globals()[name] = ControlPlaneExecutionGateway
        return ControlPlaneExecutionGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "AccountRiskSnapshot",
    "ActionableControlPlaneEngine",
    "ActionableControlState",
    "ActionableOrderDecision",
    "ActionableOrderRequest",
    "ActionablePositionRecord",
    "BracketOrderIntakeReport",
    "ControlPlaneExecutionGateway",
    "LimitProximity",
    "MasterSpecGateInput",
    "MasterSpecGateReport",
    "ProposedTradeCheck",
    "RemainingRoomReport",
    "RuleEvaluationReport",
    "TradingRuleBook",
    "evaluate_master_spec_readiness",
    "evaluate_trading_rules",
]
