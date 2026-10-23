"""Triple-barrier labels (AFML ch.3). Barriers scaled by the per-day volatility FORECAST known at
entry (VolModel.var_path, or a causal EWMA fallback): upper = entry*exp(pt*sigma*sqrt(h)), lower =
entry*exp(-sl*sigma*sqrt(h)), vertical = max_hold bars. Every label carries t1 (exit time) so purged
CV / CPCV can purge overlapping samples. Barrier widths are hyperparameters -> log them as trials."""
from __future__ import annotations

import numpy as np
import pandas as pd


def causal_daily_vol(close: pd.Series, span: int = 50) -> pd.Series:
    """EWMA std of log returns using data up to t-1 only (shifted)."""
    r = np.log(close.astype(float)).diff()
    return r.ewm(span=span, min_periods=20).std().shift(1)


def vol_from_model(close: pd.Series, vol_model) -> pd.Series:
    r = np.log(close.astype(float)).diff().dropna()
    return np.sqrt(vol_model.var_path(r)).reindex(close.index)


def triple_barrier(close: pd.Series, side: pd.Series | None = None, pt: float = 1.0, sl: float = 1.0,
                   max_hold: int = 10, vol: pd.Series | None = None, cost_bps: float = 0.0,
                   min_vol: float = 1e-4) -> pd.DataFrame:
    """Returns DataFrame indexed by entry time: t1, ret (side-adjusted log return net of cost),
    barrier ('pt'|'sl'|'vertical'), label (+1/-1 by sign of ret; meta-label bin = ret > 0), sigma.
    side: +1 long / -1 short / 0 no trade (default all long). Entries with no vol forecast are dropped."""
    c = close.astype(float)
    sig = (vol if vol is not None else causal_daily_vol(c)).reindex(c.index)
    sd = (side if side is not None else pd.Series(1, index=c.index)).reindex(c.index).fillna(0)
    vals, idx = c.to_numpy(), c.index
    rows = []
    for i in range(len(c) - 1):
        s, v = sd.iat[i], sig.iat[i]
        if s == 0 or not np.isfinite(v):
            continue
        v = max(v, min_vol)
        end = min(i + max_hold, len(c) - 1)
        path = np.log(vals[i + 1:end + 1] / vals[i]) * s
        width = v * np.sqrt(max_hold)
        up, dn = pt * width, -sl * width
        hit_up = np.nonzero(path >= up)[0] if pt > 0 else np.array([], int)
        hit_dn = np.nonzero(path <= dn)[0] if sl > 0 else np.array([], int)
        first_up = hit_up[0] if len(hit_up) else np.inf
        first_dn = hit_dn[0] if len(hit_dn) else np.inf
        if first_up == np.inf and first_dn == np.inf:
            if end - i < max_hold:   # not enough future to resolve: unknown label, drop
                continue
            j, b = len(path) - 1, "vertical"
        elif first_up <= first_dn:
            j, b = int(first_up), "pt"
        else:
            j, b = int(first_dn), "sl"
        ret = float(path[j]) - cost_bps / 1e4
        rows.append((idx[i], idx[i + 1 + j], ret, b, int(np.sign(ret)) or -1, int(ret > 0), float(v), int(s)))
    return pd.DataFrame(rows, columns=["t0", "t1", "ret", "barrier", "label", "bin", "sigma", "side"]).set_index("t0")


def label_concurrency_weights(t0: pd.Index, t1: pd.Series) -> pd.Series:
    """Average uniqueness weights (AFML 4.4): overlapping labels share information."""
    times = pd.DatetimeIndex(sorted(set(t0) | set(t1)))
    pos = {t: k for k, t in enumerate(times)}
    conc = np.zeros(len(times))
    for a, b in zip(t0, t1):
        conc[pos[a]:pos[b] + 1] += 1
    w = [float(np.mean(1.0 / conc[pos[a]:pos[b] + 1])) for a, b in zip(t0, t1)]
    return pd.Series(w, index=t0)
