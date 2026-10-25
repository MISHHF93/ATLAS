"""Walk-forward evaluation: purged/embargoed CV, out-of-sample filtered-strategy returns
vs rules-only, calibration (Brier), deflated Sharpe over all trials, SHAP summary."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from atlas.ai.models.quant.cv import purged_walk_forward
from atlas.ai.models.quant.features import FEATURES
from atlas.ai.models.quant.metrics import brier, deflated_sharpe, max_drawdown_pct, sharpe
from atlas.ai.models.quant.model import TradeFilterModel, shap_available


def walk_forward_report(ds: pd.DataFrame, horizon: int = 5, n_splits: int = 4, min_p_hit: float = 0.55,
                        prior_trial_srs: list[float] | None = None) -> dict:
    times = ds.index.values
    folds, oos_p, oos_idx, imps = [], [], [], []
    for k, (tr, te) in enumerate(purged_walk_forward(times, n_splits=n_splits, horizon=horizon)):
        m = TradeFilterModel.train(ds.iloc[tr][FEATURES], ds["y"].values[tr])
        p = m.p_hit(ds.iloc[te][FEATURES])
        y = ds["y"].values[te]
        fwd = ds["fwd"].values[te]
        take = p >= min_p_hit
        auc = float(roc_auc_score(y, p)) if len(set(y)) > 1 else float("nan")
        folds.append({"fold": k, "n_train": int(len(tr)), "n_test": int(len(te)), "train_end": str(ds.index[tr].max().date()),
                      "test_start": str(ds.index[te].min().date()), "auc": auc, "brier": brier(p, y),
                      "brier_base": brier(np.full(len(y), ds["y"].values[tr].mean()), y),
                      "take_rate": float(take.mean()), "mean_fwd_taken_bps": float(fwd[take].mean() * 1e4) if take.any() else 0.0,
                      "mean_fwd_rules_bps": float(fwd.mean() * 1e4)})
        imps.append([m.importance()[f] for f in FEATURES])
        oos_p.append(p); oos_idx.append(te)
    idx = np.concatenate(oos_idx); p = np.concatenate(oos_p)
    oos = ds.iloc[idx].assign(p=p)
    take = oos["p"] >= min_p_hit
    # daily strategy returns: equal-weight mean fwd of taken candidates per day, scaled by horizon
    filt = oos[take].groupby(level=0)["fwd"].mean().reindex(oos.index.unique(), fill_value=0.0) / horizon
    rules = oos.groupby(level=0)["fwd"].mean() / horizon
    trials = list(prior_trial_srs or [])
    srs_this = [float(filt.mean() / filt.std(ddof=1)) if filt.std(ddof=1) > 0 else 0.0,
                float(rules.mean() / rules.std(ddof=1)) if rules.std(ddof=1) > 0 else 0.0]
    stab = [spearmanr(imps[i], imps[i + 1]).statistic for i in range(len(imps) - 1)]
    final = TradeFilterModel.train(ds[FEATURES], ds["y"].values)
    sample = ds[FEATURES].iloc[-min(200, len(ds)):]
    contrib = np.abs(np.array([[v for _, v in sorted(r, key=lambda t: t[0])] for r in final.explain(sample, top=len(FEATURES))]))
    shap_global = dict(zip(sorted(FEATURES), contrib.mean(axis=0).round(6).tolist()))
    return {
        "folds": folds,
        "oos": {"n": int(len(oos)), "brier": brier(oos["p"], oos["y"]), "auc": float(roc_auc_score(oos["y"], oos["p"])),
                "sharpe_filtered": sharpe(filt), "sharpe_rules_only": sharpe(rules),
                "lift_bps_per_day": float((filt.mean() - rules.mean()) * 1e4),
                "max_drawdown_pct_filtered": max_drawdown_pct(filt)},
        "deflated_sharpe": deflated_sharpe(filt.values, trials + srs_this),
        "feature_importance_stability_spearman": float(np.nanmean(stab)) if stab else float("nan"),
        "shap_global_mean_abs": shap_global, "shap_backend": "shap" if shap_available() else "lightgbm_pred_contrib",
        "final_model": final,
        "trial_srs_added": srs_this,
    }
