"""Paper-only broker adapters. Off by default, no network unless a transport is injected,
and live endpoints/ports/accounts are hard-blocked."""
from atlas.execution.adapters.alpaca import AlpacaPaperAdapter  # noqa: F401
from atlas.execution.adapters.guards import guard_alpaca_url, guard_ibkr_port, guard_ibkr_account  # noqa: F401
from atlas.execution.adapters.ibkr import IbkrPaperAdapter  # noqa: F401
from atlas.execution.adapters.router import ExecutionRouter  # noqa: F401
