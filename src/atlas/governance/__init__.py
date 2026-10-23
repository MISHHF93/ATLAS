"""Subsystem G: Governance, Standards & 8 Separated Non-Custodial Ledgers (`src/atlas/governance/`).

Enforces ISO/IEC 42001, ISO/IEC 23894, NIST AI RMF, IOSCO alignment, and strict
separation across the 8 non-custodial money ledgers (`execution_permission = "none"`).
"""
from __future__ import annotations

from atlas.control.rules import (
    MasterSpecGateInput,
    MasterSpecGateReport,
    evaluate_master_spec_readiness,
)

EIGHT_NON_CUSTODIAL_LEDGERS: tuple[str, ...] = (
    "1_software_subscription",
    "2_broker_account",
    "3_exchange_account",
    "4_user_external_wallet",
    "5_custodian_future_only",
    "6_prop_firm_evaluation_rules",
    "7_founder_treasury",
    "8_future_double_entry_customer_ledger",
)

# Where each of the 8 non-custodial money ledgers is implemented (Lola port, docs/lola-port-plan.md).
# ATLAS never takes custody: every ledger is a record of money held elsewhere, paper/sandbox only.
LEDGER_IMPLEMENTATIONS: dict[str, dict[str, str]] = {
    "1_software_subscription": {"module": "atlas.ledgers.ledger", "page": "/payments",
                                "note": "SaaS subscription revenue recorded as double-entry postings (no card data stored)."},
    "2_broker_account": {"module": "atlas.execution.adapters", "page": "/money",
                         "note": "Read-only broker balances via paper/sandbox adapters (IBKR Canada, Alpaca paper)."},
    "3_exchange_account": {"module": "atlas.execution.adapters", "page": "/money",
                           "note": "Canadian-registered crypto dealers (spot only) via paper adapters."},
    "4_user_external_wallet": {"module": "atlas.ledgers.wallet", "page": "/portal",
                               "note": "Investor wallet: claims on a fund recorded off-chain; ATLAS holds no keys."},
    "5_custodian_future_only": {"module": "atlas.ledgers.fund", "page": "/money",
                                "note": "Fund/custodian accounting placeholder; no custodian integration enabled."},
    "6_prop_firm_evaluation_rules": {"module": "atlas.control.rules", "page": "/rules",
                                     "note": "Prop-competition rulebook (configurable 4% daily loss)."},
    "7_founder_treasury": {"module": "atlas.ledgers.treasury", "page": "/payments",
                           "note": "Founder treasury payments: manual-instruction rails, two-person + step-up approvals."},
    "8_future_double_entry_customer_ledger": {"module": "atlas.ledgers.db", "page": "/money",
                                              "note": "Double-entry postings store with reconciliation (atlas.ledgers.recon)."},
}

__all__ = [
    "LEDGER_IMPLEMENTATIONS",
    "EIGHT_NON_CUSTODIAL_LEDGERS",
    "MasterSpecGateInput",
    "MasterSpecGateReport",
    "evaluate_master_spec_readiness",
]

