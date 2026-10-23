"""alphalens-style factor tear sheet (re-implemented; alphalens-reloaded is Apache-2.0 but drags old
pandas pins). Information coefficient (Spearman, per date), IC IR, quantile spread, turnover and
IC decay across horizons. Used to screen features before they reach the stacker."""
from __future__ import annotations

import numpy as np
import pandas as pd


def forward_returns(close: pd.DataFrame, horizons=(1, 5, 10, 20)) -> dict[int, pd.DataFrame]:
    return {h: close.shift(-h) / close - 1 for h in horizons}


def ic_series(factor: pd.DataFrame, fwd: pd.DataFrame, min_names: int = 5) -> pd.Series:
    f, r = factor.rank(axis=1), fwd.reindex_like(factor).rank(axis=1)
    ok = (factor.notna() & fwd.reindex_like(factor).notna()).sum(1) >= min_names
    return f[ok].corrwith(r[ok], axis=1).dropna()


def quantile_returns(factor: pd.DataFrame, fwd: pd.DataFrame, q: int = 5) -> pd.Series:
    labels = factor.rank(axis=1, pct=True).apply(lambda s: np.ceil(s * q).clip(1, q), axis=1)
    stacked = pd.DataFrame({"q": labels.stack(), "r": fwd.reindex_like(factor).stack()}).dropna()
    return stacked.groupby("q")["r"].mean()


def turnover(factor: pd.DataFrame, q: int = 5) -> dict:
    """Top-quantile churn and factor-rank autocorrelation (lag 1)."""
    pct = factor.rank(axis=1, pct=True)
    top = pct >= 1 - 1 / q
    churn = (top & ~top.shift(1, fill_value=False)).sum(1) / top.sum(1).replace(0, np.nan)
    rank_ac = pct.corrwith(pct.shift(1), axis=1)
    return {"top_quantile_turnover": float(churn.iloc[1:].mean()), "rank_autocorr": float(rank_ac.mean())}


def tear_sheet(factor: pd.DataFrame, close: pd.DataFrame, horizons=(1, 5, 10, 20), q: int = 5) -> dict:
    fw = forward_returns(close, horizons)
    decay = {}
    for h, r in fw.items():
        ic = ic_series(factor, r)
        decay[h] = {"ic_mean": float(ic.mean()) if len(ic) else float("nan"),
                    "ic_ir": float(ic.mean() / ic.std(ddof=1)) if len(ic) > 2 and ic.std(ddof=1) > 0 else float("nan"),
                    "t_stat": float(ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))) if len(ic) > 2 and ic.std(ddof=1) > 0 else float("nan"),
                    "n_dates": int(len(ic))}
    h0 = horizons[0]
    qr = quantile_returns(factor, fw[h0], q)
    return {"ic_by_horizon": decay, "quantile_mean_return": {int(k): float(v) for k, v in qr.items()},
            "top_minus_bottom": float(qr.iloc[-1] - qr.iloc[0]) if len(qr) >= 2 else float("nan"),
            **turnover(factor, q)}


def screen(features: dict[str, pd.DataFrame], close: pd.DataFrame, horizon: int = 5, min_abs_ic: float = 0.02,
           min_abs_t: float = 2.0) -> pd.DataFrame:
    """Rank candidate features by |IC| at `horizon`; keep those with |IC| and |t| above thresholds.
    Each feature screened counts as a trial -> log it in the TrialLog."""
    rows = []
    fwd = close.shift(-horizon) / close - 1
    for name, f in features.items():
        ic = ic_series(f, fwd)
        t = ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic)) if len(ic) > 2 and ic.std(ddof=1) > 0 else 0.0
        rows.append({"feature": name, "ic": float(ic.mean()) if len(ic) else 0.0, "t": float(t)})
    out = pd.DataFrame(rows).set_index("feature")
    out["keep"] = (out.ic.abs() >= min_abs_ic) & (out.t.abs() >= min_abs_t)
    return out.sort_values("ic", key=abs, ascending=False)
