"""DEMO data seeding (clearly labelled DEMO everywhere). Offline, synthetic, simulation only.

Creates under <var> (default var/demo, gitignored):
  * console login + trading step-up + payments approver for the policy owner, with a RANDOM demo
    passphrase and TOTP secrets written to <var>/DEMO_CREDENTIALS.txt (0600). Nothing is committed.
  * a short synthetic paper simulation (models, decision trail, reports), strategy-research-2
    challengers + trial logs, paper positions/fills, pending approvals, kill-switch drill history,
    tax events (incl. a superficial-loss pattern and a T1135-size foreign holding), MCP tokens (hash only).
  * a second staff approver "cfo" (two-person payout approval) and an investor-portal login "alice".
  * an investor wallet (SIMULATION, fake administrator/custodian/rails in partners_sim.sqlite) with a random
    vault key in <var>/DEMO_VAULT_KEY (0600).
  * a payments DB: balances, payees (approved / cooling-off / pending), transfers in every status,
    investors, subscriptions/redemptions, fee runs, vendors/bills/budgets, reconciliation results."""
from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from atlas.governance.integrity.crypto import totp

MARKER = "DEMO_DATA_MARKER"


def _fake_clock(start: float):
    box = {"t": start}

    def clock():
        return box["t"]
    return clock, box


def seed(var: str | Path = "var/demo", config: str | Path = "config/founder", run_sim: bool = True, fresh: bool = True,
         verbose: bool = True) -> dict:
    from atlas.risk.safety import assert_paper_only
    assert_paper_only()
    v = Path(var)
    log = (lambda *a: print("[demo]", *a, flush=True)) if verbose else (lambda *a: None)
    if fresh and v.exists():
        if not (v / MARKER).exists():
            raise SystemExit(f"{v} exists and is not a demo directory (no {MARKER}); refusing to delete")
        shutil.rmtree(v)
    v.mkdir(parents=True, exist_ok=True)
    (v / MARKER).write_text("This directory holds DEMO data only (synthetic, simulation). Safe to delete.\n")
    from atlas.console.app import ConsolePaths
    p = ConsolePaths.under(v, config)
    from atlas.control.policy import load_all
    cfg = load_all(config)
    owner = cfg.risk.owner

    # ---------------------------------------------------------------- credentials (random, local, 0600)
    from atlas.risk.stepup import StepUp
    from atlas.ledgers.stepup import Approvers
    from atlas.console.auth import Users
    pw = "demo-" + secrets.token_urlsafe(15)
    Users(p.users).enroll(owner, pw)
    t_secret = StepUp(p.stepup).init(pw, owner)
    p.payments_var.mkdir(parents=True, exist_ok=True)
    pay_secret = Approvers(p.payments_var / "approvers.json").enroll(owner, pw)
    # second staff member for two-person payout approval (console login + payments approver only)
    cfo, cfo_pw = "cfo", "demo-" + secrets.token_urlsafe(15)
    Users(p.users).enroll(cfo, cfo_pw)
    cfo_secret = Approvers(p.payments_var / "approvers.json").enroll(cfo, cfo_pw)
    portal_pw = "demo-" + secrets.token_urlsafe(15)
    # wallet vault key (DEMO): random, local file 0600; `serve --demo` loads it into ATLAS_VAULT_KEY if unset
    from atlas.ledgers.wallet.vault import new_key
    vkey = new_key()
    fd = os.open(v / "DEMO_VAULT_KEY", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(vkey + "\n")
    os.environ["ATLAS_VAULT_KEY"] = vkey
    cred = v / "DEMO_CREDENTIALS.txt"

    def write_creds(extra=""):
        fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"DEMO ONLY - random local credentials for the demo console (never reuse).\n"
                    f"username={owner}\npassphrase={pw}\ntrading_totp_secret={t_secret}\npayments_totp_secret={pay_secret}\n"
                    f"cfo_username={cfo}\ncfo_passphrase={cfo_pw}\ncfo_payments_totp_secret={cfo_secret}\n" + extra)
    write_creds()

    # ---------------------------------------------------------------- trading: sim + research
    if run_sim:
        log("running a short synthetic paper simulation (~1 min) ...")
        from atlas.ops.sim import run_sim as _run
        _run(config_dir=str(config), var=str(v), start="2024-01-02", warmup_end="2024-10-31", end="2025-02-28", verbose=False)
        try:
            from atlas.strategies.sleeve_strategies.research import run_all
            run_all(str(p.models), seed=7)
        except Exception as e:  # noqa: BLE001
            log("research2 skipped:", type(e).__name__)
    p.models.mkdir(parents=True, exist_ok=True)
    p.reports.mkdir(parents=True, exist_ok=True)
    from atlas.mcp.trading.service import build_service
    svc = build_service(config, p.audit_db, p.state_db, tax_db_path=p.tax_db)
    svc.models_root = str(p.models)
    svc.heartbeat()
    _seed_trading(svc, owner, p, log)
    _seed_feeds(Path(p.reports).parent)
    from atlas.mcp.trading.tokens import TokenRegistry
    tr = TokenRegistry(p.tokens)
    tr.create("claude-desktop", {"read", "propose"}, 30)
    tr.create("ops-monitor", {"read"}, 7)
    from atlas.ops.summary import write_daily_summary
    from datetime import date
    write_daily_summary(svc, date.today(), p.reports)
    svc.persist()

    # ---------------------------------------------------------------- payments
    _seed_payments(p.payments_var, owner, pay_secret, log)
    log("seeding the investor wallet (SIMULATION, fake partners) ...")
    wr = _seed_wallet(p.payments_var, owner, pw, pay_secret, cfo, cfo_pw, cfo_secret, portal_pw, log)
    write_creds(f"portal_url=http://127.0.0.1:8770/portal\nportal_username=alice\nportal_passphrase={portal_pw}\n"
                f"portal_totp_secret={wr['portal_secret']}\n")
    log(f"done. DEMO credentials: {cred} (0600)")
    return {"var": str(v), "credentials": str(cred), "owner": owner}


