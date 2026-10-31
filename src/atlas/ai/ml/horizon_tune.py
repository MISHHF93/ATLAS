"""Horizon tuning for the 15m decision model (milestone c).

For each asset class, pooled over a few real instruments, measure at each candidate horizon (15m ... 24h):
  * out-of-sample rank IC of a small XGBoost on the causal multi-resolution features (15m + 1h layers, the only layers with
    long real history) against the realized forward log return, with a purge/embargo between train and test and a
    date-block bootstrap CI;
  * how often the realized move exceeds the round-trip cost (``costs.VENUE_COSTS``): a horizon whose typical move is far
    below cost cannot pay for a trade no matter the IC.
A horizon is "kept" only if the IC CI lower bound is above zero AND the share of moves above cost is >= MIN_COST_SHARE.
This is a feasibility screen on signal and cost, NOT a profit estimate or a backtest of P&L.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml import multires as M
from atlas.ai.ml.costs import VENUE_COSTS

NY = ZoneInfo("America/New_York")
MIN_COST_SHARE = 0.20
TRAIN_FRAC, TEST_FRAC = 0.60, 0.30
LAYERS = M.GROUP_FEATURES["m15"] + M.GROUP_FEATURES["h1"]

# Horizons (in 15m bars) that milestone (d) will smoke-train. Chosen from var/ml/horizon_tuning/report.json (2-year real bars):
#  * us_equity: 60 min (4 bars) is the only horizon whose OOS rank-IC CI is above zero (5 horizons tested; one hit is weak evidence
#    given multiple comparisons) and >=88% of its moves exceed the modelled cost, 15m/30m kept as secondary research horizons.
#  * crypto: NO horizon passed the IC screen. Moves clear the 124 bp round trip only at >= 8h (28%) and 24h (52%), so (d) trains
#    8h and 24h and still has to pass the unchanged gates. Shorter horizons are dropped: moves are mostly below cost.
# This is a screen on signal and cost only, not evidence of profitability.
SELECTED_FOR_D = {"crypto": (32, 96), "us_equity": (1, 2, 4)}


def forward_returns(b15: M.Bars, grid: Sequence[int], hs: Sequence[int], same_session: bool) -> pd.DataFrame:
    """log(close_end(T+h*900) / close_end(T)); NaN unless both bars exist (and, for stocks, lie in the same ET session)."""
    ce = {int(e): float(c) for e, c in zip(b15.end, b15.c)}
    out = {}
    for h in hs:
        col = []
        for T in grid:
            a, b = ce.get(int(T)), ce.get(int(T) + h * 900)
            ok = a is not None and b is not None and a > 0 and b > 0
            if ok and same_session:
                ok = datetime.fromtimestamp(int(T) - 1, NY).date() == datetime.fromtimestamp(int(T) + h * 900 - 1, NY).date()
            col.append(math.log(b / a) if ok else float("nan"))
        out[f"r{h}"] = col
    return pd.DataFrame(out, index=pd.Index([int(t) for t in grid], name="decision_ts"))


def class_frame(symbol: str, inp: M.Inputs, start: int, end: int, hs: Sequence[int], stock: bool) -> pd.DataFrame:
    b = inp.s15
    if b is None or len(b) < 100:
        return pd.DataFrame()
    grid = [t for t in M.decision_grid(max(start, int(b.end[0])), min(end, int(b.end[-1]))) if True]
    X = M.build_frame(inp, grid)[list(LAYERS)]
    R = forward_returns(b, grid, hs, same_session=stock)
    df = pd.concat([X, R], axis=1)
    df["symbol"] = symbol
    return df


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 30:
        return float("nan")
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def date_block_ci(dates: np.ndarray, a: np.ndarray, b: np.ndarray, reps=300, seed=3) -> tuple[float, float]:
    ud = np.unique(dates)
    if len(ud) < 20:
        return float("nan"), float("nan")
    idx = {d: np.where(dates == d)[0] for d in ud}
    rng = np.random.default_rng(seed)
    v = []
    for _ in range(reps):
        pick = rng.choice(ud, size=len(ud), replace=True)
        ii = np.concatenate([idx[d] for d in pick])
        v.append(spearman(a[ii], b[ii]))
    v = [x for x in v if x == x]
    return (float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))) if v else (float("nan"), float("nan"))


def tune_class(df: pd.DataFrame, hs: Sequence[int], cost_bps: float, embargo_bars: int = 96) -> list[dict]:
    import xgboost as xgb
    df = df.sort_index(kind="stable")
    ts = df.index.to_numpy()
    n = len(df)
    i_tr = int(n * TRAIN_FRAC)
    i_te = int(n * (1 - TEST_FRAC))
    res = []
    for h in hs:
        gap = (h + embargo_bars) * 900
        tr = df.iloc[:i_tr]
        tr = tr[tr.index.to_numpy() <= ts[i_te] - gap]                       # purge: train labels end before the test starts
        te = df.iloc[i_te:]
        tr, te = tr[tr[f"r{h}"].notna()], te[te[f"r{h}"].notna()]
        row = {"h_bars": int(h), "horizon_min": int(h * 15), "n_train": int(len(tr)), "n_test": int(len(te)), "cost_bps": cost_bps}
        if len(tr) < 1000 or len(te) < 300:
            row.update(ic=float("nan"), ic_ci95=[float("nan")] * 2, kept=False, reason="too few real labelled rows")
            res.append(row)
            continue
        m = xgb.XGBRegressor(n_estimators=120, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=50,
                             reg_lambda=5.0, tree_method="hist", n_jobs=2, random_state=7)
        m.fit(tr[list(LAYERS)].to_numpy(float), tr[f"r{h}"].to_numpy(float))
        p = m.predict(te[list(LAYERS)].to_numpy(float))
        y = te[f"r{h}"].to_numpy(float)
        dates = (te.index.to_numpy() // 86400)
        ic = spearman(p, y)
        lo, hi = date_block_ci(dates, p, y)
        share = float(np.mean(np.abs(y) * 1e4 > cost_bps))
        keep = lo > 0 and share >= MIN_COST_SHARE
        why = [] if keep else ([] if lo > 0 else ["IC CI includes 0"]) + ([] if share >= MIN_COST_SHARE else [f"only {share:.0%} of moves exceed {cost_bps:g} bp cost"])
        row.update(ic=ic, ic_ci95=[lo, hi], move_gt_cost_share=share, median_abs_move_bps=float(np.median(np.abs(y)) * 1e4), kept=bool(keep), reason="; ".join(why))
        res.append(row)
    return res
