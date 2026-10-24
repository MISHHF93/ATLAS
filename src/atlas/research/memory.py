"""Market Memory Retrieval and Analogous Case-Based Reasoning (CBR) for ATLAS.

This system allows the ML brain to move beyond simple parametric predictions
by retrieving the most similar historical setups from the OpportunityLedger.

By analyzing the outcomes of 'analogue' cases, ATLAS can adjust its probability
forecasts based on empirical evidence from the past.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from dataclasses import dataclass

from atlas.research.ledger import OpportunityLedger
from atlas.models.schemas import Record, Text


@dataclass(frozen=True)
class MarketAnalogue(Record):
    """A historical analogue to the current market state."""
    setup_id: Text
    symbol: Text
    timestamp: datetime
    similarity_score: float # Cosine similarity [0, 1]
    outcome: str # 'win', 'loss', 'expired'
    pnl_bps: float
    features: dict[str, Any]
    execution_permission: Literal["none"] = "none"


class MarketMemoryEngine:
    """
    Implements non-parametric memory retrieval using k-Nearest Neighbors (k-NN).
    
    It transforms the current structural state into a vector and searches the 
    OpportunityLedger for the most similar historical occurrences.
    """

    def __init__(self, ledger: OpportunityLedger):
        self.ledger = ledger
        # The 'Structural Fingerprint' - features used for similarity matching
        self.fingerprint_features = [
            "zone_overlap_count", 
            "vpin", 
            "ofi", 
            "kyles_lambda", 
            "regime",
            "rvol",
            "vol_compression"
        ]

    def find_analogues(
        self, 
        current_features: pd.DataFrame, 
        k: int = 5
    ) -> List[MarketAnalogue]:
        """
        Retrieves the k most similar historical setups.
        """
        # 1. Fetch historical closed setups from the ledger
        historical_df = self.ledger.get_training_set()
        if historical_df.empty:
            return []

        # 2. Align feature space
        # Use intersection of defined fingerprint and available ledger columns
        available_features = [f for f in self.fingerprint_features if f in historical_df.columns]
        if not available_features:
            return []

        # 3. Vectorization and Z-Score Normalization
        # Normalize to prevent high-magnitude features (like volume) from dominating
        hist_vecs = historical_df[available_features].values.astype(float)
        mean = np.mean(hist_vecs, axis=0)
        std = np.std(hist_vecs, axis=0) + 1e-9
        norm_hist_vecs = (hist_vecs - mean) / std

        # Current state vector
        curr_vec = current_features[available_features].values[0].astype(float)
        norm_curr_vec = (curr_vec - mean) / std

        # 4. Cosine Similarity Calculation
        # similarity = (A . B) / (||A|| * ||B||)
        dot_product = np.dot(norm_hist_vecs, norm_curr_vec)
        norm_hist = np.linalg.norm(norm_hist_vecs, axis=1)
        norm_curr = np.linalg.norm(norm_curr_vec)
        
        similarities = dot_product / (norm_hist * norm_curr + 1e-9)
        
        # 5. Retrieve top-k indices
        top_indices = np.argsort(similarities)[::-1][:k]
        
        analogues = []
        for idx in top_indices:
            row = historical_df.iloc[idx]
            analogues.append(MarketAnalogue(
                setup_id=row['setup_id'],
                symbol=row['symbol'],
                timestamp=row['detected_at'],
                similarity_score=float(similarities[idx]),
                outcome=row['outcome'],
                pnl_bps=float(row['pnl_bps']),
                features=row.to_dict()
            ))
            
        return analogues

    def get_consensus_probability(self, analogues: List[MarketAnalogue]) -> float:
        """
        Derives a probability of success from the analogue set.
        
        Returns: Weighted probability based on similarity scores.
        """
        if not analogues:
            return 0.5
            
        # Weight wins by their similarity score to the current case
        weighted_wins = sum(a.similarity_score for a in analogues if a.outcome == "win")
        total_weight = sum(a.similarity_score for a in analogues)
        
        return weighted_wins / (total_weight + 1e-9)


# ---------------------------------------------------------------------------------------------------------------
# Replay-trade memory, outcome attribution and read-only governance (merged from the former atlas.intel.memory).
# Memory: each resolved trade -> (candidate_id, detector, direction, regime, numeric features, outcome, R).
# ``analogues`` returns the k nearest past records by standardized Euclidean distance on shared numeric features,
# using ONLY records resolved before the query time (no look-ahead). Attribution decomposes total R by detector,
# regime, direction and UTC hour; each breakdown sums to the same total. Governance wraps models.quant.registry;
# this module never promotes.
# ---------------------------------------------------------------------------------------------------------------
RESOLVED = ("target", "stop", "timeout")


def _label_at(labels, ts):
    from atlas.intel.regime import label_at
    return label_at(labels, ts)



def build_memory(trades, labels) -> list[dict[str, Any]]:
    out = []
    for t in trades:
        if t.r_multiple is None or t.outcome not in RESOLVED:
            continue
        num = {k: float(v) for k, v in (t.features or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v)}
        out.append({"candidate_id": t.candidate_id, "detector": t.detector, "direction": t.direction, "detected_at": t.detected_at,
                    "resolved_at": t.exit_at, "regime": _label_at(labels, t.detected_at), "features": num,
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
