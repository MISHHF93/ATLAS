"""Fund NAV per unit (single series, forward pricing). Decimal throughout.

Valuation point: NAV = assets at market (CAD) - liabilities (accrued management fee, accrued
expenses, redemptions payable). Subscriptions/redemptions deal at the NEXT NAV per unit after
the order is received (forward pricing) to prevent late trading/dilution. Management fee accrues
daily (actual/365) on NAV before fee. Optional performance fee vs a high-water mark."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from atlas.governance.entity import DISCLAIMER

C = Decimal("0.01")
U4 = Decimal("0.0001")


def q2(x: Decimal) -> Decimal:
    return x.quantize(C, ROUND_HALF_UP)


@dataclass
class FundNav:
    name: str
    initial_navpu: Decimal = Decimal("10.0000")
    mgmt_fee_annual: Decimal = Decimal("0.02")
    perf_fee_rate: Decimal = Decimal("0")       # e.g. 0.20 over high-water mark
    cash: Decimal = Decimal(0)
    positions: dict[str, Decimal] = field(default_factory=dict)   # symbol -> qty
    units: dict[str, Decimal] = field(default_factory=dict)       # investor -> units
    accrued_mgmt: Decimal = Decimal(0)
    accrued_perf: Decimal = Decimal(0)
    accrued_expenses: Decimal = Decimal(0)
    hwm_navpu: Decimal | None = None
    last_valuation: date | None = None
    pending: list[tuple[str, str, Decimal]] = field(default_factory=list)  # (investor, kind, amount|units)
    history: list[dict] = field(default_factory=list)

    @property
    def units_outstanding(self) -> Decimal:
        return sum(self.units.values(), Decimal(0))

    # ---------------------------------------------------------------- dealing (forward priced)
    def order_subscription(self, investor: str, amount_cad) -> None:
        self.pending.append((investor, "sub", Decimal(str(amount_cad))))

    def order_redemption(self, investor: str, units) -> None:
        u = Decimal(str(units))
        if u > self.units.get(investor, Decimal(0)):
            raise ValueError("cannot redeem more units than held")
        self.pending.append((investor, "red", u))

    def trade(self, symbol: str, qty, price_cad, fee_cad=0) -> None:
        q, p, f = Decimal(str(qty)), Decimal(str(price_cad)), Decimal(str(fee_cad))
        self.cash -= q * p + f
        self.positions[symbol] = self.positions.get(symbol, Decimal(0)) + q
        if self.positions[symbol] == 0:
            del self.positions[symbol]

    def accrue_expense(self, amount_cad) -> None:
        self.accrued_expenses += Decimal(str(amount_cad))

    # ---------------------------------------------------------------- valuation
    def value(self, on: date, prices_cad: dict[str, Decimal]) -> dict:
        missing = [s for s in self.positions if s not in prices_cad]
        if missing:
            raise ValueError(f"no price for {missing}: NAV not struck (fail closed)")
        mv = sum((Decimal(str(prices_cad[s])) * q for s, q in self.positions.items()), Decimal(0))
        gross = self.cash + mv
        days = (on - self.last_valuation).days if self.last_valuation else 0
        pre_fee = gross - self.accrued_mgmt - self.accrued_perf - self.accrued_expenses
        fee = q2(pre_fee * self.mgmt_fee_annual * days / 365) if days > 0 and self.units_outstanding > 0 else Decimal(0)
        self.accrued_mgmt += fee
        nav = gross - self.accrued_mgmt - self.accrued_perf - self.accrued_expenses
        units = self.units_outstanding
        navpu = (nav / units).quantize(U4, ROUND_HALF_UP) if units > 0 else self.initial_navpu
        if self.perf_fee_rate and units > 0:
            hwm = self.hwm_navpu or self.initial_navpu
            if navpu > hwm:
                perf = q2((navpu - hwm) * units * self.perf_fee_rate)
                self.accrued_perf += perf
                nav -= perf
                navpu = (nav / units).quantize(U4, ROUND_HALF_UP)
                self.hwm_navpu = navpu
        # deal pending orders at this (forward) NAVPU
        dealt = []
        for inv, kind, amt in self.pending:
            if kind == "sub":
                u = (amt / navpu).quantize(U4, ROUND_HALF_UP)
                self.units[inv] = self.units.get(inv, Decimal(0)) + u
                self.cash += amt
                dealt.append({"investor": inv, "kind": "subscription", "amount": str(amt), "units": str(u)})
            else:
                pay = q2(amt * navpu)
                self.units[inv] -= amt
                self.cash -= pay
                dealt.append({"investor": inv, "kind": "redemption", "units": str(amt), "amount": str(pay)})
        self.pending = []
        self.last_valuation = on
        rec = {"date": on.isoformat(), "gross_assets": str(q2(gross)), "mgmt_fee_accrued_today": str(fee),
               "liabilities": str(q2(self.accrued_mgmt + self.accrued_perf + self.accrued_expenses)),
               "nav": str(q2(nav)), "units": str(units), "navpu": str(navpu), "dealt": dealt,
               "nav_after_dealing": str(q2(nav + sum((Decimal(d['amount']) if d['kind'] == 'subscription' else -Decimal(d['amount'])) for d in dealt))),
               "units_after_dealing": str(self.units_outstanding), "disclaimer": DISCLAIMER}
        self.history.append(rec)
        return rec

    def pay_fees(self) -> Decimal:
        paid = self.accrued_mgmt + self.accrued_perf
        self.cash -= paid
        self.accrued_mgmt = self.accrued_perf = Decimal(0)
        return paid

    def investor_statement(self, investor: str) -> dict:
        navpu = Decimal(self.history[-1]["navpu"]) if self.history else self.initial_navpu
        u = self.units.get(investor, Decimal(0))
        return {"investor": investor, "units": str(u), "navpu": str(navpu), "value": str(q2(u * navpu)), "disclaimer": DISCLAIMER}
