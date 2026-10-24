"""Keyless SEC EDGAR fundamentals: companyfacts JSON -> normalised, point-in-time annual statements.

* Needs a descriptive User-Agent with a contact e-mail (SEC fair-access policy). It is read from ATLAS_SEC_USER_AGENT
  (environment or the local gitignored .env). Without it the client reports "not_configured" and makes no request.
* Rate limit: at most ~8 requests/second process-wide (SEC allows 10).
* Cache: raw JSON under var/sec_cache/ (gitignored), 24 h TTL.
* Point-in-time: only facts whose ``filed`` date is on or before ``as_of`` are used; for each fiscal period the latest
  filing known at ``as_of`` wins (so a later 10-K/A is invisible before its filing date).
Nothing is estimated: a concept the company did not file stays ``None``."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from atlas.marketdata.sec_edgar import validate_sec_user_agent

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
MIN_INTERVAL_S = 0.125
CACHE_TTL_S = 24 * 3600

# normalised field -> ordered candidate us-gaap concepts (first one present wins), "flow" or "instant"
CONCEPTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "revenue": ("flow", ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax")),
    "gross_profit": ("flow", ("GrossProfit",)),
    "operating_income": ("flow", ("OperatingIncomeLoss",)),
    "pretax_income": ("flow", ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments")),
    "income_tax": ("flow", ("IncomeTaxExpenseBenefit",)),
    "net_income": ("flow", ("NetIncomeLoss", "ProfitLoss")),
    "interest_expense": ("flow", ("InterestExpense", "InterestExpenseNonoperating")),
    "d_and_a": ("flow", ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet")),
    "eps_diluted": ("flow", ("EarningsPerShareDiluted",)),
    "diluted_shares": ("flow", ("WeightedAverageNumberOfDilutedSharesOutstanding",)),
    "total_assets": ("instant", ("Assets",)),
    "current_assets": ("instant", ("AssetsCurrent",)),
    "total_liabilities": ("instant", ("Liabilities",)),
    "current_liabilities": ("instant", ("LiabilitiesCurrent",)),
    "equity": ("instant", ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
    "cash": ("instant", ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")),
    "long_term_debt": ("instant", ("LongTermDebtNoncurrent", "LongTermDebt")),
    "retained_earnings": ("instant", ("RetainedEarningsAccumulatedDeficit",)),
    "operating_cash_flow": ("flow", ("NetCashProvidedByUsedInOperatingActivities",)),
    "capex": ("flow", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    "dividends_paid": ("flow", ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
    "buybacks": ("flow", ("PaymentsForRepurchaseOfCommonStock",)),
}
STATEMENT = {"income": ("revenue", "gross_profit", "operating_income", "pretax_income", "income_tax", "net_income", "interest_expense", "d_and_a", "eps_diluted", "diluted_shares"),
             "balance": ("total_assets", "current_assets", "total_liabilities", "current_liabilities", "equity", "cash", "long_term_debt", "retained_earnings"),
             "cash_flow": ("operating_cash_flow", "capex", "dividends_paid", "buybacks")}

Fetcher = Callable[[str, dict[str, str]], bytes]


def _http_get(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https SEC hosts only
        return r.read()


def configured_user_agent(env_file: str | Path = ".env") -> str | None:
    ua = os.environ.get("ATLAS_SEC_USER_AGENT")
    if not ua:
        from atlas.control.policy.loader import parse_env_file
        ua = parse_env_file(Path(env_file)).get("ATLAS_SEC_USER_AGENT")
    if not ua:
        return None
    try:
        return validate_sec_user_agent(ua)
    except ValueError:
        return None


class NotConfigured(RuntimeError):
    pass


class EdgarClient:
    _lock = threading.Lock()
    _last = 0.0

    def __init__(self, user_agent: str | None = None, cache_dir: str | Path = "var/sec_cache", fetch: Fetcher | None = None,
                 ttl_s: int = CACHE_TTL_S):
        self.user_agent = validate_sec_user_agent(user_agent) if user_agent else configured_user_agent()
        self.cache_dir, self.fetch, self.ttl_s = Path(cache_dir), fetch or _http_get, ttl_s
        self.requests = 0

    @property
    def configured(self) -> bool:
        return self.user_agent is not None

    def _get_json(self, url: str, cache_name: str) -> Any:
        path = self.cache_dir / cache_name
        if path.exists() and time.time() - path.stat().st_mtime < self.ttl_s:
            return json.loads(path.read_text())
        if not self.configured:
            raise NotConfigured("ATLAS_SEC_USER_AGENT not set (format 'AppName contact@domain')")
        with EdgarClient._lock:                       # process-wide rate limit
            wait = EdgarClient._last + MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            EdgarClient._last = time.monotonic()
        raw = self.fetch(url, {"User-Agent": self.user_agent or "", "Accept-Encoding": "identity"})
        self.requests += 1
        data = json.loads(raw)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return data

    def cik_for(self, ticker: str) -> str | None:
        t = ticker.upper()
        if t.isdigit():
            return t.zfill(10)
        for row in self._get_json(TICKERS_URL, "company_tickers.json").values():
            if str(row.get("ticker", "")).upper() == t:
                return str(row["cik_str"]).zfill(10)
        return None

    def companyfacts(self, cik: str) -> dict:
        return self._get_json(FACTS_URL.format(cik=cik), f"companyfacts_{cik}.json")


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _annual_points(units: dict, kind: str, as_of: str) -> dict[str, dict]:
    """fiscal-period-end -> latest fact filed on/before as_of, annual (FY, ~1y duration) facts only."""
    out: dict[str, dict] = {}
    for unit, facts in units.items():
        for f in facts:
            if f.get("filed", "9999") > as_of or f.get("form") not in ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"):
                continue
            if kind == "flow":
                if not f.get("start") or not 330 <= _days(f["start"], f["end"]) <= 400:
                    continue
            elif f.get("start"):
                continue
            cur = out.get(f["end"])
            if cur is None or f["filed"] > cur["filed"] or (f["filed"] == cur["filed"] and f.get("accn", "") > cur.get("accn", "")):
                out[f["end"]] = {"value": f["val"], "unit": unit, "filed": f["filed"], "form": f["form"], "accn": f.get("accn"), "fy": f.get("fy")}
    return out


def normalise(facts_json: dict, as_of: str | None = None, years: int = 5) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    gaap = facts_json.get("facts", {}).get("us-gaap", {})
    series: dict[str, dict[str, dict]] = {}
    used: dict[str, str | None] = {}
    for field, (kind, cands) in CONCEPTS.items():
        used[field] = None
        for c in cands:
            if c in gaap:
                pts = _annual_points(gaap[c].get("units", {}), kind, as_of)
                if pts:
                    series[field], used[field] = pts, c
                    break
    # fiscal years are keyed on the balance-sheet/flow period end; take the most recent `years` ends seen anywhere
    ends = sorted({e for s in series.values() for e in s}, reverse=True)
    ends = [e for e in ends if any(e in series.get(f, {}) for f in ("revenue", "net_income", "total_assets"))][:years]
    periods = []
    for e in ends:
        row: dict[str, Any] = {"period_end": e, "filed": max((series[f][e]["filed"] for f in series if e in series[f]), default=None)}
        for st, fields in STATEMENT.items():
            row[st] = {f: (series[f][e]["value"] if f in series and e in series[f] else None) for f in fields}
        periods.append(row)
    dei = facts_json.get("facts", {}).get("dei", {})
    shares = None
    so = dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    so = [f for f in so if f.get("filed", "9999") <= as_of]
    if so:
        last = max(so, key=lambda f: (f["filed"], f["end"]))
        shares = {"value": last["val"], "as_of": last["end"], "filed": last["filed"]}
    return {"cik": str(facts_json.get("cik", "")).zfill(10), "entity": facts_json.get("entityName"), "as_of": as_of,
            "periods": periods, "shares_outstanding": shares, "concepts_used": used,
            "source": "SEC EDGAR companyfacts (XBRL, as filed)", "point_in_time": "facts filed on or before as_of only",
            "license": "SEC public data", "execution_permission": "none"}


def fundamentals(ticker: str, as_of: str | None = None, client: EdgarClient | None = None, years: int = 5) -> dict[str, Any]:
    c = client or EdgarClient()
    try:
        cik = c.cik_for(ticker)
        if cik is None:
            return {"ticker": ticker.upper(), "status": "unknown_ticker", "periods": [], "execution_permission": "none"}
        out = normalise(c.companyfacts(cik), as_of, years)
    except NotConfigured as e:
        return {"ticker": ticker.upper(), "status": "not_configured", "reason": str(e), "periods": [], "execution_permission": "none"}
    except Exception as e:  # network / HTTP / JSON
        return {"ticker": ticker.upper(), "status": "unavailable", "reason": f"{type(e).__name__}: {e}"[:300], "periods": [], "execution_permission": "none"}
    out.update({"ticker": ticker.upper(), "status": "ok" if out["periods"] else "no_annual_facts"})
    return out


def derived_metrics(f: dict[str, Any], price: float | None = None) -> dict[str, Any]:
    """Ratios from the latest normalised period (and the prior one for growth). None when an input is missing."""
    p = f.get("periods") or []
    if not p:
        return {}
    cur, prev = p[0], (p[1] if len(p) > 1 else None)
    inc, bal, cf = cur["income"], cur["balance"], cur["cash_flow"]

    def div(a, b):
        return None if a is None or b in (None, 0) else a / b
    shares = (f.get("shares_outstanding") or {}).get("value") or inc.get("diluted_shares")
    fcf = None if cf.get("operating_cash_flow") is None or cf.get("capex") is None else cf["operating_cash_flow"] - abs(cf["capex"])
    debt = bal.get("long_term_debt")
    m = {"roe": div(inc.get("net_income"), bal.get("equity")), "net_margin": div(inc.get("net_income"), inc.get("revenue")),
         "gross_margin": div(inc.get("gross_profit"), inc.get("revenue")), "operating_margin": div(inc.get("operating_income"), inc.get("revenue")),
         "debt_to_equity": div(debt, bal.get("equity")), "current_ratio": div(bal.get("current_assets"), bal.get("current_liabilities")),
         "fcf": fcf, "fcf_margin": div(fcf, inc.get("revenue")), "shares": shares,
         "book_value_per_share": div(bal.get("equity"), shares), "eps": inc.get("eps_diluted") or div(inc.get("net_income"), shares),
         "revenue_growth": div(None if prev is None or inc.get("revenue") is None or prev["income"].get("revenue") is None else inc["revenue"] - prev["income"]["revenue"],
                               None if prev is None else prev["income"].get("revenue")),
         "net_income_positive_years": sum(1 for r in p if (r["income"].get("net_income") or 0) > 0), "years": len(p),
         "price": price}
    if price is not None and shares:
        mc = price * shares
        m.update({"market_cap": mc, "pe": div(price, m["eps"]) if (m["eps"] or 0) > 0 else None,
                  "pb": div(price, m["book_value_per_share"]) if (m["book_value_per_share"] or 0) > 0 else None,
                  "fcf_yield": div(fcf, mc), "ev": mc + (debt or 0) - (bal.get("cash") or 0)})
    return m
