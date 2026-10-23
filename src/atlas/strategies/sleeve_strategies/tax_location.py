"""12. Account-location advice for dividends (REPORT ONLY, never trades). Dividend capture is not a
strategy (ex-date price drop); location is the actionable part:

* Canadian eligible dividends: non-registered (gross-up + dividend tax credit) is efficient.
* US dividends: 15% withholding. Recoverable in RRSP/RRIF under the treaty (US-LISTED ETFs only);
  NOT recoverable in TFSA/FHSA/RESP; foreign tax credit in non-registered.
* Canadian-listed ETFs holding US stocks lose the 15% inside the fund in every account type.
* Interest / high-yield: registered first (fully taxable otherwise).
* High-growth / speculative: TFSA (tax-free growth; losses are not deductible there)."""
from __future__ import annotations

ADVICE = {
    "ca_eligible_dividend": ("non_registered", "eligible dividend tax credit applies only in non-registered accounts"),
    "us_dividend_us_listed": ("rrsp", "treaty exempts US withholding in RRSP/RRIF for US-listed securities; TFSA loses 15%"),
    "us_dividend_ca_listed_etf": ("rrsp_or_non_registered", "15% lost inside the fund in any account; prefer US-listed in RRSP"),
    "intl_dividend": ("non_registered", "foreign tax credit only usable in non-registered"),
    "interest": ("rrsp_or_tfsa", "interest is fully taxable outside registered plans"),
    "growth": ("tfsa", "tax-free growth; no deduction for losses inside TFSA"),
}


def report(holdings: list[dict], accounts: set[str]) -> dict:
    """holdings: {symbol, income_type, current_account, annual_income_cad}. accounts: available account kinds."""
    rows = []
    for h in holdings:
        rec, why = ADVICE.get(h["income_type"], ("any", "no specific rule"))
        options = [a for a in ("non_registered", "rrsp", "tfsa") if a in rec or rec == "any"]
        options = [a for a in options if a in accounts] or ["(no suitable account available)"]
        mismatch = h.get("current_account") not in options
        est = 0.0
        if h["income_type"] == "us_dividend_us_listed" and h.get("current_account") == "tfsa":
            est = 0.15 * float(h.get("annual_income_cad", 0))
        rows.append({"symbol": h["symbol"], "income_type": h["income_type"], "current": h.get("current_account"),
                     "recommended": options, "why": why, "mismatch": mismatch, "est_annual_leak_cad": round(est, 2)})
    return {"report_only": True, "rows": rows,
            "disclaimer": "Informational only; not tax advice. Contribution room, attribution and US estate tax are not modelled."}
