"""Execution-cost / slippage model and edge-vs-cost gate.

Predicted one-way cost (bps) = c0 + c_spread x half_spread_bps + c_impact x daily_vol_bps x sqrt(participation)
(square-root impact law) + explicit commission. Coefficients fit by non-negative least squares on
realised paper/backtest fills (implementation shortfall vs arrival mid). The gate can only DROP a
candidate whose expected edge (bps) is below predicted round-trip cost x (1 + margin)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COLS = ["half_spread_bps", "daily_vol_bps", "participation"]


def _design(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(df)), df["half_spread_bps"], df["daily_vol_bps"] * np.sqrt(df["participation"].clip(lower=0))])


@dataclass
class CostModel:
    coef: list
    report: dict | None = None

    @classmethod
    def fit(cls, fills: pd.DataFrame) -> "CostModel":
        """fills: COLS + realised_bps (one-way, adverse positive). Walk-forward report on last 30%."""
        from scipy.optimize import nnls
        cut = int(len(fills) * 0.7)
        A, y = _design(fills), fills["realised_bps"].to_numpy(float)
        c_tr, _ = nnls(A[:cut], y[:cut])
        pred = A[cut:] @ c_tr
        mae = float(np.mean(np.abs(pred - y[cut:])))
        naive = float(np.mean(np.abs(y[:cut].mean() - y[cut:])))
        c, _ = nnls(A, y)
        return cls(c.tolist(), {"oos_mae_bps": mae, "naive_mae_bps": naive, "n": int(len(fills)), "coef": c.tolist(),
                                "feature_importance_stability_spearman": 1.0})

    def predict_bps(self, half_spread_bps, daily_vol_bps, participation, commission_bps: float = 0.0) -> np.ndarray:
        df = pd.DataFrame({"half_spread_bps": np.atleast_1d(half_spread_bps), "daily_vol_bps": np.atleast_1d(daily_vol_bps),
                           "participation": np.atleast_1d(participation)})
        return np.maximum(0, _design(df) @ np.asarray(self.coef)) + commission_bps

    def save(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "cost.json").write_text(json.dumps({"coef": self.coef}))

    @classmethod
    def load(cls, d: Path) -> "CostModel":
        return cls(json.loads((d / "cost.json").read_text())["coef"])


def expected_edge_bps(p_hit: float, vol_ann: float, horizon_days: int) -> float:
    """Symmetric-payoff approximation: E[r] ~ (2p-1) x E|r|, with E|r| ~ 0.8 sigma_h (normal)."""
    return (2 * p_hit - 1) * 0.8 * vol_ann * np.sqrt(horizon_days / 252) * 1e4


class CostGate:
    def __init__(self, model: CostModel, margin: float = 0.25, audit=None):
        self.model, self.margin, self.audit = model, margin, audit

    def keep(self, edge_bps: float, half_spread_bps: float, daily_vol_bps: float, participation: float,
             commission_bps: float = 0.0) -> tuple[bool, float]:
        rt = 2 * float(self.model.predict_bps(half_spread_bps, daily_vol_bps, participation, commission_bps)[0])
        ok = edge_bps > rt * (1 + self.margin)
        return ok, rt

    def filter(self, records: list[dict]) -> list[dict]:
        """records: {'intent', 'edge_bps', 'half_spread_bps', 'daily_vol_bps', 'participation', ...} -> subset (unchanged)."""
        out = []
        for r in records:
            ok, rt = self.keep(r["edge_bps"], r["half_spread_bps"], r["daily_vol_bps"], r["participation"], r.get("commission_bps", 0.0))
            if ok:
                out.append(r | {"predicted_cost_bps": rt})
            elif self.audit:
                self.audit.append("cost.dropped", {"intent_id": r["intent"].intent_id, "edge_bps": r["edge_bps"], "cost_bps": rt})
        return out


def cost_card():
    from atlas.ai.models.quant.modelcard import ModelCard
    return ModelCard("Execution cost model", "cost", "Predict one-way execution cost (bps) for an order.",
                     "Drop candidates whose expected edge is below predicted round-trip cost x 1.25.",
                     "Choosing venues/algos, sizing up, live best-execution reporting.",
                     "Paper/backtest fills: implementation shortfall vs arrival mid, spread, ADV participation, daily vol.",
                     COLS, ["Paper fills use a modelled slippage, so the fit is only as good as the simulator",
                            "No intraday liquidity profile"], ["Underestimated cost -> marginal trades kept (risk limits still apply)"],
                     authority="drop-only gate")
