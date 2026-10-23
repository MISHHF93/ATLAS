"""Reconciliation of executed transfers against provider statements (CSV fixtures).
Statement columns: date,ref,amount,currency (amount negative = outflow)."""
from __future__ import annotations
import csv
from decimal import Decimal
from atlas.ledgers.money import D

def load_statement(path) -> list[dict]:
    with open(path, newline="") as f:
        return [dict(r, amount=D(r["amount"])) for r in csv.DictReader(f)]

def reconcile(c, statement: list[dict], ref_prefix: str = "") -> dict:
    ours = {r["provider_ref"]: r for r in c.execute("SELECT * FROM transfers WHERE status='executed'")
            if r["provider_ref"].startswith(ref_prefix)}
    theirs = {r["ref"]: r for r in statement}
    matched, mismatched = [], []
    for ref in ours.keys() & theirs.keys():
        o, s = ours[ref], theirs[ref]
        (matched if -D(o["amount"]) == s["amount"] and o["currency"] == s["currency"] else mismatched).append(ref)
    return {"matched": sorted(matched), "amount_mismatch": sorted(mismatched),
            "missing_from_statement": sorted(ours.keys() - theirs.keys()),
            "unexpected_on_statement": sorted(theirs.keys() - ours.keys()),
            "ok": not mismatched and ours.keys() == theirs.keys()}
