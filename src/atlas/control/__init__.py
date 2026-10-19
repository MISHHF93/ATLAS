"""Deterministic control-plane rule definitions and evaluation scaffolding.

This package never imports `atlas.ai` or any LLM provider. All outputs in this
repository retain `execution_permission: none` until master-spec gates are met.
"""
from atlas.control.rules import (
    AccountRiskSnapshot,
    LimitProximity,
    ProposedTradeCheck,
    RemainingRoomReport,
    RuleEvaluationReport,
    TradingRuleBook,
    evaluate_trading_rules,
)

__all__ = [
    "AccountRiskSnapshot",
    "LimitProximity",
    "ProposedTradeCheck",
    "RemainingRoomReport",
    "RuleEvaluationReport",
    "TradingRuleBook",
    "evaluate_trading_rules",
]

