"""Rule-based investor-persona scorers on real (SEC-filed) fundamentals and feed prices, plus a portfolio-manager
aggregator that emits a JSON weight matrix and a disagreement log.

These are transparent checklists inspired by each investor's published principles, not imitations of the people and
not LLM role-play. A check whose input is missing is reported "n/a" and scores nothing. Advisory only."""
from __future__ import annotations

from typing import Any, Callable

from . import ADVISORY

Check = tuple[str, bool | None, str]   # (name, pass/fail/None=n/a, evidence)


def _cmp(v, op, x) -> bool | None:
    if v is None:
        return None
    return v > x if op == ">" else v < x


def _fmt(v, pct=False):
    if v is None:
        return "n/a"
    return f"{v:.1%}" if pct else f"{v:.3g}"


def buffett(m: dict, t: dict) -> list[Check]:
    return [("ROE > 15%", _cmp(m.get("roe"), ">", 0.15), f"ROE {_fmt(m.get('roe'), True)}"),
            ("net margin > 10%", _cmp(m.get("net_margin"), ">", 0.10), f"net margin {_fmt(m.get('net_margin'), True)}"),
            ("debt/equity < 0.5", _cmp(m.get("debt_to_equity"), "<", 0.5), f"D/E {_fmt(m.get('debt_to_equity'))}"),
            ("profitable every filed year", None if not m.get("years") else m.get("net_income_positive_years") == m.get("years"),
             f"{m.get('net_income_positive_years')}/{m.get('years')} years"),
            ("positive free cash flow", _cmp(m.get("fcf"), ">", 0), f"FCF {_fmt(m.get('fcf'))}"),
            ("FCF yield > 5% (price discipline)", _cmp(m.get("fcf_yield"), ">", 0.05), f"FCF yield {_fmt(m.get('fcf_yield'), True)}")]


def graham(m: dict, t: dict) -> list[Check]:
    pe, pb = m.get("pe"), m.get("pb")
    return [("P/E < 15", _cmp(pe, "<", 15), f"P/E {_fmt(pe)}"), ("P/B < 1.5", _cmp(pb, "<", 1.5), f"P/B {_fmt(pb)}"),
            ("Graham number: P/E x P/B < 22.5", None if pe is None or pb is None else pe * pb < 22.5, f"product {_fmt(None if pe is None or pb is None else pe * pb)}"),
            ("current ratio > 2", _cmp(m.get("current_ratio"), ">", 2), f"current ratio {_fmt(m.get('current_ratio'))}"),
            ("earnings positive every filed year", None if not m.get("years") else m.get("net_income_positive_years") == m.get("years"),
             f"{m.get('net_income_positive_years')}/{m.get('years')} years"),
            ("debt/equity < 1", _cmp(m.get("debt_to_equity"), "<", 1.0), f"D/E {_fmt(m.get('debt_to_equity'))}")]


def druckenmiller(m: dict, t: dict) -> list[Check]:
    c, s50, s200 = t.get("close"), t.get("sma50"), t.get("sma200")
    return [("3-month momentum > 0", _cmp(t.get("ret_3m"), ">", 0), f"3m {_fmt(t.get('ret_3m'), True)}"),
            ("12-month momentum > 10%", _cmp(t.get("ret_12m"), ">", 0.10), f"12m {_fmt(t.get('ret_12m'), True)}"),
            ("price above rising trend (SMA50 > SMA200)", None if None in (c, s50, s200) else c > s50 > s200, f"SMA50 {_fmt(s50)} SMA200 {_fmt(s200)}"),
            ("revenue growth > 10%", _cmp(m.get("revenue_growth"), ">", 0.10), f"revenue growth {_fmt(m.get('revenue_growth'), True)}"),
            ("macro/liquidity regime", None, "unavailable here: macro rates are a separate (§22) data feed; not guessed")]


def wood(m: dict, t: dict) -> list[Check]:
    return [("revenue growth > 20%", _cmp(m.get("revenue_growth"), ">", 0.20), f"revenue growth {_fmt(m.get('revenue_growth'), True)}"),
            ("gross margin > 50% (scalable model)", _cmp(m.get("gross_margin"), ">", 0.50), f"gross margin {_fmt(m.get('gross_margin'), True)}"),
            ("12-month momentum > 0", _cmp(t.get("ret_12m"), ">", 0), f"12m {_fmt(t.get('ret_12m'), True)}"),
            ("reinvesting (capex or buybacks not starving growth)", None if m.get("fcf_margin") is None else m["fcf_margin"] < 0.25,
             f"FCF margin {_fmt(m.get('fcf_margin'), True)}")]


