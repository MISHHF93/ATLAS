"""Point-in-time technical features from daily bars (only data up to t)."""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["ret_1", "ret_5", "ret_20", "vol_20", "rsi_14", "dist_ma20", "dist_ma50", "vol_z20"]


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: index=datetime, columns close, volume. Returns FEATURES (NaN warm-up rows dropped by caller)."""
    c, v = df["close"].astype(float), df["volume"].astype(float)
    r = np.log(c).diff()
    out = pd.DataFrame(index=df.index)
    out["ret_1"] = r
    out["ret_5"] = np.log(c / c.shift(5))
    out["ret_20"] = np.log(c / c.shift(20))
    out["vol_20"] = r.rolling(20).std()
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
    out["rsi_14"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    out["dist_ma20"] = c / c.rolling(20).mean() - 1
    out["dist_ma50"] = c / c.rolling(50).mean() - 1
    vs = v.rolling(20).std()
    out["vol_z20"] = ((v - v.rolling(20).mean()) / vs.replace(0, np.nan)).where(vs.notna() & (vs != 0), 0.0).where(vs.notna())
    return out[FEATURES]


def make_labels(df: pd.DataFrame, horizon: int, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    """Forward log return over `horizon` bars after costs; label = 1 if > 0 after cost."""
    c = df["close"].astype(float)
    fwd = np.log(c.shift(-horizon) / c) - cost_bps / 1e4
    return (fwd > 0).astype(float).where(fwd.notna()), fwd


def dataset(bars: dict[str, pd.DataFrame], horizon: int = 5, cost_bps: float = 10.0) -> pd.DataFrame:
    """Stacked (date, symbol) dataset sorted by time. Columns FEATURES + y + fwd + symbol."""
    parts = []
    for sym, df in bars.items():
        f = make_features(df)
        y, fwd = make_labels(df, horizon, cost_bps)
        p = f.assign(y=y, fwd=fwd, symbol=sym).dropna()
        parts.append(p)
    out = pd.concat(parts).sort_index(kind="mergesort")
    return out


def bars_frame_close_volume_time_index(bars) -> pd.DataFrame:
    return pd.DataFrame({"close": [b.close for b in bars], "volume": [b.volume for b in bars]},
                        index=pd.DatetimeIndex([b.ts for b in bars]))


# Deprecated name; use ``bars_frame_close_volume_time_index`` (close+volume, DatetimeIndex). Not the same as atlas.ml.features.bars_frame.
bars_frame = bars_frame_close_volume_time_index
