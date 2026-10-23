"""Investor wallet endpoints (SIMULATION). Never imports tradingbot. The platform never holds investor money:
these routes read balances/registers from the (fake) administrator and custodian and orchestrate requests.

Staff console (/api/w/*, owner/staff session):
  reads: summary, investor wallet, subscriptions, redemptions, payouts, recon runs + breaks CSV, partners, statements
  login + CSRF: create investor (data collection), submit onboarding, sync decisions, start bank link, request
    subscription instructions, cancel, request non-fund payout, reject, sync from administrator, run recon
  step-up (payments approver): complete bank verification (account change), forward a redemption to the
    administrator, approve a payout (TWO distinct approvers; the requester cannot approve)
  SIMULATION hooks (fake partners only): administrator review, incoming payment, month-end dealing, market move
Investor portal (/api/i/*, investor session; only the logged-in investor's own data):
  reads: own wallet, own statements; login + CSRF: request subscription instructions, cancel own unfunded
  subscription; investor step-up (passphrase + TOTP): redemption request, bank-account verification."""
from __future__ import annotations

import secrets
from pathlib import Path

from atlas.ledgers.db import connect
from atlas.ledgers.money import D
from atlas.ledgers.stepup import Approvers
from atlas.ledgers.wallet import recon
from atlas.ledgers.wallet.partners import FakeAdministrator, fake_partners
from atlas.ledgers.wallet.portal_auth import InvestorLogins
from atlas.ledgers.wallet.service import SanctionsHold, Wallet

from atlas.console.banking_api import BankingRoutes
from atlas.console.payments_api import _StepUpPassthrough
from atlas.console.web import HTTPError, Request, Response, Router

SIM_PATH = "partners_sim.sqlite"
HOLD_MSG = "This request is on hold pending a routine review. Please contact the fund administrator."


class _no_tipping_off:
    """Investors never learn that a sanctions screen caused a hold (generic message; details stay staff-side)."""
    def __enter__(self):
        return self

    def __exit__(self, et, e, tb):
        if et is not None and issubclass(et, SanctionsHold):
            raise PermissionError(HOLD_MSG) from None
        return False


