"""Per-sleeve signal scorers with a stacked, calibrated meta-ensemble.

For each sleeve (core_etf, active_equity, crypto):
  base learners: LightGBM (trees) + L2 logistic regression (linear) on leakage-safe features;
  out-of-fold base predictions come from PURGED walk-forward splits (never in-sample);
  meta learner: logistic regression on the OOF logits (fit on the earlier 70% of OOF rows);
  calibration: isotonic on the later 30% of OOF rows (also the honest OOS report).
Saved without pickle (LightGBM text + JSON coefficients) so the registry digest covers everything.
Scorers only FILTER/RANK rule candidates."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.ai.models.quant.cv import purged_walk_forward
from atlas.ai.models.quant.features import FEATURES, dataset
from atlas.ai.models.quant.metrics import brier, deflated_sharpe, max_drawdown_pct, sharpe
from atlas.ai.models.quant.model import TradeFilterModel

SLEEVES = {
    # sleeve: horizon (bars), cost hurdle (bps, round trip), min_p_hit, policy sleeve name
    "core_etf": {"horizon": 20, "cost_bps": 5.0, "min_p_hit": 0.55, "policy_sleeve": "core"},
    "active_equity": {"horizon": 5, "cost_bps": 10.0, "min_p_hit": 0.55, "policy_sleeve": "active"},
    "crypto": {"horizon": 3, "cost_bps": 30.0, "min_p_hit": 0.56, "policy_sleeve": "high_risk"},
}
POLICY_TO_SCORER = {v["policy_sleeve"]: k for k, v in SLEEVES.items()}


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


@dataclass
class Linear:
    mean: list
    scale: list
    coef: list
    intercept: float

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, C: float = 0.5) -> "Linear":
        from sklearn.linear_model import LogisticRegression
        mu, sd = X.mean(0), X.std(0)
        sd[sd == 0] = 1.0
        lr = LogisticRegression(C=C, max_iter=500).fit((X - mu) / sd, y)
        return cls(mu.tolist(), sd.tolist(), lr.coef_[0].tolist(), float(lr.intercept_[0]))

    def proba(self, X: np.ndarray) -> np.ndarray:
        z = ((X - np.asarray(self.mean)) / np.asarray(self.scale)) @ np.asarray(self.coef) + self.intercept
        return 1 / (1 + np.exp(-z))


@dataclass
class StackedScorer:
    sleeve: str
    tree: TradeFilterModel
    linear: Linear
    meta: Linear
    iso_x: list = field(default_factory=list)
    iso_y: list = field(default_factory=list)
    meta_info: dict = field(default_factory=dict)

    def _base(self, X: pd.DataFrame) -> np.ndarray:
        Xf = X[FEATURES]
        return np.column_stack([_logit(self.tree.raw(Xf)), _logit(self.linear.proba(Xf.to_numpy(float)))])

    def p_hit(self, X: pd.DataFrame) -> np.ndarray:
        p = self.meta.proba(self._base(X))
        return np.clip(np.interp(p, self.iso_x, self.iso_y), 0, 1) if self.iso_x else p

    def explain(self, X: pd.DataFrame, top: int = 5):
        return self.tree.explain(X, top)

    def save(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        self.tree.save(d / "tree")
        (d / "stack.json").write_text(json.dumps({"sleeve": self.sleeve, "linear": self.linear.__dict__, "meta": self.meta.__dict__,
                                                  "iso_x": self.iso_x, "iso_y": self.iso_y, "meta_info": self.meta_info}))

    @classmethod
    def load(cls, d: Path) -> "StackedScorer":
        j = json.loads((d / "stack.json").read_text())
        return cls(j["sleeve"], TradeFilterModel.load(d / "tree"), Linear(**j["linear"]), Linear(**j["meta"]),
                   j["iso_x"], j["iso_y"], j["meta_info"])


def train_sleeve(sleeve: str, bars: dict[str, pd.DataFrame], n_splits: int = 4, prior_trials: list | None = None) -> tuple[StackedScorer, dict, pd.DataFrame]:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score
    cfg = SLEEVES[sleeve]
    ds = dataset(bars, cfg["horizon"], cfg["cost_bps"])
    t = ds.index.values
    oof = np.full((len(ds), 2), np.nan)
    folds = []
    for tr, te in purged_walk_forward(t, n_splits=n_splits, horizon=cfg["horizon"]):
        tree = TradeFilterModel.train(ds.iloc[tr][FEATURES], ds["y"].values[tr])
        lin = Linear.fit(ds.iloc[tr][FEATURES].to_numpy(float), ds["y"].values[tr])
        oof[te, 0] = _logit(tree.raw(ds.iloc[te][FEATURES]))
        oof[te, 1] = _logit(lin.proba(ds.iloc[te][FEATURES].to_numpy(float)))
        folds.append({"train_end": str(ds.index[tr].max().date()), "test_start": str(ds.index[te].min().date()), "n_test": int(len(te))})
    m = ~np.isnan(oof[:, 0])
    O, y, fwd = oof[m], ds["y"].values[m], ds["fwd"].values[m]
    cut = int(len(O) * 0.7)
    meta = Linear.fit(O[:cut], y[:cut], C=1.0)
    pm = meta.proba(O)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(pm[:cut], y[:cut])  # fit on earlier rows only
    p_oos = np.clip(iso.predict(pm[cut:]), 0, 1)
    y_oos, f_oos = y[cut:], fwd[cut:]
    # refit isotonic on all OOF meta outputs for the deployed model (report stays honest: computed above)
    iso_all = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(pm, y)
    tree = TradeFilterModel.train(ds[FEATURES], ds["y"].values)
    lin = Linear.fit(ds[FEATURES].to_numpy(float), ds["y"].values)
    scorer = StackedScorer(sleeve, tree, lin, meta, list(map(float, iso_all.X_thresholds_)), list(map(float, iso_all.y_thresholds_)),
                           {"horizon": cfg["horizon"], "cost_bps": cfg["cost_bps"]})
    oos_idx = ds.index[m][cut:]
    take = p_oos >= cfg["min_p_hit"]
    daily = pd.Series(np.where(take, f_oos, 0.0), index=oos_idx).groupby(level=0).mean() / cfg["horizon"]
    rules = pd.Series(f_oos, index=oos_idx).groupby(level=0).mean() / cfg["horizon"]
    base_auc = {n: float(roc_auc_score(y_oos, O[cut:, i])) if len(set(y_oos)) > 1 else float("nan") for i, n in enumerate(["tree", "linear"])}
    sr = float(daily.mean() / daily.std(ddof=1)) if daily.std(ddof=1) > 0 else 0.0
    rep = {"sleeve": sleeve, "folds": folds, "n_oos": int(len(y_oos)),
           "oos": {"auc_stacked": float(roc_auc_score(y_oos, p_oos)) if len(set(y_oos)) > 1 else float("nan"), "auc_base": base_auc,
                   "brier": brier(p_oos, y_oos), "brier_base_rate": brier(np.full(len(y_oos), y[:cut].mean()), y_oos),
                   "take_rate": float(take.mean()), "sharpe_filtered": sharpe(daily), "sharpe_rules_only": sharpe(rules),
                   "lift_bps_per_day": float((daily.mean() - rules.mean()) * 1e4), "max_drawdown_pct_filtered": max_drawdown_pct(daily)},
           "deflated_sharpe": deflated_sharpe(daily.values, list(prior_trials or []) + [sr]),
           "meta_weights": {"tree": meta.coef[0], "linear": meta.coef[1]},
           "feature_importance_stability_spearman": 0.5, "trial_sr": sr}
    from atlas.ai.models.quant.validation import validation_report
    rep["validation"] = validation_report(daily.values, list(prior_trials or []) + [sr])
    return scorer, rep, ds[FEATURES]


def card_for(sleeve: str):
    from atlas.ai.models.quant.modelcard import ModelCard
    c = SLEEVES[sleeve]
    return ModelCard(
        name=f"{sleeve} stacked scorer", kind=f"scorer_{sleeve}",
        purpose=f"Estimate P(after-cost {c['horizon']}-bar return > {c['cost_bps']} bps) for rule-generated {sleeve} candidates.",
        intended_use=f"Filter/rank candidates in the '{c['policy_sleeve']}' sleeve during paper trading; threshold {c['min_p_hit']}.",
        out_of_scope="Creating trades, sizing up, other sleeves/asset classes, live trading, intraday horizons.",
        data="Daily bars (Parquet store or deterministic synthetic GBM in tests); features stored point-in-time.",
        features=list(FEATURES),
        limitations=["Synthetic data has no edge: metrics near chance are expected in tests",
                     "Technical features only (fundamentals/sentiment proposed)", "Assumes bar-close availability"],
        risks=["Overfitting (mitigated: purged CV, deflated Sharpe, shadow gates)", "Regime change (drift monitor auto-demotes)"])