_DEMO_APPROVALS = [("CASH.TO", "buy", 40, 50.02, "core", "index_etf"), ("SHOP.TO", "sell", 4, 98.7, "active", "equity"),
                   ("ETH-USD", "buy", 0.15, 3100.0, "high_risk", "crypto_spot")]


def enqueue_demo_approvals(svc, only_if_empty: bool = False) -> int:
    """Queue the sample owner approvals (queued intents; nothing executes until approved with step-up AND the
    core runs). Approvals expire after the policy TTL, so `serve --demo` re-queues them when none are pending."""
    from atlas.risk.models import OrderIntent
    if only_if_empty:
        svc.approvals.expire()
        if svc.approvals.pending():
            return 0
    for sym, side, qty, px, sleeve, ac in _DEMO_APPROVALS:
        svc.approvals.enqueue(OrderIntent(symbol=sym, side=side, qty=qty, order_type="limit", limit_price=px, reference_price=px,
                                          sleeve=sleeve, asset_class=ac, broker="ibkr" if ac != "crypto_spot" else "kraken",
                                          currency="USD" if ac == "crypto_spot" else "CAD", fx_rate_to_base=1.37 if ac == "crypto_spot" else 1.0,
                                          quote_age_s=1.0, source="strategy"))
    return len(_DEMO_APPROVALS)


def _seed_feeds(var: Path) -> None:
    """DEMO news/fundamentals caches for the autopilot feed panel (made-up text, clearly labelled; no network)."""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    d = var / "feeds"
    d.mkdir(parents=True, exist_ok=True)
    now = _dt.now(_tz.utc)
    items = [("SHOP.TO", "DEMO: Shopify merchant volumes steady in quarterly update"), ("RY.TO", "DEMO: Royal Bank holds dividend"),
             ("XIC.TO", "DEMO: TSX composite flat as energy offsets financials"), ("BTC-USD", "DEMO: Bitcoin volatility eases"),
             ("SPY", "DEMO: US equities drift ahead of central bank minutes")]
    news = [{"symbol": s, "title": t, "source": "demo", "ts": (now - _td(hours=i * 3)).isoformat(timespec="seconds")} for i, (s, t) in enumerate(items)]
    (d / "news.json").write_text(_json.dumps({"label": "DEMO DATA: not real news", "items": news}, indent=1))
    fund = {s: {"label": "DEMO", "pe": pe, "dividend_yield_pct": dy, "as_of": now.date().isoformat()}
            for s, pe, dy in (("SHOP.TO", 68.0, 0.0), ("RY.TO", 13.1, 3.6), ("XIC.TO", 17.2, 2.7), ("SPY", 24.5, 1.3))}
    (d / "fundamentals.json").write_text(_json.dumps(fund, indent=1))