def burry(m: dict, t: dict) -> list[Check]:
    r12 = t.get("ret_12m")
    return [("FCF yield > 10%", _cmp(m.get("fcf_yield"), ">", 0.10), f"FCF yield {_fmt(m.get('fcf_yield'), True)}"),
            ("P/B < 1 (asset discount)", _cmp(m.get("pb"), "<", 1.0), f"P/B {_fmt(m.get('pb'))}"),
            ("not euphoric: P/E < 25", _cmp(m.get("pe"), "<", 25), f"P/E {_fmt(m.get('pe'))}"),
            ("out of favour: 12-month return < 0", _cmp(r12, "<", 0), f"12m {_fmt(r12, True)}"),
            ("balance sheet survives: D/E < 1", _cmp(m.get("debt_to_equity"), "<", 1.0), f"D/E {_fmt(m.get('debt_to_equity'))}")]


PERSONAS: dict[str, tuple[str, Callable[[dict, dict], list[Check]]]] = {
    "buffett": ("quality compounder at a fair price", buffett), "graham": ("deep value with a margin of safety", graham),
    "druckenmiller": ("trend + growth, macro-aware", druckenmiller), "wood": ("disruptive high growth", wood),
    "burry": ("contrarian deep value", burry)}


def score_persona(pid: str, metrics: dict, tech: dict) -> dict[str, Any]:
    style, fn = PERSONAS[pid]
    checks = fn(metrics or {}, tech or {})
    ev = [c for c in checks if c[1] is not None]
    net = sum(1 if c[1] else -1 for c in ev)
    if len(ev) < 2:
        sig, conf = "insufficient_data", 0
    else:
        frac = net / len(ev)
        sig = "bullish" if frac >= 0.34 else "bearish" if frac <= -0.34 else "neutral"
        conf = round(abs(frac) * 100 * len(ev) / len(checks))
    return {"persona": pid, "style": style, "signal": sig, "confidence": conf, "net": net, "evaluated": len(ev), "of": len(checks),
            "checks": [{"check": n, "result": "pass" if r else "fail" if r is False else "n/a", "evidence": e} for n, r, e in checks]}


SIGN = {"bullish": 1, "neutral": 0, "bearish": -1, "insufficient_data": 0}


def portfolio_manager(per_ticker: dict[str, list[dict]], max_weight: float = 0.25) -> dict[str, Any]:
    """per_ticker: ticker -> list of persona results. Score = mean(sign x confidence/100) over personas with data.
    Long-only target weights proportional to positive scores, capped at max_weight; the rest is cash."""
    matrix, scores = {}, {}
    for tk, res in per_ticker.items():
        matrix[tk] = {r["persona"]: SIGN[r["signal"]] * r["confidence"] / 100 for r in res}
        valid = [r for r in res if r["signal"] != "insufficient_data"]
        scores[tk] = sum(SIGN[r["signal"]] * r["confidence"] / 100 for r in valid) / len(valid) if valid else 0.0
    pos = {k: v for k, v in scores.items() if v > 0}
    tot = sum(pos.values())
    weights = {k: 0.0 for k in scores}
    if tot > 0:
        raw = {k: v / tot for k, v in pos.items()}
        for _ in range(len(raw) + 1):          # cap and redistribute
            over = {k for k, w in raw.items() if w > max_weight}
            if not over:
                break
            spare = sum(raw[k] - max_weight for k in over)
            for k in over:
                raw[k] = max_weight
            free = {k: v for k, v in raw.items() if k not in over and v < max_weight}
            fs = sum(free.values())
            if fs <= 0:
                break
            for k in free:
                raw[k] += spare * free[k] / fs
        weights.update({k: min(max_weight, w) for k, w in raw.items()})
    log = []
    for tk, res in per_ticker.items():
        sides = {r["signal"] for r in res}
        if "bullish" in sides and "bearish" in sides:
            log.append({"ticker": tk, "bulls": [r["persona"] for r in res if r["signal"] == "bullish"],
                        "bears": [r["persona"] for r in res if r["signal"] == "bearish"],
                        "spread": max(matrix[tk].values()) - min(matrix[tk].values()),
                        "resolution": f"aggregate score {scores[tk]:+.2f} -> weight {weights[tk]:.1%}"})
    return {"weight_matrix": matrix, "aggregate_scores": scores, "target_weights": weights,
            "cash_weight": max(0.0, 1 - sum(weights.values())), "max_weight": max_weight, "disagreements": log,
            "method": "mean(sign x confidence); long-only, proportional, capped", "advisory": ADVISORY, "execution_permission": "none"}
