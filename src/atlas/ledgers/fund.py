"""Fund investor operations (SIMULATION; not legal/tax advice).

- Subscriptions/redemptions are queued and dealt at the NEXT NAV (forward pricing).
- KYC/AML gates are placeholders: accredited-investor flag + kyc_status must be
  'approved' before subscribing. FINTRAC-style large cash (>= CAD 10,000) and
  suspicious-activity flags are RECORDS ONLY; nothing is filed.
- Fees: management fee accrual and performance fee vs per-investor high-water
  mark (per-unit), crystallized by redeeming fee-equivalent units.
Redemption PAYOUTS still go through Treasury (allowlist + approval)."""
from __future__ import annotations
from decimal import Decimal
from typing import Protocol
from atlas.ledgers import audit
from atlas.ledgers.db import now, tx
from atlas.ledgers.ledger import Ledger
from atlas.ledgers.money import D, q

LARGE_CASH_CAD = Decimal("10000")

class NAVSource(Protocol):
    def nav_per_unit(self) -> Decimal: ...

class StubNAV:
    """Placeholder for a read-only NAV feed from the fund administrator / trading side."""
    def __init__(self, nav="10.00"): self.nav = D(nav)
    def nav_per_unit(self) -> Decimal: return self.nav

class GateError(PermissionError): ...