def _seed_trading(svc, owner: str, p, log) -> None:
    from atlas.risk import RiskDecision
    from atlas.risk.models import OrderIntent
    from atlas.ops.equity import KEY as EQ_KEY
    from atlas.tax.events import Trade
    from atlas.tax.fx import FxQuote

    def fill(**kw):
        i = OrderIntent(order_type="market", source="owner", quote_age_s=1.0, **kw)
        d = svc.engine.evaluate(i, svc.broker.snapshot(), record_rate=False)
        if not d.approved:   # e.g. market closed when seeding: DEMO-labelled paper fill (no real broker exists)
            svc.audit.append("demo.seed_fill", {"symbol": i.symbol, "risk_reasons": d.reasons[:3]}, actor="demo")
            d = RiskDecision(intent_id=i.intent_id, approved=True, reasons=["DEMO seed"], checks={"demo_seed": True},
                             halted=False, policy_version=svc.cfg.risk.version)
        svc.broker.submit(i, d)

    book = [("XIC.TO", "core", "index_etf", "CAD", 34.10, 120, None), ("VFV.TO", "core", "index_etf", "CAD", 142.5, 30, None),
            ("ZAG.TO", "core", "index_etf", "CAD", 13.9, 200, None), ("SHOP.TO", "active", "equity", "CAD", 101.2, 12, "Technology"),
            ("RY.TO", "active", "equity", "CAD", 168.4, 6, "Financials"), ("BTC-USD", "high_risk", "crypto_spot", "USD", 64000.0, 0.012, None)]
    for sym, sleeve, ac, ccy, px, qty, sector in book:
        fill(symbol=sym, side="buy", qty=qty, reference_price=px, sleeve=sleeve, asset_class=ac, currency=ccy,
             fx_rate_to_base=1.37 if ccy == "USD" else 1.0, broker="ibkr" if ac != "crypto_spot" else "kraken", sector=sector)
    for sym, px in [("XIC.TO", 34.55), ("VFV.TO", 144.1), ("ZAG.TO", 13.85), ("SHOP.TO", 98.7), ("RY.TO", 170.2), ("BTC-USD", 65200.0)]:
        svc.broker.mark(sym, px)
    enqueue_demo_approvals(svc)
    # equity history (DEMO, synthetic random walk ending at the current paper equity)
    import random
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    eq = svc.broker.bot_equity()
    pts, x = [], eq * 0.97
    for k in range(240, 0, -1):
        x *= 1 + rnd.gauss(0.00015, 0.0018)
        pts.append([(now - timedelta(hours=3 * k)).isoformat(), round(x, 2)])
    scale = eq / x   # rescale so the walk ends exactly at the current paper equity (no artificial jump)
    pts = [[t, round(v * scale, 2)] for t, v in pts] + [[now.isoformat(), eq]]
    svc.store.set(EQ_KEY, pts)
    # kill-switch drill history (engaged then reset with step-up => history shows both)
    svc.ks.engage("DEMO drill: monthly kill-switch test", channel="console")
    svc.ks.reset(owner, True, owner)
    # tax: superficial-loss pattern + a T1135-size foreign holding (DEMO events)
    ent = svc.tax.entity
    tz = timezone(timedelta(hours=-4))
    def tq(d): return FxQuote(Decimal(1), "identity (CAD)", d.date())
    trades = [("demo-sl-1", datetime(2026, 8, 3, 10, tzinfo=tz), "DEMO.TO", "buy", 100, "50"),
              ("demo-sl-2", datetime(2026, 9, 1, 10, tzinfo=tz), "DEMO.TO", "sell", 100, "41"),
              ("demo-sl-3", datetime(2026, 9, 15, 10, tzinfo=tz), "DEMO.TO", "buy", 100, "42"),
              ("demo-g-1", datetime(2026, 2, 2, 10, tzinfo=tz), "ZAG.TO", "buy", 300, "13.50"),
              ("demo-g-2", datetime(2026, 6, 2, 10, tzinfo=tz), "ZAG.TO", "sell", 100, "14.10")]
    for tid, ts, prop, side, qty, px in trades:
        svc.tax.add(Trade(id=tid, entity=ent, venue="paper_sim", ts=ts, property=prop, side=side, qty=Decimal(qty),
                          price=Decimal(px), currency="CAD", fee=Decimal("1"), fx=tq(ts)))
    ts = datetime(2026, 3, 2, 10, tzinfo=tz)
    svc.tax.add(Trade(id="demo-us-1", entity=ent, venue="paper_sim", ts=ts, property="US-DEMO-INDEX", side="buy",
                      qty=Decimal(1100), price=Decimal("70"), currency="USD", fee=Decimal("1"), foreign=True,
                      fx=FxQuote(Decimal("1.37"), "DEMO fixed rate (NOT Bank of Canada)", ts.date())))
    log("trading demo seeded")


