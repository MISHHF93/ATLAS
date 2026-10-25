"""Meta-labeling (AFML ch.3; Joubert 2022). A PRIMARY model picks the side (a rule, or a sleeve
scorer); the META model (the calibrated stacker: LightGBM + linear -> logistic -> isotonic) predicts
P(primary trade is profitable after cost) on triple-barrier labels; the probability sizes the bet.
The news-screener veto is a feature. The meta model can only SHRINK or DROP a primary trade:
size = qty * f(p) with f in [0, 1], f = 0 below the threshold.

Leakage control: the primary is a fixed rule fitted on nothing, or must be passed in already
fitted on data strictly before the meta training window; meta OOF predictions come from
purged K-fold on label end times (t1)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.ai.models.quant.features import FEATURES, make_features
from atlas.ai.models.quant.labels import triple_barrier, vol_from_model, causal_daily_vol
from atlas.ai.models.quant.validation import purged_kfold_t1

META_FEATURES = FEATURES + ["side", "sigma", "news_veto"]


def momentum_primary(close: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    c = close.astype(float)
    return np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()).fillna(0)


def meta_dataset(bars: dict[str, pd.DataFrame], primary=momentum_primary, pt: float = 1.0, sl: float = 1.0,
                 max_hold: int = 10, cost_bps: float = 10.0, vol_model=None, news_veto: dict | None = None) -> pd.DataFrame:
    """news_veto: {symbol: pd.Series(0/1 indexed by date)} from the screener (point-in-time)."""
    parts = []
    for sym, df in bars.items():
        c = df["close"].astype(float)
        vol = vol_from_model(c, vol_model) if vol_model is not None else causal_daily_vol(c)
        side = primary(c)
        lab = triple_barrier(c, side, pt, sl, max_hold, vol, cost_bps)
        f = make_features(df).reindex(lab.index)
        nv = (news_veto or {}).get(sym)
        f["news_veto"] = nv.reindex(lab.index).fillna(0).astype(float) if nv is not None else 0.0
        parts.append(f.join(lab).assign(symbol=sym).dropna(subset=FEATURES))
    return pd.concat(parts).sort_index(kind="mergesort")


class MetaLabeler:
    def __init__(self, tree, lin, meta, iso_x, iso_y, threshold: float):
        self.tree, self.lin, self.meta, self.iso_x, self.iso_y, self.threshold = tree, lin, meta, iso_x, iso_y, threshold
        self.params: dict = {}

    @staticmethod
    def _base(tree, lin, X: pd.DataFrame) -> np.ndarray:
        from atlas.ai.models.quant.sleeves import _logit
        return np.column_stack([_logit(tree.predict_proba(X[META_FEATURES])[:, 1]),
                                _logit(lin.proba(X[META_FEATURES].to_numpy(float)))])

    def p_profit(self, X: pd.DataFrame) -> np.ndarray:
        p = self.meta.proba(self._base(self.tree, self.lin, X))
        return np.clip(np.interp(p, self.iso_x, self.iso_y), 0, 1)

    def size_factor(self, X: pd.DataFrame) -> np.ndarray:
        """Bet size in [0,1]: 0 below threshold, then linear to 1 at p=1. Veto rows -> 0."""
        p = self.p_profit(X)
        f = np.clip((p - self.threshold) / max(1e-9, 1 - self.threshold), 0, 1)
        return np.where(X["news_veto"].to_numpy(float) > 0, 0.0, f)

    def apply(self, qty: float, X_row: pd.DataFrame) -> float:
        return float(qty) * float(self.size_factor(X_row)[0])   # never exceeds qty

    # ---------------------------------------------------------------- persistence (registry digest-checked)
    def save(self, d) -> None:
        import json
        from dataclasses import asdict
        from pathlib import Path
        import joblib
        d = Path(d); d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.tree, d / "tree.joblib")
        (d / "meta.json").write_text(json.dumps({"lin": asdict(self.lin), "meta": asdict(self.meta), "iso_x": self.iso_x,
                                                 "iso_y": self.iso_y, "threshold": self.threshold, "features": META_FEATURES,
                                                 "params": self.params}))

    @classmethod
    def load(cls, d) -> "MetaLabeler":
        import json
        from pathlib import Path
        import joblib
        from atlas.ai.models.quant.sleeves import Linear
        d = Path(d)
        j = json.loads((d / "meta.json").read_text())
        if j["features"] != META_FEATURES:
            raise ValueError("meta-labeler feature schema mismatch")
        m = cls(joblib.load(d / "tree.joblib"), Linear(**j["lin"]), Linear(**j["meta"]), j["iso_x"], j["iso_y"], j["threshold"])
        m.params = j.get("params", {})
        return m


def _tree():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)


def train_meta(ds: pd.DataFrame, n_splits: int = 5, threshold: float = 0.55) -> tuple[MetaLabeler, dict]:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score
    from atlas.ai.models.quant.labels import label_concurrency_weights
    from atlas.ai.models.quant.metrics import brier
    from atlas.ai.models.quant.sleeves import Linear
    X, y = ds[META_FEATURES], ds["bin"].to_numpy(int)
    w = label_concurrency_weights(ds.index, ds["t1"]).to_numpy()
    oof = np.full((len(ds), 2), np.nan)
    for tr, te in purged_kfold_t1(ds.index.values, ds["t1"].values, n_splits, 0.01):
        t = _tree().fit(X.iloc[tr], y[tr], sample_weight=w[tr])
        l = Linear.fit(X.iloc[tr].to_numpy(float), y[tr])
        oof[te] = MetaLabeler._base(t, l, X.iloc[te])
    cut = int(len(ds) * 0.7)
    meta = Linear.fit(oof[:cut], y[:cut], C=1.0)
    pm = meta.proba(oof)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(pm[:cut], y[:cut])
    p_oos = iso.predict(pm[cut:])
    ret_oos, take = ds["ret"].to_numpy()[cut:], p_oos >= threshold
    iso_all = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(pm, y)
    model = MetaLabeler(_tree().fit(X, y, sample_weight=w), Linear.fit(X.to_numpy(float), y), meta,
                        list(map(float, iso_all.X_thresholds_)), list(map(float, iso_all.y_thresholds_)), threshold)
    rep = {"n": len(ds), "n_oos": int(len(p_oos)), "primary_hit_rate_oos": float(y[cut:].mean()),
           "auc_oos": float(roc_auc_score(y[cut:], p_oos)) if len(set(y[cut:])) > 1 else float("nan"),
           "brier_oos": brier(p_oos, y[cut:]), "take_rate": float(take.mean()),
           "precision_taken": float(y[cut:][take].mean()) if take.any() else float("nan"),
           "mean_ret_primary": float(ret_oos.mean()), "mean_ret_meta": float((ret_oos * take).mean()),
           "barrier_mix": ds["barrier"].value_counts(normalize=True).round(3).to_dict()}
    return model, rep
