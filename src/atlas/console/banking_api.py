"""Wallet banking + compliance endpoints (SIMULATION / OFFLINE), mixed into WalletAPI. No network imports.

Staff console (/api/w/*):
  reads: compliance overview (sanctions status, hit queue, FINTRAC records, ID-verification records), business-day
    calendar, identifier validation, payment files (metadata), custodian camt.053 / camt.054 export
  login + CSRF: load sanctions lists from LOCAL files (var/sanctions, or the synthetic samples), rescreen, FINTRAC
    receipt scan + workflow marks, upload camt.053/054 for reconciliation
  step-up (payments approver): sanctions hit disposition (two DISTINCT reviewers), generate / re-download a pain.001
    (contains full account numbers), apply a pain.002 status report
  SIMULATION hook: simulated bank pain.002 answer for a generated file.
  privacy (PIPEDA / Law 25 records): incident register, access requests (export needs step-up: it contains the
    investor's personal information), consent history; close-match bank-holder name review (step-up)."""
from __future__ import annotations

import datetime as dt

from atlas.ledgers.banking import bankids, calendars
from atlas.ledgers.banking.iso20022 import camt, validate, xsd_available
from atlas.ledgers.wallet import bankfiles, recon

from atlas.console.web import HTTPError, Request, Response

MAX_XML = 5_000_000


def _xml(b, key):
    x = b.get(key)
    if not isinstance(x, str) or not x.strip():
        raise ValueError(f"{key}: XML text required")
    if len(x) > MAX_XML:
        raise ValueError(f"{key}: too large")
    return x


