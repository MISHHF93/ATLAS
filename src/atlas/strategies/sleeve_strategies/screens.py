"""5. Public-filing screens (offline: parse local exports only; no scraping from this code).

SEDI insider clusters (Cohen-Malloy-Pomorski 2012): open-market PURCHASES (transaction code 10) by
distinct insiders within a window; selling is ignored for a long-only book. Opportunistic buys
(insider without a routine same-month pattern in prior years) get extra weight.
CIRO short interest (bi-monthly, lagged): days-to-cover = short qty / ADV. Exclusion screen for the most
shorted names; positive tilt for names whose days-to-cover fell sharply."""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

OPEN_MARKET_BUY = "10"


def read_sedi_csv(path) -> list[dict]:
    """Columns: issuer,symbol,insider,role,filing_date,trade_date,code,qty,price (a SEDI/vendor export)."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            r["filing_date"] = date.fromisoformat(r["filing_date"]); r["trade_date"] = date.fromisoformat(r["trade_date"])
            r["qty"] = float(r["qty"]); r["price"] = float(r["price"]); out.append(r)
    return out


@dataclass
class InsiderClusterScreen:
    window_days: int = 30
    min_insiders: int = 3
    min_value: float = 50_000.0
    officer_weight: float = 1.5

    def score(self, filings: list[dict], as_of: date) -> dict[str, dict]:
        """Point-in-time: only filings FILED on/before as_of (filing lag up to 5 days) are used."""
        lo = as_of - timedelta(days=self.window_days)
        by = defaultdict(list)
        for f in filings:
            if f["code"] == OPEN_MARKET_BUY and f["filing_date"] <= as_of and f["trade_date"] >= lo:
                by[f["symbol"]].append(f)
        hist_months = defaultdict(set)
        for f in filings:   # routine-trader detection: same calendar month bought in a prior year
            if f["code"] == OPEN_MARKET_BUY and f["filing_date"] <= as_of and f["trade_date"].year < as_of.year:
                hist_months[(f["symbol"], f["insider"])].add(f["trade_date"].month)
        out = {}
        for sym, fs in by.items():
            insiders = {f["insider"] for f in fs}
            value = sum(f["qty"] * f["price"] for f in fs)
            w = sum(self.officer_weight if f["role"].lower() in ("ceo", "cfo", "officer", "president") else 1.0 for f in fs)
            opportunistic = sum(1 for i in insiders if not any(f["trade_date"].month in hist_months[(sym, i)] for f in fs if f["insider"] == i))
            ok = len(insiders) >= self.min_insiders and value >= self.min_value
            out[sym] = {"insiders": len(insiders), "value": round(value, 2), "weighted": round(w, 2),
                        "opportunistic": opportunistic, "cluster": ok, "score": round(w + opportunistic, 2) if ok else 0.0}
        return out


def read_ciro_csv(path) -> list[dict]:
    """Columns: report_date,symbol,short_qty,adv (adv = average daily volume from your own bars)."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out.append({"report_date": date.fromisoformat(r["report_date"]), "symbol": r["symbol"],
                        "short_qty": float(r["short_qty"]), "adv": float(r["adv"])})
    return out


@dataclass
class ShortInterestScreen:
    publication_lag_days: int = 7          # CIRO publishes with a lag; use only reports already public
    exclude_top_pct: float = 10.0
    tilt_drop_pct: float = 30.0            # days-to-cover fell by >= 30% vs previous report

    def evaluate(self, rows: list[dict], as_of: date) -> dict:
        usable = [r for r in rows if r["report_date"] + timedelta(days=self.publication_lag_days) <= as_of]
        by = defaultdict(list)
        for r in sorted(usable, key=lambda r: r["report_date"]):
            by[r["symbol"]].append(r["short_qty"] / r["adv"] if r["adv"] > 0 else float("inf"))
        last = {s: v[-1] for s, v in by.items()}
        if not last:
            return {"exclude": [], "tilt": [], "dtc": {}}
        ranked = sorted(last, key=lambda s: -last[s])
        n_ex = max(1, int(round(len(ranked) * self.exclude_top_pct / 100)))
        tilt = [s for s, v in by.items() if len(v) >= 2 and v[-2] > 0 and (v[-2] - v[-1]) / v[-2] * 100 >= self.tilt_drop_pct
                and s not in ranked[:n_ex]]
        return {"exclude": ranked[:n_ex], "tilt": sorted(tilt), "dtc": {s: round(v, 2) for s, v in last.items()}}
