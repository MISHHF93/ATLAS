"""Meta-label training + honest out-of-sample evaluation.

Pre-declared before any run (do not change after seeing results):
  * primary variant per group = ``hgb_conformal`` (HistGradientBoosting meta-model, isotonic calibration,
    take only if EV_R > 0 AND the conformal set is {1}); the gates are evaluated on this variant only.
  * other variants (``logit_ev``, ``logit_conformal``, ``hgb_ev``) and the ``take_all`` baseline are trials:
    they count toward the DSR trial set and the PBO matrix, never toward selection.
  * gates = research.setup_evidence.registry_gates thresholds: n_oos >= 200, Brier skill > 0 vs the training
    base rate, logloss < baseline, DSR > 0.95, PBO < 0.5, shadow weeks >= 4 (control-plane min_shadow_weeks).
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from atlas.ai.ml import metrics as M
from atlas.ai.ml.calibration import Calibrator, Conformal, fit_calibrator, fit_conformal
from atlas.ai.ml.cv import inner_split, walk_forward_splits
from atlas.ai.ml.dataset import FEATURES

PRIMARY = "hgb_conformal"
VARIANTS = ("logit_ev", "logit_conformal", "hgb_ev", "hgb_conformal")
KELLY_FRACTION = 0.25
ALPHA = 0.2
EMBARGO = 86400
SEED = 0
GATES = {"min_oos": 200, "min_dsr": 0.95, "max_pbo": 0.5, "min_shadow_weeks": 4}


def make_model(kind: str):
    if kind == "xgb":          # challenger only (installed; benchmarked in research, never default)
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                             min_child_weight=10, reg_lambda=1.0, n_jobs=2, random_state=SEED, verbosity=0)
    if kind == "lgbm":         # challenger only
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05, min_child_samples=40, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, n_jobs=2, random_state=SEED, verbose=-1)
    if kind == "ridge":        # strongly L2-penalised logistic (ridge-classifier analogue with probabilities)
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.005, max_iter=2000))
    if kind == "logit":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                          l2_regularization=1.0, random_state=SEED)


@dataclass
class MetaModel:
    """Fitted meta-labeler: raw model -> calibrator -> conformal + payoff stats for EV/size."""
    kind: str
    model: Any
    calibrator: Calibrator
    conformal: Conformal
    win_r: dict[str, float]          # per detector mean after-cost R of winners (fit block)
    loss_r: dict[str, float]         # per detector mean |R| of losers
    features: tuple[str, ...] = FEATURES
    base_rate: float = 0.5

    def raw(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X[list(self.features)].to_numpy(float))[:, 1]

    def proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.calibrator(self.raw(X))

    def ev_r(self, X: pd.DataFrame, p: np.ndarray) -> np.ndarray:
        w = X["detector"].map(self.win_r).fillna(np.mean(list(self.win_r.values())) if self.win_r else 1.0).to_numpy(float)
        l = X["detector"].map(self.loss_r).fillna(np.mean(list(self.loss_r.values())) if self.loss_r else 1.0).to_numpy(float)
        return p * w - (1 - p) * l

    def size(self, X: pd.DataFrame, p: np.ndarray) -> np.ndarray:
        """Fractional Kelly on the empirical payoff ratio b = W/L; clipped to [0, 1]. A proposal input only."""
        w = X["detector"].map(self.win_r).fillna(1.0).to_numpy(float)
        l = X["detector"].map(self.loss_r).fillna(1.0).to_numpy(float)
        b = np.maximum(w / np.maximum(l, 1e-9), 1e-9)
        return np.clip(KELLY_FRACTION * (b * p - (1 - p)) / b, 0.0, 1.0)

    def decide(self, X: pd.DataFrame, use_conformal: bool = True) -> dict[str, np.ndarray]:
        p = self.proba(X)
        ev = self.ev_r(X, p)
        take = ev > 0
        if use_conformal:
            take &= self.conformal.take_mask(p)
        return {"p": p, "ev_r": ev, "take": take, "size": np.where(take, self.size(X, p), 0.0)}


def _payoffs(df: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    w, l = {}, {}
    for d, g in df.groupby("detector"):
        pos, neg = g.r[g.r > 0], g.r[g.r <= 0]
        w[d] = float(pos.mean()) if len(pos) else 0.0
        l[d] = float(-neg.mean()) if len(neg) else 1.0
    return w, l


def fit_meta(df: pd.DataFrame, idx: np.ndarray, kind: str, features: tuple[str, ...] = FEATURES) -> MetaModel | None:
    t, e = df.t.to_numpy(np.int64), df.exit_at.to_numpy(np.int64)
    fit, cal, conf = inner_split(t, e, idx, embargo=EMBARGO)
    if len(fit) < 60 or len(cal) < 20 or len(conf) < 20 or df.y.iloc[fit].nunique() < 2:
        return None
    X = df[list(features)].to_numpy(float)
    m = make_model(kind).fit(X[fit], df.y.to_numpy()[fit])
    c = fit_calibrator(m.predict_proba(X[cal])[:, 1], df.y.to_numpy()[cal], fitted_through=int(e[cal].max()))
    pc = c(m.predict_proba(X[conf])[:, 1])
    cf = fit_conformal(pc, df.y.to_numpy()[conf], ALPHA)
    w, l = _payoffs(df.iloc[np.concatenate([fit, cal])])
    return MetaModel(kind, m, c, cf, w, l, tuple(features), float(df.y.iloc[idx].mean()))


def evaluate_group(df: pd.DataFrame, n_folds: int = 5) -> dict[str, Any]:
    """Walk-forward OOS for every variant on one (asset_class, interval) group."""
    df = df.sort_values(["t", "instrument", "candidate_id"]).reset_index(drop=True)
    t, e = df.t.to_numpy(np.int64), df.exit_at.to_numpy(np.int64)
    oos = []
    folds = []
    for k, tr, te in walk_forward_splits(t, e, n_folds=n_folds, embargo=EMBARGO):
        base = float(df.y.iloc[tr].mean())
        rec = {"fold": k, "n_train": int(len(tr)), "n_test": int(len(te)), "test_from": int(t[te[0]]), "test_to": int(t[te[-1]]),
               "train_base_rate": base}
        mdl = {kind: fit_meta(df, tr, kind) for kind in ("logit", "hgb")}
        if any(v is None for v in mdl.values()):
            rec["skipped"] = "insufficient_inner_split"
            folds.append(rec)
            continue
        part = df.iloc[te][["instrument", "detector", "candidate_id", "t", "exit_at", "y", "r"]].copy()
        part["fold"], part["base"] = k, base
        for kind, mm in mdl.items():
            for conf in (False, True):
                d = mm.decide(df.iloc[te], use_conformal=conf)
                v = f"{kind}_{'conformal' if conf else 'ev'}"
                part[f"p_{kind}"] = d["p"]
                part[f"take_{v}"] = d["take"]
                part[f"size_{v}"] = d["size"]
            rec[f"{kind}_calibrator"] = mm.calibrator.kind
            rec[f"{kind}_qhat"] = mm.conformal.qhat
        folds.append(rec)
        oos.append(part)
    if not oos:
        return {"n_rows": len(df), "n_oos": 0, "folds": folds}
    o = pd.concat(oos, ignore_index=True)
    return {"n_rows": len(df), "n_oos": len(o), "folds": folds, "oos": o}


def summarize(o: pd.DataFrame, kind: str, variant: str) -> dict[str, Any]:
    p, y, b = o[f"p_{kind}"].to_numpy(), o.y.to_numpy(), o.base.to_numpy()
    take = o[f"take_{variant}"].to_numpy(bool)
    r = o.r.to_numpy()
    bs, bb = M.brier(p, y), M.brier(b, y)
    return {"n_oos": int(len(o)), "base_rate_oos": float(y.mean()), "brier": bs, "brier_baseline": bb,
            "brier_skill": (1 - bs / bb) if bb > 0 else None, "logloss": M.logloss(p, y), "logloss_baseline": M.logloss(b, y),
            "ece": M.ece(p, y), "auc": M.auc(p, y), "n_taken": int(take.sum()), "coverage": float(take.mean()),
            "mean_r_taken": float(r[take].mean()) if take.any() else None, "total_r_taken": float(r[take].sum()),
            "hit_rate_taken": float((r[take] > 0).mean()) if take.any() else None,
            "size_weighted_r": float((r * o[f"size_{variant}"].to_numpy()).sum()),
            "mean_r_all": float(r.mean()), "total_r_all": float(r.sum())}


def run_training(data: pd.DataFrame, groups: list[tuple[str, str]] | None = None, n_folds: int = 5) -> dict[str, Any]:
    groups = groups or sorted({(a, i) for a, i in zip(data.asset_class, data.interval)})
    res: dict[str, Any] = {"groups": {}, "pre_declared": {"primary": PRIMARY, "variants": VARIANTS, "gates": GATES,
                                                          "alpha": ALPHA, "embargo_s": EMBARGO, "kelly_fraction": KELLY_FRACTION}}
    daily: dict[str, dict[str, np.ndarray]] = {}
    for ac, iv in groups:
        g = data[(data.asset_class == ac) & (data.interval == iv)]
        key = f"{ac}-{iv}"
        ev = evaluate_group(g, n_folds=n_folds)
        out = {k: v for k, v in ev.items() if k != "oos"}
        if ev.get("n_oos"):
            o = ev["oos"]
            out["variants"] = {v: summarize(o, v.split("_")[0], v) for v in VARIANTS}
            out["take_all"] = {"n": int(len(o)), "mean_r": float(o.r.mean()), "total_r": float(o.r.sum())}
            out["per_instrument"] = {}
            for inst, oi in o.groupby("instrument"):
                out["per_instrument"][inst] = {v: summarize(oi, v.split("_")[0], v) for v in (PRIMARY, "logit_conformal")}
            out["per_detector"] = {d: summarize(od, "hgb", PRIMARY) for d, od in o.groupby("detector")}
            out["reliability"] = M.reliability(o["p_hgb"], o.y)
            t0, t1 = int(o.t.min()), int(o.t.max())
            daily[key] = {v: M.daily_series(o.t, np.where(o[f"take_{v}"], o.r, 0.0), t0, t1) for v in VARIANTS}
            daily[key]["take_all"] = M.daily_series(o.t, o.r, t0, t1)
            out["_oos"] = o
        res["groups"][key] = out
    trials = [s for d in daily.values() for s in d.values()]
    res["n_trials"] = len(trials)
    for key, d in daily.items():
        out = res["groups"][key]
        for v in VARIANTS:
            out["variants"][v]["dsr"] = M.dsr(d[v], trials)
        mat = np.column_stack([d[v] for v in (*VARIANTS, "take_all")])
        out["pbo"] = M.pbo(mat)
        out["gates"] = gates(out)
    return res


def gates(out: dict[str, Any], shadow_weeks: int = 0) -> list[dict[str, Any]]:
    s = out["variants"][PRIMARY]
    d = (s.get("dsr") or {}).get("dsr", 0.0)
    p = (out.get("pbo") or {}).get("pbo")
    return [
        {"gate": "n_oos", "passed": s["n_oos"] >= GATES["min_oos"], "value": s["n_oos"], "threshold": f">= {GATES['min_oos']}"},
        {"gate": "brier_beats_base_rate", "passed": s["brier_skill"] is not None and s["brier_skill"] > 0, "value": s["brier_skill"], "threshold": "> 0"},
        {"gate": "logloss_beats_base_rate", "passed": s["logloss"] < s["logloss_baseline"], "value": [s["logloss"], s["logloss_baseline"]], "threshold": "model < baseline"},
        {"gate": "deflated_sharpe", "passed": d > GATES["min_dsr"], "value": d, "threshold": f"> {GATES['min_dsr']}"},
        {"gate": "pbo", "passed": p is not None and p < GATES["max_pbo"], "value": p, "threshold": f"< {GATES['max_pbo']}"},
        {"gate": "shadow_weeks", "passed": shadow_weeks >= GATES["min_shadow_weeks"], "value": shadow_weeks, "threshold": f">= {GATES['min_shadow_weeks']}"},
    ]


def fit_final(data: pd.DataFrame, asset_class: str, interval: str, kind: str = "hgb") -> MetaModel | None:
    g = data[(data.asset_class == asset_class) & (data.interval == interval)].sort_values(["t", "instrument", "candidate_id"]).reset_index(drop=True)
    return fit_meta(g, np.arange(len(g)), kind)


def dumps(m: MetaModel) -> bytes:
    return pickle.dumps(m)
