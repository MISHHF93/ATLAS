"""Subsystem N: Non-Custodial Safety & Prop Risk Bounds (`src/atlas/risk/`).

Re-exports deterministic prop-competition and open-market risk evaluation, single-day
profit consistency gates (<= 35%), trailing drawdown floors (8%), and VPIN stop-widening.

Founder/owner capital track (ported from Lola): deterministic paper-only RiskEngine with the owner's
2% daily-loss Safe stop, persisted KillSwitch ("Safe stop"), separate-process Watchdog, TTL approval
queue and owner step-up (`atlas.risk.approvals`, `atlas.risk.stepup`). AI may only shrink or veto.
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
from atlas.risk.models import OrderIntent, RiskDecision, PortfolioState, Position  # noqa: E402
from atlas.risk.engine import RiskEngine  # noqa: E402
from atlas.risk.killswitch import KillSwitch  # noqa: E402
from atlas.risk.watchdog import Watchdog  # noqa: E402

__all__ = [
    "OrderIntent",
    "RiskDecision",
    "PortfolioState",
    "Position",
    "RiskEngine",
    "KillSwitch",
    "Watchdog",
    "AccountRiskSnapshot",
    "LimitProximity",
    "ProposedTradeCheck",
    "RemainingRoomReport",
    "RuleEvaluationReport",
    "TradingRuleBook",
    "evaluate_trading_rules",
]

