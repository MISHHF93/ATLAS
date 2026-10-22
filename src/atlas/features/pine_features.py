"""Causal indicator columns in the shape of common Pine Script studies.

Each value at index i uses bars 0..i only. Warmup cells are None.
These columns do not submit orders.
"""

from __future__ import annotations

import math
from typing import Any


def _finite(values: list[float | None]) -> list[float | None]:
    return [None if value is None or not math.isfinite(value) else value for value in values]


def vwap_bands(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> dict[str, Any]:
    """Session VWAP with volume-weighted 1, 2, and 3 sigma bands."""
    count = len(closes)
    vwap: list[float | None] = [None] * count
    band1: list[float | None] = [None] * count
    band2: list[float | None] = [None] * count
    band3: list[float | None] = [None] * count
    sum_volume = 0.0
    sum_pv = 0.0
    sum_p2v = 0.0
    for index in range(count):
        volume = max(0.0, float(volumes[index]))
        typical = (float(highs[index]) + float(lows[index]) + float(closes[index])) / 3.0
        sum_volume += volume
        sum_pv += typical * volume
        sum_p2v += typical * typical * volume
        if sum_volume <= 0:
            continue
        center = sum_pv / sum_volume
        variance = max(0.0, sum_p2v / sum_volume - center * center)
        sigma = math.sqrt(variance)
        vwap[index] = center
        band1[index] = sigma
        band2[index] = 2.0 * sigma
        band3[index] = 3.0 * sigma
    return {
        "vwap": _finite(vwap),
        "sigma1": _finite(band1),
        "sigma2": _finite(band2),
        "sigma3": _finite(band3),
        "execution_permission": "none",
    }


def average_true_range(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> list[float | None]:
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


def volatility_squeeze(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    window: int = 20,
    atr_window: int = 14,
) -> dict[str, Any]:
    """Bollinger width inside the Keltner width is a squeeze. ATR ratio is ATR/close."""
    count = len(closes)
    atr = average_true_range(highs, lows, closes, atr_window)
    ratio: list[float | None] = [None] * count
    squeeze: list[int | None] = [None] * count
    for index in range(count):
        if atr[index] is None or index + 1 < window:
            continue
        sample = [float(closes[cursor]) for cursor in range(index + 1 - window, index + 1)]
        mean = sum(sample) / window
        variance = sum((value - mean) ** 2 for value in sample) / window
        bollinger_width = 4.0 * math.sqrt(variance)
        keltner_width = 3.0 * float(atr[index])
        close = float(closes[index])
        ratio[index] = float(atr[index]) / close if close else None
        squeeze[index] = 1 if keltner_width > 0 and bollinger_width < keltner_width else 0
    return {
        "atr": atr,
        "atr_ratio": _finite(ratio),
        "squeeze": squeeze,
        "execution_permission": "none",
    }


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
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


def _ema(values: list[float], period: int) -> list[float | None]:
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


def momentum_divergence(closes: list[float], *, rsi_period: int = 14, lookback: int = 10) -> dict[str, Any]:
    """RSI and MACD. Divergence compares this bar with a prior swing, using no future bar."""
    count = len(closes)
    rsi = _rsi(closes, rsi_period)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd: list[float | None] = [None] * count
    for index in range(count):
        if ema12[index] is None or ema26[index] is None:
            continue
        macd[index] = float(ema12[index]) - float(ema26[index])
    signal = [None] * count
    macd_values = [0.0 if value is None else value for value in macd]
    ema_signal = _ema(macd_values, 9)
    histogram: list[float | None] = [None] * count
    divergence: list[int | None] = [None] * count
    for index in range(count):
        if macd[index] is None or ema_signal[index] is None or index < 26:
            continue
        signal[index] = ema_signal[index]
        histogram[index] = float(macd[index]) - float(ema_signal[index])
        if index < lookback or rsi[index] is None or rsi[index - lookback] is None:
            divergence[index] = 0
            continue
        price_delta = float(closes[index]) - float(closes[index - lookback])
        rsi_delta = float(rsi[index]) - float(rsi[index - lookback])
        if price_delta > 0 and rsi_delta < 0:
            divergence[index] = -1
        elif price_delta < 0 and rsi_delta > 0:
            divergence[index] = 1
        else:
            divergence[index] = 0
    return {
        "rsi": rsi,
        "macd": _finite(macd),
        "macd_signal": _finite(signal),
        "macd_histogram": _finite(histogram),
        "rsi_divergence": divergence,
        "execution_permission": "none",
    }


def volume_delta(opens: list[float], closes: list[float], volumes: list[float], window: int = 20) -> dict[str, Any]:
    """Bar-sign volume delta. This is not a bid/ask print."""
    count = len(closes)
    delta = [0.0] * count
    rolling: list[float | None] = [None] * count
    for index in range(count):
        volume = max(0.0, float(volumes[index]))
        delta[index] = volume if float(closes[index]) >= float(opens[index]) else -volume
        if index + 1 >= window:
            rolling[index] = sum(delta[index + 1 - window : index + 1])
    return {
        "bar_delta": delta,
        "rolling_delta": _finite(rolling),
        "delta_basis": "close_versus_open",
        "execution_permission": "none",
    }