class BankingRoutes:
    def banking_routes(self, g, post) -> None:
        g("/api/w/compliance", self.compliance)
        g("/api/w/compliance/hits", self.hits)
        post("/api/w/compliance/hits/<hid>/review", self.review_hit, stepup="payments")
        post("/api/w/compliance/sanctions/load", self.sanctions_load)
        post("/api/w/compliance/rescreen", self.rescreen)
        g("/api/w/compliance/fintrac", self.fintrac)
        post("/api/w/compliance/fintrac/scan", self.fintrac_scan)
        post("/api/w/compliance/fintrac/<rid>/mark", self.fintrac_mark)
        g("/api/w/banking/calendar", self.calendar)
        post("/api/w/banking/validate", self.validate_id)
        g("/api/w/bankfiles", self.bankfiles)
        g("/api/w/bankfiles/camt053.xml", self.camt053)
        g("/api/w/bankfiles/camt054.xml", self.camt054)
        post("/api/w/bankfiles/pain001", self.pain001, stepup="payments")
        post("/api/w/bankfiles/<fid>/xml", self.pain001_xml, stepup="payments")
        post("/api/w/bankfiles/pain002", self.pain002, stepup="payments")
        post("/api/w/bankfiles/<fid>/simulate", self.pain002_sim, stepup="payments")
        post("/api/w/bankfiles/camt/recon", self.camt_recon)
        post("/api/w/bankfiles/cpa005", self.cpa005, stepup="payments")
        post("/api/w/banks/<bid>/name-review", self.name_review, stepup="payments")
        g("/api/w/privacy", self.privacy)
        post("/api/w/privacy/incidents", self.incident_new)
        post("/api/w/privacy/incidents/<inc>/assess", self.incident_assess)
        post("/api/w/privacy/access", self.access_new)
        post("/api/w/privacy/access/<rid>/extend", self.access_extend)
        post("/api/w/privacy/access/<rid>/export", self.access_export, stepup="payments")

    # ------------------------------------------------------------------ compliance
    def compliance(self, req: Request):
        w = self._w()
        names = self._names(w)
        sc = w.screening
        hits = [h | {"investor": names.get(h["investor_id"])} for h in sc.hits(limit=100)]
        today = dt.date.fromtimestamp(w.clock())
        upcoming = [r for r in calendars.calendar_view(today.year) + calendars.calendar_view(today.year + 1) if r["date"] >= today.isoformat()][:6]
        return {"sanctions": sc.status(), "hits": hits, "fintrac": w.fintrac.status(),
                "records": [r | {"investor": names.get(r["investor_id"])} for r in w.fintrac.records()][:100],
                "id_verifications": [v | {"investor": names.get(v["investor_id"])} for v in w.fintrac.id_verifications()][:100],
                "calendar": {"today": today.isoformat(), "is_business_day": calendars.is_business_day(today),
                             "next_business_day": calendars.next_business_day(today).isoformat(), "upcoming_closures": upcoming,
                             "next_dealing_date": w.dealing_date()},
                "note": "Internal controls and records only. Nothing is filed with FINTRAC from this app."}

    def hits(self, req: Request):
        w = self._w()
        names = self._names(w)
        return {"hits": [h | {"investor": names.get(h["investor_id"])} for h in w.screening.hits(req.query.get("status") or None)]}

    def review_hit(self, req: Request):
        b = req.body
        return self._w(req).screening.review(int(req.params["hid"]), req.stepup_user, "", "", str(b.get("decision", "")), str(b.get("reason", "")))

    def sanctions_load(self, req: Request):
        w = self._w()
        src = str(req.body.get("source", "var"))
        if src == "samples":
            res = w.screening.load_samples(self._actor(req))
        elif src == "var":
            d = self.var.parent / "sanctions" if (self.var.parent / "sanctions").exists() else self.var / "sanctions"
            if not d.exists():
                raise KeyError("no local list directory: run `python tools/fetch_sanctions_lists.py --out var/sanctions` first")
            res = w.screening.load_dir(self._actor(req), d)
        else:
            raise ValueError("source: var | samples")
        return {"loaded": res, "rescreen": w.rescreen_all(self._actor(req))}

    def rescreen(self, req: Request):
        return self._w().rescreen_all(self._actor(req))

    def fintrac(self, req: Request):
        w = self._w()
        names = self._names(w)
        return {"status": w.fintrac.status(), "records": [r | {"investor": names.get(r["investor_id"])} for r in w.fintrac.records(req.query.get("kind"))]}

    def fintrac_scan(self, req: Request):
        return self._w().fintrac_scan(self._actor(req))

    def fintrac_mark(self, req: Request):
        b = req.body
        w = self._w()
        w.fintrac.mark(self._actor(req), int(req.params["rid"]), str(b.get("status", "")), str(b.get("external_ref", "")), str(b.get("note", "")))
        return {"ok": True}

    # ------------------------------------------------------------------ banking utilities
    def calendar(self, req: Request):
        year = int(req.query.get("year") or dt.date.today().year)
        region = str(req.query.get("region") or "CA")
        return {"year": year, "region": region, "closures": calendars.calendar_view(year, region), "regions": list(calendars.REGIONS)}

    def validate_id(self, req: Request):
        b = req.body
        try:
            return bankids.validate_any(str(b.get("kind", "")), str(b.get("value", "")), institution=b.get("institution"), transit=b.get("transit"))
        except bankids.InvalidIdentifier as e:
            return {"valid": False, "error": str(e)}

    # ------------------------------------------------------------------ ISO 20022 files
    def bankfiles(self, req: Request):
        w = self._w()
        waiting = w.c.execute("SELECT COUNT(*) FROM w_payouts WHERE status IN ('paid','released') AND release_ref IS NOT NULL").fetchone()[0]
        files = bankfiles.payfiles(w)
        filed = sum(f["n"] for f in files)
        doc = camt.parse(w.p.custodian.camt053()) if hasattr(w.p.custodian, "camt053") else None
        return {"files": files, "payouts_waiting": max(waiting - filed, 0), "xsd_validation": xsd_available(),
                "statement": {"msg_id": doc["msg_id"], "reports": [{k: r[k] for k in ("account", "currency", "opening", "closing", "check")} |
                                                                    {"entries": len(r["entries"])} for r in doc["reports"]]} if doc else None,
                "messages": ["pain.001.001.09", "pain.002.001.10", "camt.053.001.08", "camt.054.001.08"]}

    def camt053(self, req: Request):
        w = self._w()
        return Response.download(w.p.custodian.camt053(req.query.get("from"), req.query.get("to")), "application/xml",
                                 f"camt053_{dt.date.fromtimestamp(w.clock()):%Y%m%d}.xml")

    def camt054(self, req: Request):
        w = self._w()
        return Response.download(w.p.custodian.camt054(), "application/xml", f"camt054_{dt.date.fromtimestamp(w.clock()):%Y%m%d}.xml")

    def pain001(self, req: Request):
        w = self._w(req)
        ids = req.body.get("payout_ids")
        f = bankfiles.export_pain001(w, f"console:{req.stepup_user}", [int(i) for i in ids] if ids else None)
        return {"file": f, "xml": bankfiles.payfile(w, f["id"], with_xml=True)["xml"]}

    def pain001_xml(self, req: Request):
        w = self._w(req)
        f = bankfiles.payfile(w, int(req.params["fid"]), with_xml=True)
        w._a(f"console:{req.stepup_user}", "bankfile.download", id=f["id"], msg_id=f["msg_id"])
        return {"msg_id": f["msg_id"], "xml": f["xml"]}

    def pain002(self, req: Request):
        return bankfiles.apply_pain002(self._w(req), f"console:{req.stepup_user}", _xml(req.body, "xml"))

    def pain002_sim(self, req: Request):
        w = self._w(req)
        if not self.sim_enabled(w):
            raise HTTPError(404, "simulation hooks exist only with offline fake partners")
        rej = {str(e): str(req.body.get("reason") or "AC01") for e in (req.body.get("reject") or [])}
        xml = bankfiles.simulate_bank_response(w, int(req.params["fid"]), rej)
        return {"xml": xml, "applied": bankfiles.apply_pain002(w, f"console:{req.stepup_user}", xml)}

    def camt_recon(self, req: Request):
        b = req.body
        x53 = _xml(b, "camt053") if b.get("camt053") else None
        x54 = _xml(b, "camt054") if b.get("camt054") else None
        for x in (x53, x54):
            if x:
                validate(x)
        return recon.run(self._w(), self._actor(req), camt053=x53, camt054=x54)

    def cpa005(self, req: Request):
        w = self._w(req)
        ids = req.body.get("payout_ids")
        f = bankfiles.export_cpa005(w, f"console:{req.stepup_user}", [int(i) for i in ids] if ids else None)
        return {"file": f, "text": bankfiles.payfile(w, f["id"], with_xml=True)["xml"]}

    # ------------------------------------------------------------------ name review + privacy
    def name_review(self, req: Request):
        b = req.body
        return self._w(req).review_bank_name(f"console:{req.stepup_user}", int(req.params["bid"]), bool(b.get("approve")), str(b.get("reason", "")))

    def privacy(self, req: Request):
        w = self._w()
        names = self._names(w)
        pv = w.privacy
        return {"status": pv.status(), "incidents": pv.incidents(),
                "access_requests": [r | {"investor": names.get(r["investor_id"])} for r in pv.access_requests()],
                "name_reviews": [r | {"investor": names.get(r["investor_id"])} for r in w.name_reviews()],
                "note": "Records only (PIPEDA s.10.1-10.3 / Quebec Law 25). Breach reports to the OPC/CAI are made outside this app."}

    def incident_new(self, req: Request):
        b = req.body
        types = b.get("data_types") or []
        types = [t.strip() for t in (types.split(",") if isinstance(types, str) else types) if str(t).strip()]
        return {"id": self._w().privacy.record_incident(self._actor(req), summary=str(b.get("summary", "")), detected_at=str(b.get("detected_at", "")),
                                                        data_types=types, individuals=int(b.get("individuals") or 0),
                                                        cause=str(b.get("cause", "")), containment=str(b.get("containment", "")))}

    def incident_assess(self, req: Request):
        b = req.body
        return self._w().privacy.assess_incident(self._actor(req), int(req.params["inc"]), str(b.get("rrosh")) in ("1", "true", "True", "yes"),
                                                 str(b.get("reason", "")), b.get("regulator_notified_at") or None,
                                                 b.get("individuals_notified_at") or None, bool(b.get("close")))

    def access_new(self, req: Request):
        b = req.body
        w = self._w()
        w.investor(int(b.get("investor_id") or 0))
        return w.privacy.open_access_request(self._actor(req), int(b["investor_id"]), b.get("received_on") or None)

    def access_extend(self, req: Request):
        return self._w().privacy.extend_access_request(self._actor(req), int(req.params["rid"]), str(req.body.get("reason", "")))

    def access_export(self, req: Request):
        w = self._w(req)
        r = w.privacy.access_request(int(req.params["rid"]))
        return w.access_export(f"console:{req.stepup_user}", r["investor_id"], r["id"])