def _seed_payments(pvar: Path, owner: str, secret: str, log) -> None:
    from atlas.ledgers.costs import Costs
    from atlas.ledgers.db import connect
    from atlas.ledgers.fund import Fund, StubNAV
    from atlas.ledgers.manual import Manual
    from atlas.ledgers.stepup import Approvers
    from atlas.ledgers.treasury import Treasury
    import time as _t

    real = _t.time()
    aclock, abox = _fake_clock(real - 40 * 86400)
    appr = Approvers(pvar / "approvers.json", clock=aclock)

    def creds():
        abox["t"] += 61
        return owner, "", totp(secret, abox["t"])

    # passphrase is verified too: re-read it from the credentials file written by seed()
    pw = [l.split("=", 1)[1] for l in (pvar.parent / "DEMO_CREDENTIALS.txt").read_text().splitlines() if l.startswith("passphrase=")][0]

    def cr():
        o, _, code = creds()
        return o, pw, code

    tclock, tbox = _fake_clock(real - 30 * 86400)
    c = connect(str(pvar / "payments.sqlite"))
    tr = Treasury(c, appr, clock=tclock)
    tr.ledger.clock = tclock
    c.execute("INSERT OR REPLACE INTO settings VALUES('demo_nav','10.42')")
    c.execute("INSERT OR REPLACE INTO settings VALUES('demo','1')")
    L = tr.ledger
    L.post("DEMO opening balance (bank CAD)", [("asset:bank:cad", Decimal("185000"), "CAD"), ("liability:investor_capital", Decimal("-185000"), "CAD")])
    usd = Decimal("42000")
    L.post("DEMO opening balance (bank USD)", [("asset:bank:usd", usd, "USD"), ("liability:investor_capital", -tr.fx.to_cad(usd, "USD"), "CAD")])
    L.post("DEMO broker funding (IBKR)", [("asset:broker:ibkr", Decimal("15000"), "USD"), ("asset:bank:usd", Decimal("-15000"), "USD")])

    def payee(name, kind, rail, ccy, dest, approve=True):
        pid = tr.request_payee("demo", name, kind, rail, ccy, dest)
        if approve:
            tr.approve_payee(pid, *cr())
        return pid

    p_ibkr = payee("Interactive Brokers Canada (funding)", "broker", "WIRE", "CAD", "IBKR-U1234567")
    p_aws = payee("AWS Canada", "vendor", "EFT", "CAD", "003-12345-9876543")
    p_poly = payee("Polygon.io", "vendor", "WIRE", "USD", "CHASUS33-000123456789")
    p_kr = payee("Kraken (own account)", "wallet", "CRYPTO", "USDC", "0x9f3a6c2e4b71d0a8c5e2f19b7d36a40e1c58b2d7")
    p_inv = payee("Investor A (redemption)", "investor", "EFT", "CAD", "004-55555-1112223")
    tbox["t"] = real - 20 * 86400  # payees past their 24h cooling-off

    def transfer(key, pid, amt, ccy, purpose, src="asset:bank:cad", debit="liability:payables"):
        return tr.request_transfer("demo", key, pid, Decimal(amt), ccy, src, purpose, debit)

    m = Manual(tr, pvar / "sheets")
    # settled (old)
    for i, (pid, amt, ccy, src, purpose) in enumerate([(p_aws, "412.80", "CAD", "asset:bank:cad", "AWS September"),
                                                       (p_ibkr, "10000", "CAD", "asset:bank:cad", "Broker funding Q3")]):
        tid = transfer(f"demo-settled-{i}", pid, amt, ccy, purpose, src, "asset:broker:ibkr" if pid == p_ibkr else "liability:payables")
        tr.approve_transfer(tid, *cr()); m.prepare(tid); m.mark_executed(tid, f"CONF-{8800 + i}", *cr())
    settled_refs = [r[0] for r in c.execute("SELECT reference FROM manual_instructions ORDER BY transfer_id")]
    stmt = [{"date": "2026-09-30", "ref": ref, "amount": -Decimal(a), "currency": "CAD", "memo": ""} for ref, a in zip(settled_refs, ["412.80", "10000"])]
    tbox["t"] = real - 12 * 86400
    m.reconcile(stmt)
    # overdue: executed long ago, never on a statement
    tid = transfer("demo-overdue", p_poly, "1290.00", "USD", "Polygon annual data plan", "asset:bank:usd")
    tr.approve_transfer(tid, *cr()); m.prepare(tid); m.mark_executed(tid, "WIRE-77120", *cr())
    tbox["t"] = real - 1 * 86400
    m.reconcile([])  # flags overdue
    tbox["t"] = real - 3600
    # pending settlement (recent)
    tid = transfer("demo-pending-settle", p_aws, "438.15", "CAD", "AWS October")
    tr.approve_transfer(tid, *cr()); m.prepare(tid); m.mark_executed(tid, "EFT-55102", *cr())
    # instructed (sheet ready, awaiting manual execution)
    tid = transfer("demo-instructed", p_ibkr, "5000", "CAD", "Broker top-up (core sleeve)", debit="asset:broker:ibkr")
    tr.approve_transfer(tid, *cr()); m.prepare(tid)
    # approved (sheet not yet prepared)
    tid = transfer("demo-approved", p_kr, "2500", "USDC", "High-risk sleeve funding", "asset:bank:usd", "asset:broker:kraken")
    tr.approve_transfer(tid, *cr())
    # pending approval x2 and a rejected one
    transfer("demo-pending-1", p_inv, "12500", "CAD", "Investor A redemption payout (order #3)", debit="liability:redemptions_payable")
    transfer("demo-pending-2", p_poly, "199.00", "USD", "Polygon add-on (options data)", "asset:bank:usd")
    tid = transfer("demo-rejected", p_aws, "9999", "CAD", "Duplicate invoice (rejected)")
    tr.reject_transfer(tid, "demo", "duplicate invoice")
    # cooling-off and pending payees (created now)
    tbox["t"] = real - 2 * 3600
    payee("Bank of Montreal (new account)", "bank", "EFT", "CAD", "001-00011-7654321")   # approved 2h ago -> cooling-off
    payee("New data vendor (pending)", "vendor", "WIRE", "USD", "BOFAUS3N-99887766", approve=False)
    tbox["t"] = real

    # investors / fund
    f = Fund(c, L, clock=tclock)
    tbox["t"] = real - 90 * 86400
    ids = []
    for name, acc, commit in [("Investor A (DEMO)", True, "150000"), ("Investor B Holdings Ltd (DEMO)", True, "250000"),
                              ("Investor C (DEMO)", True, "80000"), ("Prospect D (DEMO, KYC pending)", False, "0")]:
        iid = f.add_investor(name, acc, commit)
        ids.append(iid)
        if acc:
            f.set_kyc(iid, "approved")
    f.subscribe(ids[0], "60000"); f.subscribe(ids[1], "120000"); f.subscribe(ids[2], "15000", method="cash")
    f.deal(StubNAV("10.00"))
    tbox["t"] = real - 45 * 86400
    f.capital_call("10", "2026-11-30")
    for period, navp in [("2026-08", "10.18"), ("2026-09", "10.31")]:
        for iid in ids[:3]:
            f.management_fee(iid, StubNAV(navp), period=period)
    f.performance_fee(ids[1], StubNAV("10.31"), period="2026-Q3")
    tbox["t"] = real - 5 * 86400
    f.subscribe(ids[2], "20000")
    f.redeem(ids[0], "1200")
    tbox["t"] = real

    # platform costs
    co = Costs(c, tr.fx, invoice_dir=str(pvar / "invoices"), clock=tclock)
    vend = {n: co.add_vendor(n, cat, ccy) for n, cat, ccy in [("Polygon.io", "data_feeds", "USD"), ("AWS Canada", "servers", "CAD"),
                                                              ("OpenAI API", "apis", "USD"), ("IBKR market data", "exchange_fees", "USD"),
                                                              ("GitHub", "software", "USD")]}
    for mth in ("2026-07", "2026-08", "2026-09", "2026-10"):
        for cat, amt in [("data_feeds", "350"), ("servers", "450"), ("apis", "120"), ("exchange_fees", "40"), ("software", "30")]:
            co.set_budget(cat, mth, amt)
    for n, amt in [("Polygon.io", "199"), ("AWS Canada", "420"), ("OpenAI API", "95"), ("IBKR market data", "14.5"), ("GitHub", "21")]:
        co.add_recurring(vend[n], amt, "2026-07")
    co.run_recurring("2026-10")
    co.add_bill(vend["OpenAI API"], "160", "2026-10")  # over budget this month
    for (bid,) in c.execute("SELECT id FROM bills WHERE month <= '2026-09'").fetchall():
        co.approve_bill(bid, appr, *cr())
        co.mark_paid(bid, None)
    log("payments demo seeded")


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="atlas-console seed-demo")
    ap.add_argument("--var", default="var/demo")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--no-sim", action="store_true")
    a = ap.parse_args(argv)
    seed(a.var, a.config, run_sim=not a.no_sim)


