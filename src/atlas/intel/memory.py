"""Market memory + outcome attribution over resolved replay trades, and a read-only view of model governance.

Memory: each resolved trade is stored as (candidate_id, detector, direction, regime, numeric features, outcome, R).
``analogues`` returns the k nearest past records by standardized Euclidean distance on shared numeric features,
using ONLY records that resolved before the query time (no look-ahead). Attribution decomposes total R by detector,
regime, direction and UTC hour; each breakdown sums to the same total. Governance wraps models.quant.registry
(candidate -> challenger -> champion, gated promotion, one-call rollback); this module never promotes."""
from __future__ import annotations

from typing import Any

import numpy as np

from .regime import label_at

RESOLVED = ("target", "stop", "timeout")


def build_memory(trades, labels) -> list[dict[str, Any]]:
    out = []
    for t in trades:
        if t.r_multiple is None or t.outcome not in RESOLVED:
            continue
        num = {k: float(v) for k, v in (t.features or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v)}
        out.append({"candidate_id": t.candidate_id, "detector": t.detector, "direction": t.direction, "detected_at": t.detected_at,
                    "resolved_at": t.exit_at, "regime": label_at(labels, t.detected_at), "features": num,
                    "outcome": t.outcome, "r": float(t.r_multiple)})
    return out


def analogues(memory, query_features: dict[str, float], as_of: int, k: int = 5, detector: str | None = None) -> dict[str, Any]:
    past = [m for m in memory if m["resolved_at"] is not None and m["resolved_at"] <= as_of and (detector is None or m["detector"] == detector)]
    keys = sorted(set(query_features) & set().union(*[set(m["features"]) for m in past])) if past else []
    past = [m for m in past if all(x in m["features"] for x in keys)]
    if not keys or len(past) < k:
        return {"status": "insufficient_history", "n_eligible": len(past), "features": keys, "analogues": []}
    X = np.array([[m["features"][x] for x in keys] for m in past])
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    q = (np.array([query_features[x] for x in keys]) - mu) / sd
    d = np.sqrt((((X - mu) / sd - q) ** 2).sum(1))
    idx = np.argsort(d, kind="stable")[:k]
    rows = [{**{x: past[i][x] for x in ("candidate_id", "detector", "regime", "outcome", "r")}, "distance": round(float(d[i]), 4)} for i in idx]
    rs = np.array([r["r"] for r in rows])
    return {"status": "ok", "n_eligible": len(past), "features": keys, "analogues": rows,
            "analogue_mean_r": float(rs.mean()), "analogue_win_rate": float((rs > 0).mean()), "k": k,
            "note": "nearest-neighbour description of past outcomes; not a probability or forecast"}


def attribution(memory) -> dict[str, Any]:
    total = float(sum(m["r"] for m in memory))

    def by(key):
        g: dict[str, list[float]] = {}
        for m in memory:
            g.setdefault(str(key(m)), []).append(m["r"])
        return [{"bucket": b, "n": len(v), "total_r": round(float(sum(v)), 4), "mean_r": round(float(np.mean(v)), 4),
                 "share_of_total": None if total == 0 else round(float(sum(v)) / total, 4)} for b, v in sorted(g.items())]
    return {"n": len(memory), "total_r": round(total, 4), "by_detector": by(lambda m: m["detector"]), "by_regime": by(lambda m: m["regime"]),
            "by_direction": by(lambda m: m["direction"]), "by_hour_utc": by(lambda m: f"{(m['detected_at'] // 3600) % 24:02d}"),
            "by_outcome": by(lambda m: m["outcome"])}


def governance(root: str | None = None) -> dict[str, Any]:
    import os
    root = root or os.environ.get("ATLAS_MODELS_DIR", "var/models")
    from pathlib import Path
    from atlas.models.quant.registry import ModelRegistry
    if not Path(root).exists():
        return {"status": "no_registry", "root": root, "note": "no quant model registry on disk yet (weekly_retrain has not run)",
                "flow": "candidate -> challenger (shadow) -> champion; promote() is gated + owner step-up; rollback() is one call"}
    reg = ModelRegistry(root)
    return {"status": "ok", "root": root, "summary": reg.summary(), "champion": reg.champion, "challenger": reg.challenger,
            "flow": "candidate -> challenger (shadow) -> champion; promote() is gated + owner step-up; rollback() is one call",
            "promotion_via_api": False}