class Fund:
    def __init__(self, c, ledger: Ledger, clock=now):
        self.c, self.ledger, self.clock = c, ledger, clock

    def _a(self, actor, action, **d): audit.append(self.c, actor, action, d, self.clock)

    def add_investor(self, name, accredited=False, committed="0") -> int:
        i = self.c.execute("INSERT INTO investors(name,accredited,kyc_status,units,hwm,committed,called) VALUES(?,?,?,?,?,?,?)",
                           (name, int(accredited), "pending", "0", "0", str(D(committed)), "0")).lastrowid
        self._a("ops", "investor.add", id=i, name=name)
        return i

    def set_kyc(self, iid, status, actor="compliance"):
        assert status in ("pending", "approved", "rejected")
        self.c.execute("UPDATE investors SET kyc_status=? WHERE id=?", (status, iid))
        self._a(actor, "investor.kyc", id=iid, status=status)

    def investor(self, iid): return self.c.execute("SELECT * FROM investors WHERE id=?", (iid,)).fetchone()

    def flag(self, iid, kind, detail):
        self.c.execute("INSERT INTO compliance_flags(investor_id,kind,detail,ts) VALUES(?,?,?,?)", (iid, kind, detail, self.clock()))
        self._a("compliance", "flag." + kind, investor=iid, detail=detail)

    def flags(self, iid=None):
        sql = "SELECT * FROM compliance_flags" + (" WHERE investor_id=?" if iid else "")
        return self.c.execute(sql, (iid,) if iid else ()).fetchall()

    def subscribe(self, iid, amount_cad, method="wire") -> int:
        inv = self.investor(iid)
        if not inv["accredited"]:
            raise GateError("investor not marked accredited (placeholder check)")
        if inv["kyc_status"] != "approved":
            raise GateError("KYC not approved")
        amt = D(amount_cad)
        if method == "cash" and amt >= LARGE_CASH_CAD:
            self.flag(iid, "large_cash", f"cash subscription CAD {amt} (record only; no report filed)")
        oid = self.c.execute("INSERT INTO orders(investor_id,kind,amount,status,created_at) VALUES(?,?,?,?,?)",
                             (iid, "sub", str(amt), "pending", self.clock())).lastrowid
        # cash received into bank against investor capital pending dealing
        self.ledger.post(f"subscription order {oid}", [("asset:bank:cad", amt, "CAD"), ("liability:investor_capital", -amt, "CAD")],
                         ref=f"order:{oid}")
        self._a("ops", "order.sub", id=oid, investor=iid, amount=str(amt))
        return oid

    def redeem(self, iid, units) -> int:
        u = D(units)
        # include redemptions already pending: two orders for all units must not over-redeem
        pend = sum((D(r[0]) for r in self.c.execute(
            "SELECT units FROM orders WHERE investor_id=? AND kind='red' AND status='pending'", (iid,))), Decimal(0))
        if u <= 0 or u + pend > D(self.investor(iid)["units"]):
            raise ValueError("invalid redemption units (exceeds holdings net of pending redemptions)")
        oid = self.c.execute("INSERT INTO orders(investor_id,kind,units,status,created_at) VALUES(?,?,?,?,?)",
                             (iid, "red", str(u), "pending", self.clock())).lastrowid
        self._a("ops", "order.red", id=oid, investor=iid, units=str(u))
        return oid

    def deal(self, nav: NAVSource) -> list[int]:
        """Deal all pending orders at the next NAV."""
        p = nav.nav_per_unit(); done = []
        if not p.is_finite() or p <= 0:
            raise ValueError(f"invalid NAV per unit {p}")
        for o in self.c.execute("SELECT * FROM orders WHERE status='pending' ORDER BY id").fetchall():
            with tx(self.c):  # each order deals atomically (units, order row, ledger)
                inv = self.investor(o["investor_id"]); units = D(inv["units"])
                if o["kind"] == "sub":
                    nu = q(D(o["amount"]) / p, "0.0001")
                    hwm = D(inv["hwm"]) or p
                    # blended HWM so new money doesn't pay perf fee on prior losses' recovery
                    hwm = q((units * hwm + nu * p) / (units + nu), "0.0001") if units else p
                    self.c.execute("UPDATE investors SET units=?, hwm=? WHERE id=?", (str(units + nu), str(hwm), inv["id"]))
                    self.c.execute("UPDATE orders SET units=?, nav=?, status='dealt', dealt_at=? WHERE id=?", (str(nu), str(p), self.clock(), o["id"]))
                else:
                    amt = q(D(o["units"]) * p)
                    self.c.execute("UPDATE investors SET units=? WHERE id=?", (str(units - D(o["units"])), inv["id"]))
                    self.c.execute("UPDATE orders SET amount=?, nav=?, status='dealt', dealt_at=? WHERE id=?", (str(amt), str(p), self.clock(), o["id"]))
                    self.ledger.post(f"redemption order {o['id']}", [("liability:investor_capital", amt, "CAD"),
                                     ("liability:redemptions_payable", -amt, "CAD")], ref=f"order:{o['id']}")
                self._a("ops", "order.dealt", id=o["id"], nav=str(p)); done.append(o["id"])
        return done

    def capital_call(self, pct, due: str) -> list[int]:
        ids = []
        for inv in self.c.execute("SELECT * FROM investors").fetchall():
            amt = q(D(inv["committed"]) * D(pct) / 100)
            remaining = D(inv["committed"]) - D(inv["called"])
            amt = min(amt, remaining)
            if amt > 0:
                ids.append(self.c.execute("INSERT INTO capital_calls(investor_id,amount,due,status) VALUES(?,?,?,?)",
                                          (inv["id"], str(amt), due, "issued")).lastrowid)
                self.c.execute("UPDATE investors SET called=? WHERE id=?", (str(D(inv["called"]) + amt), inv["id"]))
        self._a("ops", "capital_call", pct=str(pct), due=due, calls=ids)
        return ids

    def management_fee(self, iid, nav: NAVSource, annual_rate="0.02", days=30, period="") -> Decimal:
        inv = self.investor(iid)
        fee = q(D(inv["units"]) * nav.nav_per_unit() * D(annual_rate) * days / 365)
        return self._charge(inv, fee, "management", period, nav.nav_per_unit())

    def performance_fee(self, iid, nav: NAVSource, rate="0.20", period="", crystallize=True) -> Decimal:
        inv = self.investor(iid); p = nav.nav_per_unit(); hwm = D(inv["hwm"])
        fee = q(max(Decimal(0), p - hwm) * D(inv["units"]) * D(rate))
        if crystallize and fee > 0:
            with tx(self.c):  # fee + HWM reset together or not at all
                self._charge(inv, fee, "performance", period, p)
                self.c.execute("UPDATE investors SET hwm=? WHERE id=?", (str(p), iid))
        return fee

    def _charge(self, inv, fee, kind, period, p) -> Decimal:
        if fee <= 0:
            return Decimal(0)
        if not p.is_finite() or p <= 0:
            raise ValueError(f"invalid NAV per unit {p}")
        if period and self.c.execute("SELECT 1 FROM fees WHERE investor_id=? AND kind=? AND period=?",
                                     (inv["id"], kind, period)).fetchone():
            raise ValueError(f"{kind} fee for period {period} already charged")
        with tx(self.c):
            units = D(self.investor(inv["id"])["units"]) - q(fee / p, "0.0001")
            self.c.execute("UPDATE investors SET units=? WHERE id=?", (str(units), inv["id"]))
            self.c.execute("INSERT INTO fees(investor_id,kind,period,amount,ts) VALUES(?,?,?,?,?)", (inv["id"], kind, period, str(fee), self.clock()))
            self.ledger.post(f"{kind} fee {inv['name']} {period}", [("liability:investor_capital", fee, "CAD"), ("income:fees", -fee, "CAD")])
            self._a("ops", f"fee.{kind}", investor=inv["id"], amount=str(fee), period=period)
        return fee
