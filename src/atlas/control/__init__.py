"""Deterministic control-plane rule definitions, execution engine, and readiness gates.

This package never imports `atlas.ai` or any LLM provider. All order, position,
kill-switch, and lifecycle actions are governed deterministically by the control plane.
"""
from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableControlState,
    ActionableOrderDecision,
    ActionableOrderRequest,
    ActionablePositionRecord,
    BracketOrderIntakeReport,
)
from atlas.control.gateway import ControlPlaneExecutionGateway
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
