"""Hard blocks for live endpoints. Not configurable."""
from __future__ import annotations

from urllib.parse import urlparse

from atlas.risk.safety import LiveTradingForbidden

ALPACA_PAPER_HOST = "paper-api.alpaca.markets"
ALPACA_LIVE_HOSTS = {"api.alpaca.markets"}
IBKR_PAPER_PORTS = {4002, 7497}  # IB Gateway paper, TWS paper
IBKR_LIVE_PORTS = {4001, 7496}


def guard_alpaca_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != ALPACA_PAPER_HOST or u.port not in (None, 443):
        raise LiveTradingForbidden(f"Alpaca URL {url!r} is not the paper endpoint (only https://{ALPACA_PAPER_HOST})")
    return url


def guard_ibkr_port(port: int) -> int:
    port = int(port)
    if port in IBKR_LIVE_PORTS or port not in IBKR_PAPER_PORTS:
        raise LiveTradingForbidden(f"IBKR port {port} is not a paper port {sorted(IBKR_PAPER_PORTS)}")
    return port


def guard_ibkr_account(account: str) -> str:
    if not account or not account.upper().startswith("DU"):
        raise LiveTradingForbidden(f"IBKR account {account!r} is not a paper (DU…) account")
    return account


def guard_alpaca_account(account: dict) -> None:
    num = str(account.get("account_number", ""))
    if not num.upper().startswith("PA"):
        raise LiveTradingForbidden(f"Alpaca account {num!r} is not a paper (PA…) account")
