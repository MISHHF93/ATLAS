"""Moved: the Alpaca paper broker lives in ``atlas.execution.adapters.alpaca`` (one paper execution module).
This alias keeps the old import path working."""
from atlas.execution.adapters.alpaca import (  # noqa: F401
    PAPER_URL, AlpacaPaperAdapter, AlpacaPaperBroker, UrllibTransport, _Adapt, _env,
)
from atlas.execution.adapters.guards import ALPACA_PAPER_HOST  # noqa: F401
from atlas.risk.safety import LiveTradingForbidden  # noqa: F401
