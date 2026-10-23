"""Double-entry ledger. Each posting stores native amount + CAD equivalent;
journals must balance in CAD (and per-currency when single-currency)."""
from __future__ import annotations
from decimal import Decimal
from atlas.ledgers.money import D, q, FX
from atlas.ledgers.db import now, tx

class LedgerError(ValueError): ...

DEFAULT_ACCOUNTS = [
    ("asset:bank:cad", "asset", "CAD"), ("asset:bank:usd", "asset", "USD"),
    ("asset:broker:ibkr", "asset", "USD"), ("asset:broker:kraken", "asset", "USD"),
    ("asset:broker:coinbase", "asset", "USD"), ("asset:transit", "asset", "CAD"),
    ("liability:investor_capital", "liability", "CAD"), ("liability:redemptions_payable", "liability", "CAD"),
    ("liability:payables", "liability", "CAD"), ("income:fees", "income", "CAD"),
    ("expense:platform", "expense", "CAD"), ("equity:fx", "equity", "CAD"),
]

class Ledger:
    def __init__(self, c, fx: FX | None = None, clock=now):
        self.c, self.fx, self.clock = c, fx or FX(), clock
        for a in DEFAULT_ACCOUNTS:
            c.execute("INSERT OR IGNORE INTO accounts VALUES(?,?,?)", a)

    def post(self, memo: str, legs: list[tuple[str, object, str]], ref: str = "") -> int:
        """legs: (account, signed amount (debit +, credit -), currency)."""
        if len(legs) < 2:
            raise LedgerError("need >= 2 legs")
        cad = [self.fx.to_cad(a, ccy) for _, a, ccy in legs]
        diff = sum(cad, Decimal(0))
        if abs(diff) > Decimal("0.05") * (len(legs)):
            raise LedgerError(f"unbalanced journal (CAD diff {diff})")
        for acct, _, _ in legs:
            if not self.c.execute("SELECT 1 FROM accounts WHERE code=?", (acct,)).fetchone():
                raise LedgerError(f"unknown account {acct}")
        with tx(self.c):
            jid = self.c.execute("INSERT INTO journal(ts,memo,ref) VALUES(?,?,?)", (self.clock(), memo, ref)).lastrowid
            if diff:  # rounding residue to FX equity
                legs = legs + [("equity:fx", -diff, "CAD")]
                cad = cad + [-diff]
            for (acct, a, ccy), ac in zip(legs, cad):
                self.c.execute("INSERT INTO postings(journal_id,account,currency,amount,amount_cad) VALUES(?,?,?,?,?)",
                               (jid, acct, ccy, str(q(a, "0.00000001")), str(ac)))
        return jid

    def balance(self, account: str, currency: str | None = None) -> Decimal:
        sql, args = "SELECT amount FROM postings WHERE account=?", [account]
        if currency:
            sql += " AND currency=?"; args.append(currency)
        return sum((D(r[0]) for r in self.c.execute(sql, args)), Decimal(0))

    def balance_cad(self, account: str) -> Decimal:
        return sum((D(r[0]) for r in self.c.execute("SELECT amount_cad FROM postings WHERE account=?", (account,))), Decimal(0))

    def trial_balance_cad(self) -> Decimal:
        return sum((D(r[0]) for r in self.c.execute("SELECT amount_cad FROM postings")), Decimal(0))
