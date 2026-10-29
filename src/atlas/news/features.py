"""Point-in-time news features (layer 26 numbers -> model inputs). Same contract as ``layers25``: row i uses only items whose ``avail`` time is
<= bar end i; NaN (never 0) when the source has no coverage at that bar or nothing in the window.

``avail`` rules (the leak controls, see ATLAS_MODEL_SPEC.md 3B.3):
* filings: the SEC acceptance time (when EDGAR published it), not the filing date and not when we downloaded it. A backfill is therefore valid.
* GDELT articles: the first-seen time GDELT reports. Tone is GDELT's own number at that time.
* LLM sentiment / materiality: only items scored LIVE, i.e. analysed within ``LIVE_LAG_S`` of publication, and only after the analysis happened
  (``avail = max(published, analysed)``). Items scored later, in a backfill, are excluded from training: the model has seen the future of them.
* coverage: a bar earlier than the first time a source was actually collected is NaN, so "we did not look" is never confused with "nothing happened"."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

NEWS_FEATURES = ("nw_n_filings_24h", "nw_hrs_since_filing", "nw_severe_72h", "nw_n_news_24h", "nw_gdelt_tone_24h",
                 "nw_sent_mean_24h", "nw_sent_wtd_24h", "nw_mat_max_24h", "nw_hype_any_24h")
DAY, SEVERE_W, LIVE_LAG_S, HRS_CAP = 86400.0, 3 * 86400.0, 6 * 3600.0, 720.0


def _bounds(avail: np.ndarray, end: np.ndarray, w: float) -> tuple[np.ndarray, np.ndarray]:
    return np.searchsorted(avail, end - w, side="right"), np.searchsorted(avail, end, side="right")


def _cum(x: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(x)])


def _empty() -> dict[str, Any]:
    return {"filing": {"avail": np.empty(0), "severe": np.empty(0)}, "news": {"avail": np.empty(0), "tone": np.empty(0), "hype": np.empty(0)},
            "llm": {"avail": np.empty(0), "sent": np.empty(0), "mat": np.empty(0)}, "cov": {"filing": None, "news": None, "llm": None}}


def make_input(filings: pd.DataFrame | None = None, news: pd.DataFrame | None = None, llm: pd.DataFrame | None = None,
               cov: Mapping[str, float | None] | None = None) -> dict[str, Any]:
    """filings: avail, severe. news: avail, tone, hype. llm: avail, sent, mat (already restricted to live-scored). Sorted here."""
    out = _empty()
    for key, df, cols in (("filing", filings, ("severe",)), ("news", news, ("tone", "hype")), ("llm", llm, ("sent", "mat"))):
        if df is not None and len(df):
            d = df.sort_values("avail")
            out[key] = {"avail": d["avail"].to_numpy(float), **{c: d[c].to_numpy(float) for c in cols}}
    out["cov"] = {**out["cov"], **dict(cov or {})}
    return out


def news_frame(end: np.ndarray, news: Mapping[str, Any] | None) -> pd.DataFrame:
    n = len(end)
    cols = {c: np.full(n, np.nan) for c in NEWS_FEATURES}
    if not news:
        return pd.DataFrame(cols)
    e = np.asarray(end, float)
    cov = news.get("cov", {})
    in_f = np.zeros(n, bool) if cov.get("filing") is None else e >= cov["filing"]
    in_n = np.zeros(n, bool) if cov.get("news") is None else e >= cov["news"]
    in_l = np.zeros(n, bool) if cov.get("llm") is None else e >= cov["llm"]
    f = news["filing"]
    if len(f["avail"]):
        lo, hi = _bounds(f["avail"], e, DAY)
        cols["nw_n_filings_24h"] = np.where(in_f, hi - lo, np.nan)
        lo3, hi3 = _bounds(f["avail"], e, SEVERE_W)
        sv = _cum(f["severe"])
        cols["nw_severe_72h"] = np.where(in_f, (sv[hi3] - sv[lo3] > 0).astype(float), np.nan)
        last = np.where(hi > 0, f["avail"][np.maximum(hi - 1, 0)], np.nan)
        cols["nw_hrs_since_filing"] = np.where(in_f, np.where(np.isnan(last), HRS_CAP, np.minimum((e - last) / 3600.0, HRS_CAP)), np.nan)
    else:
        cols["nw_n_filings_24h"] = np.where(in_f, 0.0, np.nan)
        cols["nw_severe_72h"] = np.where(in_f, 0.0, np.nan)
        cols["nw_hrs_since_filing"] = np.where(in_f, HRS_CAP, np.nan)
    g = news["news"]
    if len(g["avail"]):
        lo, hi = _bounds(g["avail"], e, DAY)
        k = hi - lo
        cols["nw_n_news_24h"] = np.where(in_n, k, np.nan)
        tone_ok = np.isfinite(g["tone"])
        ct, st = _cum(tone_ok.astype(float)), _cum(np.where(tone_ok, g["tone"], 0.0))
        nt = ct[hi] - ct[lo]
        cols["nw_gdelt_tone_24h"] = np.where(in_n & (nt > 0), (st[hi] - st[lo]) / np.maximum(nt, 1), np.nan)
        hy = _cum(g["hype"])
        cols["nw_hype_any_24h"] = np.where(in_n & (k > 0), ((hy[hi] - hy[lo]) > 0).astype(float), np.nan)
    else:
        cols["nw_n_news_24h"] = np.where(in_n, 0.0, np.nan)
    m = news["llm"]
    if len(m["avail"]):
        lo, hi = _bounds(m["avail"], e, DAY)
        k = hi - lo
        ok = in_l & (k > 0)
        cs, cm = _cum(m["sent"]), _cum(m["mat"])
        cols["nw_sent_mean_24h"] = np.where(ok, (cs[hi] - cs[lo]) / np.maximum(k, 1), np.nan)
        cw = _cum(m["sent"] * m["mat"])
        den = cm[hi] - cm[lo]
        cols["nw_sent_wtd_24h"] = np.where(ok & (den > 0), (cw[hi] - cw[lo]) / np.where(den > 0, den, 1.0), np.nan)
        mx = np.full(n, np.nan)
        for i in np.flatnonzero(ok):
            mx[i] = m["mat"][lo[i]:hi[i]].max()
        cols["nw_mat_max_24h"] = mx
    return pd.DataFrame(cols)


def ticker_of(instrument: str | None) -> str | None:
    """Filings exist only for SEC-registered equities. Anything else (crypto, FX, ETFs, indices) has no news features: NaN, not 0."""
    from atlas.feeds.universe import STOCKS
    s = (instrument or "").upper()
    return s if s in set(STOCKS) else None


def news_input(ticker: str | None, scope: str | None = None) -> dict[str, Any] | None:
    """Build the point-in-time input for one ticker from the store, or None when the ticker has no source coverage at all."""
    if not ticker:
        return None
    from atlas.news import rules as R
    from atlas.news import store as S
    scope = scope or S.current_scope()
    cov = {"filing": S.coverage_start(ticker, "sec_edgar"), "news": S.coverage_start(ticker, "gdelt"), "llm": None}
    if cov["filing"] is None and cov["news"] is None:
        return None
    items = S.items_for([ticker], limit=20000)
    fil = pd.DataFrame([{"avail": i["published_at"], "severe": float(R.event_for_filing(i.get("form"), i.get("codes"))["severe_negative"])} for i in items if i["kind"] == "filing"])
    new = pd.DataFrame([{"avail": i["published_at"], "tone": i["tone"] if i["tone"] is not None else np.nan, "hype": float(bool(R.hype_flags(i["title"])))} for i in items if i["kind"] == "news"])
    ann = S.annotations_for([(i["id"], i["ticker"]) for i in items], scope)
    pub = {(i["id"], i["ticker"]): i["published_at"] for i in items}
    rows = []
    for key, lst in ann.items():
        for a in lst:
            if a["analyzer"] == "llm" and a["grounded"] and a["sentiment"] is not None and a["materiality"] is not None and a["analyzed_at"] - pub[key] <= LIVE_LAG_S:
                rows.append({"avail": max(pub[key], a["analyzed_at"]), "sent": a["sentiment"], "mat": a["materiality"]})
    llm = pd.DataFrame(rows)
    if len(llm):
        cov["llm"] = float(llm["avail"].min())
    return make_input(fil, new, llm, cov)
