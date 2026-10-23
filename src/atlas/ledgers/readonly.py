"""The ONLY interface the trading side may use: a read-only balance view.
Opens the payments DB with SQLite `mode=ro`; exposes no write methods."""
from __future__ import annotations
import sqlite3
from decimal import Decimal
from atlas.ledgers.money import D

class BalanceView:
    def __init__(self, db_path: str):
        self._c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    def balances(self) -> dict[str, dict[str, Decimal]]:
        out: dict = {}
        for acct, ccy, amt in self._c.execute("SELECT account, currency, amount FROM postings"):
            if acct.startswith("asset:"):
                out.setdefault(acct, {}); out[acct][ccy] = out[acct].get(ccy, Decimal(0)) + D(amt)
        return out

    def summary(self) -> dict:
        c = self._c
        kill = c.execute("SELECT v FROM settings WHERE k='kill'").fetchone()
        return {"balances": {a: {k: str(v) for k, v in d.items()} for a, d in self.balances().items()},
                "kill_switch": bool(kill and kill[0] == "1"),
                "transfers": [dict(zip(("id", "status", "amount", "currency", "rail", "purpose"), r)) for r in
                              c.execute("SELECT id,status,amount,currency,rail,purpose FROM transfers ORDER BY id DESC LIMIT 20")],
                "pending_manual": [dict(zip(("id", "status", "amount", "currency", "rail", "reference", "value_date", "flag"), r)) for r in
                              c.execute("SELECT t.id,t.status,t.amount,t.currency,t.rail,m.reference,m.value_date,m.flag FROM transfers t"
                                        " JOIN manual_instructions m ON m.transfer_id=t.id WHERE t.status IN ('instructed','pending_settlement')"
                                        " OR (m.flag IS NOT NULL AND t.status!='settled') ORDER BY t.id")],
                "audit_entries": c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]}
