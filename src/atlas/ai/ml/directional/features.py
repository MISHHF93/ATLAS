"""Features v2 (ATLAS_MODEL_SPEC.md section 3). Every feature at bar i uses only bars <= i (and reference bars ending <= end_i).

Groups added on top of ``atlas.ai.ml.features.bar_features`` (price action, volatility, volume, session, VWAP, vol regime):
  har        log realised variance over 1 day / 1 week / 1 month of bars (Corsi HAR-RV inputs) + their ratios
  mtf        multi-timeframe: volatility-normalised returns and range position over 4/16/64/256 bars
  regime     trend strength, drawdown from rolling high, vol-of-vol state, high-vol flag (causal, no look-ahead)
  cross      lagged returns of reference assets aligned by bar end (strictly <=), and rolling correlation
Account-aware features are NOT training columns: an account snapshot has no history in the feed. They are inference-time,
read-only inputs to sizing feasibility (``account_context``), kept out of the model so no fake history is learned.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from atlas.ai.ml.features import BAR_FEATURES, bar_features, bars_frame
from atlas.ai.ml.directional.layers25 import LAYER_FEATURE_NAMES, layer_features
from atlas.features.price_action.bars import Bar

# approximate bars per trading day by (is_24x7, interval); used only to set window lengths
_DAY_BARS_24 = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}
_DAY_BARS_RTH = {"1m": 390, "5m": 78, "15m": 26, "1h": 7, "4h": 2, "1d": 1}

HAR_FEATURES = ("log_rv_d", "log_rv_w", "log_rv_m", "har_ratio_dw", "har_ratio_wm")
MTF_FEATURES = tuple(f"z_ret_{k}" for k in (4, 16, 64, 256)) + tuple(f"range_pos_{k}" for k in (16, 64, 256))
REGIME_FEATURES = ("trend_strength_64", "drawdown_256", "volvol_64", "high_vol_flag")
CROSS_LAGS = (1, 4, 16)


def cross_feature_names(refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"x_{r}_ret_{k}" for r in refs for k in CROSS_LAGS) + tuple(f"x_{r}_corr_64" for r in refs)


def v2_feature_names(refs: Sequence[str] = ()) -> tuple[str, ...]:
    """The evo-14 v2 set before the layer features (kept for the before/after count)."""
    return BAR_FEATURES + HAR_FEATURES + MTF_FEATURES + REGIME_FEATURES + cross_feature_names(refs)


def feature_names(refs: Sequence[str] = ()) -> tuple[str, ...]:
    """v2 set + the numeric output of every chart layer that can be a feature (layers25.LAYER_FEATURES)."""
    return v2_feature_names(refs) + LAYER_FEATURE_NAMES


def day_bars(interval: str, is_24x7: bool) -> int:
    return (_DAY_BARS_24 if is_24x7 else _DAY_BARS_RTH).get(interval, 1)


def _roll_rv(r2: pd.Series, n: int) -> pd.Series:
    return r2.rolling(max(2, n), min_periods=max(2, n // 2)).sum()


def own_features(bars: Sequence[Bar], interval: str, asset_class: str | None, instrument: str | None, is_24x7: bool) -> pd.DataFrame:
    base = bar_features(list(bars), asset_class, instrument)
    df = bars_frame(bars)
    c = df["close"]
    lr = np.log(c).diff()
    r2 = lr ** 2
    d = day_bars(interval, is_24x7)
    rv_d, rv_w, rv_m = _roll_rv(r2, d), _roll_rv(r2, 5 * d), _roll_rv(r2, 22 * d)
    f = base.copy()
    eps = 1e-12
    f["log_rv_d"], f["log_rv_w"], f["log_rv_m"] = [np.log(x.to_numpy() + eps) for x in (rv_d, rv_w, rv_m)]
    f["har_ratio_dw"] = f["log_rv_d"] - f["log_rv_w"]
    f["har_ratio_wm"] = f["log_rv_w"] - f["log_rv_m"]
    sig = lr.ewm(span=100, min_periods=20, adjust=False).std()
    for k in (4, 16, 64, 256):
        f[f"z_ret_{k}"] = (np.log(c / c.shift(k)) / (sig * np.sqrt(k))).to_numpy()
    for k in (16, 64, 256):
        hi, lo = df["high"].rolling(k, min_periods=k).max(), df["low"].rolling(k, min_periods=k).min()
        f[f"range_pos_{k}"] = ((c - lo) / (hi - lo).replace(0, np.nan)).to_numpy()
    f["trend_strength_64"] = f["z_ret_64"]
    f["drawdown_256"] = (c / df["high"].rolling(256, min_periods=32).max() - 1.0).to_numpy()
    f["volvol_64"] = sig.rolling(64, min_periods=32).std().to_numpy() / (sig.rolling(64, min_periods=32).mean().to_numpy() + eps)
    f["high_vol_flag"] = (sig.to_numpy() > sig.expanding(min_periods=100).median().to_numpy()).astype(float)
    return f.replace([np.inf, -np.inf], np.nan)


def cross_features(own_end: np.ndarray, own_close: np.ndarray, refs: Mapping[str, tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    """refs: name -> (end_times, closes). Reference value at own bar i is the last reference bar with end <= own_end[i]."""
    own_end = np.asarray(own_end, np.int64)
    out = pd.DataFrame(index=range(len(own_end)))
    own_ret = pd.Series(np.log(np.asarray(own_close, float))).diff()
    left = pd.DataFrame({"end": own_end})
    for name, (r_end, r_close) in refs.items():
        right = pd.DataFrame({"end": np.asarray(r_end, np.int64), "c": np.asarray(r_close, float)}).sort_values("end")
        m = pd.merge_asof(left, right, on="end", direction="backward")
        lc = np.log(m["c"])
        for k in CROSS_LAGS:
            out[f"x_{name}_ret_{k}"] = (lc - lc.shift(k)).to_numpy()
        out[f"x_{name}_corr_64"] = own_ret.rolling(64, min_periods=32).corr(lc.diff()).to_numpy()
    return out.replace([np.inf, -np.inf], np.nan)


def build_features(bars: Sequence[Bar], interval: str, asset_class: str | None, instrument: str | None, is_24x7: bool,
                   refs: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None, horizon: int | None = None, cost_bps: float = 4.0,
                   corr_refs: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None, events: Sequence[float] | None = None, news: Mapping | None = None, extra: Mapping | None = None) -> pd.DataFrame:
    """corr_refs: symbol -> (end, close) for the cross-asset layer (DXY/UUP, GLD, BTC, SPY where stored). events: scheduled release times (epoch s)."""
    f = own_features(bars, interval, asset_class, instrument, is_24x7)
    refs = {k: v for k, v in (refs or {}).items() if k != instrument}
    if refs:
        x = cross_features(f.index.to_numpy(), [b.close for b in bars], refs)
        x.index = f.index
        f = pd.concat([f, x], axis=1)
    H = horizon or max(4, day_bars(interval, is_24x7))
    lay = layer_features(bars, interval, asset_class, instrument, H, cost_bps, corr_refs, events, news, extra)
    lay.index = f.index
    return pd.concat([f, lay], axis=1)


def account_context(snapshot) -> dict:
    """Read-only account inputs for sizing feasibility. Not a model feature (see module docstring)."""
    from atlas.broker_state.features import snapshot_features
    return snapshot_features(snapshot)
