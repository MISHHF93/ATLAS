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

__all__ = [
    "EIGHT_NON_CUSTODIAL_LEDGERS",
    "MasterSpecGateInput",
    "MasterSpecGateReport",
    "evaluate_master_spec_readiness",
]

