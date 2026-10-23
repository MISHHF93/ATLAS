"""HRP / HERC portfolio construction (skfolio, BSD-3, optional) with an in-house HRP fallback
(López de Prado 2016) and an inverse-volatility benchmark. Long-only, fully invested, then clipped
to a per-asset cap and renormalised: these weights only ALLOCATE a budget the risk gate still caps.
Benchmarking is walk-forward: fit on a trailing window, hold for `rebalance` days, OOS only."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform


def skfolio_available() -> bool:
    try:
        import skfolio  # noqa: F401
        return True
    except Exception:
        return False


def inverse_vol(returns: pd.DataFrame) -> pd.Series:
    iv = 1 / returns.std().replace(0, np.nan)
    return (iv / iv.sum()).fillna(0)


def _hrp_inhouse(returns: pd.DataFrame) -> pd.Series:
    cov, corr = returns.cov().to_numpy(), returns.corr().fillna(0).to_numpy()
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
    np.fill_diagonal(dist, 0)
    order = leaves_list(linkage(squareform(dist, checks=False), "single"))
    w = np.ones(len(order))
    clusters = [list(order)]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) < 2:
                continue
            a, b = c[: len(c) // 2], c[len(c) // 2:]
            def cvar(ix):
                sub = cov[np.ix_(ix, ix)]; iv = 1 / np.diag(sub); iv /= iv.sum()
                return float(iv @ sub @ iv)
            va, vb = cvar(a), cvar(b)
            alpha = 1 - va / (va + vb)
            w[a] *= alpha; w[b] *= 1 - alpha
            nxt += [a, b]
        clusters = nxt
    return pd.Series(w / w.sum(), index=returns.columns)


def hrp(returns: pd.DataFrame, use_skfolio: bool = True) -> pd.Series:
    if use_skfolio and skfolio_available():
        from skfolio.optimization import HierarchicalRiskParity
        m = HierarchicalRiskParity().fit(returns.to_numpy())
        return pd.Series(m.weights_, index=returns.columns)
    return _hrp_inhouse(returns)


def herc(returns: pd.DataFrame) -> pd.Series:
    if not skfolio_available():
        raise RuntimeError("HERC needs the optional 'portfolio' extra (skfolio)")
    from skfolio.optimization import HierarchicalEqualRiskContribution
    m = HierarchicalEqualRiskContribution().fit(returns.to_numpy())
    return pd.Series(m.weights_, index=returns.columns)


def cap_weights(w: pd.Series, max_weight: float) -> pd.Series:
    w = w.clip(lower=0)
    w = w / w.sum()
    for _ in range(50):
        over = w > max_weight + 1e-12
        if not over.any():
            break
        excess = (w[over] - max_weight).sum()
        w[over] = max_weight
        free = ~over & (w < max_weight)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


METHODS = {"inverse_vol": inverse_vol, "hrp": hrp, "herc": herc}


def walk_forward_benchmark(returns: pd.DataFrame, methods=("inverse_vol", "hrp", "herc"), lookback: int = 252,
                           rebalance: int = 21, max_weight: float = 1.0, ann: int = 252) -> dict:
    from atlas.models.quant.metrics import max_drawdown_pct
    res = {}
    for name in methods:
        if name == "herc" and not skfolio_available():
            continue
        f = METHODS[name]
        oos, turn, prev = [], [], None
        for start in range(lookback, len(returns), rebalance):
            w = cap_weights(f(returns.iloc[start - lookback:start]), max_weight)
            hold = returns.iloc[start:start + rebalance]
            oos.append(hold.to_numpy() @ w.to_numpy())
            if prev is not None:
                turn.append(float((w - prev).abs().sum() / 2))
            prev = w
        r = np.concatenate(oos)
        sd = r.std(ddof=1)
        res[name] = {"ann_return": float(r.mean() * ann), "ann_vol": float(sd * np.sqrt(ann)),
                     "sharpe": float(r.mean() / sd * np.sqrt(ann)) if sd > 0 else 0.0,
                     "max_drawdown_pct": max_drawdown_pct(np.log1p(r)), "avg_turnover": float(np.mean(turn)) if turn else 0.0,
                     "n_oos_days": int(len(r))}
    return res
