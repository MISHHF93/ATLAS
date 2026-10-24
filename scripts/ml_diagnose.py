"""Honest diagnosis of the meta-labeler population data (why no challenger beats baseline).
Usage: ATLAS_FEED_DB=... PYTHONPATH=src python scripts/ml_diagnose.py [--universe default|extended] [--out f.json]
Prints/writes: label balance, gross vs net R, per-instrument/detector/outcome/regime/quarter/cost-quintile
breakdowns, fold sizes, shuffled-label leakage check, univariate AUCs and OOS permutation importance (lgbm, full)."""
import argparse
import json

import numpy as np
import pandas as pd


def grp(d, by):
    g = d.groupby(by, observed=True).agg(n=("y", "size"), base=("y", "mean"), net_r=("r", "mean"), gross_r=("gross", "mean"))
    return {str(k): {c: round(float(v), 4) for c, v in row.items()} for k, row in g.iterrows()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=("default", "extended", "evo6", "evo7", "evo7_1h"), default="default")
    ap.add_argument("--model", default="lgbm")
    ap.add_argument("--out")
    a = ap.parse_args()
    from atlas.feeds.feed import get_feed
    from atlas.ml import evolution as E
    from atlas.ml import metrics as M
    from atlas.ml.train import fit_meta
    d, meta = (E.build_population_data(get_feed(), {"evo6": E.UNIVERSE_EVO6, "evo7": E.UNIVERSE_EVO7, "evo7_1h": E.UNIVERSE_EVO7_1H}[a.universe], variant=E.EVO6_VARIANT, detectors=E.EVO6_DETECTORS) if a.universe.startswith("evo") else
        E.build_population_data(get_feed(), E.UNIVERSE_EXTENDED if a.universe == "extended" else E.UNIVERSE))
    d = d.copy()
    d["gross"] = d.r + d.cost_r
    d["regime"] = np.where(d.reg_hi > 0, "hi", np.where(d.reg_lo > 0, "lo", "mid"))
    d["quarter"] = pd.to_datetime(d.t, unit="s").dt.to_period("Q").astype(str)
    d["cost_q"] = pd.qcut(d.cost_r, 5, labels=[f"q{i}" for i in range(1, 6)])
    rep = {"n_rows": len(d), "data_hash": meta["data_hash"], "base_rate": float(d.y.mean()), "mean_net_r": float(d.r.mean()),
           "mean_gross_r": float(d.gross.mean()), "median_cost_r": float(d.cost_r.median())}
    for by in ("instrument", "interval", "detector", "outcome", "regime", "quarter", "cost_q"):
        rep[f"by_{by}"] = grp(d, by)
    fs = E.folds(d)
    rep["folds"] = [{"fold": k, "n_train": len(tr), "n_test": len(te)} for k, tr, te in fs]
    g = {"model": a.model, "features": "full", "regime": "none", "bar_type": "time", "context": "none"}
    feats = list(E.feature_list(g))
    r0 = E.evaluate_genome(d, g, fs)
    rep["model_full"] = {k: r0.get(k) for k in ("auc", "brier_skill", "ev_r_per_opportunity", "take_all_ev", "coverage")}
    rng = np.random.default_rng(0)
    ds = d.copy()
    ds["y"] = rng.permutation(ds.y.to_numpy())
    ds["r"] = np.where(ds.y == 1, ds.r.abs(), -ds.r.abs())
    r1 = E.evaluate_genome(ds, g, fs)
    rep["shuffled_label"] = {"auc": r1.get("auc"), "brier_skill": r1.get("brier_skill")}
    rep["univariate_auc"] = dict(sorted(((c, round(float(M.auc(d[c].fillna(d[c].median()).to_numpy(), d.y.to_numpy())), 4)) for c in feats),
                                        key=lambda kv: -abs(kv[1] - 0.5))[:15])
    imp = {c: [] for c in feats}
    aucs = []
    for k, tr, te in fs:
        mm = fit_meta(d, tr, a.model, feats)
        if mm is None:
            continue
        X = d.iloc[te]
        a0 = M.auc(mm.raw(X), X.y.to_numpy())    # same (uncalibrated) score for base and permuted -> unbiased drop
        aucs.append(round(float(a0), 4))
        for c in feats:
            Xp = X.copy()
            Xp[c] = rng.permutation(Xp[c].to_numpy())
            imp[c].append(a0 - M.auc(mm.raw(Xp), X.y.to_numpy()))
    rep["fold_raw_auc"] = aucs
    rep["perm_importance_auc_drop"] = dict(sorted(((c, round(float(np.mean(v)), 4)) for c, v in imp.items() if v), key=lambda kv: -kv[1])[:15])
    s = json.dumps(rep, indent=1, default=str)
    if a.out:
        open(a.out, "w").write(s)
    print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
