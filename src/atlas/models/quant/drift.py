"""Drift monitoring with the Population Stability Index (PSI).
PSI < 0.1 stable, 0.1-0.25 moderate, > 0.25 significant => auto-demote the champion to the previous
champion (risk-reducing; promotion is never automatic)."""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-4


def reference_stats(X: pd.DataFrame, bins: int = 10) -> dict:
    out = {}
    for c in X.columns:
        v = pd.to_numeric(X[c], errors="coerce").dropna().to_numpy(float)
        if len(v) < bins:
            continue
        edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)))
        if len(edges) < 3:
            continue
        cnt = np.histogram(np.clip(v, edges[0], edges[-1]), edges)[0]
        out[c] = {"edges": edges.tolist(), "p": (cnt / cnt.sum()).tolist()}
    return out


def psi_from_ref(ref: dict, values) -> float:
    e = np.asarray(ref["edges"])
    v = np.clip(np.asarray(values, float), e[0], e[-1])
    a = np.histogram(v, e)[0]
    a = a / max(1, a.sum())
    p = np.asarray(ref["p"])
    a, p = np.clip(a, EPS, None), np.clip(p, EPS, None)
    return float(((a - p) * np.log(a / p)).sum())


def psi(expected, actual, bins: int = 10) -> float:
    ref = reference_stats(pd.DataFrame({"x": expected}), bins)["x"]
    return psi_from_ref(ref, actual)


class DriftMonitor:
    def __init__(self, registry, threshold: float = 0.25, warn: float = 0.1, min_rows: int = 50):
        self.reg, self.threshold, self.warn, self.min_rows = registry, threshold, warn, min_rows

    def check(self, X: pd.DataFrame) -> dict:
        mid = self.reg.champion
        if mid is None:
            return {"model_id": None, "status": "no_champion"}
        ref = self.reg.reference(mid)
        if not ref or len(X) < self.min_rows:
            return {"model_id": mid, "status": "insufficient_data"}
        scores = {c: round(psi_from_ref(r, X[c].dropna()), 4) for c, r in ref.items() if c in X}
        worst = max(scores.values(), default=0.0)
        status = "drift" if worst > self.threshold else ("watch" if worst > self.warn else "stable")
        res = {"model_id": mid, "status": status, "max_psi": worst, "psi": scores}
        self.reg._log("drift_check", {"model_id": mid, "status": status, "max_psi": worst}, "drift_monitor")
        if status == "drift":
            res["restored"] = self.reg.demote("drift_monitor", f"PSI {worst:.3f} > {self.threshold}")
        self.reg._save()
        return res