# ============================================================================== investor wallet (SIMULATION)
def _wallet_person(name, email, **kw):
    d = {"legal_name": name, "email": email, "entity_type": "individual", "country": "CA", "province": "ON",
         "dob_or_incorporation": "1980-01-01", "address": "100 Example Ave, Toronto ON (DEMO)", "occupation": "engineer",
         "income": "250000", "financial_assets": "600000", "net_assets": "1200000", "risk_tolerance": "high",
         "horizon_years": 5, "objective": "growth", "id_type": "passport", "id_last4": "0000"}
    d.update(kw)
    return d


def _seed_wallet(pvar: Path, owner: str, pw: str, owner_secret: str, cfo: str, cfo_pw: str, cfo_secret: str,
                 portal_pw: str, log) -> dict:
    """Synthetic fund history (14 month-ends) through the FAKE administrator/custodian/rails. Simulation only."""
    import random
    from datetime import date
    from atlas.ledgers.db import connect
    from atlas.ledgers.stepup import Approvers
    from atlas.ledgers.wallet import bankfiles, recon
    from atlas.ledgers.wallet.partners import fake_partners, month_end
    from atlas.ledgers.wallet.portal_auth import InvestorLogins
    from atlas.compliance.lists import SAMPLE_DIR, parse_dir
    from atlas.ledgers.wallet.service import SanctionsHold, Wallet
    from atlas.ledgers.wallet.vault import Vault

    rnd = random.Random(11)
    ts = lambda y, m, d: datetime(y, m, d, 15, tzinfo=timezone.utc).timestamp()  # noqa: E731
    clock, box = _fake_clock(ts(2025, 8, 1))
    c = connect(str(pvar / "payments.sqlite"))
    appr = Approvers(pvar / "approvers.json", clock=clock)
    parts = fake_partners(str(pvar / "partners_sim.sqlite"), clock)
    w = Wallet(c, parts, appr, Vault(c, clock=clock), clock)
    w.screening.load_samples(f"console:{owner}")      # SYNTHETIC sample sanctions lists (screening fails closed without lists)
    adm, cust, sim = parts.administrator, parts.custodian, parts.administrator.sim
    who = {owner: (pw, owner_secret), cfo: (cfo_pw, cfo_secret)}

    def at(y, m, d):
        box["t"] = max(box["t"], ts(y, m, d))

    def approve(pid, name):
        box["t"] += 61
        return w.approve_payout(pid, name, who[name][0], totp(who[name][1], box["t"]))

    staff = f"console:{owner}"
    # GP seed capital held at the custodian in the fund's name (off-platform holder "GP")
    sim.line("custody:cad", Decimal("1000000"), "seed capital (GP) - DEMO")
    sim.line("custody:cad", Decimal("-700000"), "fund transfer to broker accounts")
    sim.line("broker:ibkr", Decimal("600000"), "fund transfer from custody")
    sim.line("broker:kraken", Decimal("100000"), "fund transfer from custody")
    sim.c.execute("INSERT INTO adm_register VALUES('GP', '100000')")
    w.set_off_platform_refs(staff, ["GP"])

    def onboard(data, review=True):
        iid = w.create_investor(staff, data)
        w.submit_onboarding(staff, iid)
        if review:
            adm.review(w.investor(iid)["admin_ref"])            # administrator back office (SIMULATED)
            w.sync_onboarding(staff, iid)
        return iid

    def review(hid, name, decision, reason):
        box["t"] += 61
        return w.screening.review(hid, name, who[name][0], totp(who[name][1], box["t"]), decision, reason)

    def onboard_screened(data, rationale):
        """Submission held by a sanctions hit; two reviewers clear it as a false positive; then resubmit."""
        iid = w.create_investor(staff, data)
        try:
            w.submit_onboarding(staff, iid)
        except SanctionsHold:
            for h in w.screening.blocking_hits(iid):
                review(h["id"], owner, "false_positive", rationale)
                review(h["id"], cfo, "false_positive", "agree - " + rationale)
            w.submit_onboarding(staff, iid)
        adm.review(w.investor(iid)["admin_ref"])
        w.sync_onboarding(staff, iid)
        return iid

    def bank(iid, scenario="own", inst="rbc"):
        return w.bank_link_complete(staff, iid, w.bank_link_start(iid), inst, scenario)

    alice = onboard(_wallet_person("Alice Martin", "alice@example.com", id_last4="4821"))
    bank(alice, "third_party")                                    # rejected: not in her own name
    bank(alice, "own", "td")
    north = onboard_screened(_wallet_person("Northwind Holdings Ltd", "treasury@northwind.example", entity_type="corporation",
                                            dob_or_incorporation="2011-04-01", occupation="holding company", income="0",
                                            financial_assets="3000000", net_assets="8000000", horizon_years=7,
                                            beneficial_owners="Jane Northwind 60%; Raj Patel 40%"),
                             "beneficial owner Jane Northwind (Canadian resident, b. 1979) is not listed Jane Northwood (Belarus, b. 1975)")
    bank(north, "own", "bmo")
    s = w.request_subscription(staff, alice, "100000", "demo-sub-alice-1")
    at(2025, 8, 20); adm.receive_payment(s["reference"], Decimal("100000"))
    nav1 = month_end(date(2025, 8, 1))                            # last Payments Canada business day (Fri Aug 29)
    at(nav1.year, nav1.month, nav1.day); adm.deal(nav1.isoformat()); w.sync()
    at(2025, 9, 3)
    s = w.request_subscription(staff, north, "250000", "demo-sub-north-1")
    at(2025, 9, 18)                                               # paid by international wire from the US parent -> EFTR record
    adm.receive_payment(s["reference"], Decimal("250000"), "wire_international",
                        {"name": "Northwind Holdings Ltd", "address": "500 Main St, Wilmington DE 19801", "country": "US",
                         "account": "021000021-000123456789"})
    nav2 = month_end(date(2025, 9, 1))                            # Sep 30 is a closure day -> Mon Sep 29
    at(nav2.year, nav2.month, nav2.day); adm.deal(nav2.isoformat()); w.sync()
    for r in w.fintrac.records("EFTR_IN"):
        w.fintrac.mark(staff, r["id"], "handed_to_reporting_entity", "ADMIN-EFTR-2025-0912")
    # monthly market moves + NAV
    d = date(2025, 10, 31)
    while d <= date(2026, 9, 30):
        at(d.year, d.month, max(1, d.day - 10))
        cust.mark_market("broker:ibkr", Decimal(str(round(rnd.uniform(-2.5, 3.5), 2))))
        cust.mark_market("broker:kraken", Decimal(str(round(rnd.uniform(-9, 11), 2))))
        at(d.year, d.month, d.day)
        adm.deal(d.isoformat())
        w.sync()
        if d == date(2026, 8, 31):                                # Alice's lockup ends; 30 days' notice -> Sep NAV
            box["t"] += 3600
            r1 = w.request_redemption(staff, alice, "1500", "demo-red-alice-1")
            r2 = w.request_redemption(staff, alice, "800", "demo-red-alice-2")
            box["t"] += 61
            w.forward_redemption(owner, r1["id"])
            w.forward_redemption(owner, r2["id"])
        d = month_end(d + timedelta(days=5))
    # payouts created by the administrator's redemption dealing: one fully approved, one 1 of 2
    at(2026, 10, 2)
    pend = [r[0] for r in c.execute("SELECT id FROM w_payouts WHERE status='pending_approval' ORDER BY id")]
    if pend:
        approve(pend[0], owner); approve(pend[0], cfo)
        w.sync()
    if len(pend) > 1:
        approve(pend[1], owner)
    # Northwind (lockup ended 2026-09-30) asks to redeem: waits for staff to forward
    at(2026, 10, 5)
    w.request_redemption(staff, north, "3000", "demo-red-north-1")
    # Carol: OM-eligible, small subscription funded and awaiting the October NAV
    carol = onboard(_wallet_person("Carol Nguyen", "carol@example.com", income="85000", financial_assets="90000",
                                   net_assets="210000", province="BC", id_last4="1177"))
    bank(carol, "own", "desjardins")
    s = w.request_subscription(staff, carol, "8000", "demo-sub-carol-1")
    at(2026, 10, 7); adm.receive_payment(s["reference"], Decimal("8000")); w.sync()
    # Alice top-up: instructions issued (funds arrive by international wire on Oct 13)
    at(2026, 10, 9)
    s_top = w.request_subscription(staff, alice, "25000", "demo-sub-alice-2")
    # non-fund payout via a payout rail (SIM): referral reward, needs two approvers
    w.request_payout("console:ops-demo", alice, "150", "zumrails", "referral reward (DEMO, non-fund)", "demo-pay-ref-1")
    # other onboarding states
    onboard(_wallet_person("Bob Low", "bob@example.com", risk_tolerance="low", horizon_years=1, id_last4="3302"))
    try:                                                          # held by platform screening: open hit in the review queue
        onboard(_wallet_person("Sanctioned Person (DEMO)", "blocked@example.com", id_last4="9999"))
    except SanctionsHold:
        pass
    w.request_payout("console:ops-demo", carol, "75", "zumrails", "referral reward (DEMO, non-fund)", "demo-pay-carol-1")
    at(2026, 10, 10)
    recon.run(w, staff)                                           # clean run
    erin = onboard(_wallet_person("Erin Review", "erin@example.com", id_last4="5150"), review=False)
    dmitri = w.create_investor(staff, _wallet_person("Dmitri Draft", "dmitri@example.com", id_last4="2468"))
    bank(north, "own", "bmo")                                     # account change: new verified, still cooling off
    # timing breaks for the breaks report: post-NAV market move + an unidentified trust receipt
    # weekly list refresh: an OFAC update adds a (synthetic) name close to Carol -> rescreen -> open hit, payouts blocked
    at(2026, 10, 12)
    docs = parse_dir(SAMPLE_DIR)
    ofac = next(d for d in docs if d["source"] == "OFAC-SDN")
    ofac["entries"].append({"uid": "990004", "kind": "individual", "name": "Carol NGUYEN-TRAN", "names": ["Carol NGUYEN-TRAN"],
                            "dobs": ["1980"], "countries": ["Testland"], "programs": ["DEMO"], "listed_on": "", "low_quality_aliases": []})
    ofac["published"], ofac["sha256"] = "10/12/2026", "demo-update"
    w.screening.load_docs(staff, docs, sample=True)
    w.rescreen_all(staff)
    for h in w.screening.blocking_hits(carol):
        review(h["id"], owner, "false_positive", "Carol Nguyen (BC, b. 1980) vs listed Carol Nguyen-Tran: need ID re-check")
    at(2026, 10, 13)                                              # Alice's top-up arrives by wire from her US account
    adm.receive_payment(s_top["reference"], Decimal("25000"), "wire_international",
                        {"name": "Alice Martin", "country": "US", "account": "026009593-4455667788"})   # no address: travel-rule gap
    w.sync()
    bank(erin, "close", "scotia")                                 # "Erin Q. Review" at the bank: close match -> staff review
    for purpose, ok in (("service", True), ("identity_verification", True), ("statements_email", True), ("marketing", False)):
        if ok or w.privacy.has_consent(alice, purpose):
            w.privacy.record_consent("portal:alice", alice, purpose, ok, "2025-08", "portal_checkbox")
    bankfiles.export_pain001(w, staff)                            # released payouts so far -> one pain.001 (SIMULATION)
    inc = w.privacy.record_incident(staff, summary="Quarterly statement emailed to an outdated address (DEMO)", detected_at="2026-10-08",
                                    data_types=["name", "holdings"], individuals=1, investor_ids=[carol],
                                    containment="Recipient confirmed deletion; address updated")
    w.privacy.assess_incident(staff, inc, False, "Low sensitivity, recipient known and confirmed deletion", close=True)
    w.privacy.open_access_request(staff, north, "2026-10-02")
    at(2026, 10, 14)
    cust.mark_market("broker:kraken", Decimal("4.2"))
    sim.line("trust:subscriptions", Decimal("500"), "incoming EFT - no reference (DEMO)")
    res = recon.run(w, staff)
    portal_secret = InvestorLogins(pvar / "investor_logins.json").enroll("alice", portal_pw, alice)
    log(f"wallet: investors alice={alice} northwind={north} carol={carol} erin={erin} dmitri={dmitri}; "
        f"recon breaks={len(res.get('breaks', []))}")
    return {"alice": alice, "portal_secret": portal_secret}
