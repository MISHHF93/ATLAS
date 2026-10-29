"""Paper capital pipeline. The ledger is the book. The control plane holds a snapshot."""

from atlas.capital.paper import (
    PAPER_ACCOUNT_ID,
    PAPER_TENANT,
    bind_paper_journal,
    capital_status,
    deposit_paper,
    replay_paper_capital,
    withdraw_paper,
)

__all__ = [
    "PAPER_ACCOUNT_ID",
    "PAPER_TENANT",
    "bind_paper_journal",
    "capital_status",
    "deposit_paper",
    "replay_paper_capital",
    "withdraw_paper",
]
