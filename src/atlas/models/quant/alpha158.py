"""Alpha158-style price/volume feature library (after Microsoft Qlib's Alpha158, MIT; re-implemented
in pandas, no Qlib dependency). 9 KBAR + 4 price ratios + 29 rolling operators x 5 windows = 158.
Strictly causal: every feature at t uses bars <= t. Missing open/high/low fall back to close."""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = (5, 10, 20, 30, 60)
ROLL_OPS = ["ROC", "MA", "STD", "BETA", "RSQR", "RESI", "MAX", "MIN", "QTLU", "QTLD", "RANK", "RSV", "IMAX", "IMIN",
            "IMXD", "CORR", "CORD", "CNTP", "CNTN", "CNTD", "SUMP", "SUMN", "SUMD", "VMA", "VSTD", "WVMA", "VSUMP", "VSUMN", "VSUMD"]
KBAR = ["KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT", "KSFT2"]
PRICE = ["OPEN0", "HIGH0", "LOW0", "VWAP0"]
ALPHA158 = KBAR + PRICE + [f"{op}{w}" for op in ROLL_OPS for w in WINDOWS]
EPS = 1e-12


def _slope_stats(y: pd.Series, w: int):
    x = pd.Series(np.arange(len(y), dtype=float), index=y.index)
    mx, my = x.rolling(w).mean(), y.rolling(w).mean()
    cov = (x * y).rolling(w).mean() - mx * my
    vx = (x * x).rolling(w).mean() - mx ** 2
    vy = (y * y).rolling(w).mean() - my ** 2
    beta = cov / (vx + EPS)
    r2 = cov ** 2 / (vx * vy + EPS)
    resid = y - (my + beta * (x - mx))
    return beta, r2, resid


def alpha158(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float)
    o = df.get("open", c).astype(float); h = df.get("high", c).astype(float); l = df.get("low", c).astype(float)
    v = df.get("volume", pd.Series(1.0, index=c.index)).astype(float)
    vw = df.get("vwap", (h + l + c) / 3).astype(float)
    f: dict[str, pd.Series] = {}
    rng = h - l + EPS
    f["KMID"] = (c - o) / o; f["KLEN"] = (h - l) / o; f["KMID2"] = (c - o) / rng
    f["KUP"] = (h - np.maximum(o, c)) / o; f["KUP2"] = (h - np.maximum(o, c)) / rng
    f["KLOW"] = (np.minimum(o, c) - l) / o; f["KLOW2"] = (np.minimum(o, c) - l) / rng
    f["KSFT"] = (2 * c - h - l) / o; f["KSFT2"] = (2 * c - h - l) / rng
    f["OPEN0"], f["HIGH0"], f["LOW0"], f["VWAP0"] = o / c, h / c, l / c, vw / c
    ret = c / c.shift(1) - 1
    lv = np.log(v + 1)
    dv = v / v.shift(1)
    up, dn = (c - c.shift(1)).clip(lower=0), (c.shift(1) - c).clip(lower=0)
    vup, vdn = (v - v.shift(1)).clip(lower=0), (v.shift(1) - v).clip(lower=0)
    absd = (c - c.shift(1)).abs()
    for w in WINDOWS:
        r = lambda s: s.rolling(w)
        f[f"ROC{w}"] = c.shift(w) / c
        f[f"MA{w}"] = r(c).mean() / c
        f[f"STD{w}"] = r(c).std() / c
        beta, r2, resid = _slope_stats(c, w)
        f[f"BETA{w}"] = beta / c; f[f"RSQR{w}"] = r2; f[f"RESI{w}"] = resid / c
        mx, mn = r(h).max(), r(l).min()
        f[f"MAX{w}"] = mx / c; f[f"MIN{w}"] = mn / c
        f[f"QTLU{w}"] = r(c).quantile(0.8) / c; f[f"QTLD{w}"] = r(c).quantile(0.2) / c
        f[f"RANK{w}"] = r(c).rank(pct=True)
        f[f"RSV{w}"] = (c - mn) / (mx - mn + EPS)
        imax = r(h).apply(np.argmax, raw=True); imin = r(l).apply(np.argmin, raw=True)
        f[f"IMAX{w}"] = (w - 1 - imax) / w; f[f"IMIN{w}"] = (w - 1 - imin) / w   # bars since max/min
        f[f"IMXD{w}"] = (imax - imin) / w
        f[f"CORR{w}"] = c.rolling(w).corr(lv)
        f[f"CORD{w}"] = (c / c.shift(1)).rolling(w).corr(np.log(dv + 1))
        f[f"CNTP{w}"] = r((ret > 0).astype(float)).mean(); f[f"CNTN{w}"] = r((ret < 0).astype(float)).mean()
        f[f"CNTD{w}"] = f[f"CNTP{w}"] - f[f"CNTN{w}"]
        su, sd, sa = r(up).sum(), r(dn).sum(), r(absd).sum() + EPS
        f[f"SUMP{w}"] = su / sa; f[f"SUMN{w}"] = sd / sa; f[f"SUMD{w}"] = (su - sd) / sa
        f[f"VMA{w}"] = r(v).mean() / (v + EPS); f[f"VSTD{w}"] = r(v).std() / (v + EPS)
        wv = ret.abs() * v
        f[f"WVMA{w}"] = r(wv).std() / (r(wv).mean() + EPS)
        vsu, vsd, vsa = r(vup).sum(), r(vdn).sum(), r((v - v.shift(1)).abs()).sum() + EPS
        f[f"VSUMP{w}"] = vsu / vsa; f[f"VSUMN{w}"] = vsd / vsa; f[f"VSUMD{w}"] = (vsu - vsd) / vsa
    out = pd.DataFrame(f, index=c.index)[ALPHA158]
    return out.replace([np.inf, -np.inf], np.nan)
