"""Canonical causal indicators for the price-action engine.

Each indicator has a streaming class (one value per completed bar) and an independent batch
function. Parity between the two is tested. Conventions (documented in docs/spec/price-action.md):

* EMA: alpha = 2/(n+1); seeded with the SMA of the first n values; None before that.
* RSI: Wilder smoothing. First averages = simple mean of the first n changes, then
  avg = (avg_prev*(n-1) + x)/n. Zero cases: loss==0 & gain>0 -> 100; gain==0 & loss>0 -> 0;
  both 0 -> 50 (flat series, no directional information).
* ATR: Wilder. TR[0] = H-L (no previous close); ATR = mean of first n TR, then Wilder.
* Bollinger: SMA_n +/- k * population std (ddof=0, same convention as TradingView ta.stdev).
* VWAP (bar approximation): sum(typical*vol)/sum(vol), typical=(H+L+C)/3, reset per session key.
  It is NOT trade-level VWAP.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Sequence

import numpy as np


class EMA:
    def __init__(self, n: int):
        self.n, self.alpha, self._seed, self.value = n, 2.0 / (n + 1), [], None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.n:
                self.value = sum(self._seed) / self.n
            return self.value
        self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value


def _rsi_from(g: float, l: float, flat: float = 50.0) -> float:
    if l == 0.0:
        return flat if g == 0.0 else 100.0
    if g == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + g / l)


class WilderRSI:
    def __init__(self, n: int = 14):
        self.n, self.prev, self.g, self.l, self._buf, self.value = n, None, None, None, [], None

    def update(self, x: float) -> float | None:
        if self.prev is None:
            self.prev = x
            return None
        ch, self.prev = x - self.prev, x
        gain, loss = max(ch, 0.0), max(-ch, 0.0)
        if self.g is None:
            self._buf.append((gain, loss))
            if len(self._buf) == self.n:
                self.g = sum(a for a, _ in self._buf) / self.n
                self.l = sum(b for _, b in self._buf) / self.n
                self.value = _rsi_from(self.g, self.l)
            return self.value
        self.g = (self.g * (self.n - 1) + gain) / self.n
        self.l = (self.l * (self.n - 1) + loss) / self.n
        self.value = _rsi_from(self.g, self.l)
        return self.value


class WilderATR:
    def __init__(self, n: int = 14):
        self.n, self.prev_close, self._buf, self.value = n, None, [], None

    def update(self, high: float, low: float, close: float) -> float | None:
        tr = high - low if self.prev_close is None else max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        if self.value is None:
            self._buf.append(tr)
            if len(self._buf) == self.n:
                self.value = sum(self._buf) / self.n
            return self.value
        self.value = (self.value * (self.n - 1) + tr) / self.n
        return self.value


class Bollinger:
    def __init__(self, n: int, k: float):
        self.n, self.k, self.win = n, k, deque(maxlen=n)
        self.value: tuple[float, float, float] | None = None

    def update(self, x: float) -> tuple[float, float, float] | None:
        self.win.append(x)
        if len(self.win) < self.n:
            return None
        m = sum(self.win) / self.n
        sd = math.sqrt(sum((v - m) ** 2 for v in self.win) / self.n)
        self.value = (m - self.k * sd, m, m + self.k * sd)
        return self.value


class BarVWAP:
    """Bar-approximated VWAP (typical price), reset when session_key changes. Label: approximation."""
    label = "bar_approx_typical_price"

    def __init__(self):
        self.key, self.pv, self.v, self.value = None, 0.0, 0.0, None

    def update(self, high: float, low: float, close: float, volume: float, session_key: object = None) -> float | None:
        if session_key != self.key:
            self.key, self.pv, self.v = session_key, 0.0, 0.0
        self.pv += (high + low + close) / 3.0 * volume
        self.v += volume
        self.value = self.pv / self.v if self.v > 0 else None
        return self.value


# ---- independent batch implementations (numpy) ----

def ema_batch(x: Sequence[float], n: int) -> list[float | None]:
    a = np.asarray(x, float)
    out: list[float | None] = [None] * len(a)
    if len(a) < n:
        return out
    alpha, v = 2.0 / (n + 1), float(a[:n].mean())
    out[n - 1] = v
    for i in range(n, len(a)):
        v = alpha * a[i] + (1 - alpha) * v
        out[i] = v
    return out


def rsi_batch(x: Sequence[float], n: int = 14, *, flat_value: float = 50.0) -> list[float | None]:
    """Wilder RSI. ``flat_value`` is returned when avg gain == avg loss == 0 (canonical 50; legacy shims pass 100)."""
    a = np.asarray(x, float)
    out: list[float | None] = [None] * len(a)
    if len(a) <= n:
        return out
    d = np.diff(a)
    gains, losses = np.clip(d, 0, None), np.clip(-d, 0, None)
    g, l = float(gains[:n].mean()), float(losses[:n].mean())
    out[n] = _rsi_from(g, l, flat_value)
    for i in range(n, len(d)):
        g = (g * (n - 1) + gains[i]) / n
        l = (l * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi_from(g, l, flat_value)
    return out


def true_range_batch(h, l, c) -> np.ndarray:
    h, l, c = (np.asarray(v, float) for v in (h, l, c))
    tr = h - l
    if len(c) > 1:
        pc = c[:-1]
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - pc), np.abs(l[1:] - pc)])
    return tr


def atr_batch(h, l, c, n: int = 14) -> list[float | None]:
    tr = true_range_batch(h, l, c)
    out: list[float | None] = [None] * len(tr)
    if len(tr) < n:
        return out
    v = float(tr[:n].mean())
    out[n - 1] = v
    for i in range(n, len(tr)):
        v = (v * (n - 1) + tr[i]) / n
        out[i] = v
    return out


def atr_rolling_mean_batch(h, l, c, n: int = 14) -> list[float | None]:
    """Rolling *simple-mean* ATR (a documented variant distinct from Wilder): mean of the last n TRs, TR0 = H-L."""
    tr = true_range_batch(h, l, c)
    out: list[float | None] = [None] * len(tr)
    for i in range(n - 1, len(tr)):
        out[i] = float(tr[i + 1 - n:i + 1].mean())
    return out


def bollinger_batch(x: Sequence[float], n: int, k: float) -> list[tuple[float, float, float] | None]:
    a = np.asarray(x, float)
    out: list[tuple[float, float, float] | None] = [None] * len(a)
    if len(a) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(a, n)
    m, sd = w.mean(axis=1), w.std(axis=1, ddof=0)
    for j in range(len(m)):
        out[j + n - 1] = (float(m[j] - k * sd[j]), float(m[j]), float(m[j] + k * sd[j]))
    return out


def vwap_batch(h, l, c, v, session_keys) -> list[float | None]:
    out: list[float | None] = []
    key, pv, vol = object(), 0.0, 0.0
    for hi, lo, cl, vv, sk in zip(h, l, c, v, session_keys):
        if sk != key:
            key, pv, vol = sk, 0.0, 0.0
        pv += (hi + lo + cl) / 3.0 * vv
        vol += vv
        out.append(pv / vol if vol > 0 else None)
    return out
