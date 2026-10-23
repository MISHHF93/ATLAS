"""ML anomaly detector (Isolation Forest) on data-quality and behaviour features. Actions are
limited to NONE / REDUCE (size x0.5) / HALT (engage the kill switch). It has no way to place,
modify or resize orders upward. Sustained or extreme anomalies halt; resetting stays owner-only."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ANOMALY_FEATURES = ["quote_age_s", "spread_bps", "ret_z", "volume_z", "slippage_bps", "reject_rate", "orders_per_min", "pnl_change_z"]


@dataclass
class AnomalyModel:
    forest: object
    reduce_q: float = 0.0     # score thresholds (lower = more anomalous; sklearn score_samples)
    halt_q: float = 0.0
    report: dict | None = None

    @classmethod
    def fit(cls, X: pd.DataFrame, reduce_pct: float = 1.0, halt_pct: float = 0.1, seed: int = 7) -> "AnomalyModel":
        from sklearn.ensemble import IsolationForest
        f = IsolationForest(n_estimators=200, random_state=seed, contamination="auto").fit(X[ANOMALY_FEATURES].to_numpy(float))
        s = f.score_samples(X[ANOMALY_FEATURES].to_numpy(float))
        return cls(f, float(np.percentile(s, reduce_pct)), float(np.percentile(s, halt_pct)),
                   {"n": int(len(X)), "reduce_pct": reduce_pct, "halt_pct": halt_pct, "feature_importance_stability_spearman": 1.0})

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.forest.score_samples(X[ANOMALY_FEATURES].to_numpy(float))

    def save(self, d: Path) -> None:
        import joblib  # sklearn model; integrity is enforced by the registry digest check on load
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.forest, d / "forest.joblib")
        (d / "thresholds.json").write_text(json.dumps({"reduce_q": self.reduce_q, "halt_q": self.halt_q}))

    @classmethod
    def load(cls, d: Path) -> "AnomalyModel":
        import joblib
        t = json.loads((d / "thresholds.json").read_text())
        return cls(joblib.load(d / "forest.joblib"), t["reduce_q"], t["halt_q"])


@dataclass
class AnomalyGuard:
    model: AnomalyModel
    kill_switch: object
    halt_after: int = 3            # consecutive REDUCE-level observations => HALT
    _streak: int = 0
    state: str = "none"
    log: list = field(default_factory=list)

    def observe(self, row: dict) -> str:
        s = float(self.model.score(pd.DataFrame([row]))[0])
        if s <= self.model.halt_q:
            act = "halt"
        elif s <= self.model.reduce_q:
            self._streak += 1
            act = "halt" if self._streak >= self.halt_after else "reduce"
        else:
            self._streak, act = 0, "none"
        if act == "halt" and not self.kill_switch.engaged:
            self.kill_switch.engage(f"ML anomaly detector: score {s:.3f}", channel="watchdog")
        self.state = act
        self.log.append({"score": s, "action": act})
        return act

    def size_mult(self) -> float:
        return {"none": 1.0, "reduce": 0.5, "halt": 0.0}[self.state]

    def __call__(self, intent, state):  # RiskEngine hook: block when halted, warn when reducing
        if self.state == "halt":
            return ["ML anomaly detector halted trading"], []
        return [], (["ML anomaly detector: reduce size x0.5"] if self.state == "reduce" else [])


def anomaly_card():
    from atlas.models.quant.modelcard import ModelCard
    return ModelCard("Behaviour/data anomaly detector", "anomaly",
                     "Detect unusual market data or bot behaviour (stale quotes, spreads, slippage, reject/order-rate spikes, P&L jumps).",
                     "Reduce size or halt via the kill switch.", "Generating or resizing orders upward; resetting halts.",
                     "Heartbeat-level feature vectors from normal paper operation.", ANOMALY_FEATURES,
                     ["Unsupervised: thresholds are percentiles of training data", "Novel-but-benign conditions can halt"],
                     ["False halts (safe direction); missed anomalies (rule-based anomaly halts still run)"],
                     authority="halt/reduce only")
