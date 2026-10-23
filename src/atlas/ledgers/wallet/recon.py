"""Daily three-way reconciliation: internal ledger <-> administrator register / NAV <-> custodian statements.

Checks (each mismatch beyond tolerance is a BREAK, stored with the run and exported as CSV):
 1. units per investor: internal append-only unit ledger vs the administrator's register
 2. units outstanding: internal total vs administrator NAV record
 3. value per investor: internal units x administrator NAV vs administrator register x NAV
 4. fund net assets: administrator NAV (net assets + accrued fees) vs custodian fund accounts (custody + brokers)
 5. cash in transit: internal funded-but-not-issued subscriptions minus unpaid dealt redemptions vs administrator trust
    records vs the custodian trust-account balance
 6. payouts: internal paid payouts vs administrator payout report / partner rail reports (reference + amount)
 7. receipts: every credit on the trust account (ISO 20022 camt.054 notifications) must carry a known SUB- reference
    with the expected amount; unidentified receipts are held for return, never applied by guesswork
Custodian balances come from the custodian's ISO 20022 camt.053 statement (closing booked balance per account; the
statement must be internally consistent: opening + booked entries = closing). A statement file can be supplied
(uploaded) instead of the simulated custodian's export.
Every run is audited; breaks never auto-correct anything."""
from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal

from atlas.ledgers.banking.iso20022 import camt
from atlas.ledgers.money import D, q
from atlas.ledgers.wallet.partners import ACCOUNT_IDS, FUND_ACCOUNTS, TRUST

UNIT_TOL = Decimal("0.0001")
CASH_TOL = Decimal("1.00")


SUB_REF = re.compile(r"\bSUB-[0-9A-F]{8}\b")


def custodian_balances(cust, camt053: str | None = None) -> tuple[dict, dict]:
    """{internal account name: closing balance} from a camt.053, plus source info. Falls back to the custodian
    API-style statement when the custodian cannot produce camt (real adapters are disabled anyway)."""
    xml = camt053 or (cust.camt053() if hasattr(cust, "camt053") else None)
    if xml is None:
        st = cust.statement()
        return {a: D(v) for a, v in st["accounts"].items()}, {"source": "custodian statement (API)"}
    doc = camt.parse(xml)
    rev = {v: k for k, v in ACCOUNT_IDS.items()}
    bals, issues = {}, []
    for r in doc["reports"]:
        name = rev.get(r["account"], r["account"])
        if r.get("closing"):
            bals[name] = r["closing"]["amount"]
        if r.get("check") and not r["check"]["opening_plus_booked_equals_closing"]:
            issues.append(f"{r['account']}: opening + entries != closing ({r['check']['difference']})")
    return bals, {"source": f"camt.053 {doc['msg_id']}", "message": doc["message"], "statement_issues": issues}


