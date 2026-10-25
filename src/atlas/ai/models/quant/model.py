"""LightGBM trade-scoring filter with isotonic calibration and SHAP explanations.
Deterministic (fixed seed, single thread). Saved as LightGBM text + JSON (no pickle)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.ai.models.quant.features import FEATURES

PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=15, max_depth=4, min_data_in_leaf=40,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, seed=7,
              deterministic=True, num_threads=1, verbose=-1)


def shap_available() -> bool:
    try:
        import shap  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class _XgbBoosterAdapter:
    """Deterministic XGBoost fallback with identical interface to LightGBM Booster (JSON text storage, no pickle)."""

    def __init__(self, bst, features: list[str], best_iteration: int):
        self.bst = bst
        self.features = list(features)
        self.best_iteration = int(best_iteration)

    def predict(self, X: pd.DataFrame, num_iteration: int | None = None, pred_contrib: bool = False) -> np.ndarray:
        import xgboost as xgb
        dm = xgb.DMatrix(X[self.features], feature_names=self.features)
        end = int(num_iteration or self.best_iteration or 0)
        kw = {"iteration_range": (0, end)} if end > 0 else {}
        if pred_contrib:
            return np.asarray(self.bst.predict(dm, pred_contribs=True, **kw), dtype=float)
        return np.asarray(self.bst.predict(dm, **kw), dtype=float)

    def feature_importance(self, kind: str = "gain") -> np.ndarray:
        scores = self.bst.get_score(importance_type=kind)
        return np.array([float(scores.get(f, 0.0)) for f in self.features], dtype=float)

    def model_to_string(self) -> str:
        return "XGB_JSON:" + self.bst.save_raw(raw_format="json").decode("utf-8")

    @classmethod
    def from_string(cls, txt: str, features: list[str], best_iteration: int) -> "_XgbBoosterAdapter":
        import xgboost as xgb
        bst = xgb.Booster()
        raw = txt[len("XGB_JSON:"):] if txt.startswith("XGB_JSON:") else txt
        bst.load_model(bytearray(raw.encode("utf-8")))
        return cls(bst, features, best_iteration)


@dataclass
class TradeFilterModel:
    booster: object
    iso_x: list[float] = field(default_factory=list)
    iso_y: list[float] = field(default_factory=list)
    features: list[str] = field(default_factory=lambda: list(FEATURES))
    meta: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- training
    @classmethod
    def train(cls, X: pd.DataFrame, y, num_rounds: int = 300, calib_frac: float = 0.2) -> "TradeFilterModel":
        from sklearn.isotonic import IsotonicRegression
        X = X[FEATURES]
        y = np.asarray(y, float)
        n = len(X)
        cut = int(n * (1 - calib_frac))
        es = int(cut * 0.85)
        try:
            import lightgbm as lgb
            dtr = lgb.Dataset(X.iloc[:es], y[:es])
            dva = lgb.Dataset(X.iloc[es:cut], y[es:cut], reference=dtr)
            bst = lgb.train(PARAMS, dtr, num_boost_round=num_rounds, valid_sets=[dva],
                            callbacks=[lgb.early_stopping(30, verbose=False)])
            best_it = int(bst.best_iteration or num_rounds)
            raw = bst.predict(X.iloc[cut:], num_iteration=best_it)
        except ImportError:
            import xgboost as xgb
            dtr = xgb.DMatrix(X.iloc[:es], label=y[:es], feature_names=list(FEATURES))
            dva = xgb.DMatrix(X.iloc[es:cut], label=y[es:cut], feature_names=list(FEATURES))
            xparams = dict(objective="binary:logistic", eval_metric="logloss", eta=0.05, max_depth=4,
                           min_child_weight=40, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                           seed=7, nthread=1, verbosity=0)
            xbst = xgb.train(xparams, dtr, num_boost_round=num_rounds, evals=[(dva, "val")],
                             early_stopping_rounds=30, verbose_eval=False)
            best_it = int(getattr(xbst, "best_iteration", num_rounds - 1)) + 1
            bst = _XgbBoosterAdapter(xbst, list(FEATURES), best_it)
            raw = bst.predict(X.iloc[cut:], num_iteration=best_it)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y[cut:])
        return cls(bst, list(map(float, iso.X_thresholds_)), list(map(float, iso.y_thresholds_)),
                   meta={"best_iteration": best_it, "n_train": n})

    # ---------------------------------------------------------------- inference
    def raw(self, X: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(X[self.features], num_iteration=self.meta.get("best_iteration") or None)

    def p_hit(self, X: pd.DataFrame) -> np.ndarray:
        r = self.raw(X)
        if not self.iso_x:
            return r
        return np.clip(np.interp(r, self.iso_x, self.iso_y), 0, 1)

    def explain(self, X: pd.DataFrame, top: int = 5) -> list[list[tuple[str, float]]]:
        """Per-row top SHAP contributions (TreeSHAP). Uses `shap` if installed, else LightGBM's
        built-in TreeSHAP (pred_contrib) which computes the same values."""
        Xf = X[self.features]
        if shap_available():
            import shap
            vals = np.asarray(shap.TreeExplainer(self.booster).shap_values(Xf))
            if vals.ndim == 3:
                vals = vals[-1]
        else:
            vals = self.booster.predict(Xf, pred_contrib=True)[:, :-1]
        out = []
        for row in vals:
            idx = np.argsort(-np.abs(row))[:top]
            out.append([(self.features[i], float(row[i])) for i in idx])
        return out

    def importance(self) -> dict[str, float]:
        g = self.booster.feature_importance("gain")
        tot = float(g.sum()) or 1.0
        return {f: float(v) / tot for f, v in zip(self.features, g)}

    # ---------------------------------------------------------------- persistence
    def save(self, d: Path) -> str:
        d.mkdir(parents=True, exist_ok=True)
        txt = self.booster.model_to_string()
        (d / "model.txt").write_text(txt)
        (d / "calib.json").write_text(json.dumps({"iso_x": self.iso_x, "iso_y": self.iso_y,
                                                  "features": self.features, "meta": self.meta}))
        return hashlib.sha256(txt.encode() + json.dumps([self.iso_x, self.iso_y]).encode()).hexdigest()

    @classmethod
    def load(cls, d: Path) -> "TradeFilterModel":
        c = json.loads((d / "calib.json").read_text())
        txt = (d / "model.txt").read_text()
        if txt.startswith("XGB_JSON:"):
            bst = _XgbBoosterAdapter.from_string(txt, c["features"], int(c["meta"].get("best_iteration", 0)))
        else:
            import lightgbm as lgb
            bst = lgb.Booster(model_str=txt)
        return cls(bst, c["iso_x"], c["iso_y"], c["features"], c["meta"])
