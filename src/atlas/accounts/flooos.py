"""Finance export for Flooos (cost and cash tracking). Read-only aggregation over invoices, tax_records, usage_events and payouts_ledger.

Output is plain JSON / CSV with stable column names (no vendor SDK, no network call). It contains NO user ids, emails or secrets:
only amounts, plan codes, tax jurisdictions and counterparties. Mapping follows monetization_plan.md section 7.3.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import ledger

CATEGORY = {"stripe_payout": "cash", "stripe_fee": "payment_processing_cost", "refund": "refunds_disputes", "chargeback": "refunds_disputes",
            "dispute_fee": "refunds_disputes", "partner_cpa": "referral_income", "tax_remittance": "tax_remitted", "user_credit": "user_credit",
            "adjustment": "adjustment"}
CSV_COLUMNS = ("seq", "ts_utc", "flooos_category", "kind", "direction", "amount_cents", "currency", "fx_rate_micros", "counterparty",
               "stripe_payout_id", "bank_ref", "memo", "flooos_batch", "hash")


def _month(ts: int | None) -> str:
    return datetime.fromtimestamp(int(ts or 0), tz=timezone.utc).strftime("%Y-%m")


def build(conn: sqlite3.Connection, start: int = 0, end: int | None = None) -> dict[str, Any]:
    end_i = end if end is not None else 2**62
    led = ledger.rows(conn, start, end_i)
    rows_out = [{"seq": r["seq"], "ts_utc": datetime.fromtimestamp(r["ts"], tz=timezone.utc).isoformat(), "flooos_category": CATEGORY[r["kind"]],
                 **{k: r[k] for k in ("kind", "direction", "amount_cents", "currency", "fx_rate_micros", "counterparty", "stripe_payout_id", "bank_ref", "memo", "flooos_batch", "hash")}}
                for r in led]
    cash: dict[str, dict[str, int]] = {}
    for r in led:
        d = cash.setdefault(f"{CATEGORY[r['kind']]}:{r['currency']}", {"in": 0, "out": 0})
        d[r["direction"]] += r["amount_cents"]
    revenue: dict[str, int] = {}
    for r in conn.execute("SELECT i.currency AS cur, i.amount_subtotal AS sub, i.created_at AS ts, COALESCE(p.code,'unknown') AS plan FROM invoices i"
                          " LEFT JOIN subscriptions s ON s.stripe_subscription_id=i.subscription_id LEFT JOIN plans p ON p.id=s.plan_id"
                          " WHERE i.status='paid' AND i.created_at>=? AND i.created_at<?", (int(start), int(end_i))):
        k = f"{_month(r['ts'])}:{r['plan']}:{r['cur']}"
        revenue[k] = revenue.get(k, 0) + int(r["sub"])
    tax: dict[str, int] = {}
    for r in conn.execute("SELECT filing_period, tax_type, region, country, currency, SUM(tax_amount) AS amt FROM tax_records WHERE created_at>=? AND created_at<?"
                          " GROUP BY filing_period, tax_type, region, country, currency", (int(start), int(end_i))):
        tax[f"{r['filing_period'] or 'none'}:{r['country']}:{r['region'] or '-'}:{r['tax_type']}:{r['currency']}"] = int(r["amt"])
    cost: dict[str, int] = {}
    for r in conn.execute("SELECT key, SUM(quantity*unit_cost_micros) AS m FROM usage_events WHERE ts>=? AND ts<? AND unit_cost_micros>0 GROUP BY key", (int(start), int(end_i))):
        cost[r["key"]] = int(r["m"])
    fee = conn.execute("SELECT COALESCE(SUM(stripe_fee_cents),0) FROM invoices WHERE created_at>=? AND created_at<?", (int(start), int(end_i))).fetchone()[0]
    return {"format": "atlas-flooos-v1", "range": {"start": int(start), "end": None if end is None else int(end)}, "per_trade_fees": 0, "performance_fees": 0,
            "ledger": rows_out, "chain": ledger.verify_chain(conn),
            "summary": {"cash_by_category": cash, "revenue_subscriptions_subtotal_cents": revenue, "tax_collected_cents": tax,
                        "variable_cost_usd_micros_by_key": cost, "invoice_stripe_fee_cents": int(fee)}}


def to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("'" + str(v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in r.items() if k in CSV_COLUMNS})  # neutralise CSV formula injection
    return buf.getvalue()
