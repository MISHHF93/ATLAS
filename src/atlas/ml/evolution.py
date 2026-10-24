"""Governed model-evolution loop (research only; execution_permission "none"; never auto-promotes).

Population genome = {model, features, regime, bar_type, context}:
  model     logit | ridge | hgb | xgb | lgbm           (ml.train.make_model; xgb/lgbm are challengers)
  features  full | no_setup | no_signed | no_time | bar_only        (ablations of ml.dataset.FEATURES)
  regime    none | vol_conditioned  (adds low/high rv_pctile_480 flags and their interaction with the signed features)
  bar_type  time | heikin_ashi | renko_atr | range_atr | volume | dollar | kagi_atr | pnf_atr   (features.representations; tick is gated)
  context   none | htf | macro | htf_macro   (ml.context: closed 1d/4h buckets; section-22 FRED macro gated on availability date)

Fair comparison: ONE dataset (ml.dataset rows = real-price replay of the existing setup library: entries, exits,
costs and labels are always on real time bars) and ONE set of purged + embargoed walk-forward folds
(ml.cv.walk_forward_splits, embargo 1 day) shared by every genome. A bar type only changes the feature columns
(``rep_*`` of that representation, causally aligned: only alt bars completed at or before the detection bar's end).

Per fold: ml.train.fit_meta (fit | isotonic/Platt calibration | conformal blocks, purged) -> calibrated p on the
test block -> take iff EV_R(p) > 0 (payoffs from the training blocks). Pre-declared fitness:
  ev      = sum(after-cost R of taken trades) / n_oos            (R per opportunity; take-none = 0)
  bss     = 1 - Brier(p) / Brier(train base rate)                (Brier skill vs base rate)
  stab    = share of folds with fold ev > 0
  fitness = ev + bss + 0.1 * (stab - 0.5)
  beats_baseline = ev > max(0, take_all_ev) AND bss > 0          (take_all_ev = mean R of every opportunity)
Evolution: generation 0 = seeds; each later generation mutates one gene of each of the top-3 genomes (2 children
each, deterministic RNG, no re-evaluation of seen genomes). Leaderboard + lineage (generation, parent, mutation,
metrics) are appended to the ML registry root (``<registry>/evolution/``). Champion/challenger: the best genome that
beats baseline becomes the *research* champion only if it beats the previous research champion; nothing is ever
promoted to execution (``promoted_to_execution`` is always False).
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from atlas.features.representations import REP_FEATURES, availability, rep_features
from atlas.ml import metrics as M
from atlas.ml.cv import walk_forward_splits
from atlas.ml.dataset import BAR_FEATURES, FEATURES, SETUP_FEATURES, SIGNED, build_rows, load_series
from atlas.ml.registry import _clean, code_sha, root

GENES: dict[str, tuple[str, ...]] = {
    "model": ("logit", "ridge", "hgb", "xgb", "lgbm"),
    "features": ("full", "no_setup", "no_signed", "no_time", "bar_only"),
    "regime": ("none", "vol_conditioned"),
    "bar_type": ("time", "heikin_ashi", "renko_atr", "range_atr", "volume", "dollar", "kagi_atr", "pnf_atr"),
    "context": ("none", "htf", "macro", "htf_macro"),
}
SEEDS = [
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "logit", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "ridge", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "xgb", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "lgbm", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "hgb", "features": "full", "regime": "vol_conditioned", "bar_type": "time"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "heikin_ashi"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "renko_atr"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "range_atr"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "volume"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "dollar"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "kagi_atr"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "pnf_atr"},
    {"model": "logit", "features": "no_setup", "regime": "none", "bar_type": "time"},
]
SEEDS += [
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time", "context": "htf"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time", "context": "macro"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time", "context": "htf_macro"},
    {"model": "logit", "features": "full", "regime": "none", "bar_type": "time", "context": "htf_macro"},
]
DEFAULTS = {"context": "none"}
UNIVERSE = [(i, "15m") for i in ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM")]
# Extended pooled universe (opt-in): 1h history back to 2023/24 (lower cost per R) + 15m crypto alts.
UNIVERSE_EXTENDED = UNIVERSE + [(i, "1h") for i in ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM")]
# evo6: the only setup family with positive mean gross R (before costs) in docs/research/evo6-setup-variants.md:
# prior_day_range_reversal on 4h (crypto, derived from closed 1h bars) with ATR-scaled stops. Gross CI still spans 0.
UNIVERSE_EVO6 = [(i, "4h") for i in ("BTCUSDT", "ETHUSDT")]
EVO6_VARIANT, EVO6_DETECTORS = "atr2_rr2", ("prior_day_range_reversal",)
N_FOLDS = 5
EMBARGO = 86400
TIME_FEATS = ("hod_sin", "hod_cos", "dow_sin", "dow_cos")
SIGNED_X = tuple(f"{s}_x_dir" for s in SIGNED)


def gid(g: dict[str, str]) -> str:
    return "|".join(f"{k}={g.get(k, DEFAULTS.get(k))}" for k in GENES)


def build_population_data(feed, universe: Sequence[tuple[str, str]] = UNIVERSE, as_of: int | None = None,
                          variant: str | None = None, detectors: Sequence[str] | None = None) -> tuple[pd.DataFrame, dict]:
    """``variant``/``detectors``: evo6 re-labelling on a research setup variant (research.setup_variants)."""
    from atlas.ml.context import htf_frame
    frames, meta = [], {"series": [], "bar_type_availability": {}, "variant": variant, "detectors": list(detectors) if detectors else None}
    v = None
    if variant is not None:
        from atlas.research.setup_variants import VARIANT_BY_ID
        v = VARIANT_BY_ID[variant]
    for inst, iv in universe:
        sd = load_series(feed, inst, iv, as_of=as_of)
        df = build_rows(sd, variant=v, detectors=detectors)
        meta["series"].append({"instrument": inst, "interval": iv, "n_bars": len(sd.bars), "n_rows": len(df),
                               "first_bar": sd.bars[0].start if sd.bars else None, "last_bar_end": sd.bars[-1].end if sd.bars else None})
        if not len(df):
            continue
        meta["bar_type_availability"][f"{inst}:{iv}"] = availability(sd.bars)
        for bt in GENES["bar_type"]:
            if bt == "time":
                continue
            rf = rep_features(sd.bars, bt)
            rf.columns = [f"{bt}:{c}" for c in rf.columns]
            df = df.join(rf, on="t")
        df = df.join(htf_frame(sd.bars), on="t")
        df["risk_d1atr"] = df.risk_bps / df.d1_atr_bps
        frames.append(df)
    if not frames:
        return pd.DataFrame(), meta
    data = pd.concat(frames, ignore_index=True).sort_values(["t", "instrument", "candidate_id"]).reset_index(drop=True)
    data = data[data.exit_at >= data.t].reset_index(drop=True)
    hi = (data.rv_pctile_480 >= 2 / 3).astype(float)
    lo = (data.rv_pctile_480 <= 1 / 3).astype(float)
    data["reg_hi"], data["reg_lo"] = hi, lo
    for s in SIGNED_X:
        data[f"{s}_x_hi"] = data[s] * hi
    data = add_macro(data, getattr(feed, "store", None), meta)
    h = hashlib.sha256(pd.util.hash_pandas_object(data[["t", "instrument", "candidate_id", "r"]], index=False).values.tobytes())
    meta["data_hash"], meta["n_rows"] = h.hexdigest(), len(data)
    return data, meta


def add_macro(data: pd.DataFrame, store, meta: dict) -> pd.DataFrame:
    """Join section-22 macro as known at each detection time (detection-bar end); all-NaN if no observations."""
    from atlas.ml.context import MACRO_FEATURES, macro_frame
    dur = data.interval.map({"15m": 900, "1h": 3600, "4h": 14400}).fillna(0).astype(int)
    end = data.t + dur
    mf = macro_frame(store, end) if store is not None else pd.DataFrame(index=pd.Index([], name="t"), columns=list(MACRO_FEATURES))
    data = data.join(mf.reindex(end.to_numpy()).reset_index(drop=True).set_axis(data.index))
    meta["macro_coverage"] = {c: float(data[c].notna().mean()) for c in MACRO_FEATURES}
    return data


def feature_list(g: dict[str, str]) -> tuple[str, ...]:
    from atlas.ml.context import HTF_FEATURES, MACRO_FEATURES
    f = list(FEATURES)
    if g["features"] == "no_setup":
        f = [c for c in f if c not in SETUP_FEATURES]
    elif g["features"] == "no_signed":
        f = [c for c in f if c not in SIGNED_X]
    elif g["features"] == "no_time":
        f = [c for c in f if c not in TIME_FEATS]
    elif g["features"] == "bar_only":
        f = [c for c in BAR_FEATURES]
    if g["regime"] == "vol_conditioned":
        f += ["reg_hi", "reg_lo"] + [f"{s}_x_hi" for s in SIGNED_X]
    if g["bar_type"] != "time":
        f += [f"{g['bar_type']}:{c}" for c in REP_FEATURES]
    ctx = g.get("context", "none")
    if ctx in ("htf", "htf_macro"):
        f += list(HTF_FEATURES)
    if ctx in ("macro", "htf_macro"):
        f += list(MACRO_FEATURES)
    return tuple(f)


def folds(data: pd.DataFrame, n_folds: int = N_FOLDS) -> list[tuple[int, np.ndarray, np.ndarray]]:
    return list(walk_forward_splits(data.t.to_numpy(np.int64), data.exit_at.to_numpy(np.int64), n_folds=n_folds, embargo=EMBARGO))


def evaluate_genome(data: pd.DataFrame, g: dict[str, str], fs: list) -> dict[str, Any]:
    from atlas.ml.train import fit_meta
    feats = feature_list(g)
    missing = [c for c in feats if c not in data.columns]
    if missing:
        return {"status": "unavailable", "reason": f"missing features {missing[:3]}"}
    if data[list(feats)].isna().all().any():
        return {"status": "unavailable", "reason": "a feature column is entirely empty (bar type unavailable for this data)"}
    ps, ys, bs, rs, takes, per_fold = [], [], [], [], [], []
    for k, tr, te in fs:
        try:
            mm = fit_meta(data, tr, g["model"], feats)
        except Exception as e:  # noqa: BLE001 - optional challenger libs missing -> genome unavailable
            return {"status": "unavailable", "reason": f"{type(e).__name__}: {e}"[:200]}
        if mm is None:
            per_fold.append({"fold": k, "skipped": "insufficient_inner_split"})
            continue
        X = data.iloc[te]
        d = mm.decide(X, use_conformal=False)
        r = X.r.to_numpy(float)
        base = float(data.y.iloc[tr].mean())
        ps.append(d["p"]); ys.append(X.y.to_numpy()); bs.append(np.full(len(te), base)); rs.append(r); takes.append(d["take"])
        per_fold.append({"fold": k, "n_test": int(len(te)), "ev": float(r[d["take"]].sum() / len(te)), "n_taken": int(d["take"].sum()),
                         "calibrator": mm.calibrator.kind})
    if not ps:
        return {"status": "insufficient", "reason": "no fold had enough data", "folds": per_fold}
    p, y, b, r, take = (np.concatenate(v) for v in (ps, ys, bs, rs, takes))
    take = take.astype(bool)
    bsc, bb = M.brier(p, y), M.brier(b, y)
    bss = 1 - bsc / bb if bb > 0 else 0.0
    ev = float(r[take].sum() / len(r))
    fev = [f["ev"] for f in per_fold if "ev" in f]
    stab = float(np.mean([e > 0 for e in fev])) if fev else 0.0
    take_all = float(r.mean())
    fitness = ev + bss + 0.1 * (stab - 0.5)
    return {"status": "ok", "n_oos": int(len(r)), "n_taken": int(take.sum()), "coverage": float(take.mean()),
            "ev_r_per_opportunity": ev, "mean_r_taken": float(r[take].mean()) if take.any() else None,
            "take_all_ev": take_all, "brier": bsc, "brier_baseline": bb, "brier_skill": bss, "ece": M.ece(p, y), "auc": M.auc(p, y),
            "stability": stab, "fitness": fitness, "beats_baseline": bool(ev > max(0.0, take_all) and bss > 0), "folds": per_fold,
            "n_features": len(feats)}


def mutate(g: dict[str, str], rng: random.Random) -> tuple[dict[str, str], str]:
    gene = rng.choice(list(GENES))
    opts = [v for v in GENES[gene] if v != g[gene]]
    v = rng.choice(opts)
    return {**g, gene: v}, f"{gene}:{g[gene]}->{v}"


def evolve(data: pd.DataFrame, meta: dict, generations: int = 3, seed: int = 11, seeds: list | None = None,
           children_per_parent: int = 2, top_k: int = 3, n_folds: int = N_FOLDS, log=print) -> dict[str, Any]:
    rng = random.Random(seed)
    fs = folds(data, n_folds)
    seen: dict[str, dict] = {}
    pop = [({**DEFAULTS, **s}, None, "seed") for s in (seeds or SEEDS)]
    for gen in range(generations):
        for g, parent, mut in pop:
            k = gid(g)
            if k in seen:
                continue
            t0 = time.time()
            m = evaluate_genome(data, g, fs)
            seen[k] = {"genome_id": k, "genome": g, "generation": gen, "parent": parent, "mutation": mut, "metrics": m,
                       "eval_seconds": round(time.time() - t0, 2)}
            log(f"gen{gen} {k} -> {m.get('status')} fitness={m.get('fitness')}")
        ranked = sorted([v for v in seen.values() if v["metrics"].get("status") == "ok"], key=lambda v: -v["metrics"]["fitness"])
        pop = []
        for par in ranked[:top_k]:
            for _ in range(children_per_parent):
                for _try in range(10):
                    child, mut = mutate(par["genome"], rng)
                    if gid(child) not in seen and gid(child) not in [gid(c) for c, _, _ in pop]:
                        pop.append((child, par["genome_id"], mut))
                        break
    board = sorted(seen.values(), key=lambda v: -(v["metrics"].get("fitness") if v["metrics"].get("status") == "ok" else -1e9))
    by_bt: dict[str, Any] = {}
    for v in board:
        bt = v["genome"]["bar_type"]
        if v["metrics"].get("status") == "ok" and bt not in by_bt:
            by_bt[bt] = {"best_genome": v["genome_id"], "fitness": v["metrics"]["fitness"], "ev": v["metrics"]["ev_r_per_opportunity"],
                         "brier_skill": v["metrics"]["brier_skill"]}
    winners = [v for v in board if v["metrics"].get("beats_baseline")]
    return {"leaderboard": board, "by_bar_type": by_bt, "best": board[0] if board else None,
            "best_beating_baseline": winners[0] if winners else None,
            "no_model_beats_baseline": not winners, "folds": [{"fold": k, "n_train": int(len(tr)), "n_test": int(len(te)),
                                                              "test_from": int(data.t.iloc[te[0]]), "test_to": int(data.t.iloc[te[-1]])} for k, tr, te in fs],
            "data": meta, "generations": generations, "seed": seed}


def evo_dir(path=None) -> Path:
    return root(path) / "evolution"


def record(result: dict[str, Any], path=None, now: int | None = None, oos: pd.DataFrame | None = None) -> dict[str, Any]:
    d = evo_dir(path)
    d.mkdir(parents=True, exist_ok=True)
    now = now or int(time.time())
    run_id = hashlib.sha256(f"{result['data'].get('data_hash')}|{result['seed']}|{result['generations']}|{now}".encode()).hexdigest()[:12]
    prev = champion(path)
    chal = result.get("best_beating_baseline")
    decision = "no_challenger_beats_baseline"
    new_champ = prev
    if chal:
        if prev is None or chal["metrics"]["fitness"] > prev["metrics"]["fitness"]:
            decision = "challenger_becomes_research_champion"
            new_champ = {**chal, "run_id": run_id, "crowned_at": now}
        else:
            decision = "champion_retained"
    run = {"run_id": run_id, "created_at": now, "code_sha": code_sha(), "execution_permission": "none",
           "promoted_to_execution": False, "decision": decision, **result}
    (d / f"run_{run_id}.json").write_text(json.dumps(_clean(run), default=str))
    with (d / "lineage.jsonl").open("a") as f:
        for v in result["leaderboard"]:
            f.write(json.dumps(_clean({"run_id": run_id, **{k: v[k] for k in ("genome_id", "generation", "parent", "mutation")},
                                       "metrics": {k: x for k, x in v["metrics"].items() if k != "folds"}}), default=str) + "\n")
    if new_champ is not prev:
        (d / "champion.json").write_text(json.dumps(_clean(new_champ), default=str))
    if oos is not None and len(oos):
        oos.to_json(d / f"oos_{run_id}.json", orient="records")
    return run


def champion(path=None) -> dict | None:
    p = evo_dir(path) / "champion.json"
    return json.loads(p.read_text()) if p.exists() else None


def latest_run(path=None) -> dict | None:
    d = evo_dir(path)
    runs = sorted(d.glob("run_*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    return json.loads(runs[-1].read_text()) if runs else None


def oos_predictions(data: pd.DataFrame, g: dict[str, str], n_folds: int = N_FOLDS) -> pd.DataFrame:
    """OOS (walk-forward) calibrated p / EV / take for one genome: the only ML numbers ever shown as chart markers."""
    from atlas.ml.train import fit_meta
    feats = feature_list(g)
    parts = []
    for k, tr, te in folds(data, n_folds):
        mm = fit_meta(data, tr, g["model"], feats)
        if mm is None:
            continue
        X = data.iloc[te]
        d = mm.decide(X, use_conformal=True)
        lo, hi = mm.conformal.qhat if hasattr(mm.conformal, "qhat") else None, None
        parts.append(pd.DataFrame({"instrument": X.instrument, "interval": X.interval, "detector": X.detector, "candidate_id": X.candidate_id,
                                   "t": X.t, "exit_at": X.exit_at, "direction": X.direction, "entry": X.entry, "stop": X.stop, "target": X.target,
                                   "outcome": X.outcome, "r": X.r, "p": d["p"], "ev_r": d["ev_r"], "take": d["take"],
                                   "conformal_qhat": lo, "fold": k, "calibrator": mm.calibrator.kind}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
