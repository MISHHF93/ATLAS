"""Governed model-evolution loop (research only; execution_permission "none"; never auto-promotes).

Population genome = {model, features, regime, bar_type, context}:
  model     logit | ridge | hgb | xgb | lgbm           (ml.train.make_model; xgb/lgbm are challengers)
  features  full | no_setup | no_signed | no_time | bar_only        (ablations of ml.dataset.FEATURES)
  regime    none | vol_conditioned | trend_conditioned | daily_trend
            vol_conditioned adds low/high rv_pctile_480 flags and their interaction with the signed features.
            trend_conditioned uses the bar-timeframe EMA trend. daily_trend uses the closed daily trend
            (close versus its 20-day mean, in ATR), the same horizon as the trend ledger.
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
metrics) are appended to the ML registry root (``<registry>/evolution/``). Champion/challenger: a genome becomes
the research champion only when ``strict_gate.passed`` is true and its fitness beats the stored strict-gate
champion. Beating the take-all baseline is not sufficient. Nothing is ever promoted to execution
(``promoted_to_execution`` is always False). A niche or island run publishes through the same ``record`` path.

evo8 strict champion gate (stricter only; applied on top of beats_baseline, see ``strict_gate``):
  * min_trades_per_fold: every one of the N_FOLDS folds must be evaluated and take >= MIN_TRADES_PER_FOLD trades;
  * majority: strictly more than half of ALL folds must have fold ev > 0 (skipped folds count as non-positive);
  * multiple testing over every genome tried in the run (n_trials = genomes with status ok):
      DSR (Bailey & Lopez de Prado) of the per-trade after-cost R of taken trades, benchmark = expected max Sharpe
      of all trials, must be >= DSR_MIN; AND the one-sided t-test p-value of mean taken R > 0 times n_trials
      (Bonferroni) must be <= BONFERRONI_ALPHA.
A genome must pass ALL checks to become research champion. A stored champion that fails is demoted (``regate``).
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
from atlas.ai.ml import metrics as M
from atlas.ai.ml.cv import walk_forward_splits
from atlas.ai.ml.dataset import BAR_FEATURES, FEATURES, SETUP_FEATURES, SIGNED, build_rows, load_series
from atlas.ai.ml.registry import _clean, code_sha, root

GENES: dict[str, tuple[str, ...]] = {
    "model": ("logit", "ridge", "hgb", "xgb", "lgbm"),
    "features": ("full", "no_setup", "no_signed", "no_time", "bar_only"),
    "regime": ("none", "vol_conditioned", "trend_conditioned", "daily_trend"),
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
    {"model": "hgb", "features": "full", "regime": "trend_conditioned", "bar_type": "time"},
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
# Compact seed set for a live research run. The full SEEDS list stays the pooled search.
LIVE_SEEDS = [
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "logit", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "ridge", "features": "full", "regime": "none", "bar_type": "time"},
    {"model": "hgb", "features": "full", "regime": "vol_conditioned", "bar_type": "time"},
    {"model": "hgb", "features": "full", "regime": "trend_conditioned", "bar_type": "time"},
    {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time", "context": "htf"},
    # Stored baseline-beater from niches_1793221168. It failed evo8. Kept in the seed list so a later run still scores it.
    {"model": "ridge", "features": "full", "regime": "none", "bar_type": "time", "context": "htf"},
    # Continues the only genome that beat its own baseline (prior-day range, ATR stops).
    # It still has to pass the evo8 strict gate on the data of this run.
    {"model": "logit", "features": "no_signed", "regime": "none", "bar_type": "time", "context": "macro"},
    # Links that genome to the closed daily trend. The bar-timeframe EMA trend does not separate R.
    {"model": "logit", "features": "no_setup", "regime": "daily_trend", "bar_type": "time", "context": "macro"},
    # Declared challengers (GENES["model"]). Same features as the stored baseline-beater so the
    # comparison is the model gene only. They stay research-only and still face evo8.
    {"model": "lgbm", "features": "full", "regime": "none", "bar_type": "time", "context": "htf"},
    {"model": "xgb", "features": "full", "regime": "none", "bar_type": "time", "context": "htf"},
]
UNIVERSE = [(i, "15m") for i in ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM")]
# Keyless official venues only. 4h is complete UTC buckets of official 1h bars.
# The 1h cost-capped book is still about -0.15R per trade, so it is not in this search.
# Equities stay out until an official provider is configured.
UNIVERSE_OFFICIAL = [(i, "4h") for i in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
OFFICIAL_VARIANT = "atr2_rr2_cf15"
# Extended pooled universe (opt-in): 1h history back to 2023/24 (lower cost per R) + 15m crypto alts.
UNIVERSE_EXTENDED = UNIVERSE + [(i, "1h") for i in ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM")]
# evo6: the only setup family with positive mean gross R (before costs) in docs/research/evo6-setup-variants.md:
# prior_day_range_reversal on 4h (crypto, derived from closed 1h bars) with ATR-scaled stops. Gross CI still spans 0.
UNIVERSE_EVO6 = [(i, "4h") for i in ("BTCUSDT", "ETHUSDT")]
EVO6_VARIANT, EVO6_DETECTORS = "atr2_rr2", ("prior_day_range_reversal",)
# evo7: PDR meta-label filter on the widened crypto universe (BTC/ETH 1h feed bars from 2024-10; alts 1h derived from
# 15m feed bars from 2026-04), 4h and 1h. Same variant/detector as evo6; see docs/research/evo7-reversal-probe.md.
EVO7_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
                "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT", "ETCUSDT", "XLMUSDT", "FILUSDT", "APTUSDT", "ARBUSDT",
                "SUIUSDT", "NEARUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "FETUSDT", "RENDERUSDT", "ALGOUSDT", "WIFUSDT")
UNIVERSE_EVO7 = [(i, "4h") for i in EVO7_SYMBOLS]
UNIVERSE_EVO7_1H = [(i, "1h") for i in EVO7_SYMBOLS]
# evo9: full 34-symbol 2-year crypto universe (2024-10..2026-10) + multi-asset 4h/1h pool with wider ATR/cost variants.
EVO9_SYMBOLS = EVO7_SYMBOLS + ("PEPEUSDT", "ICPUSDT", "HBARUSDT", "TONUSDT")
UNIVERSE_EVO9_4H = [(i, "4h") for i in EVO9_SYMBOLS]
UNIVERSE_EVO9_1H = [(i, "1h") for i in EVO9_SYMBOLS]
UNIVERSE_EVO9_MULTI = UNIVERSE_EVO9_4H + [(i, "1h") for i in ("SPY", "QQQ", "IWM")]
EVO9_VARIANT = "atr2.5_rr2_cf10"
N_FOLDS = 5
EMBARGO = 86400
MIN_TRADES_PER_FOLD = 20
DSR_MIN = 0.95
BONFERRONI_ALPHA = 0.05
GATE_VERSION = "evo8-strict-1"
TIME_FEATS = ("hod_sin", "hod_cos", "dow_sin", "dow_cos")
SIGNED_X = tuple(f"{s}_x_dir" for s in SIGNED)


def gid(g: dict[str, str]) -> str:
    return "|".join(f"{k}={g.get(k, DEFAULTS.get(k))}" for k in GENES)


def alt_bar_types(bar_types: Sequence[str] | None = None) -> tuple[str, ...]:
    """Bar types whose feature columns must be joined. ``time`` is the base frame, so it is never joined."""
    wanted = GENES["bar_type"] if bar_types is None else tuple(bar_types)
    return tuple(bt for bt in wanted if bt != "time" and bt in GENES["bar_type"])


def build_population_data(feed, universe: Sequence[tuple[str, str]] = UNIVERSE, as_of: int | None = None,
                          variant: str | None = None, detectors: Sequence[str] | None = None,
                          bar_types: Sequence[str] | None = None, log=None) -> tuple[pd.DataFrame, dict]:
    """``variant``/``detectors``: evo6 re-labelling on a research setup variant (research.setup_variants).

    ``bar_types`` limits which alternative bar features are built. ``None`` keeps every gene.
    """
    from atlas.ai.ml.context import htf_frame
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
        if log:
            log(f"series {inst} {iv} bars={len(sd.bars)} rows={len(df)}")
        if not len(df):
            continue
        meta["bar_type_availability"][f"{inst}:{iv}"] = availability(sd.bars)
        for bt in alt_bar_types(bar_types):
            rf = rep_features(sd.bars, bt)
            rf.columns = [f"{bt}:{c}" for c in rf.columns]
            df = df.join(rf, on="t")
        hf = htf_frame(sd.bars)
        if len(hf) == len(sd.bars):
            hf = hf.copy()
            hf.index = pd.Index([b.end for b in sd.bars], name="t")
        df = df.join(hf, on="t")
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
    dir_sign = np.where(data.dir_long > 0, 1.0, -1.0)
    tr_align = (data.trend_sign * dir_sign).fillna(0.0)
    tr_with = (tr_align > 0).astype(float)
    data["reg_trend_with"] = tr_with
    data["reg_trend_counter"] = (tr_align < 0).astype(float)
    for s in SIGNED_X:
        data[f"{s}_x_trend"] = data[s] * tr_with
    d1 = data["d1_trend20"] if "d1_trend20" in data.columns else pd.Series(np.nan, index=data.index)
    d1_align = pd.Series(np.sign(d1.to_numpy(float)) * dir_sign, index=data.index).replace(0, np.nan)
    d1_with = (d1_align > 0).astype(float)
    data["reg_d1_with"] = d1_with
    data["reg_d1_counter"] = (d1_align < 0).astype(float)
    for s in SIGNED_X:
        data[f"{s}_x_d1"] = data[s] * d1_with
    data = add_macro(data, getattr(feed, "store", None), meta)
    meta["data_hash"], meta["n_rows"] = data_hash(data), len(data)
    return data, meta


def data_hash(data: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(data[["t", "instrument", "candidate_id", "r"]], index=False).values.tobytes()).hexdigest()


def add_macro(data: pd.DataFrame, store, meta: dict) -> pd.DataFrame:
    """Join section-22 macro as known at each detection time (data.t is already detection-bar end); all-NaN if no observations."""
    from atlas.ai.ml.context import MACRO_FEATURES, macro_frame
    end = data.t.astype(int)
    mf = macro_frame(store, end) if store is not None else pd.DataFrame(index=pd.Index([], name="t"), columns=list(MACRO_FEATURES))
    data = data.join(mf.reindex(end.to_numpy()).reset_index(drop=True).set_axis(data.index))
    meta["macro_coverage"] = {c: float(data[c].notna().mean()) for c in MACRO_FEATURES}
    return data


def feature_list(g: dict[str, str]) -> tuple[str, ...]:
    from atlas.ai.ml.context import HTF_FEATURES, MACRO_FEATURES
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
    elif g["regime"] == "trend_conditioned":
        f += ["reg_trend_with", "reg_trend_counter"] + [f"{s}_x_trend" for s in SIGNED_X]
    elif g["regime"] == "daily_trend":
        f += ["reg_d1_with", "reg_d1_counter"] + [f"{s}_x_d1" for s in SIGNED_X]
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
    from atlas.ai.ml.train import fit_meta
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
            "n_features": len(feats), "_taken_r": r[take]}


def _t_pvalue(x: np.ndarray) -> float:
    """One-sided p-value for mean(x) > 0 (Student t)."""
    from scipy import stats
    x = np.asarray(x, float)
    if len(x) < 3 or x.std(ddof=1) == 0:
        return 1.0
    return float(stats.t.sf(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), len(x) - 1))


def _sr(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1)) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def strict_gate(m: dict[str, Any], taken_r: np.ndarray, trial_srs: list[float], n_folds: int = N_FOLDS) -> dict[str, Any]:
    """evo8 champion gate (see module doc). Returns every check with its value so a failure is explainable."""
    from atlas.ai.models.quant.metrics import deflated_sharpe
    fl = m.get("folds") or []
    ev_folds = [f for f in fl if "ev" in f]
    min_taken = min((f["n_taken"] for f in ev_folds), default=0)
    n_pos = sum(1 for f in ev_folds if f["ev"] > 0)
    n_trials = max(1, len(trial_srs))
    d = deflated_sharpe(taken_r, trial_srs) if len(taken_r) > 2 else {"dsr": 0.0, "sr_per_period": 0.0, "sr0_expected_max_per_period": None}
    pv = _t_pvalue(taken_r)
    checks = {
        "beats_baseline": bool(m.get("beats_baseline")),
        "all_folds_evaluated": len(ev_folds) == n_folds,
        "min_trades_per_fold": min_taken >= MIN_TRADES_PER_FOLD,
        "majority_folds_positive": n_pos > n_folds / 2,
        "dsr": float(d["dsr"]) >= DSR_MIN,
        "bonferroni": min(1.0, pv * n_trials) <= BONFERRONI_ALPHA,
    }
    failed = [k for k, v in checks.items() if not v]
    return {"gate_version": GATE_VERSION, "passed": not failed, "checks": checks, "failed": failed,
            "values": {"min_taken_per_fold": int(min_taken), "required_min_taken_per_fold": MIN_TRADES_PER_FOLD,
                       "positive_folds": n_pos, "n_folds": n_folds, "n_trials": n_trials, "dsr": float(d["dsr"]), "dsr_min": DSR_MIN,
                       "sr_per_trade": float(d.get("sr_per_period") or 0.0), "sr0_expected_max": d.get("sr0_expected_max_per_period"),
                       "t_pvalue": pv, "bonferroni_p": min(1.0, pv * n_trials), "bonferroni_alpha": BONFERRONI_ALPHA,
                       "n_taken_total": int(len(taken_r))}}


def apply_gate(board: list[dict], n_folds: int = N_FOLDS) -> None:
    """Attach ``strict_gate`` to every ok genome in place (n_trials = all ok genomes of the run); drops raw arrays."""
    ok = [v for v in board if v["metrics"].get("status") == "ok"]
    srs = [_sr(v["metrics"].get("_taken_r", [])) for v in ok]
    for v in ok:
        v["metrics"]["strict_gate"] = strict_gate(v["metrics"], v["metrics"].get("_taken_r", np.array([])), srs, n_folds)
    for v in board:
        v["metrics"].pop("_taken_r", None)
        if "strict_gate" not in v["metrics"]:
            v["metrics"]["strict_gate"] = {
                "gate_version": GATE_VERSION, "passed": False, "checks": {},
                "failed": [v["metrics"].get("status") or "not_ok"], "values": {},
            }


def mutate(g: dict[str, str], rng: random.Random, genes: dict[str, tuple[str, ...]] | None = None) -> tuple[dict[str, str], str]:
    """Change one gene. ``genes`` limits the search to values the built dataset can score."""
    space = genes or GENES
    g = {**DEFAULTS, **g}
    movable = [k for k in space if any(v != g.get(k) for v in space[k])]
    if not movable:
        return dict(g), "none"
    gene = rng.choice(movable)
    opts = [v for v in space[gene] if v != g.get(gene)]
    v = rng.choice(opts)
    return {**g, gene: v}, f"{gene}:{g.get(gene)}->{v}"


def evolve(data: pd.DataFrame, meta: dict, generations: int = 3, seed: int = 11, seeds: list | None = None,
           children_per_parent: int = 2, top_k: int = 3, n_folds: int = N_FOLDS, log=print,
           genes: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
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
                    child, mut = mutate(par["genome"], rng, genes)
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
    apply_gate(board, len(fs))
    winners = [v for v in board if v["metrics"].get("beats_baseline")]
    strict = [v for v in board if (v["metrics"].get("strict_gate") or {}).get("passed")]
    return {"leaderboard": board, "by_bar_type": by_bt, "best": board[0] if board else None,
            "best_beating_baseline": winners[0] if winners else None,
            "best_passing_strict_gate": strict[0] if strict else None, "gate_version": GATE_VERSION,
            "no_model_beats_baseline": not winners, "no_model_passes_strict_gate": not strict, "folds": [{"fold": k, "n_train": int(len(tr)), "n_test": int(len(te)),
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
    chal = result.get("best_passing_strict_gate")
    if not ((chal or {}).get("metrics") or {}).get("strict_gate", {}).get("passed"):
        chal = None
    decision = "no_challenger_beats_baseline" if not result.get("best_beating_baseline") else "no_challenger_passes_strict_gate"
    new_champ = prev
    if prev is not None and not (prev.get("metrics", {}).get("strict_gate") or {}).get("passed"):
        prev = None  # a champion crowned under an older/looser gate never blocks a strict-gate challenger
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


def publish_research_champion(results: list[dict], path=None) -> list[str]:
    """Crown a research champion from evolve() results that already passed the strict gate.

    Results that only beat the take-all baseline are ignored. The run file still records
    ``execution_permission: none`` and ``promoted_to_execution: false``. This does not call
    ``registry.load_eligible`` and does not submit an order.
    """
    crowned = []
    for result in results:
        chal = (result or {}).get("best_passing_strict_gate") or {}
        if not ((chal.get("metrics") or {}).get("strict_gate") or {}).get("passed"):
            continue
        run = record(result, path=path)
        if run.get("decision") == "challenger_becomes_research_champion":
            crowned.append(run["run_id"])
    return crowned


def latest_run(path=None) -> dict | None:
    d = evo_dir(path)
    runs = sorted(d.glob("run_*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    return json.loads(runs[-1].read_text()) if runs else None


_HAND_METRICS = (
    "brier", "brier_baseline", "brier_skill", "auc", "ece", "n_oos", "n_taken",
    "ev_r_per_opportunity", "take_all_ev", "mean_r_taken", "stability", "fitness", "beats_baseline",
)


def _closed_hand(**extra: Any) -> dict[str, Any]:
    hand = {
        "linked": False,
        "role": "research_hand",
        "source": None,
        "created_at": None,
        "genome_id": None,
        "stance": "abstain",
        "stance_reason": None,
        "beats_baseline": False,
        "strict_gate_passed": False,
        "strict_gate_failed": [],
        "metrics": {},
        "research_champion": False,
        "champion_genome_id": None,
        "can_buy": False,
        "can_sell": False,
        "execution_permission": "none",
        "promoted_to_execution": False,
        "may_propose_order": False,
        "orders": "none",
    }
    hand.update(extra)
    hand["can_buy"] = False
    hand["can_sell"] = False
    hand["execution_permission"] = "none"
    hand["promoted_to_execution"] = False
    hand["may_propose_order"] = False
    hand["orders"] = "none"
    return hand


def research_hand(path=None) -> dict[str, Any]:
    """Newest stored research genome as a desk hand.

    Reads niches_*.json and run_*.json. Does not write champion.json, does not call
    registry.load_eligible, and does not grant an order.
    """
    d = evo_dir(path)
    champ = champion(path)
    champ_gate = ((champ or {}).get("metrics") or {}).get("strict_gate") or {}
    champ_passed = bool(champ_gate.get("passed")) if isinstance(champ_gate, dict) else False
    if not d.exists():
        return _closed_hand(
            research_champion=champ_passed,
            champion_genome_id=(champ or {}).get("genome_id") if champ_passed else None,
        )
    candidates: list[tuple[int, float, str, dict]] = []
    for file in list(d.glob("niches_*.json")) + list(d.glob("run_*.json")):
        try:
            doc = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        created = doc.get("created_at")
        created_i = int(created) if isinstance(created, (int, float)) and not isinstance(created, bool) else 0
        candidates.append((created_i, file.stat().st_mtime, file.name, doc))
    if not candidates:
        return _closed_hand(
            research_champion=champ_passed,
            champion_genome_id=(champ or {}).get("genome_id") if champ_passed else None,
        )
    created_i, _mtime, name, doc = max(candidates, key=lambda row: (row[0], row[1], row[2]))
    genome_id = None
    metrics: dict[str, Any] = {}
    stance = "abstain"
    reason = None
    if name.startswith("niches_"):
        islands = [row for row in (doc.get("islands") or []) if isinstance(row, dict) and row.get("genome_id")]
        picked = next((row for row in islands if not row.get("no_model_beats_baseline")), None) or (islands[0] if islands else None)
        if picked:
            genome_id = picked.get("genome_id")
            metrics = dict(picked.get("metrics") or {})
        selection = doc.get("selection") if isinstance(doc.get("selection"), dict) else {}
        stance = str(selection.get("decision") or "abstain")
        reason = selection.get("reason")
    else:
        best = doc.get("best_beating_baseline") or doc.get("best") or {}
        if isinstance(best, dict):
            genome_id = best.get("genome_id")
            metrics = dict(best.get("metrics") or {})
        stance = "abstain" if doc.get("no_model_beats_baseline", True) else "research"
        reason = doc.get("decision")
    gate = metrics.get("strict_gate") if isinstance(metrics.get("strict_gate"), dict) else {}
    compact = {key: metrics.get(key) for key in _HAND_METRICS}
    return _closed_hand(
        linked=bool(genome_id),
        source=name,
        created_at=created_i or None,
        genome_id=genome_id,
        stance=stance,
        stance_reason=reason,
        beats_baseline=bool(metrics.get("beats_baseline")),
        strict_gate_passed=bool(gate.get("passed")),
        strict_gate_failed=list(gate.get("failed") or []),
        metrics=compact,
        research_champion=champ_passed,
        champion_genome_id=(champ or {}).get("genome_id") if champ_passed else None,
    )


def oos_predictions(data: pd.DataFrame, g: dict[str, str], n_folds: int = N_FOLDS) -> pd.DataFrame:
    """OOS (walk-forward) calibrated p / EV / take for one genome: the only ML numbers ever shown as chart markers."""
    from atlas.ai.ml.train import fit_meta
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


def regate(run: dict, data: pd.DataFrame, path=None, now: int | None = None, data_hash: str | None = None) -> dict[str, Any]:
    """Re-evaluate every genome of a stored run on the same rebuilt data and folds under the strict gate.
    If the stored champion came from this run and fails, it is demoted to research-only (champion.json removed,
    demotion record written). Never promotes anything."""
    if data_hash and run["data"].get("data_hash") and data_hash != run["data"]["data_hash"]:
        raise ValueError("rebuilt data hash differs from the run's data hash; refusing to re-gate on different data")
    fs = folds(data, len(run.get("folds") or []) or N_FOLDS)
    board = []
    for v in run["leaderboard"]:
        if v["metrics"].get("status") != "ok":
            continue
        m = evaluate_genome(data, v["genome"], fs)
        board.append({"genome_id": v["genome_id"], "genome": v["genome"], "metrics": m,
                      "stored_fitness": v["metrics"].get("fitness")})
    apply_gate(board, len(fs))
    d = evo_dir(path)
    champ = champion(path)
    target = (run.get("best_beating_baseline") or {}).get("genome_id")
    entry = next((b for b in board if b["genome_id"] == target), None)
    g = (entry or {}).get("metrics", {}).get("strict_gate")
    out = {"run_id": run["run_id"], "gate_version": GATE_VERSION, "regated_at": now or int(time.time()), "n_trials": len(board),
           "genome_id": target, "strict_gate": g, "reproduced_fitness": (entry or {}).get("metrics", {}).get("fitness"),
           "stored_fitness": (entry or {}).get("stored_fitness"), "any_genome_passes": any(b["metrics"]["strict_gate"]["passed"] for b in board),
           "leaderboard_gate": [{"genome_id": b["genome_id"], "passed": b["metrics"]["strict_gate"]["passed"],
                                 "failed": b["metrics"]["strict_gate"]["failed"]} for b in board],
           "execution_permission": "none", "promoted_to_execution": False}
    if champ and champ.get("run_id") == run["run_id"] and g is not None and not g["passed"]:
        out["decision"] = "champion_demoted_to_research_only"
        out["reason"] = "fails evo8 strict gate: " + ", ".join(g["failed"])
        (d / f"demoted_{run['run_id']}.json").write_text(json.dumps(_clean({**champ, "status": "research_only", "demotion": out}), default=str))
        (d / "champion.json").unlink()
    else:
        out["decision"] = "champion_retained" if g and g["passed"] else "not_champion"
    (d / f"regate_{run['run_id']}.json").write_text(json.dumps(_clean(out), default=str))
    return out
