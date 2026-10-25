"""Cross-sectional factor sleeves (value, momentum, quality, low-vol) with sector neutralization, and
time-series momentum (trend) for FX/crypto. Factor scores are research signals feeding the sleeve
scorers / portfolio construction; they never bypass the risk gate.

Inputs are point-in-time panels (index=date, columns=symbol). Fundamentals must be aligned by
FILING/availability date (see FeatureStore / PITUniverse), never by fiscal period end."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _z(x: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional winsorized z-score per date."""
    lo, hi = x.quantile(0.02, axis=1), x.quantile(0.98, axis=1)
    x = x.clip(lo, hi, axis=0)
    return x.sub(x.mean(1), axis=0).div(x.std(1).replace(0, np.nan), axis=0)


def sector_neutralize(score: pd.DataFrame, sectors: pd.DataFrame | dict) -> pd.DataFrame:
    """Demean within sector per date (then re-standardize). sectors: date x symbol panel or {symbol: sector}."""
    if isinstance(sectors, dict):
        sectors = pd.DataFrame([sectors] * len(score), index=score.index)
    sectors = sectors.reindex_like(score)
    out = score.copy()
    for t in score.index:
        s, g = score.loc[t], sectors.loc[t]
        out.loc[t] = s - s.groupby(g).transform("mean")
    return out.div(out.std(1).replace(0, np.nan), axis=0)   # rescale only: keeps sector means at 0


def momentum(close: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """12-1 momentum: return from t-lookback to t-skip (skips the short-term reversal month)."""
    return _z(np.log(close.shift(skip) / close.shift(lookback)))


def low_vol(close: pd.DataFrame, window: int = 126) -> pd.DataFrame:
    return _z(-np.log(close).diff().rolling(window).std())


def value(book_to_price: pd.DataFrame | None = None, earnings_yield: pd.DataFrame | None = None,
          close: pd.DataFrame | None = None, long_rev: int = 1260) -> pd.DataFrame:
    """Composite value from PIT fundamentals; falls back to 5y price reversal (Asness et al. 2013 use
    this proxy for asset classes without book values, e.g. FX/commodities)."""
    parts = [_z(x) for x in (book_to_price, earnings_yield) if x is not None]
    if not parts:
        if close is None:
            raise ValueError("need fundamentals or close")
        parts = [_z(-np.log(close / close.shift(long_rev)))]
    return _z(sum(parts) / len(parts))


def quality(roe: pd.DataFrame | None = None, gross_profitability: pd.DataFrame | None = None,
            leverage: pd.DataFrame | None = None, earnings_vol: pd.DataFrame | None = None) -> pd.DataFrame:
    """QMJ-style: profitability up, safety (low leverage / low earnings volatility) up."""
    parts = [_z(x) for x in (roe, gross_profitability) if x is not None] + [-_z(x) for x in (leverage, earnings_vol) if x is not None]
    if not parts:
        raise ValueError("quality needs at least one PIT fundamental")
    return _z(sum(parts) / len(parts))


def composite(scores: dict[str, pd.DataFrame], sectors=None, weights: dict[str, float] | None = None) -> pd.DataFrame:
    w = weights or {k: 1.0 for k in scores}
    tot = sum(w[k] * (sector_neutralize(s, sectors) if sectors is not None else s).fillna(0) for k, s in scores.items())
    return _z(tot / sum(w.values()))


def ts_momentum(close: pd.Series | pd.DataFrame, lookbacks=(21, 63, 126, 252), target_vol: float = 0.15,
                vol_window: int = 60, ann: int = 252, max_leverage: float = 1.0, long_only: bool = True):
    """Time-series momentum (Moskowitz-Ooi-Pedersen 2012): average sign of past returns over several
    lookbacks, scaled to a vol target using trailing (causal) vol. Spot-only => long_only clips shorts
    to 0 (flat). Output is a target exposure in [0 or -max_leverage, max_leverage]."""
    lc = np.log(close)
    sig = sum(np.sign(lc - lc.shift(L)) for L in lookbacks) / len(lookbacks)
    vol = lc.diff().rolling(vol_window).std() * np.sqrt(ann)
    pos = (sig * target_vol / vol.replace(0, np.nan)).clip(-max_leverage, max_leverage)
    return pos.clip(lower=0) if long_only else pos
