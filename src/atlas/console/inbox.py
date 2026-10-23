"""'Action needed' inbox for the Home page: one list aggregating everything that waits on a person, across
trading, money (treasury payments + investor wallet) and compliance. Read-only; every item links to the page
where the action is taken (with the same step-up / two-person rules as before). Counts feed the sidebar badges,
so the numbers on Home, the sidebar and each page come from the same queries."""
from __future__ import annotations

import time

SEV = {"critical": 0, "high": 1, "normal": 2, "info": 3}


def _item(area, kind, title, detail, href, severity="normal", count=1):
    return {"area": area, "kind": kind, "title": title, "detail": detail, "href": href, "severity": severity, "count": count}


def build(svc, trading, payments, wallet, demo: bool = False) -> dict:
    items: list[dict] = []
    # ------------------------------------------------------------------ trading
    if svc.ks.engaged:
        items.append(_item("trading", "kill_switch", "Trading is halted", f"Safe stop: {svc.ks.reason or 'no reason'}. Reset needs step-up.",
                           "/trading/risk", "critical"))
    pend = svc.approvals.pending()
    if pend:
        what = ", ".join(f"{a.intent.side.upper()} {a.intent.qty:g} {a.intent.symbol}" for a in pend[:3]) + (" …" if len(pend) > 3 else "")
        items.append(_item("trading", "approval", f"{len(pend)} proposed trade(s) to approve or reject",
                           f"{what}. Paper orders; each expires if you do nothing.", "/trading/approvals", "high", len(pend)))
    hb = trading.core_heartbeat()
    if not hb["healthy"]:
        items.append(_item("trading", "heartbeat", "Core process not running", "Start core, watchdog and console together with "
                           f"`atlas-console up{' --demo' if demo else ''}`.", "/trading/risk", "normal" if demo else "high"))
    # ------------------------------------------------------------------ money: own payments (treasury)
    try:
        s = payments.summary(None) if payments.available() else {"available": False}
    except Exception:  # noqa: BLE001
        s = {"available": False}
    if s.get("available"):
        if s.get("kill_switch"):
            items.append(_item("money", "payments_kill", "Payments are frozen", "Payments safe stop is on: nothing can be requested or approved.",
                               "/payments", "critical"))
        n = s.get("by_status", {}).get("pending_approval", 0)
        if n:
            items.append(_item("money", "transfer_approval", f"{n} payment(s) to approve", "Each needs two approvers with step-up.",
                               "/payments/transfers", "high", n))
        for t in s.get("pending_manual", []):
            if t.get("flag") == "overdue":
                items.append(_item("money", "manual_overdue", f"Confirm payment #{t['id']} ({t['amount']} {t['currency']})",
                                   f"{t.get('payee')}: value date {t.get('value_date')} has passed; confirm it was sent or cancel.",
                                   f"/payments/transfers/{t['id']}", "high"))
    # ------------------------------------------------------------------ money + compliance: investor wallet
    if wallet.available():
        w = wallet._w()
        c = w.c
        n = c.execute("SELECT COUNT(*) FROM w_payouts WHERE status='pending_approval'").fetchone()[0]
        if n:
            items.append(_item("money", "payout_approval", f"{n} investor payout(s) to approve", "Two different approvers, each with step-up.",
                               "/wallet/payouts", "high", n))
        n = c.execute("SELECT COUNT(*) FROM w_reds WHERE status='requested'").fetchone()[0]
        if n:
            items.append(_item("money", "redemption_forward", f"{n} redemption request(s) to send to the administrator", "Forwarding needs step-up.",
                               "/wallet/redemptions", "normal", n))
        last = c.execute("SELECT id, breaks FROM w_recon ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            import json
            nb = len(json.loads(last["breaks"]))
            if nb:
                items.append(_item("money", "recon_breaks", f"{nb} reconciliation difference(s)", "Internal records differ from the administrator or custodian.",
                                   "/wallet/recon", "high", nb))
        nr = len(w.name_reviews("pending"))
        if nr:
            items.append(_item("compliance", "name_review", f"{nr} bank account name(s) to check", "Bank name is close to, but not exactly, the investor's name.",
                               "/compliance", "normal", nr))
        sc = w.screening
        st = sc.status()
        if st["blocking_hits"]:
            items.append(_item("compliance", "sanctions_hits", f"{st['blocking_hits']} possible sanctions match(es) to review",
                               "Money movement for these investors is on hold until two reviewers decide.", "/compliance", "critical", st["blocking_hits"]))
        if not st["lists"]:
            items.append(_item("compliance", "sanctions_lists", "No sanctions lists loaded", "Everything is on hold (fail-closed). Load the lists.",
                               "/compliance", "critical"))
        elif any(x.get("stale") for x in st["lists"]):
            items.append(_item("compliance", "sanctions_stale", "Sanctions lists are out of date", "Download and load the latest lists.",
                               "/compliance", "high"))
        f = w.fintrac.status()
        if f["open"]:
            items.append(_item("compliance", "fintrac_records", f"{f['open']} FINTRAC record(s) to complete",
                               f"{f['overdue']} overdue, {f['travel_rule_incomplete']} missing sender/receiver details. Records only; nothing is filed here.",
                               "/compliance", "high" if f["overdue"] else "normal", f["open"]))
        pv = w.privacy.status()
        if pv["open_access_requests"]:
            items.append(_item("compliance", "access_requests", f"{pv['open_access_requests']} personal-data access request(s)",
                               f"{pv['overdue_access_requests']} past the 30-day deadline.", "/compliance", "high" if pv["overdue_access_requests"] else "normal",
                               pv["open_access_requests"]))
        if pv["open_incidents"]:
            items.append(_item("compliance", "privacy_incidents", f"{pv['open_incidents']} privacy incident(s) open", "Assess the risk of harm and close.",
                               "/compliance", "normal", pv["open_incidents"]))
    items.sort(key=lambda x: (SEV[x["severity"]], x["area"]))
    counts = {a: sum(i["count"] for i in items if i["area"] == a) for a in ("trading", "money", "compliance")}
    counts["total"] = sum(counts.values())
    return {"items": items, "counts": counts, "generated_at": time.time()}
