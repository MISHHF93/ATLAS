"""evo-14 training + evaluation. Pre-declared; gates are imported from the existing strict gate and only ever added to.

Per group (asset group x interval) pooled over instruments that have stored bars:
  events (CUSUM) -> vol-scaled triple-barrier labels + forward returns -> features v2 -> purged/embargoed walk-forward
  -> HGB (primary) and logit (challenger) probability of an up-move, calibrated -> adaptive conformal -> side rule
  -> net-of-cost R -> DSR / PBO and the extended gate list. Quantile regressors give a forward-return interval.
A group that fails any gate is labelled ``research / below gate``. No group is ever "eligible" here: the shadow gate
(4 forward weeks) cannot pass at training time, exactly as in the registered meta-labeller.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from atlas.ai.ml import metrics as M
from atlas.ai.ml.calibration import fit_calibrator
from atlas.ai.ml.costs import VENUE_COSTS, venue_for
from atlas.ai.ml.cv import MIN_CAL, MIN_CONF, MIN_FIT, inner_split, walk_forward_splits
from atlas.ai.ml.dataset import max_hold_bars
from atlas.ai.ml.directional import labels as L
from atlas.ai.ml.directional.aci import aci_binary
from atlas.ai.ml.directional import layers25 as LC
from atlas.ai.ml.directional.features import build_features, feature_names
from atlas.ai.ml.train import EMBARGO, GATES as META_GATES, _fit_weighted, average_uniqueness, make_model

SEED = 14
CONFIG = {"cusum_h_mult": 2.0, "barrier_k": 1.0, "sigma_span": 100, "n_folds": 5, "margin": 0.02, "alpha": 0.2, "gamma": 0.01,
          "aci_window": 500, "quantiles": (0.1, 0.5, 0.9), "min_bars": 400, "min_events": 120, "primary": "hgb_aci",
          "variants": ("hgb_ev", "hgb_aci", "logit_ev", "logit_aci")}
# Existing gates are inherited unchanged (never looser); two new ones are added.
GATE_SET = {**META_GATES, "min_aci_coverage": 0.75, "min_pinball_skill": 0.0}
REFS = {"crypto": ("BTCUSDT",), "equity": ("SPY",), "gold": ("GLD",)}
P_FLOOR = 0.02   # isotonic is a step function and emits 0/1 on small blocks; probabilities are clipped to [P_FLOOR, 1-P_FLOOR]
LABEL_BELOW = "research / below gate"
LABEL_SHADOW = "offline gates passed; shadow pending"


def group_of(symbol: str) -> str:
    from atlas.ai.ml.chart_prediction import asset_group
    return asset_group(symbol)


def horizon_for(interval: str, group: str) -> int:
    return max_hold_bars(interval, "crypto" if group == "crypto" else "equity")


def cost_bps(group: str) -> float:
    return float(VENUE_COSTS[venue_for(group)]["cost_bps"])


def series_rows(bars: Sequence, instrument: str, interval: str, group: str, refs: Mapping[str, tuple[np.ndarray, np.ndarray]] | None,
                cfg: Mapping[str, Any] = CONFIG, corr_refs: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None, events: Sequence[float] | None = None) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """(events+labels, aligned features) for one series, or None when it is too short."""
    if len(bars) < cfg["min_bars"]:
        return None
    df = pd.DataFrame({"end": [b.end for b in bars], "high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars]})
    sigma = L.ewma_sigma(df["close"].to_numpy(), cfg["sigma_span"])
    ev = L.cusum_events(df["close"].to_numpy(), sigma, cfg["cusum_h_mult"])
    lab = L.triple_barrier(df, ev, sigma, horizon_for(interval, group), cfg["barrier_k"])
    if len(lab) == 0:
        return None
    f = build_features(list(bars), interval, group, instrument, group == "crypto", refs, horizon_for(interval, group), cost_bps(group), corr_refs, events)
    lab["instrument"] = instrument
    lab["cost_r"] = cost_bps(group) / 1e4 / lab["width"]
    return lab, f.iloc[lab["i"].to_numpy()].reset_index(drop=True)


class FlooredCalibrator:
    """Calibrator whose output is clipped to [P_FLOOR, 1-P_FLOOR]."""

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, s):
        return np.clip(self.inner(s), P_FLOOR, 1 - P_FLOOR)


def _dead_to_zero(X: np.ndarray, fit: np.ndarray) -> np.ndarray:
    dead = ~np.isfinite(X[fit]).any(axis=0)
    if dead.any():
        X = X.copy()
        X[:, dead] = 0.0
    return X


def _pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def _fit_fold(X, y, fwd, t, e, train, taus):
    fit, cal, conf = inner_split(t, e, train, embargo=EMBARGO)
    if len(fit) < MIN_FIT or len(cal) < MIN_CAL or len(conf) < MIN_CONF or len(np.unique(y[fit])) < 2:
        return None
    X = _dead_to_zero(X, fit)
    sw = average_uniqueness(t[train], e[train])
    pos = {int(i): k for k, i in enumerate(train)}
    w = np.array([sw[pos[int(i)]] for i in fit])
    w = w / w.mean()
    out = {"idx": (fit, cal, conf), "X": X, "models": {}}
    for kind in ("hgb", "logit"):
        m = _fit_weighted(make_model(kind), X[fit], y[fit], w)
        c0 = fit_calibrator(m.predict_proba(X[cal])[:, 1], y[cal], fitted_through=int(e[cal].max()))
        c = FlooredCalibrator(c0)
        pc = c(m.predict_proba(X[conf])[:, 1])
        out["models"][kind] = (m, c, 1 - np.where(y[conf] == 1, pc, 1 - pc))
    out["quant"] = {tau: HistGradientBoostingRegressor(loss="quantile", quantile=tau, max_iter=120, learning_rate=0.05, max_leaf_nodes=15,
                                                       min_samples_leaf=40, l2_regularization=1.0, random_state=SEED).fit(X[fit], fwd[fit])
                    for tau in taus}
    out["base_q"] = {tau: float(np.quantile(fwd[fit], tau)) for tau in taus}
    return out


def evaluate_group(rows: pd.DataFrame, F: pd.DataFrame, cfg: Mapping[str, Any] = CONFIG) -> dict[str, Any]:
    order = np.lexsort((rows["instrument"].to_numpy(), rows["t"].to_numpy()))
    rows, F = rows.iloc[order].reset_index(drop=True), F.iloc[order].reset_index(drop=True)
    t, e = rows["t"].to_numpy(np.int64), rows["exit_at"].to_numpy(np.int64)
    y, fwd = rows["y_up"].to_numpy(int), rows["fwd_ret"].to_numpy(float)
    X = F.to_numpy(float)
    taus = tuple(cfg["quantiles"])
    parts, folds, init = [], [], {}
    for k, tr, te in walk_forward_splits(t, e, n_folds=cfg["n_folds"], embargo=EMBARGO):
        fit = _fit_fold(X, y, fwd, t, e, tr, taus)
        if fit is None:
            folds.append({"fold": int(k), "skipped": "insufficient_inner_split"})
            continue
        Xf = fit["X"]
        part = rows.iloc[te][["instrument", "t", "exit_at", "y_up", "ret", "width", "cost_r", "fwd_ret"]].copy()
        part["fold"], part["base"] = int(k), float(y[tr].mean())
        for kind, (m, c, scores) in fit["models"].items():
            part[f"p_{kind}"] = c(m.predict_proba(Xf[te])[:, 1])
            init.setdefault(kind, scores)
        for tau in taus:
            part[f"q{int(tau * 100)}"] = fit["quant"][tau].predict(Xf[te])
            part[f"bq{int(tau * 100)}"] = fit["base_q"][tau]
        parts.append(part)
        folds.append({"fold": int(k), "n_train": int(len(tr)), "n_test": int(len(te)), "test_from": int(t[te[0]]), "test_to": int(t[te[-1]])})
    if not parts:
        return {"n_rows": int(len(rows)), "n_oos": 0, "folds": folds}
    o = pd.concat(parts, ignore_index=True).sort_values(["t", "instrument"]).reset_index(drop=True)
    aci = {}
    for kind in ("hgb", "logit"):
        aci[kind] = aci_binary(o["t"].to_numpy(), o["exit_at"].to_numpy(), o[f"p_{kind}"].to_numpy(), o["y_up"].to_numpy(),
                               init_scores=init.get(kind), alpha=cfg["alpha"], gamma=cfg["gamma"], window=cfg["aci_window"])
        s = np.where(o[f"p_{kind}"] > 0.5 + cfg["margin"], 1, np.where(o[f"p_{kind}"] < 0.5 - cfg["margin"], -1, 0))
        o[f"side_{kind}_ev"] = s
        o[f"side_{kind}_aci"] = np.where((s == 1) & aci[kind]["take_up"], 1, np.where((s == -1) & aci[kind]["take_down"], -1, 0))
    r_long = (o["ret"] / o["width"]).to_numpy()
    for v in cfg["variants"]:
        o[f"R_{v}"] = o[f"side_{v}"] * r_long - np.abs(o[f"side_{v}"]) * o["cost_r"].to_numpy()
    o["R_always_long"] = r_long - o["cost_r"].to_numpy()
    return {"n_rows": int(len(rows)), "n_oos": int(len(o)), "folds": folds, "oos": o, "aci": aci}


def _prob_metrics(o: pd.DataFrame, kind: str) -> dict[str, Any]:
    p, y, b = o[f"p_{kind}"].to_numpy(), o["y_up"].to_numpy(), o["base"].to_numpy()
    bs, bb = M.brier(p, y), M.brier(b, y)
    return {"n_oos": int(len(o)), "base_rate_oos": float(y.mean()), "brier": bs, "brier_baseline": bb, "brier_skill": (1 - bs / bb) if bb > 0 else None,
            "logloss": M.logloss(p, y), "logloss_baseline": M.logloss(b, y), "ece": M.ece(p, y), "auc": M.auc(p, y)}


def _quantile_metrics(o: pd.DataFrame, taus) -> dict[str, Any]:
    y = o["fwd_ret"].to_numpy()
    lo, hi = f"q{int(min(taus) * 100)}", f"q{int(max(taus) * 100)}"
    model = float(np.mean([_pinball(y, o[f"q{int(t * 100)}"].to_numpy(), t) for t in taus]))
    base = float(np.mean([_pinball(y, o[f"bq{int(t * 100)}"].to_numpy(), t) for t in taus]))
    return {"pinball": model, "pinball_baseline": base, "pinball_skill": (1 - model / base) if base > 0 else None,
            "interval_nominal": float(max(taus) - min(taus)),
            "interval_coverage": float(((y >= o[lo].to_numpy()) & (y <= o[hi].to_numpy())).mean())}


def summarize_variant(o: pd.DataFrame, v: str) -> dict[str, Any]:
    side, R = o[f"side_{v}"].to_numpy(), o[f"R_{v}"].to_numpy()
    took = side != 0
    return {"n_taken": int(took.sum()), "coverage": float(took.mean()), "total_R_net": float(R.sum()),
            "mean_R_net_taken": float(R[took].mean()) if took.any() else None, "hit_rate_taken": float((R[took] > 0).mean()) if took.any() else None}


def evaluate_and_gate(ev: dict[str, Any], cfg: Mapping[str, Any] = CONFIG, trials: list[np.ndarray] | None = None) -> dict[str, Any]:
    out = {k: v for k, v in ev.items() if k not in ("oos", "aci")}
    if not ev.get("n_oos"):
        out["label"] = LABEL_BELOW
        out["gates"] = [{"gate": "n_oos", "passed": False, "value": 0, "threshold": f">= {GATE_SET['min_oos']}"}]
        return out
    o, aci = ev["oos"], ev["aci"]
    t0, t1 = int(o["t"].min()), int(o["t"].max())
    out["prob"] = {k: _prob_metrics(o, k) for k in ("hgb", "logit")}
    out["quantile"] = _quantile_metrics(o, cfg["quantiles"])
    out["aci"] = {k: {x: a[x] for x in ("coverage", "target_coverage", "gap", "gap_bound", "singleton_rate")} for k, a in aci.items()}
    out["variants"] = {v: summarize_variant(o, v) for v in cfg["variants"]}
    out["always_long"] = {"n": int(len(o)), "total_R_net": float(o["R_always_long"].sum())}
    out["per_instrument"] = {i: {"n_oos": int(len(g)), "brier_skill": _prob_metrics(g, "hgb")["brier_skill"], "auc": _prob_metrics(g, "hgb")["auc"],
                                 "R_net_primary": float(g[f"R_{cfg['primary']}"].sum())} for i, g in o.groupby("instrument")}
    daily = {v: M.daily_series(o["t"], o[f"R_{v}"], t0, t1) for v in cfg["variants"]}
    daily["always_long"] = M.daily_series(o["t"], o["R_always_long"], t0, t1)
    out["_daily"] = daily
    out["pbo"] = M.pbo(np.column_stack(list(daily.values())))
    out["_o"] = o
    return out


def gates(out: dict[str, Any], dsr_value: float | None, cfg: Mapping[str, Any] = CONFIG, shadow_weeks: int = 0) -> list[dict[str, Any]]:
    pm = out["prob"]["hgb"]
    q = out["quantile"]
    p = (out.get("pbo") or {}).get("pbo")
    cov = out["aci"]["hgb"]["coverage"]
    G = GATE_SET
    return [
        {"gate": "n_oos", "passed": pm["n_oos"] >= G["min_oos"], "value": pm["n_oos"], "threshold": f">= {G['min_oos']}"},
        {"gate": "brier_beats_base_rate", "passed": pm["brier_skill"] is not None and pm["brier_skill"] > 0, "value": pm["brier_skill"], "threshold": "> 0"},
        {"gate": "logloss_beats_base_rate", "passed": pm["logloss"] < pm["logloss_baseline"], "value": [pm["logloss"], pm["logloss_baseline"]], "threshold": "model < baseline"},
        {"gate": "deflated_sharpe", "passed": dsr_value is not None and dsr_value > G["min_dsr"], "value": dsr_value, "threshold": f"> {G['min_dsr']}"},
        {"gate": "pbo", "passed": p is not None and p < G["max_pbo"], "value": p, "threshold": f"< {G['max_pbo']}"},
        {"gate": "aci_coverage", "passed": cov >= G["min_aci_coverage"], "value": cov, "threshold": f">= {G['min_aci_coverage']} (target {1 - cfg['alpha']})"},
        {"gate": "quantile_beats_unconditional", "passed": q["pinball_skill"] is not None and q["pinball_skill"] > G["min_pinball_skill"], "value": q["pinball_skill"], "threshold": f"> {G['min_pinball_skill']}"},
        {"gate": "shadow_weeks", "passed": shadow_weeks >= G["min_shadow_weeks"], "value": shadow_weeks, "threshold": f">= {G['min_shadow_weeks']}"},
    ]


def label_for(gate_list: list[dict[str, Any]]) -> str:
    failed = [g["gate"] for g in gate_list if not g["passed"] and g["gate"] != "shadow_weeks"]
    return LABEL_BELOW if failed else LABEL_SHADOW


def corr_avail(bars_cache: Mapping, iv: str, load: Callable | None = None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Cross-asset proxies (DXY/UUP, GLD, BTC, SPY) available at this interval: from the training cache, else loaded if the feed has them."""
    from atlas.ai.ml.directional.layers25 import CORR_ROLES
    out = {}
    for cands in CORR_ROLES.values():
        for s in cands:
            b = bars_cache.get((s, iv))
            if b is None and load is not None:
                try:
                    b = load(s, iv)
                except Exception:
                    b = None
            if b is not None and len(b) >= 300:
                out[s] = (np.array([x.end for x in b]), np.array([x.close for x in b]))
    return out


