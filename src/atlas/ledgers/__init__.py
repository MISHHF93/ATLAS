"""atlas.ledgers: SIMULATION-ONLY payments/treasury service.

Isolated from the trading bot: own process, own SQLite DB, own step-up auth.
No real payment network calls are made anywhere in this package."""
__version__ = "0.1.0"
