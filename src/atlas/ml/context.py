"""Causal context features for the meta-labeler: higher-timeframe (HTF) bars and section-22 macro.

HTF: daily (UTC-day) and 4h buckets aggregated from the series' own bars; a bucket is usable only once its last
bar has closed (bucket end <= detection-bar end). Macro: feed ``observations`` rows whose conservative
``realtime_start`` (availability date, see feeds.providers.fred_public) is <= the detection date, so a value is
used only from 00:00 UTC of the day it is certainly public. Missing context -> NaN (genome gated if all-NaN).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

HTF_FEATURES = ("d1_ret1", "d1_ret5", "d1_trend20", "d1_atr_bps", "risk_d1atr", "h4_ret1", "h4_trend12", "d1_pos_range")
MACRO_SERIES = ("DGS10", "DGS2", "VIXCLS", "DTWEXBGS", "CPIAUCNS")
MACRO_FEATURES = ("m_dgs10", "m_dgs10_chg20", "m_curve_2s10s", "m_vix", "m_vix_z60", "m_usd_ret20", "m_cpi_yoy")


def _buckets(bars, seconds: int) -> pd.DataFrame:
    df = pd.DataFrame({"start": [b.start for b in bars], "end": [b.start + b.duration for b in bars],
                       "o": [b.open for b in bars], "h": [b.high for b in bars], "l": [b.low for b in bars], "c": [b.close for b in bars]})
    df["k"] = df.start // seconds
    g = df.groupby("k").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), last_end=("end", "max"))
    g["avail"] = (g.index + 1) * seconds    # usable only once the whole period has ended (never at last_end)
    return g


def htf_frame(bars) -> pd.DataFrame:
    """Per detection-bar start t: HTF features using only buckets whose period has ended by the bar's end."""
    if len(bars) < 50:
        return pd.DataFrame(columns=HTF_FEATURES)
    d = _buckets(bars, 86400)
    tr = pd.concat([d.h - d.l, (d.h - d.c.shift()).abs(), (d.l - d.c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=5).mean()
    dd = pd.DataFrame({"avail": d.avail, "d1_ret1": np.log(d.c / d.c.shift()), "d1_ret5": np.log(d.c / d.c.shift(5)),
                       "d1_trend20": (d.c - d.c.rolling(20, min_periods=10).mean()) / atr,
                       "d1_atr_bps": atr / d.c * 1e4, "d1_hi": d.h, "d1_lo": d.l})
    h = _buckets(bars, 4 * 3600)
    hh = pd.DataFrame({"avail": h.avail, "h4_ret1": np.log(h.c / h.c.shift()),
                       "h4_trend12": np.log(h.c / h.c.ewm(span=12, min_periods=6).mean())})
    t = pd.DataFrame({"t": [b.start for b in bars], "end": [b.start + b.duration for b in bars], "c": [b.close for b in bars]})
    out = pd.merge_asof(t.sort_values("end"), dd.sort_values("avail"), left_on="end", right_on="avail", direction="backward")
    out = pd.merge_asof(out.drop(columns="avail"), hh.sort_values("avail"), left_on="end", right_on="avail", direction="backward")
    rng = (out.d1_hi - out.d1_lo).replace(0, np.nan)
    out["d1_pos_range"] = (out.c - out.d1_lo) / rng
    return out.set_index("t")[[c for c in HTF_FEATURES if c != "risk_d1atr"]]


def _avail_ts(s: str) -> int:
    return int(datetime.combine(date.fromisoformat(s), datetime.min.time(), tzinfo=timezone.utc).timestamp())


def macro_table(store) -> list[pd.DataFrame]:
    """Daily (availability-date) table of macro features; each row uses only values public by that date.
    Uses the *final* stored vintage per observation date with its conservative availability date."""
    cols = {}
    for s in MACRO_SERIES:
        rows = store.observations(s)
        if not rows:
            continue
        cols[s] = pd.DataFrame(rows, columns=["date", "v", "rs"])
    if not cols:
        return []
    feats: list[pd.DataFrame] = []

    def daily(s, f):
        if s not in cols:
            return
        x = cols[s].dropna()
        x = x.assign(avail=x.rs.map(_avail_ts)).sort_values("date")
        for name, val in f(x.v.astype(float)).items():
            feats.append(pd.DataFrame({"avail": x.avail.to_numpy(), name: val.to_numpy()}))

    daily("DGS10", lambda v: {"m_dgs10": v, "m_dgs10_chg20": v - v.shift(20)})
    daily("VIXCLS", lambda v: {"m_vix": v, "m_vix_z60": (v - v.rolling(60, min_periods=20).mean()) / v.rolling(60, min_periods=20).std()})
    daily("DTWEXBGS", lambda v: {"m_usd_ret20": np.log(v / v.shift(20))})
    daily("CPIAUCNS", lambda v: {"m_cpi_yoy": np.log(v / v.shift(12))})
    if "DGS10" in cols and "DGS2" in cols:
        a = cols["DGS10"].dropna().set_index("date")
        b = cols["DGS2"].dropna().set_index("date")
        j = a.join(b, rsuffix="2", how="inner")
        av = np.maximum(j.rs.map(_avail_ts), j.rs2.map(_avail_ts))
        feats.append(pd.DataFrame({"avail": av.to_numpy(), "m_curve_2s10s": (j.v - j.v2).to_numpy()}))
    return feats


def macro_frame(store, ts) -> pd.DataFrame:
    """Macro features as known at each unix time in ``ts`` (index = ts)."""
    ts = np.asarray(ts, dtype=np.int64)
    left = pd.DataFrame({"t": ts}).sort_values("t").drop_duplicates()
    out = left.copy()
    for f in macro_table(store):
        f = f.dropna().sort_values("avail")
        out = pd.merge_asof(out, f, left_on="t", right_on="avail", direction="backward").drop(columns="avail")
    for c in MACRO_FEATURES:
        if c not in out:
            out[c] = np.nan
    return out.set_index("t")[list(MACRO_FEATURES)]