def run(feed, universe: Sequence[tuple[str, str]], cfg: Mapping[str, Any] = CONFIG, load: Callable | None = None,
        registry_root: str | Path | None = None, fit_final: bool = True, events: Sequence[float] | None = None,
        events_note: str | None = None) -> dict[str, Any]:
    """Train every (instrument, interval) in ``universe`` that has stored bars, pooled by (group, interval)."""
    from atlas.ai.ml.dataset import load_series
    load = load or (lambda inst, iv: load_series(feed, inst, iv).bars)
    t_start = time.time()
    bars_cache: dict[tuple[str, str], list] = {}
    skipped: list[dict[str, Any]] = []
    for inst, iv in universe:
        try:
            b = load(inst, iv)
        except Exception as exc:
            skipped.append({"instrument": inst, "interval": iv, "reason": f"load_error: {type(exc).__name__}: {exc}"})
            continue
        if len(b) < cfg["min_bars"]:
            skipped.append({"instrument": inst, "interval": iv, "reason": f"only {len(b)} bars (< {cfg['min_bars']})"})
            continue
        bars_cache[(inst, iv)] = b
    by_group: dict[tuple[str, str], list[str]] = {}
    for (inst, iv) in bars_cache:
        by_group.setdefault((group_of(inst), iv), []).append(inst)
    res: dict[str, Any] = {"config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()}, "gates_inherited": META_GATES,
                           "gate_set": GATE_SET, "skipped": skipped, "groups": {}, "created_at": int(time.time()),
                           "execution_permission": "none", "note": "research only; out-of-sample, net of assumed costs; no profitability claim"}
    prepared: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]] = {}
    cov_: dict[str, Any] = {}
    res["layer_feature_coverage"] = cov_
    res["events_note"] = events_note or ("no event schedule supplied: ev_* features are NaN" if not events else f"{len(events)} scheduled events")
    res["n_features"] = len(feature_names(()))
    for (g, iv), insts in sorted(by_group.items()):
        refs = {r: (np.array([x.end for x in bars_cache[(r, iv)]]), np.array([x.close for x in bars_cache[(r, iv)]]))
                for r in REFS.get(g, ()) if (r, iv) in bars_cache}
        rs, fs = [], []
        ca = corr_avail(bars_cache, iv, load)
        for inst in sorted(insts):
            got = series_rows(bars_cache[(inst, iv)], inst, iv, g, refs, cfg, ca, events)
            if got is None:
                skipped.append({"instrument": inst, "interval": iv, "reason": "no resolved events"})
                continue
            rs.append(got[0]); fs.append(got[1])
        if not rs:
            continue
        rows = pd.concat(rs, ignore_index=True)
        F = pd.concat(fs, ignore_index=True).reindex(columns=list(feature_names(REFS.get(g, ()))))
        if len(rows) < cfg["min_events"]:
            skipped.append({"group": f"{g}-{iv}", "reason": f"only {len(rows)} events (< {cfg['min_events']})"})
            continue
        prepared[(g, iv)] = (rows, F)
        cov_[f"{g}-{iv}"] = {**LC.coverage(F), "_proxies_used": sorted(ca)}
    evals = {k: evaluate_and_gate(evaluate_group(r, F, cfg), cfg) for k, (r, F) in prepared.items()}
    trials = [d for ev in evals.values() for d in ev.get("_daily", {}).values()]
    res["n_trials"] = len(trials)
    for (g, iv), ev in evals.items():
        key = f"{g}-{iv}"
        if "_daily" in ev:
            ev["dsr"] = M.dsr(ev["_daily"][cfg["primary"]], trials)
            ev["gates"] = gates(ev, (ev["dsr"] or {}).get("dsr", 0.0), cfg)
            ev["label"] = label_for(ev["gates"])
            ev["instruments"] = sorted({i for i in prepared[(g, iv)][0]["instrument"]})
        ev.pop("_daily", None)
        ev.pop("_o", None)
        res["groups"][key] = ev
    res["elapsed_s"] = round(time.time() - t_start, 1)
    res["data_digest"] = hashlib.sha256(json.dumps({f"{k[0]}|{k[1]}": [len(v), v[0].start, v[-1].start] for k, v in sorted(bars_cache.items())}).encode()).hexdigest()[:16]
    if fit_final and registry_root is not None:
        _persist(res, prepared, cfg, Path(registry_root))
    return res


