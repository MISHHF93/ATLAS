"""Causal bar features. Row i uses only bars[0..i] (known at bars[i].end). Leakage is tested in tests/ml.

Groups: price action (returns, body/wick ratios), volatility (ATR, realized vol, vol ratio), volume (z-score),
session (hour/day-of-week cyclic, minutes since session open), regime (rolling vol percentile, trend sign,
efficiency ratio) and distance to rolling extremes in ATR units, and VWAP regime (session VWAP distance/slope/band z; see vwap_features).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

from atlas.ai.ml.vwap_features import VWAP_FEATURES, vwap_regime_features
from atlas.features.price_action.bars import Bar

BASE_BAR_FEATURES = (
    "ret_1", "ret_4", "ret_16", "ret_64", "rv_16", "rv_64", "rv_ratio", "atr_bps", "range_atr", "body_frac",
    "upper_wick_frac", "lower_wick_frac", "vol_z", "ema20_dist_atr", "ema50_dist_atr", "ema20_slope_atr",
    "eff_ratio_16", "rsi_14", "hod_sin", "hod_cos", "dow_sin", "dow_cos", "rv_pctile_480", "trend_sign",
    "dist_hi64_atr", "dist_lo64_atr",
)
# VWAP regime features (evo-10). Models registered before evo-10 store their own feature list and are unaffected.
BAR_FEATURES = BASE_BAR_FEATURES + VWAP_FEATURES


def bars_frame(bars: Sequence[Bar]) -> pd.DataFrame:
    return pd.DataFrame({"start": [b.start for b in bars], "end": [b.end for b in bars], "open": [b.open for b in bars],
                         "high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars],
                         "volume": [b.volume for b in bars]})


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def bar_features(bars: Sequence[Bar], asset_class: str | None = None, instrument: str | None = None) -> pd.DataFrame:
    """Index = bar end (unix s). Every operation is a backward-looking rolling/ewm window.

    ``asset_class``/``instrument`` pick the VWAP session (crypto/None: UTC day, equity: US RTH, GC/MGC: CME day)."""
    df = bars_frame(bars)
    c, h, l, o = df.close, df.high, df.low, df.open
    lr = np.log(c).diff()
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    rng = (h - l).replace(0, np.nan)
    ema20, ema50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    f = pd.DataFrame(index=df.end.values)
    f["ret_1"] = lr.values
    for k in (4, 16, 64):
        f[f"ret_{k}"] = np.log(c / c.shift(k)).values
    f["rv_16"] = lr.rolling(16).std().values
    f["rv_64"] = lr.rolling(64).std().values
    f["rv_ratio"] = (f["rv_16"] / f["rv_64"]).values
    f["atr_bps"] = (atr / c * 1e4).values
    f["range_atr"] = ((h - l) / atr).values
    f["body_frac"] = ((c - o) / rng).values
    f["upper_wick_frac"] = ((h - np.maximum(o, c)) / rng).values
    f["lower_wick_frac"] = ((np.minimum(o, c) - l) / rng).values
    lv = np.log1p(df.volume)
    f["vol_z"] = ((lv - lv.rolling(96, min_periods=20).mean()) / lv.rolling(96, min_periods=20).std()).values
    f["ema20_dist_atr"] = ((c - ema20) / atr).values
    f["ema50_dist_atr"] = ((c - ema50) / atr).values
    f["ema20_slope_atr"] = ((ema20 - ema20.shift(5)) / atr).values
    f["eff_ratio_16"] = ((c - c.shift(16)).abs() / c.diff().abs().rolling(16).sum()).values
    f["rsi_14"] = _rsi(c).values
    ts = pd.to_datetime(df.start, unit="s", utc=True)
    hod = ts.dt.hour + ts.dt.minute / 60
    f["hod_sin"], f["hod_cos"] = np.sin(2 * math.pi * hod / 24).values, np.cos(2 * math.pi * hod / 24).values
    f["dow_sin"], f["dow_cos"] = np.sin(2 * math.pi * ts.dt.day_of_week / 7).values, np.cos(2 * math.pi * ts.dt.day_of_week / 7).values
    rv = pd.Series(f["rv_64"].values)
    f["rv_pctile_480"] = rv.rolling(480, min_periods=100).rank(pct=True).values   # vol regime (causal rank)
    f["trend_sign"] = np.sign(ema20 - ema50).values
    f["dist_hi64_atr"] = ((h.rolling(64).max() - c) / atr).values
    f["dist_lo64_atr"] = ((c - l.rolling(64).min()) / atr).values
    v = vwap_regime_features(bars, asset_class, instrument)
    for col in VWAP_FEATURES:
        f[col] = v[col].values
    return f.replace([np.inf, -np.inf], np.nan)
