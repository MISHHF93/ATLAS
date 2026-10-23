"""11. Tax-loss harvesting: TAXABLE accounts only (no value in TFSA/RRSP/RRIF/FHSA).

Canadian superficial-loss rule (ITA s.54): the loss is denied if the taxpayer OR an affiliated person
(spouse, controlled corp, their RRSP/TFSA...) acquires identical property in the 61-day window
(30 days before through 30 days after the sale) and still holds it at day 30. So a candidate is
skipped if ANY affiliated entity bought the identical property in the prior 30 days, and the plan sets a
no-repurchase date (sale + 30 days) across all affiliated accounts. Replacements must NOT be identical
property: prefer an ETF tracking a DIFFERENT index (XIC<->VCN is debated; a different benchmark is safer).

WARNING carried in every plan: frequent automated trading risks CRA treating gains as BUSINESS INCOME
(fully taxable; losses fully deductible but harvesting logic changes). Get advice from a Canadian tax
professional. Plans are advisory; any trade still goes through the risk engine + owner approval."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

BUSINESS_INCOME_WARNING = ("Frequent automated trading may be treated by CRA as business income (100% taxable) rather than "
                           "capital gains; tax-loss harvesting assumptions change. Not tax advice; consult a Canadian tax professional.")

# different underlying index => not identical property (owner-editable; documented assumptions)
DEFAULT_REPLACEMENTS = {
    "XIC": ("VCN", "S&P/TSX Capped Composite -> FTSE Canada All Cap (debated; different index provider)"),
    "ZCN": ("VCN", "S&P/TSX Capped Composite -> FTSE Canada All Cap"),
    "VCN": ("XIC", "FTSE Canada All Cap -> S&P/TSX Capped Composite"),
    "VFV": ("XUU", "S&P 500 -> S&P Total Market (different index)"),
    "XUS": ("XUU", "S&P 500 -> S&P Total Market"),
    "XUU": ("VFV", "S&P Total Market -> S&P 500"),
    "XEF": ("VIU", "MSCI EAFE IMI -> FTSE Developed ex North America"),
    "VIU": ("XEF", "FTSE Developed ex NA -> MSCI EAFE IMI"),
}
IDENTICAL_GROUPS = [{"XIC", "ZCN"}, {"VFV", "XUS", "ZSP"}]  # same underlying index => treated as identical property


@dataclass
class Holding:
    entity: str
    symbol: str
    qty: Decimal
    acb_per_unit_cad: Decimal
    price_cad: Decimal


@dataclass
class TlhPlanner:
    min_loss_cad: Decimal = Decimal("500")
    min_loss_pct: Decimal = Decimal("5")
    replacements: dict = field(default_factory=lambda: dict(DEFAULT_REPLACEMENTS))

    def _identical(self, a: str, b: str) -> bool:
        return a == b or any(a in g and b in g for g in IDENTICAL_GROUPS)

    def plan(self, holdings: list[Holding], entities: dict, affiliations, trades: list, today: date) -> dict:
        """entities: id -> Entity (tax.entities); affiliations: tax.entities.Affiliations; trades: tax.events.Trade list."""
        out = {"as_of": today.isoformat(), "candidates": [], "skipped": [], "warning": BUSINESS_INCOME_WARNING}
        for h in holdings:
            ent = entities.get(h.entity)
            if ent is None or ent.registered:
                out["skipped"].append({"symbol": h.symbol, "entity": h.entity, "why": "registered account: no tax value"})
                continue
            loss = (h.acb_per_unit_cad - h.price_cad) * h.qty
            pct = (h.acb_per_unit_cad - h.price_cad) / h.acb_per_unit_cad * 100 if h.acb_per_unit_cad > 0 else Decimal(0)
            if loss < self.min_loss_cad or pct < self.min_loss_pct:
                continue
            aff = affiliations.affiliated(h.entity)
            recent = [t for t in trades if t.side == "buy" and t.entity in aff and self._identical(t.property, h.symbol)
                      and timedelta(0) <= today - t.ts.date() <= timedelta(days=30)]
            if recent:
                out["skipped"].append({"symbol": h.symbol, "entity": h.entity,
                                       "why": f"affiliated purchase on {recent[-1].ts.date()} ({recent[-1].entity}) within 30 days: loss would be superficial"})
                continue
            rep = self.replacements.get(h.symbol)
            if rep and self._identical(rep[0], h.symbol):
                rep = None
            out["candidates"].append({
                "entity": h.entity, "symbol": h.symbol, "qty": str(h.qty), "loss_cad": str(loss.quantize(Decimal("0.01"))),
                "taxable_capital_loss_cad": str((loss / 2).quantize(Decimal("0.01"))),  # 50% inclusion
                "replacement": rep[0] if rep else None, "replacement_note": rep[1] if rep else "no non-identical replacement configured: hold cash",
                "no_repurchase_until": (today + timedelta(days=31)).isoformat(),
                "no_repurchase_accounts": sorted(aff)})
        return out
