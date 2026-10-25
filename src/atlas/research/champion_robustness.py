"""evo8: robustness of an evolution champion candidate on its walk-forward OOS trades (research only).

* ``oos_trades``: re-fits the genome per purged walk-forward fold exactly as ml.evolution.evaluate_genome does
  (``use_conformal=False``), returning every OOS opportunity with its take decision and after-cost R.
* ``block_bootstrap_ci``: circular block bootstrap (Politis-Romano style, fixed block length) of a statistic over
  a series ordered in time; blocks preserve short-range dependence between neighbouring trades.
* ``stability``: taken-trade R grouped by symbol, symbol group (BTC/ETH vs alts), fold, calendar month, and time halves.
No profitability claim: CIs that span 0 mean the sign of the edge is not established.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd


def oos_trades(data: pd.DataFrame, genome: dict[str, str], n_folds: int | None = None) -> pd.DataFrame:
    from atlas.ml import evolution as E
    from atlas.ml.train import fit_meta
    feats = E.feature_list(genome)
    parts = []
    for k, tr, te in E.folds(data, n_folds or E.N_FOLDS):
        mm = fit_meta(data, tr, genome["model"], feats)
        if mm is None:
            continue
        X = data.iloc[te]
        d = mm.decide(X, use_conformal=False)
        parts.append(pd.DataFrame({"t": X.t.to_numpy(), "instrument": X.instrument.to_numpy(), "r": X.r.to_numpy(float),
                                   "p": d["p"], "take": np.asarray(d["take"], bool), "fold": k}))
    return pd.concat(parts, ignore_index=True).sort_values(["t", "instrument"]).reset_index(drop=True) if parts else pd.DataFrame()


def block_bootstrap_ci(x, stat: Callable[[np.ndarray], float] = np.mean, block: int = 10, n_boot: int = 2000,
                       seed: int = 8, alpha: float = 0.05) -> dict[str, Any]:
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return {"n": n, "status": "insufficient"}
    b = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    k = int(np.ceil(n / b))
    xx = np.concatenate([x, x[:b]])  # circular
    stats = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, k)
        idx = (starts[:, None] + np.arange(b)[None, :]).ravel()[:n]
        stats[i] = stat(xx[idx])
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    return {"n": n, "block": b, "n_boot": n_boot, "point": float(stat(x)), "lo": float(lo), "hi": float(hi),
            "share_boot_gt_0": float((stats > 0).mean()), "spans_zero": bool(lo <= 0 <= hi)}


def _grp(df: pd.DataFrame, key) -> list[dict[str, Any]]:
    out = []
    for k, g in df.groupby(key, sort=True):
        tk = g[g["take"]]
        out.append({"key": str(k), "n_opps": int(len(g)), "n_taken": int(len(tk)),
                    "mean_r_taken": float(tk.r.mean()) if len(tk) else None,
                    "ev_r_per_opportunity": float(tk.r.sum() / len(g)) if len(g) else None,
                    "take_all_mean_r": float(g.r.mean())})
    return out


def stability(oos: pd.DataFrame, core=("BTCUSDT", "ETHUSDT")) -> dict[str, Any]:
    df = oos.copy()
    df["group"] = np.where(df.instrument.isin(core), "btc_eth", "alts")
    df["month"] = pd.to_datetime(df.t, unit="s", utc=True).dt.strftime("%Y-%m")
    mid = df.t.iloc[len(df) // 2] if len(df) else 0
    df["half"] = np.where(df.t < mid, "first_half", "second_half")
    by_sym = _grp(df, "instrument")
    pos = [s for s in by_sym if s["n_taken"] and s["mean_r_taken"] > 0]
    with_trades = [s for s in by_sym if s["n_taken"]]
    by_month = _grp(df, "month")
    return {"by_group": _grp(df, "group"), "by_fold": _grp(df, "fold"), "by_half": _grp(df, "half"), "by_month": by_month,
            "by_symbol": by_sym, "symbols_with_trades": len(with_trades), "symbols_positive_mean_r": len(pos),
            "months_with_trades": sum(1 for m in by_month if m["n_taken"]),
            "months_positive_ev": sum(1 for m in by_month if m["n_taken"] and m["ev_r_per_opportunity"] > 0),
            "share_taken_r_from_last_fold": _share_last_fold(df)}


def _share_last_fold(df: pd.DataFrame) -> float | None:
    tk = df[df["take"]]
    tot = tk.r.sum()
    if not len(tk) or tot == 0:
        return None
    return float(tk[tk.fold == tk.fold.max()].r.sum() / tot)


def report(oos: pd.DataFrame, block: int = 10, n_boot: int = 2000) -> dict[str, Any]:
    tk = oos[oos["take"]]
    ev_series = np.where(oos["take"], oos.r, 0.0)
    return {"n_opps": int(len(oos)), "n_taken": int(len(tk)),
            "ci_mean_r_taken": block_bootstrap_ci(tk.r.to_numpy(), block=block, n_boot=n_boot),
            "ci_ev_r_per_opportunity": block_bootstrap_ci(ev_series, block=block, n_boot=n_boot),
            "ci_take_all_mean_r": block_bootstrap_ci(oos.r.to_numpy(), block=block, n_boot=n_boot),
            "ci_mean_r_taken_excl_last_fold": block_bootstrap_ci(tk[tk.fold != oos.fold.max()].r.to_numpy(), block=block, n_boot=n_boot),
            "block_sensitivity": {str(b): block_bootstrap_ci(tk.r.to_numpy(), block=b, n_boot=n_boot) for b in (1, 5, 20)},
            "stability": stability(oos)}