def _persist(res: dict[str, Any], prepared, cfg: Mapping[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for (g, iv), (rows, F) in prepared.items():
        key = f"{g}-{iv}"
        ev = res["groups"].get(key) or {}
        order = np.lexsort((rows["instrument"].to_numpy(), rows["t"].to_numpy()))
        rows, F = rows.iloc[order].reset_index(drop=True), F.iloc[order].reset_index(drop=True)
        t, e = rows["t"].to_numpy(np.int64), rows["exit_at"].to_numpy(np.int64)
        fit = _fit_fold(F.to_numpy(float), rows["y_up"].to_numpy(int), rows["fwd_ret"].to_numpy(float), t, e, np.arange(len(rows)), tuple(cfg["quantiles"]))
        if fit is None:
            continue
        m, _c, scores = fit["models"]["hgb"]
        bundle = {"features": list(F.columns), "hgb": m, "calibrator": _c, "quant": fit["quant"], "init_scores": scores,
                  "dead_cols": [i for i in range(F.shape[1]) if not np.isfinite(F.to_numpy(float)[fit["idx"][0]][:, i]).any()],
                  "group": g, "interval": iv, "fitted_through": int(e.max()), "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()}}
        d = root / key
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.pkl").write_bytes(pickle.dumps(bundle))
        man = {"group": key, "label": ev.get("label", LABEL_BELOW), "gates": ev.get("gates"), "prob": ev.get("prob"), "quantile": ev.get("quantile"),
               "aci": ev.get("aci"), "instruments": ev.get("instruments"), "created_at": res["created_at"], "fitted_through": int(e.max()),
               "data_digest": res["data_digest"], "execution_permission": "none"}
        (d / "manifest.json").write_text(json.dumps(man, indent=2, default=float))
