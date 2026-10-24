"""Discounted cash flow: FCFF (enterprise value at WACC) and FCFE (equity value at cost of equity).

Inputs are explicit; nothing is assumed silently. Forecast cash flows are grown from a base at the given growth path,
then a Gordon terminal value is added. Returns every intermediate so the result is auditable. Research only."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class DCFInputs:
    base_cash_flow: float                 # last fiscal-year FCFF or FCFE (USD)
    growth: Sequence[float]               # per-year growth for the explicit forecast, e.g. (0.08, 0.07, 0.06, 0.05, 0.04)
    discount_rate: float                  # WACC for FCFF, cost of equity for FCFE
    terminal_growth: float = 0.02
    net_debt: float = 0.0                 # FCFF only: debt - cash, subtracted from EV
    shares_outstanding: float | None = None
    mid_year: bool = False

    def validate(self) -> None:
        if not self.growth:
            raise ValueError("growth path is empty")
        if self.discount_rate <= self.terminal_growth:
            raise ValueError("discount rate must exceed terminal growth")
        if self.discount_rate <= -1 or self.discount_rate > 1:
            raise ValueError("discount rate out of range")


def wacc(equity_value: float, debt_value: float, cost_equity: float, cost_debt: float, tax_rate: float) -> float:
    v = equity_value + debt_value
    if v <= 0:
        raise ValueError("equity + debt must be positive")
    return equity_value / v * cost_equity + debt_value / v * cost_debt * (1 - tax_rate)


def capm(risk_free: float, beta: float, equity_risk_premium: float) -> float:
    return risk_free + beta * equity_risk_premium


def fcff_from_statements(ebit: float, tax_rate: float, d_and_a: float, capex: float, delta_nwc: float) -> float:
    """FCFF = EBIT(1-t) + D&A - CapEx - dNWC (capex as a positive outflow)."""
    return ebit * (1 - tax_rate) + d_and_a - abs(capex) - delta_nwc


def fcfe_from_statements(operating_cash_flow: float, capex: float, net_borrowing: float) -> float:
    """FCFE = CFO - CapEx + net borrowing."""
    return operating_cash_flow - abs(capex) + net_borrowing


@dataclass
class DCFResult:
    method: str
    forecast: list[dict] = field(default_factory=list)
    pv_forecast: float = 0.0
    terminal_value: float = 0.0
    pv_terminal: float = 0.0
    enterprise_or_equity_value: float = 0.0
    equity_value: float = 0.0
    per_share: float | None = None
    terminal_share: float = 0.0
    inputs: dict = field(default_factory=dict)
    label: str = "research valuation model; output depends entirely on the stated inputs"

    def to_dict(self) -> dict:
        return asdict(self)


def _run(method: str, i: DCFInputs) -> DCFResult:
    i.validate()
    cf, rows, pv = i.base_cash_flow, [], 0.0
    for t, g in enumerate(i.growth, start=1):
        cf *= 1 + g
        df = (1 + i.discount_rate) ** (t - 0.5 if i.mid_year else t)
        rows.append({"year": t, "growth": g, "cash_flow": cf, "discount_factor": 1 / df, "pv": cf / df})
        pv += cf / df
    n = len(i.growth)
    tv = cf * (1 + i.terminal_growth) / (i.discount_rate - i.terminal_growth)
    pv_tv = tv / (1 + i.discount_rate) ** n
    total = pv + pv_tv
    equity = total - i.net_debt if method == "FCFF" else total
    ps = equity / i.shares_outstanding if i.shares_outstanding else None
    d = asdict(i); d["growth"] = list(i.growth)
    return DCFResult(method, rows, pv, tv, pv_tv, total, equity, ps, pv_tv / total if total else 0.0, d)


def dcf_fcff(i: DCFInputs) -> DCFResult:
    return _run("FCFF", i)


def dcf_fcfe(i: DCFInputs) -> DCFResult:
    return _run("FCFE", DCFInputs(i.base_cash_flow, i.growth, i.discount_rate, i.terminal_growth, 0.0, i.shares_outstanding, i.mid_year))


def sensitivity(i: DCFInputs, method: str = "FCFF", rates: Sequence[float] = (-0.01, 0.0, 0.01),
                tgs: Sequence[float] = (-0.005, 0.0, 0.005)) -> list[dict]:
    fn = dcf_fcff if method == "FCFF" else dcf_fcfe
    out = []
    for dr in rates:
        for dg in tgs:
            j = DCFInputs(i.base_cash_flow, i.growth, i.discount_rate + dr, i.terminal_growth + dg, i.net_debt, i.shares_outstanding, i.mid_year)
            try:
                r = fn(j)
                out.append({"discount_rate": j.discount_rate, "terminal_growth": j.terminal_growth, "equity_value": r.equity_value, "per_share": r.per_share})
            except ValueError:
                out.append({"discount_rate": j.discount_rate, "terminal_growth": j.terminal_growth, "equity_value": None, "per_share": None})
    return out
