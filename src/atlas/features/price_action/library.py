"""Indicator and quantitative math library (mandate §14-15).

Reuses EMA/RSI/ATR/Bollinger/VWAP from ``indicators.py``; adds the rest.
Conventions: inputs are sequences aligned to *confirmed* bars; output index i
uses only inputs[0..i] (no look-ahead). Warmup positions return ``None``.
Missing data: NaN inputs propagate as ``None`` for windowed stats.
Formulas are documented in docs/research/indicator-catalog.md.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from atlas.features.price_action.indicators import atr_batch, ema_batch, true_range_batch

EPS = 1e-12


def _window_ok(w) -> bool:
    return not any(v is None or (isinstance(v, float) and math.isnan(v)) for v in w)


def sma_batch(x: Sequence[float], n: int) -> list[float | None]:
    """SMA_t = (1/n) sum_{i<n} P_{t-i}; warmup n-1."""
    out: list[float | None] = []
    for i in range(len(x)):
        w = x[i - n + 1:i + 1] if i >= n - 1 else None
        out.append(sum(w) / n if w is not None and _window_ok(w) else None)
    return out


def slope_batch(x: Sequence[float | None], k: int = 1) -> list[float | None]:
    """(x_t - x_{t-k}) / k."""
    return [None if i < k or x[i] is None or x[i - k] is None else (x[i] - x[i - k]) / k for i in range(len(x))]


def macd_batch(x, fast=12, slow=26, signal=9):
    """MACD = EMA_fast - EMA_slow; signal = EMA(MACD, signal); hist = MACD - signal."""
    f, s = ema_batch(x, fast), ema_batch(x, slow)
    m = [None if a is None or b is None else a - b for a, b in zip(f, s)]
    start = next((i for i, v in enumerate(m) if v is not None), len(m))
    sig_tail = ema_batch([v for v in m[start:]], signal) if start < len(m) else []
    sig = [None] * start + list(sig_tail)
    hist = [None if a is None or b is None else a - b for a, b in zip(m, sig)]
    return m, sig, hist


def adx_batch(h, l, c, n: int = 14):
    """Wilder DMI/ADX. Returns (+DI, -DI, ADX). Warmup: DI at n, ADX at 2n-1."""
    N = len(c)
    pdi: list[float | None] = [None] * N
    mdi: list[float | None] = [None] * N
    adx: list[float | None] = [None] * N
    if N <= n:
        return pdi, mdi, adx
    tr = true_range_batch(h, l, c)
    pdm = [0.0] * N
    mdm = [0.0] * N
    for i in range(1, N):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
    atr = sum(tr[1:n + 1]); sp = sum(pdm[1:n + 1]); sm = sum(mdm[1:n + 1])
    dxs: list[float] = []
    for i in range(n, N):
        if i > n:
            atr = atr - atr / n + tr[i]; sp = sp - sp / n + pdm[i]; sm = sm - sm / n + mdm[i]
        p = 100 * sp / max(atr, EPS); m = 100 * sm / max(atr, EPS)
        pdi[i], mdi[i] = p, m
        dxs.append(100 * abs(p - m) / max(p + m, EPS))
        if len(dxs) == n:
            adx[i] = sum(dxs) / n
        elif len(dxs) > n:
            adx[i] = (adx[i - 1] * (n - 1) + dxs[-1]) / n
    return pdi, mdi, adx


def roc_batch(x, n: int = 10):
    """ROC = 100 (P_t / P_{t-n} - 1)."""
    return [None if i < n else 100.0 * (x[i] / x[i - n] - 1.0) for i in range(len(x))]


def momentum_batch(x, n: int = 10):
    return [None if i < n else x[i] - x[i - n] for i in range(len(x))]


def log_returns(x):
    """r_t = ln(P_t / P_{t-1}); r_0 = None."""
    return [None] + [math.log(x[i] / x[i - 1]) for i in range(1, len(x))]


def realized_vol_batch(x, n: int = 20, annualization: float = 1.0):
    """Sample std of last n log returns × sqrt(annualization)."""
    r = log_returns(x)
    out: list[float | None] = []
    for i in range(len(x)):
        if i < n:
            out.append(None); continue
        w = np.array(r[i - n + 1:i + 1], dtype=float)
        out.append(float(np.std(w, ddof=1) * math.sqrt(annualization)))
    return out


def donchian_batch(h, l, n: int = 20):
    """(upper, lower, mid) over the last n bars including t."""
    out = []
    for i in range(len(h)):
        if i < n - 1:
            out.append(None); continue
        u, d = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        out.append((u, d, (u + d) / 2))
    return out


def anchored_vwap_batch(h, l, c, v, anchor: int):
    """AVWAP from bar index ``anchor`` using typical price (H+L+C)/3. None before anchor or zero volume."""
    out: list[float | None] = [None] * len(c)
    pv = vv = 0.0
    for i in range(anchor, len(c)):
        tp = (h[i] + l[i] + c[i]) / 3.0
        pv += tp * v[i]; vv += v[i]
        out[i] = pv / vv if vv > 0 else None
    return out


def rvol_batch(v, n: int = 20):
    """RVOL_t = V_t / mean(V_{t-n..t-1}); prior bars only, so the current bar is not in the baseline."""
    return [None if i < n or sum(v[i - n:i]) <= 0 else v[i] / (sum(v[i - n:i]) / n) for i in range(len(v))]


def candle_anatomy(o, h, l, c) -> dict[str, float]:
    body = abs(c - o); rng = h - l
    uw = h - max(o, c); lw = min(o, c) - l
    return {"body": body, "range": rng, "upper_wick": uw, "lower_wick": lw,
            "body_ratio": body / max(rng, EPS), "upper_wick_to_body": uw / max(body, EPS),
            "lower_wick_to_body": lw / max(body, EPS)}


def is_doji(o, h, l, c, max_body_ratio: float = 0.1) -> bool:
    return candle_anatomy(o, h, l, c)["body_ratio"] <= max_body_ratio


def engulfing(prev: tuple, cur: tuple) -> str | None:
    """prev/cur = (o,h,l,c). Body-engulfing candidate (not a signal)."""
    po, _, _, pc = prev; co, _, _, cc = cur
    if pc < po and cc > co and co <= pc and cc >= po:
        return "bullish"
    if pc > po and cc < co and co >= pc and cc <= po:
        return "bearish"
    return None


def displacement(o, h, l, c, atr: float | None, k: float = 1.5, min_body_ratio: float = 0.6) -> bool:
    if atr is None:
        return False
    a = candle_anatomy(o, h, l, c)
    return a["range"] >= k * atr and a["body_ratio"] >= min_body_ratio


def trend_band_batch(h, l, c, n: int = 20, k: float = 1.0):
    """Transparent trend band: EMA(close,n) ± k·ATR(n). State +1 when close > upper, −1 when < lower, else
    carries previous. Not a reproduction of any proprietary indicator."""
    e, a = ema_batch(c, n), atr_batch(h, l, c, n)
    out, state = [], 0
    for i in range(len(c)):
        if e[i] is None or a[i] is None:
            out.append(None); continue
        up, dn = e[i] + k * a[i], e[i] - k * a[i]
        state = 1 if c[i] > up else (-1 if c[i] < dn else state)
        out.append((up, e[i], dn, state))
    return out


def htf_context_for_ltf(ltf_starts: Sequence[int], htf_ends: Sequence[int], htf_values: Sequence) -> list:
    """Map higher-tf values onto lower-tf bars using only HTF bars whose end <= the LTF bar end (no leakage).
    ltf_starts given with implicit equal duration => caller passes LTF bar *ends*."""
    out, j = [], -1
    for t in ltf_starts:
        while j + 1 < len(htf_ends) and htf_ends[j + 1] <= t:
            j += 1
        out.append(htf_values[j] if j >= 0 else None)
    return out


def fib_retracements(swing_low: float, swing_high: float, levels=(0.236, 0.382, 0.5, 0.618, 0.786)) -> dict[float, float]:
    rng = swing_high - swing_low
    return {f: swing_high - f * rng for f in levels}


# ---- range / level math -------------------------------------------------------------------------
def midpoint(h, l):
    return (h + l) / 2.0


def range_overlap(h1, l1, h2, l2) -> float:
    return max(0.0, min(h1, h2) - max(l1, l2))


def overlap_ratio(h1, l1, h2, l2, eps: float = EPS) -> float:
    return range_overlap(h1, l1, h2, l2) / max(eps, min(h1 - l1, h2 - l2))


def normalized_distance(price: float, level: float, atr: float | None, eps: float = EPS) -> float | None:
    return None if atr is None else (price - level) / max(atr, eps)


# ---- microstructure (data-tier gated by callers) ------------------------------------------------
def order_book_imbalance(bid_depth: float, ask_depth: float, eps: float = EPS) -> float:
    """Requires L2 (tier 'L2'). Never compute from OHLCV."""
    return (bid_depth - ask_depth) / (bid_depth + ask_depth + eps)


def trade_imbalance(buy_vol: float | None, sell_vol: float | None, total: float | None, eps: float = EPS) -> float | None:
    """Requires aggressor-flagged trades (tier 'TRADES_AGGRESSOR'); returns None if not supplied."""
    if buy_vol is None or sell_vol is None or total is None:
        return None
    return (buy_vol - sell_vol) / (total + eps)


def kyle_lambda(dp: Sequence[float], q: Sequence[float]) -> dict[str, float] | None:
    """OLS ΔP = α + λQ + ε. Research only. Returns None for <10 obs or zero-variance Q."""
    x, y = np.asarray(q, float), np.asarray(dp, float)
    if len(x) < 10 or np.var(x) <= EPS:
        return None
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = float(resid @ resid) / (len(x) - 2)
    se = math.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    return {"alpha": float(beta[0]), "lambda": float(beta[1]), "se_lambda": se, "n": len(x)}


def hawkes_intensity(t: float, events: Sequence[float], mu: float, alpha: float, beta: float) -> float:
    """λ(t) = μ + Σ_{t_i<t} α e^{-β(t-t_i)}. Research; parameters must come from a fitted model."""
    return mu + sum(alpha * math.exp(-beta * (t - ti)) for ti in events if ti < t)


def vpin(buy_vols: Sequence[float], sell_vols: Sequence[float], window: int = 50) -> float | None:
    """VPIN over equal-volume buckets: mean |V_b - V_s| / (V_b + V_s). Requires classified volume buckets."""
    if len(buy_vols) < window:
        return None
    b, s = np.asarray(buy_vols[-window:], float), np.asarray(sell_vols[-window:], float)
    return float(np.mean(np.abs(b - s) / np.maximum(b + s, EPS)))


# ---- trade / portfolio math ---------------------------------------------------------------------
def expected_value(p: float, gain: float, loss: float, cost: float) -> float:
    """EV = pG − (1−p)L − C (loss L given as a positive magnitude)."""
    return p * gain - (1 - p) * loss - cost


def breakeven_probability(gain: float, loss: float, cost: float) -> float:
    """p_BE = (L + C) / (G + L)."""
    return (loss + cost) / max(gain + loss, EPS)


def position_quantity(risk_budget: float, stop_distance: float, value_per_price_unit: float,
                      lot_step: float = 1.0, max_qty: float | None = None) -> float:
    """floor((Risk / (stop·value)) / lot) · lot, capped. Research sizing; control plane has final say."""
    if stop_distance <= 0 or value_per_price_unit <= 0 or risk_budget <= 0:
        return 0.0
    q = math.floor(risk_budget / (stop_distance * value_per_price_unit) / lot_step + 1e-9) * lot_step
    return min(q, max_qty) if max_qty is not None else q


def portfolio_mean_var(w, mu, cov) -> tuple[float, float]:
    w = np.asarray(w, float)
    return float(w @ np.asarray(mu, float)), float(w @ np.asarray(cov, float) @ w)


def historical_var_es(returns: Sequence[float], alpha: float = 0.95) -> dict[str, float] | None:
    """Historical VaR/CVaR(ES) as positive loss numbers at confidence alpha."""
    r = np.sort(np.asarray(returns, float))
    if len(r) < 20:
        return None
    k = max(1, int(math.floor((1 - alpha) * len(r))))
    var = -float(np.quantile(r, 1 - alpha))
    es = -float(np.mean(r[:k]))
    return {"var": var, "cvar": es, "es": es, "n": len(r)}


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y, eps: float = 1e-15) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_bins(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1); out = []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))
        if m.any():
            out.append({"lo": float(edges[i]), "hi": float(edges[i + 1]), "n": int(m.sum()),
                        "mean_p": float(p[m].mean()), "freq": float(y[m].mean())})
    return out


def implementation_shortfall(side: int, decision_price: float, fills: Sequence[tuple[float, float]],
                             intended_qty: float, close_price: float, fees: float = 0.0) -> dict[str, float]:
    """Perold IS. side=+1 buy/−1 sell. fills=[(qty, price)]. Unfilled qty charged opportunity cost at close."""
    filled = sum(q for q, _ in fills)
    exec_cost = side * sum(q * (px - decision_price) for q, px in fills)
    opp = side * (intended_qty - filled) * (close_price - decision_price)
    total = exec_cost + opp + fees
    return {"execution": exec_cost, "opportunity": opp, "fees": fees, "total": total,
            "bps": 1e4 * total / max(abs(intended_qty * decision_price), EPS)}
