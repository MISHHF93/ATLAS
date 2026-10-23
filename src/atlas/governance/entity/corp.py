"""Corporate passive-income tracking (REPORTS / FLAGS ONLY).

* AAII (adjusted aggregate investment income, s.125(7)) estimate: taxable capital gains net of
  current-year allowable capital losses (not below 0; carried-forward net capital losses NOT
  deducted), plus interest, foreign investment income, rents/royalties, and portfolio dividends
  from non-connected corporations. Gains on active-business assets are excluded (not modelled).
* Small business deduction (SBD) grind: the $500,000 business limit falls by $5 per $1 of AAII
  over $50,000, so it reaches $0 at $150,000 (associated group, prior-year AAII).
* RDTOH estimate: Part I refundable tax = 30 2/3% of aggregate investment income -> NERDTOH;
  Part IV tax = 38 1/3% of portfolio dividends (eligible -> ERDTOH, non-eligible -> NERDTOH).
  Dividend refund capacity = 38 1/3% of taxable dividends paid (eligible dividends draw ERDTOH only).
  Simplified: no foreign-tax-credit adjustments, no connected-corp Part IV, no capital dividend
  account, ignores provincial details. Rates as of 2026; verify annually.
* Also flags when trading activity looks like a BUSINESS (then income may be active, not passive)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from atlas.governance.entity import DISCLAIMER

C = Decimal("0.01")
AAII_THRESHOLD = Decimal(50_000)
AAII_ELIMINATED = Decimal(150_000)
BUSINESS_LIMIT = Decimal(500_000)
PART1_REFUNDABLE = Decimal(92) / Decimal(300)   # 30 2/3 %
PART4_RATE = Decimal(115) / Decimal(300)        # 38 1/3 %
REFUND_RATE = Decimal(115) / Decimal(300)       # 38 1/3 %


def q2(x: Decimal) -> Decimal:
    return x.quantize(C, ROUND_HALF_UP)


@dataclass
class PassiveIncome:
    taxable_capital_gains: Decimal = Decimal(0)      # already x inclusion rate
    allowable_capital_losses: Decimal = Decimal(0)   # already x inclusion rate (current year)
    interest: Decimal = Decimal(0)
    foreign_investment_income: Decimal = Decimal(0)
    rents_royalties: Decimal = Decimal(0)
    eligible_portfolio_dividends: Decimal = Decimal(0)
    non_eligible_portfolio_dividends: Decimal = Decimal(0)


def corp_report(pi: PassiveIncome, prior_year_aaii: Decimal | None = None, eligible_dividends_paid: Decimal = Decimal(0),
                non_eligible_dividends_paid: Decimal = Decimal(0), opening_erdtoh: Decimal = Decimal(0),
                opening_nerdtoh: Decimal = Decimal(0), business_evidence: dict | None = None) -> dict:
    net_tcg = max(Decimal(0), pi.taxable_capital_gains - pi.allowable_capital_losses)
    agg_inv = net_tcg + pi.interest + pi.foreign_investment_income + pi.rents_royalties   # Part I aggregate investment income
    aaii = agg_inv + pi.eligible_portfolio_dividends + pi.non_eligible_portfolio_dividends
    basis = prior_year_aaii if prior_year_aaii is not None else aaii
    grind = min(BUSINESS_LIMIT, max(Decimal(0), (basis - AAII_THRESHOLD) * 5))
    part1 = q2(agg_inv * PART1_REFUNDABLE)
    part4_e = q2(pi.eligible_portfolio_dividends * PART4_RATE)
    part4_ne = q2(pi.non_eligible_portfolio_dividends * PART4_RATE)
    erdtoh = opening_erdtoh + part4_e
    nerdtoh = opening_nerdtoh + part1 + part4_ne
    ref_elig = min(erdtoh, q2(eligible_dividends_paid * REFUND_RATE))
    ne_cap = q2(non_eligible_dividends_paid * REFUND_RATE)
    ref_ne = min(nerdtoh, ne_cap)
    if ref_ne < ne_cap:  # non-eligible dividends may also draw on ERDTOH
        extra = min(erdtoh - ref_elig, ne_cap - ref_ne)
        ref_ne += extra
        erdtoh_used = ref_elig + extra
    else:
        erdtoh_used = ref_elig
    flags = []
    if basis > AAII_THRESHOLD:
        flags.append(f"AAII {q2(basis)} > $50,000: small business limit reduced by {q2(grind)}")
    if basis >= AAII_ELIMINATED:
        flags.append("AAII >= $150,000: small business deduction fully eliminated")
    if prior_year_aaii is None:
        flags.append("SBD grind uses PRIOR-year AAII; current-year figure shown as a forecast")
    ev = business_evidence or {}
    if ev and (ev.get("pct_held_under_30d", 0) >= 50 or ev.get("trades", 0) >= 200):
        flags.append("trading pattern may indicate a business: gains could be active business income, not AAII (get advice)")
    return {
        "aggregate_investment_income": str(q2(agg_inv)), "aaii": str(q2(aaii)), "aaii_basis_for_grind": str(q2(basis)),
        "sbd_business_limit_reduction": str(q2(grind)), "sbd_business_limit_remaining": str(q2(BUSINESS_LIMIT - grind)),
        "part1_refundable_tax_to_nerdtoh": str(part1), "part4_tax_eligible_to_erdtoh": str(part4_e),
        "part4_tax_non_eligible_to_nerdtoh": str(part4_ne),
        "erdtoh_before_refund": str(q2(erdtoh)), "nerdtoh_before_refund": str(q2(nerdtoh)),
        "dividend_refund_estimate": str(q2(ref_elig + ref_ne)),
        "erdtoh_closing": str(q2(erdtoh - erdtoh_used)), "nerdtoh_closing": str(q2(nerdtoh - (ref_ne - (erdtoh_used - ref_elig)))),
        "flags": flags, "disclaimer": DISCLAIMER,
    }


def passive_income_from_tax_report(report, taxpayer: str, year: int) -> PassiveIncome:
    """Build PassiveIncome from the tax engine's report for a corporate taxpayer (dispositions + dividends).
    Note: Dividend records don't say eligible vs non-eligible or connected; Canadian ones are treated as
    ELIGIBLE PORTFOLIO dividends and foreign ones as foreign investment income (flag for review)."""
    from atlas.tax.engine import INCLUSION_RATE
    rate = INCLUSION_RATE.get(year, Decimal("0.5"))
    gains = sum((d.gain for d in report.dispositions if d.taxpayer == taxpayer and d.date.year == year and d.gain > 0), Decimal(0))
    losses = sum((-d.allowable for d in report.dispositions if d.taxpayer == taxpayer and d.date.year == year and d.allowable < 0), Decimal(0))
    pi = PassiveIncome(taxable_capital_gains=q2(gains * rate), allowable_capital_losses=q2(losses * rate))
    for dv in getattr(report, "dividends", []):
        if dv.get("taxpayer") != taxpayer or not str(dv.get("date", "")).startswith(str(year)):
            continue
        amt = Decimal(str(dv.get("gross_cad", 0)))
        if dv.get("country", "CA") == "CA":
            pi.eligible_portfolio_dividends += amt
        else:
            pi.foreign_investment_income += amt
    return pi
