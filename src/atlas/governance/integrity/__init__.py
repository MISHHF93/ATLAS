"""Shared, stdlib-only primitives. Deliberately has NO state and no knowledge of either service, so
sharing it keeps the bot/payments isolation (separate DBs, separate secrets, separate processes)."""
