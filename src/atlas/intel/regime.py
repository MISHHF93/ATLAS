"""Causal bar-level regime classifier + strategy-by-regime performance.

Label at bar i uses only bars <= i (incremental EMA/ATR from features.price_action.indicators):
  trend: EMA(20) vs EMA(50) spread in ATR units -> trend_up (> +0.5), trend_down (< -0.5), else range
  vol:   ATR(14) percentile within the trailing 200 ATR values -> low (< 33%), normal, high (> 67%)
Bars before warm-up are "warmup". Rule-based and deterministic (no fitting), so no look-ahead by construction.
The daily HMM in models.quant.regime remains the risk-multiplier source; this classifier is descriptive only.
"""
from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque
from typing import Any

import numpy as np

from atlas.features.price_action.indicators import EMA, WilderATR

WARMUP = 60


def classify(bars, fast: int = 20, slow: int = 50, atr_n: int = 14, lookback: int = 200) -> list[dict[str, Any]]:
    ef, es, atr = EMA(fast), EMA(slow), WilderATR(atr_n)
    win: deque[float] = deque()
    srt: list[float] = []
    out = []
    for i, b in enumerate(bars):
        f, s, a = ef.update(b.close), es.update(b.close), atr.update(b.high, b.low, b.close)
        if a is not None:
            win.append(a); insort(srt, a)
            if len(win) > lookback:
                old = win.popleft(); del srt[bisect_left(srt, old)]
        if i < WARMUP or f is None or s is None or not a:
            out.append({"t": b.start, "trend": "warmup", "vol": "warmup", "label": "warmup"})
            continue
        z = (f - s) / a
        trend = "trend_up" if z > 0.5 else "trend_down" if z < -0.5 else "range"
        pct = bisect_left(srt, a) / max(1, len(srt) - 1)
        vol = "low" if pct < 1 / 3 else "high" if pct > 2 / 3 else "normal"
        out.append({"t": b.start, "trend": trend, "vol": vol, "label": f"{trend}/{vol}", "trend_z": round(z, 3), "atr_pct": round(pct, 3)})
    return out


def label_at(labels: list[dict[str, Any]], ts: int) -> str:
    """Regime of the last bar that STARTED at or before ts (causal lookup)."""
    keys = [x["t"] for x in labels]
    i = bisect_left(keys, ts + 1) - 1
    return labels[i]["label"] if i >= 0 else "warmup"


def strategy_by_regime(trades, labels, min_n: int = 10) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[float]] = {}
    for t in trades:
        if t.r_multiple is None or t.outcome not in ("target", "stop", "timeout"):
            continue
        groups.setdefault((t.detector, label_at(labels, t.detected_at)), []).append(float(t.r_multiple))
    rows = []
    for (det, reg), r in sorted(groups.items()):
        a = np.array(r)
        rows.append({"detector": det, "regime": reg, "n": len(a), "mean_r": float(a.mean()), "win_rate": float((a > 0).mean()),
                     "total_r": float(a.sum()), "sufficient_n": len(a) >= min_n})
    return rows


def distribution(labels) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in labels:
        out[x["label"]] = out.get(x["label"], 0) + 1
    return out
