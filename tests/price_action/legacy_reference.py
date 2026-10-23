"""Verbatim copies of the pre-consolidation indicator implementations (frozen reference for shim-equivalence tests)."""

from __future__ import annotations

import math
from typing import Sequence



def _finite(values):
    return [None if value is None or not math.isfinite(value) else value for value in values]



def pine_average_true_range(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> list[float | None]:
    count = len(closes)
    spans: list[float] = []
    out: list[float | None] = [None] * count
    for index in range(count):
        if index == 0:
            spans.append(float(highs[index]) - float(lows[index]))
        else:
            spans.append(
                max(
                    float(highs[index]) - float(lows[index]),
                    abs(float(highs[index]) - float(closes[index - 1])),
                    abs(float(lows[index]) - float(closes[index - 1])),
                )
            )
        if index + 1 >= window:
            out[index] = sum(spans[index + 1 - window : index + 1]) / window
    return _finite(out)


def pine_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    count = len(closes)
    out: list[float | None] = [None] * count
    if count <= period:
        return out
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = float(closes[index]) - float(closes[index - 1])
        gains += max(0.0, change)
        losses += max(0.0, -change)
    average_gain = gains / period
    average_loss = losses / period
    out[period] = 100.0 if average_loss == 0 else 100.0 - 100.0 / (1.0 + average_gain / average_loss)
    for index in range(period + 1, count):
        change = float(closes[index]) - float(closes[index - 1])
        average_gain = (average_gain * (period - 1) + max(0.0, change)) / period
        average_loss = (average_loss * (period - 1) + max(0.0, -change)) / period
        out[index] = 100.0 if average_loss == 0 else 100.0 - 100.0 / (1.0 + average_gain / average_loss)
    return _finite(out)


def pine_ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(values)):
        previous = values[index] * alpha + previous * (1.0 - alpha)
        out[index] = previous
    return out


def research_ema(xs: list[float], n: int) -> list[float | None]:
    k, out, e = 2 / (n + 1), [], None
    for i, x in enumerate(xs):
        if i == n - 1:
            e = sum(xs[:n]) / n
        elif i >= n:
            e = x * k + e * (1 - k)
        out.append(e)
    return out


def research_rsi(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = [max(xs[i] - xs[i - 1], 0.0) for i in range(1, len(xs))]
    losses = [max(xs[i - 1] - xs[i], 0.0) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(xs)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def research_atr(bars, n: int) -> list[float | None]:
    trs = [b.high - b.low if i == 0 else max(b.high - b.low, abs(b.high - bars[i - 1].close), abs(b.low - bars[i - 1].close))
           for i, b in enumerate(bars)]
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(bars)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def micro_compute_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    window: int = 14,
) -> float:
    """Canonical Rolling Average True Range (ATR) over a fixed bar ``window``.

    True Range is Wilder's definition — the greatest of:
    - $high_t - low_t$ (intra-bar range)
    - $|high_t - close_{t-1}|$ (upward gap against prior close)
    - $|low_t - close_{t-1}|$ (downward gap against prior close)

    ATR$(t)$ = mean of the latest ``window`` True Range values. Requires at least
    ``window + 1`` bars so each TR is computed against a realized prior close
    (zero lookahead: the prior close must already exist at time ``t``).
    """
    n = min(len(highs), len(lows), len(closes))
    if n != len(highs) or n != len(lows) or n != len(closes):
        raise ValueError("highs, lows, and closes must have identical lengths")
    if len(closes) < max(2, window + 1):
        raise ValueError(
            f"compute_atr requires at least {max(2, window + 1)} bars to compute a "
            f"{window}-bar true-range average against realized prior closes"
        )
    tr_values: list[float] = []
    for i in range(1, n):
        h_i = float(highs[i])
        l_i = float(lows[i])
        pc = float(closes[i - 1])
        tr_values.append(max(h_i - l_i, abs(h_i - pc), abs(l_i - pc)))
    return sum(tr_values[-window:]) / window


def udf_atr(rows: list[tuple[int, float, float, float, float, float]], index: int) -> float:
    start = max(1, index - 13)
    spans = []
    for cursor in range(start, index + 1):
        _t, _o, high, low, close, _v = rows[cursor]
        prev_close = rows[cursor - 1][4]
        spans.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(spans) / len(spans) if spans else 0.0
