"""Causal VWAP regime features.

Row i uses only bars[0..i]. VWAP is the bar-approximated one: sum(typical price x volume) / sum(volume), typical =
(H+L+C)/3, accumulated from the session open. It is NOT trade-level VWAP (the feed has bars, not ticks).

Session definitions (explicit, never guessed):
* ``utc_day``   24/7 markets (crypto): UTC calendar day.
* ``us_rth``    US cash session 09:30-16:00 America/New_York, Mon-Fri. Bars outside the session carry no VWAP (NaN).
* ``cme_globex`` CME Globex trading day for metals/futures: the day rolls at 18:00 America/New_York.
Daily-or-longer bars have no intraday session, so every VWAP feature is NaN there (never a fabricated value).

Event-anchored VWAP: the generic ``anchored_vwap`` accumulates from caller-supplied anchor timestamps and only becomes
defined on the first bar that STARTS at or after an anchor (so an anchor can never reach back before it happened).
The repo has no free scheduled-macro-release calendar (price_action/events.py is an interface only), so the default
features are anchored to the session open only, and no macro anchors are invented. Pass real release times to
``anchored_vwap`` once a verified free calendar exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Hashable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.features.price_action.bars import Bar

NY = ZoneInfo("America/New_York")
VWAP_FEATURES = ("vwap_dist_atr", "vwap_dist_bps", "vwap_slope_atr", "vwap_band_z", "vwap_sess_frac")
SESSION_KINDS = ("utc_day", "us_rth", "cme_globex")
GOLD_INSTRUMENTS = frozenset({"GC", "MGC", "GLD", "IAU", "XAUUSD", "GC=F"})
SLOPE_BARS = 5
_RTH_OPEN, _RTH_CLOSE = 9 * 60 + 30, 16 * 60


def session_kind_for(asset_class: str | None, instrument: str | None = None) -> str:
    if instrument and instrument.upper() in GOLD_INSTRUMENTS and instrument.upper() not in {"GLD", "IAU"}:
        return "cme_globex"
    if asset_class in (None, "crypto"):
        return "utc_day"
    return "us_rth"


def session_key(ts: int, kind: str) -> Hashable | None:
    """Session id for a bar START time (unix s), or None when the bar is outside any session."""
    if kind == "utc_day":
        return ts // 86400
    loc = datetime.fromtimestamp(ts, timezone.utc).astimezone(NY)
    if kind == "us_rth":
        m = loc.hour * 60 + loc.minute
        return loc.date().toordinal() if loc.weekday() < 5 and _RTH_OPEN <= m < _RTH_CLOSE else None
    if kind == "cme_globex":
        return (loc + timedelta(hours=6)).date().toordinal()   # 18:00 ET belongs to the next trading day
    raise ValueError(f"unknown session kind {kind!r}")


def _session_vwap(df: pd.DataFrame, keys: Sequence[Hashable | None]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Running VWAP, running volume-weighted std of typical price about VWAP, and bars-since-open (1-based)."""
    n = len(df)
    vwap, sd, k = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    tp = ((df.high + df.low + df.close) / 3.0).to_numpy(float)
    vol = df.volume.to_numpy(float)
    cur, sv, spv, spv2, cnt = object(), 0.0, 0.0, 0.0, 0
    for i in range(n):
        key = keys[i]
        if key is None:
            cur = object()
            continue
        if key != cur:
            cur, sv, spv, spv2, cnt = key, 0.0, 0.0, 0.0, 0
        cnt += 1
        k[i] = cnt
        v = max(vol[i], 0.0)
        sv += v
        spv += tp[i] * v
        spv2 += tp[i] * tp[i] * v
        if sv > 0:
            m = spv / sv
            vwap[i] = m
            sd[i] = float(np.sqrt(max(spv2 / sv - m * m, 0.0)))
    return vwap, sd, k


def anchored_vwap(bars: Sequence[Bar], anchors: Sequence[int]) -> np.ndarray:
    """VWAP accumulated from the latest anchor at or before each bar's start. NaN before the first anchor or when no
    volume has traded since the anchor. Causal: anchor times are inputs, bars after bar i are never read."""
    n, out = len(bars), np.full(len(bars), np.nan)
    anchors = sorted(int(a) for a in anchors)
    if not anchors:
        return out
    j, sv, spv, active = 0, 0.0, 0.0, False
    for i, b in enumerate(bars):
        while j < len(anchors) and anchors[j] <= b.start:
            j += 1
            sv, spv, active = 0.0, 0.0, True
        if not active:
            continue
        v = max(float(b.volume), 0.0)
        sv += v
        spv += (b.high + b.low + b.close) / 3.0 * v
        if sv > 0:
            out[i] = spv / sv
    return out


def vwap_regime_features(bars: Sequence[Bar], asset_class: str | None = None, instrument: str | None = None,
                         kind: str | None = None) -> pd.DataFrame:
    """Index = bar end (unix s), like ``bar_features``. Columns = VWAP_FEATURES.

    vwap_dist_atr   (close - session VWAP) / ATR14       session VWAP distance in ATR units
    vwap_dist_bps   (close - session VWAP) / close * 1e4  the same in basis points
    vwap_slope_atr  (VWAP_i - VWAP_{i-5}) / ATR14 within one session (NaN across a session break)
    vwap_band_z     (close - VWAP) / volume-weighted std of typical price about VWAP
    vwap_sess_frac  bars since the session open / 100 (how mature the session VWAP is; clipped at 3)
    """
    n = len(bars)
    idx = [b.end for b in bars]
    if n == 0:
        return pd.DataFrame(columns=list(VWAP_FEATURES))
    if bars[0].duration >= 86400:   # no intraday session on daily bars
        return pd.DataFrame(np.nan, index=idx, columns=list(VWAP_FEATURES))
    kind = kind or session_kind_for(asset_class, instrument)
    df = pd.DataFrame({"high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars],
                       "volume": [b.volume for b in bars]})
    keys = [session_key(b.start, kind) for b in bars]
    vwap, sd, k = _session_vwap(df, keys)
    c = df.close
    pc = c.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy(float)
    v = pd.Series(vwap)
    same = pd.Series([keys[i] is not None and i >= SLOPE_BARS and keys[i] == keys[i - SLOPE_BARS] for i in range(n)])
    slope = ((v - v.shift(SLOPE_BARS)) / pd.Series(atr)).where(same)
    out = pd.DataFrame(index=idx)
    cc = c.to_numpy(float)
    out["vwap_dist_atr"] = (cc - vwap) / atr
    out["vwap_dist_bps"] = (cc - vwap) / cc * 1e4
    out["vwap_slope_atr"] = slope.to_numpy(float)
    out["vwap_band_z"] = np.where(sd > 0, (cc - vwap) / np.where(sd > 0, sd, np.nan), np.nan)
    out["vwap_sess_frac"] = np.where(k > 0, np.minimum(k / 100.0, 3.0), np.nan)
    return out.replace([np.inf, -np.inf], np.nan)
