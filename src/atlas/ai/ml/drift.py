"""Drift detection: PSI per feature vs the training reference, and ADWIN on the live error stream.

PSI (Siddiqi 2006 convention): < 0.1 stable, 0.1-0.25 moderate, > 0.25 significant.
ADWIN (Bifet & Gavaldà 2007, "Learning from time-changing data with adaptive windowing", SDM): keep a window W;
signal change when some split W = W0·W1 has |mean0 - mean1| >= eps_cut, with
eps_cut = sqrt( (1/(2m)) · ln(4|W|/delta) ),  m = 1/(1/n0 + 1/n1)  (Hoeffding bound for values in [0,1]).
This is the exact (O(|W|) per step) variant, fine for the few thousand resolved trades we see.
Drift is advisory + risk-reducing only: it can mark a model ``drifted`` (blocking eligibility), never promote.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from atlas.ai.models.quant.drift import psi_from_ref, reference_stats

PSI_MODERATE, PSI_SIGNIFICANT = 0.1, 0.25


def reference(df: pd.DataFrame, features: Iterable[str], bins: int = 10) -> dict:
    return reference_stats(df[[f for f in features if f in df.columns]], bins)


def feature_psi(ref: dict, cur: pd.DataFrame, min_n: int = 50) -> dict[str, Any]:
    rows = []
    for f, r in ref.items():
        if f not in cur.columns:
            continue
        v = pd.to_numeric(cur[f], errors="coerce").dropna().to_numpy(float)
        if len(v) < min_n:
            continue
        p = psi_from_ref(r, v)
        rows.append({"feature": f, "psi": round(p, 4),
                     "level": "significant" if p > PSI_SIGNIFICANT else "moderate" if p > PSI_MODERATE else "stable"})
    rows.sort(key=lambda x: -x["psi"])
    worst = rows[0]["psi"] if rows else None
    return {"n_current": int(len(cur)), "features": rows, "max_psi": worst,
            "n_significant": sum(r["level"] == "significant" for r in rows),
            "status": "insufficient_data" if not rows else
            ("significant" if any(r["level"] == "significant" for r in rows) else
             "moderate" if any(r["level"] == "moderate" for r in rows) else "stable")}


class ADWIN:
    def __init__(self, delta: float = 0.002, max_window: int = 5000, min_sub: int = 10):
        self.delta, self.max_window, self.min_sub = delta, max_window, min_sub
        self.window: list[float] = []
        self.detections: list[int] = []
        self.t = 0

    def update(self, x: float) -> bool:
        self.t += 1
        self.window.append(float(min(1.0, max(0.0, x))))
        if len(self.window) > self.max_window:
            self.window.pop(0)
        changed = False
        while self._cut():
            changed = True
        if changed:
            self.detections.append(self.t)
        return changed

    def _cut(self) -> bool:
        w = np.asarray(self.window)
        n = len(w)
        if n < 2 * self.min_sub:
            return False
        cs = np.cumsum(w)
        tot = cs[-1]
        for i in range(self.min_sub, n - self.min_sub + 1):
            n0, n1 = i, n - i
            m0, m1 = cs[i - 1] / n0, (tot - cs[i - 1]) / n1
            m = 1.0 / (1.0 / n0 + 1.0 / n1)
            eps = math.sqrt(math.log(4.0 * n / self.delta) / (2.0 * m))
            if abs(m0 - m1) >= eps:
                del self.window[:i]
                return True
        return False

    @property
    def mean(self) -> float | None:
        return float(np.mean(self.window)) if self.window else None


def adwin_report(errors: Iterable[float], delta: float = 0.002) -> dict[str, Any]:
    a = ADWIN(delta)
    for e in errors:
        a.update(e)
    return {"n": a.t, "detections": a.detections, "drift": bool(a.detections), "window": len(a.window),
            "current_mean": a.mean, "delta": delta}
