"""Subsystem N: Non-Custodial Safety & Prop Risk Bounds (`src/atlas/risk/`).

Re-exports deterministic prop-competition and open-market risk evaluation, single-day
profit consistency gates (<= 35%), trailing drawdown floors (8%), and VPIN stop-widening.
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