def run(w, actor: str = "system", camt053: str | None = None, camt054: str | None = None) -> dict:
    adm, cust = w.p.administrator, w.p.custodian
    breaks: list[dict] = []

    def brk(check, subject, internal, administrator, custodian, diff, severity="high", note=""):
        breaks.append({"check": check, "subject": subject, "internal": str(internal), "administrator": str(administrator),
                       "custodian": str(custodian), "difference": str(diff), "severity": severity, "note": note})

    reg = adm.register()
    nav = adm.nav()
    p = D(nav["nav_per_unit"])
    cust_bal, cust_src = custodian_balances(cust, camt053)
    stmt = {"accounts": cust_bal}
    inv = {r["admin_ref"]: r for r in w.c.execute("SELECT * FROM w_investors WHERE admin_ref IS NOT NULL")}
    off = set(w.off_platform_refs())          # holders registered directly with the administrator (e.g. GP seed units)
    off_units = sum((reg.get(r, Decimal(0)) for r in off), Decimal(0))
    # 1 + 3: per investor
    for ref in sorted((set(reg) | set(inv)) - off):
        internal = w.units(inv[ref]["id"]) if ref in inv else Decimal(0)
        admin_u = reg.get(ref, Decimal(0))
        name = inv[ref]["legal_name"] if ref in inv else f"unknown administrator account {ref}"
        if abs(internal - admin_u) > UNIT_TOL:
            brk("units_per_investor", name, internal, admin_u, "n/a", q(internal - admin_u, "0.0001"),
                note="unit register differs from internal ledger (sync pending, or a register error)")
            brk("value_per_investor", name, q(internal * p), q(admin_u * p), "n/a", q((internal - admin_u) * p), "medium",
                note=f"at administrator NAV {p}")
    # 2: units outstanding
    tot_int = sum((w.units(r["id"]) for r in inv.values()), Decimal(0)) + off_units
    tot_adm = D(nav["units_outstanding"] or 0)
    tot_reg = sum(reg.values(), Decimal(0))
    if nav["nav_date"] and (abs(tot_int - tot_adm) > UNIT_TOL or abs(tot_reg - tot_adm) > UNIT_TOL):
        brk("units_outstanding", "fund", tot_int, f"register {tot_reg} / NAV record {tot_adm}", "n/a",
            q(max(abs(tot_int - tot_adm), abs(tot_reg - tot_adm)), "0.0001"))
    # 4: fund net assets vs custodian
    cust_fund = sum((D(stmt["accounts"].get(a, 0)) for a in FUND_ACCOUNTS), Decimal(0))
    accrued = D(adm.sim.kv("accrued_fees", "0")) if hasattr(adm, "sim") else Decimal(0)
    adm_na = D(nav["net_assets"] or 0) + accrued
    moved = cust_fund - adm_na if nav["nav_date"] else Decimal(0)
    if nav["nav_date"] and abs(moved) > CASH_TOL:
        brk("fund_net_assets", "fund", "n/a", q(adm_na), q(cust_fund), q(moved), "medium",
            note="custodian holdings vs administrator NAV (+accrued fees); market moves after the NAV date also show here")
    # 5: cash in transit (trust account)
    subs = {r["reference"]: r for r in adm.subscriptions()}
    int_funded = sum((D(r["received"] or 0) for r in w.c.execute("SELECT received FROM w_subs WHERE status IN ('funds_received','awaiting_funds')")), Decimal(0))
    int_reds_unpaid = sum((D(r[0] or 0) for r in w.c.execute("SELECT net FROM w_reds WHERE status='dealt'")), Decimal(0))
    int_transit = int_funded + int_reds_unpaid
    adm_transit = sum((D(s["received"]) for s in subs.values() if s["status"] in ("funds_received", "awaiting_funds")), Decimal(0)) + \
        sum((D(r["net"] or 0) for r in adm.redemptions() if r["status"] == "dealt"), Decimal(0))
    cust_trust = D(stmt["accounts"].get(TRUST, 0))
    if abs(int_transit - adm_transit) > CASH_TOL or abs(adm_transit - cust_trust) > CASH_TOL:
        brk("trust_cash_in_transit", "administrator trust account", q(int_transit), q(adm_transit), q(cust_trust),
            q(max(abs(int_transit - adm_transit), abs(adm_transit - cust_trust))),
            note="funded subscriptions not yet issued + dealt redemptions not yet paid")
    # 6: payouts
    adm_paid = {r["release_ref"]: D(r["net"]) for r in adm.payout_report()}
    rail_paid = {}
    for rail in w.p.rails.values():
        if getattr(rail, "enabled", False):
            rail_paid.update({r["reference"]: D(r["amount"]) for r in rail.report()})
    for r in w.c.execute("SELECT * FROM w_payouts WHERE status='paid'"):
        src = adm_paid if r["kind"] == "redemption" else rail_paid
        got = src.get(r["release_ref"])
        if got is None or abs(got - D(r["amount"])) > CASH_TOL:
            brk("payouts", f"payout #{r['id']} ({r['kind']})", r["amount"], got if r["kind"] == "redemption" else "n/a",
                got if r["kind"] != "redemption" else "n/a", "missing" if got is None else q(D(r["amount"]) - got))
    for issue in cust_src.get("statement_issues", []):
        brk("custodian_statement", "camt.053", "n/a", "n/a", issue, "n/a", note="statement does not balance internally")
    # 7: receipts on the trust account (camt.054)
    receipts = 0
    xml54 = camt054 or (cust.camt054() if hasattr(cust, "camt054") else None)
    if xml54:
        for r in camt.parse(xml54)["reports"]:
            if ACCOUNT_IDS.get(TRUST) not in (r["account"], None):
                continue
            for e in r["entries"]:
                if e["amount"] <= 0 or e["reversal"] or (e["bank_tx_code"] or "").endswith("/BOOK"):   # internal book transfers
                    continue
                receipts += 1
                m = SUB_REF.search(" ".join(x for x in (e["end_to_end_id"], e["remittance"]) if x))
                sub = subs.get(m.group(0)) if m else None
                if sub is None:
                    brk("receipts", f"credit {e['servicer_ref'] or ''} {e['booking_date']}", "n/a", "no matching SUB- reference",
                        q(e["amount"]), q(e["amount"]), note="unidentified receipt: hold and return to sender; do not apply")
                elif D(sub["amount"]) != e["amount"] and D(sub["received"]) != D(sub["amount"]):
                    brk("receipts", m.group(0), q(D(sub["amount"])), q(D(sub["received"])), q(e["amount"]),
                        q(e["amount"] - D(sub["amount"])), "medium", note="partial or over-payment against the subscription")
    internal_refs = {r[0] for r in w.c.execute("SELECT release_ref FROM w_payouts WHERE status='paid'")}
    for ref, amt in {**adm_paid, **rail_paid}.items():
        if ref not in internal_refs:
            brk("payouts", f"partner payout {ref}", "missing", amt, "n/a", amt, note="paid by partner but not in internal records")

    summary = {"as_of_nav_date": nav["nav_date"], "nav_per_unit": nav["nav_per_unit"], "investors": len(inv),
               "units_internal": str(tot_int), "off_platform_units": str(off_units), "units_administrator": str(tot_adm), "custodian_fund_assets": str(q(cust_fund)),
               "custodian_trust": str(q(cust_trust)), "breaks": len(breaks), "custodian_source": cust_src["source"],
               "receipts_checked": receipts,
               "checks": ["units_per_investor", "units_outstanding", "value_per_investor", "fund_net_assets", "trust_cash_in_transit",
                          "payouts", "receipts", "custodian_statement"]}
    status = "clean" if not breaks else "breaks"
    rid = w.c.execute("INSERT INTO w_recon(ts,status,summary,breaks) VALUES(?,?,?,?)",
                      (w.clock(), status, json.dumps(summary), json.dumps(breaks))).lastrowid
    w._a(actor, "recon.run", id=rid, status=status, breaks=len(breaks))
    return {"id": rid, "status": status, "summary": summary, "breaks": breaks}


def runs(w, limit=30) -> list[dict]:
    return [{**dict(r), "summary": json.loads(r["summary"]), "breaks": json.loads(r["breaks"])}
            for r in w.c.execute("SELECT * FROM w_recon ORDER BY id DESC LIMIT ?", (limit,))]


def breaks_csv(w, rid) -> str:
    r = w.c.execute("SELECT * FROM w_recon WHERE id=?", (int(rid),)).fetchone()
    if not r:
        raise KeyError(f"recon run {rid}")
    buf = io.StringIO()
    cols = ["check", "subject", "internal", "administrator", "custodian", "difference", "severity", "note"]
    wr = csv.DictWriter(buf, fieldnames=cols)
    wr.writeheader()
    for b in json.loads(r["breaks"]):
        wr.writerow(b)
    return buf.getvalue()