class WalletAPI(BankingRoutes):
    def __init__(self, var_dir: str | Path):
        self.var = Path(var_dir)
        self.db = str(self.var / "payments.sqlite")
        self.approvers = Approvers(self.var / "approvers.json")
        self.logins = InvestorLogins(self.var / "investor_logins.json")

    def _w(self, req: Request | None = None) -> Wallet:
        if not Path(self.db).exists():
            raise KeyError("payments database not initialised (run atlas-console seed-demo)")
        auth = _StepUpPassthrough(req.stepup_user) if req is not None and req.stepup_user else self.approvers
        return Wallet(connect(self.db), fake_partners(str(self.var / SIM_PATH)), auth)

    def available(self) -> bool:
        return Path(self.db).exists()

    def sim_enabled(self, w: Wallet) -> bool:
        return isinstance(w.p.administrator, FakeAdministrator)

    # ------------------------------------------------------------------ portal auth hooks
    def portal_login(self, username: str, passphrase: str) -> int:
        return self.logins.check(username, passphrase)

    def verify_investor_stepup(self, session, passphrase: str, code: str) -> bool:
        try:
            return self.logins.verify(session.user, passphrase, code) == session.meta.get("investor_id")
        except PermissionError:
            return False

    # ------------------------------------------------------------------ routes
    def routes(self, r: Router) -> None:
        g = lambda p, f, **k: r.add("GET", p, f, **k)  # noqa: E731
        post = lambda p, f, **k: r.add("POST", p, f, **k)  # noqa: E731
        g("/api/w/summary", self.summary)
        g("/api/w/investors/<iid>", self.investor)
        g("/api/w/investors/<iid>/statement/<fmt>", self.statement)
        g("/api/w/subscriptions", self.subscriptions)
        g("/api/w/redemptions", self.redemptions)
        g("/api/w/payouts", self.payouts)
        g("/api/w/recon", self.recon_runs)
        g("/api/w/recon/<rid>/breaks.csv", self.breaks_csv)
        g("/api/w/partners", self.partners)
        post("/api/w/investors", self.create_investor)
        post("/api/w/investors/<iid>/submit", self.submit)
        post("/api/w/investors/<iid>/sync", self.sync_investor)
        post("/api/w/investors/<iid>/bank/start", self.bank_start)
        post("/api/w/investors/<iid>/bank/complete", self.bank_complete, stepup="payments")
        post("/api/w/banks/<bid>/revoke", self.bank_revoke)
        post("/api/w/subscriptions", self.request_subscription)
        post("/api/w/subscriptions/<sid>/cancel", self.cancel_subscription)
        post("/api/w/investors/<iid>/redemptions", self.request_redemption)
        post("/api/w/redemptions/<rid>/forward", self.forward, stepup="payments")
        post("/api/w/redemptions/<rid>/cancel", self.cancel_redemption)
        post("/api/w/payouts", self.request_payout)
        post("/api/w/payouts/<pid>/approve", self.approve_payout, stepup="payments")
        post("/api/w/payouts/<pid>/reject", self.reject_payout)
        post("/api/w/sync", self.sync)
        post("/api/w/recon/run", self.recon_run)
        post("/api/w/sim/review/<iid>", self.sim_review)
        post("/api/w/sim/receive/<sid>", self.sim_receive)
        post("/api/w/sim/deal", self.sim_deal)
        post("/api/w/sim/market", self.sim_market)
        self.banking_routes(g, post)
        # investor portal: own data only
        g("/api/i/me", self.i_me, role="investor")
        g("/api/i/statement/<fmt>", self.i_statement, role="investor")
        post("/api/i/subscriptions", self.i_subscribe, role="investor")
        post("/api/i/subscriptions/<sid>/cancel", self.i_cancel, role="investor")
        post("/api/i/redemptions", self.i_redeem, role="investor", stepup="investor")
        post("/api/i/bank/start", self.i_bank_start, role="investor")
        post("/api/i/bank/complete", self.i_bank_complete, role="investor", stepup="investor")

    # ------------------------------------------------------------------ staff reads
    def summary(self, req: Request):
        if not self.available():
            return {"available": False}
        w = self._w()
        k = w.c.execute("SELECT v FROM settings WHERE k='kill'").fetchone()
        return {"available": True, **w.overview(), "partners": w.p.info(), "sim": self.sim_enabled(w),
                "kill_switch": bool(k and k[0] == "1"), "portal_users": self.logins.users(),
                "custodian": w.p.custodian.statement()["accounts"], "nav_history": w.p.administrator.nav_history(),
                "compliance_blocking": w.screening.status()["blocking_hits"], "fintrac_open": w.fintrac.status()["open"],
                "principle": "The platform never holds investor money. Balances are read from the administrator/custodian."}

    def investor(self, req: Request):
        w = self._w()
        iid = int(req.params["iid"])
        out = w.investor_wallet(iid)
        try:
            p = w.pii(iid)
            out["collected"] = {k: v for k, v in p.items() if k not in ("id_last4",)} | {"id_last4": "••" + str(p.get("id_last4", ""))[-2:]}
        except Exception as e:  # noqa: BLE001  vault unavailable: still show the wallet
            out["collected"] = {"error": f"vault unavailable: {type(e).__name__}"}
        out["portal_users"] = [u["username"] for u in self.logins.users() if u["investor_id"] == iid]
        return out

    def statement(self, req: Request):
        w = self._w()
        iid, fmt = int(req.params["iid"]), req.params["fmt"]
        return self._statement(w, iid, fmt)

    @staticmethod
    def _statement(w, iid, fmt):
        name = w.investor(iid)["legal_name"].replace(" ", "_")[:40]
        if fmt == "csv":
            return Response.download(w.statement_csv(iid), "text/csv", f"wallet_statement_{name}.csv")
        if fmt == "pdf":
            return Response.download(w.statement_pdf(iid), "application/pdf", f"wallet_statement_{name}.pdf")
        raise KeyError(fmt)

    def _names(self, w):
        return {r[0]: r[1] for r in w.c.execute("SELECT id, legal_name FROM w_investors")}

    def subscriptions(self, req: Request):
        w = self._w()
        n = self._names(w)
        rows = [w.subscription(r[0]) | {"investor": n.get(r[1])} for r in w.c.execute("SELECT id, investor_id FROM w_subs ORDER BY id DESC")]
        st = req.query.get("status")
        return {"subscriptions": [x for x in rows if not st or x["status"] == st]}

    def redemptions(self, req: Request):
        w = self._w()
        n = self._names(w)
        return {"redemptions": [dict(r) | {"investor": n.get(r["investor_id"])} for r in w.c.execute("SELECT * FROM w_reds ORDER BY id DESC")],
                "terms": w.terms(), "next_dealing_date": w.dealing_date()}

    def payouts(self, req: Request):
        w = self._w()
        n = self._names(w)
        held = {r[0] for r in w.c.execute("SELECT DISTINCT investor_id FROM s_hits WHERE status IN ('open','pending_second','escalated','confirmed')")}
        return {"payouts": [w.payout(r[0]) | {"investor": n.get(r[1]), "sanctions_hold": r[1] in held and w.payout(r[0])["status"] == "pending_approval"}
                            for r in w.c.execute("SELECT id, investor_id FROM w_payouts ORDER BY id DESC")],
                "rails": sorted(w.p.rails), "required_approvals": 2}

    def recon_runs(self, req: Request):
        return {"runs": recon.runs(self._w(), 30)}

    def breaks_csv(self, req: Request):
        rid = int(req.params["rid"])
        return Response.download(recon.breaks_csv(self._w(), rid), "text/csv", f"wallet_recon_breaks_{rid}.csv")

    def partners(self, req: Request):
        w = self._w()
        return {"partners": w.p.info(), "sim": self.sim_enabled(w),
                "note": "Real adapters are disabled in this build (no network code). Offline fakes simulate the partners."}

    # ------------------------------------------------------------------ staff writes
    @staticmethod
    def _actor(req):
        return f"console:{req.session.user}"

    def create_investor(self, req: Request):
        w = self._w()
        iid = w.create_investor(self._actor(req), dict(req.body))
        return {"id": iid, "status": "draft"}

    def submit(self, req: Request):
        w = self._w()
        ref = w.submit_onboarding(self._actor(req), int(req.params["iid"]))
        return {"admin_ref": ref, "status": "submitted", "note": "the administrator/dealer performs KYC, eligibility, suitability and screening"}

    def sync_investor(self, req: Request):
        return self._w().sync_onboarding(self._actor(req), int(req.params["iid"]))

    def bank_start(self, req: Request):
        return {"link_token": self._w().bank_link_start(int(req.params["iid"])), "institutions": ["rbc", "td", "bmo", "scotia", "cibc", "desjardins"]}

    def bank_complete(self, req: Request):
        b = req.body
        return self._w(req).bank_link_complete(f"console:{req.stepup_user}", int(req.params["iid"]), str(b.get("link_token", "")),
                                               str(b.get("institution", "")), str(b.get("scenario", "own")))

    def bank_revoke(self, req: Request):
        self._w().revoke_bank(self._actor(req), int(req.params["bid"]))
        return {"revoked": True}

    def request_subscription(self, req: Request):
        b = req.body
        return self._w().request_subscription(self._actor(req), int(b.get("investor_id", 0)), str(b.get("amount", "")),
                                              str(b.get("idem_key") or "w-" + secrets.token_hex(8))[:64])

    def cancel_subscription(self, req: Request):
        self._w().cancel_subscription(self._actor(req), int(req.params["sid"]))
        return {"cancelled": True}

    def request_redemption(self, req: Request):
        b = req.body
        return self._w().request_redemption(self._actor(req), int(req.params["iid"]), str(b.get("units", "")),
                                            str(b.get("idem_key") or "wr-" + secrets.token_hex(8))[:64])

    def forward(self, req: Request):
        return self._w(req).forward_redemption(req.stepup_user, int(req.params["rid"]))

    def cancel_redemption(self, req: Request):
        self._w().reject_redemption(self._actor(req), int(req.params["rid"]), str(req.body.get("reason", "")))
        return {"cancelled": True}

    def request_payout(self, req: Request):
        b = req.body
        return self._w().request_payout(self._actor(req), int(b.get("investor_id", 0)), str(b.get("amount", "")), str(b.get("rail", "")),
                                        str(b.get("purpose", "")), str(b.get("idem_key") or "p-" + secrets.token_hex(8))[:64])

    def approve_payout(self, req: Request):
        return self._w(req).approve_payout(int(req.params["pid"]), req.stepup_user, "", "")

    def reject_payout(self, req: Request):
        self._w().reject_payout(self._actor(req), int(req.params["pid"]), str(req.body.get("reason", "")))
        return {"rejected": True}

    def sync(self, req: Request):
        return self._w().sync(self._actor(req))

    def recon_run(self, req: Request):
        return recon.run(self._w(), self._actor(req))

    # ------------------------------------------------------------------ SIMULATION hooks (fake partners only)
    def _sim(self) -> Wallet:
        w = self._w()
        if not self.sim_enabled(w):
            raise HTTPError(404, "simulation hooks exist only with offline fake partners")
        return w

    def sim_review(self, req: Request):
        w = self._sim()
        inv = w.investor(int(req.params["iid"]))
        if not inv["admin_ref"]:
            raise ValueError("not submitted")
        w.p.administrator.review(inv["admin_ref"])
        w._a(self._actor(req), "sim.administrator_review", investor=inv["id"])
        return w.sync_onboarding(self._actor(req), inv["id"])

    def sim_receive(self, req: Request):
        w = self._sim()
        s = w.subscription(int(req.params["sid"]))
        amt = D(str(req.body.get("amount") or s["amount"]))
        w.p.administrator.receive_payment(s["reference"], amt)
        w._a(self._actor(req), "sim.incoming_payment", reference=s["reference"], amount=str(amt))
        return w.sync(self._actor(req))

    def sim_deal(self, req: Request):
        w = self._sim()
        nav_date = str(req.body.get("nav_date") or w.dealing_date(w.clock() - int(w.terms()["notice_days"]) * 86400))
        res = w.p.administrator.deal(nav_date, gate_pct=str(w.terms()["gate_pct"]))
        w._a(self._actor(req), "sim.administrator_deal", **{k: v for k, v in res.items() if k in ("nav_date", "closing_nav")})
        return {"deal": res, "sync": w.sync(self._actor(req))}

    def sim_market(self, req: Request):
        w = self._sim()
        chg = w.p.custodian.mark_market(str(req.body.get("account", "broker:ibkr")), D(str(req.body.get("pct", "1"))))
        return {"change": str(chg)}

    # ------------------------------------------------------------------ investor portal (own data only)
    @staticmethod
    def _iid(req) -> int:
        iid = req.session.meta.get("investor_id")
        if not iid:
            raise PermissionError("no investor bound to this session")
        return int(iid)

    def i_me(self, req: Request):
        w = self._w()
        out = w.investor_wallet(self._iid(req))
        out.pop("ledger", None)
        for p in out["payouts"]:
            p.pop("approvals", None)
        # Fund-level NAV per unit only (no fund totals) so the portal can draw a NAV sparkline.
        out["nav_history"] = [{"nav_date": x["nav_date"], "nav_per_unit": x["nav_per_unit"]} for x in w.p.administrator.nav_history()]
        return out

    def i_statement(self, req: Request):
        return self._statement(self._w(), self._iid(req), req.params["fmt"])

    def i_subscribe(self, req: Request):
        b = req.body
        with _no_tipping_off():
            return self._w().request_subscription(f"investor:{req.session.user}", self._iid(req), str(b.get("amount", "")),
                                              str(b.get("idem_key") or "i-" + secrets.token_hex(8))[:64])

    def i_cancel(self, req: Request):
        w = self._w()
        sid = int(req.params["sid"])
        if w.subscription(sid)["investor_id"] != self._iid(req):
            raise KeyError(sid)                             # not yours: indistinguishable from missing
        w.cancel_subscription(f"investor:{req.session.user}", sid)
        return {"cancelled": True}

    def i_redeem(self, req: Request):
        b = req.body
        with _no_tipping_off():
            return self._w().request_redemption(f"investor:{req.session.user}", self._iid(req), str(b.get("units", "")),
                                            str(b.get("idem_key") or "ir-" + secrets.token_hex(8))[:64])

    def i_bank_start(self, req: Request):
        return {"link_token": self._w().bank_link_start(self._iid(req)), "institutions": ["rbc", "td", "bmo", "scotia", "cibc", "desjardins"]}

    def i_bank_complete(self, req: Request):
        b = req.body
        with _no_tipping_off():
            return self._w().bank_link_complete(f"investor:{req.session.user}", self._iid(req), str(b.get("link_token", "")),
                                            str(b.get("institution", "")), str(b.get("scenario", "own")))
