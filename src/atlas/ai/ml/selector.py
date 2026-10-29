"""Strategy selector: context (regime) labelling + per-strategy meta-label models -> ranked candidates or NO_TRADE.

Context (all causal, known at detection time):
  htf_bias  in {bullish, bearish, neutral, conflicting, insufficient}  (features/price_action/htf.py)
  vol_regime = tercile of rv_pctile_480 (low < 1/3 <= mid < 2/3 <= high)    (ml/features.py)
  session   = NY-time bucket of detection: asia [19:00,03:00), london [03:00,08:00), ny_am [08:00,12:00), ny_pm [12:00,19:00)
  interaction = the level-interaction outcome that produced the candidate (reclaim / acceptance / retest_success / legacy)
Scenario key = htf_bias|vol_regime|session.

Per enabled strategy family f a meta-labeler M_f (existing MetaModel: model -> isotonic/Platt calibrator -> conformal),
target y = after-cost R > 0, features = bar features + setup features + one-hot context. Score of a candidate:
EV_R = p*W_f - (1-p)*L_f (W/L = mean win/loss R in the fit block). At each decision time the selector keeps candidates
with EV_R > 0 (and, in the conformal variant, conformal set == {1}); among same-time candidates it keeps the max EV_R,
otherwise NO_TRADE(MODEL_ABSTAINED). Output carries execution_permission "none"; the control plane decides.
Evaluation: purged/embargoed walk-forward (ml/cv.py) vs baselines: take-all, HTF-aligned rule, best-scenario table
(per scenario pick the family with best mean train R if > 0) and always-abstain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.replay import ReplayConfig, replay, trade_cost
from atlas.ai.ml.cv import walk_forward_splits
from atlas.ai.ml.features import BAR_FEATURES, bar_features
from atlas.ai.ml.metrics import brier, ece, logloss, reliability
from atlas.ai.ml.train import EMBARGO, fit_meta

NY = ZoneInfo("America/New_York")
BIASES = ("bullish", "bearish", "neutral", "conflicting", "insufficient")
VOLS = ("low", "mid", "high")
SESSIONS = ("asia", "london", "ny_am", "ny_pm")
CTX_FEATURES = tuple(f"bias_{b}" for b in BIASES) + tuple(f"vol_{v}" for v in VOLS) + tuple(f"sess_{s}" for s in SESSIONS) + ("htf_aligned", "htf_against")
SETUP_NUM = ("dir_long", "reward_risk", "cost_r", "risk_atr", "level_priority", "level_age_h", "confluence",
             "sweep_depth_atr", "wick_frac", "box_height_atr")
SEL_FEATURES = tuple(BAR_FEATURES) + SETUP_NUM + CTX_FEATURES


def session_bucket(ts: int) -> str:
    h = datetime.fromtimestamp(ts, timezone.utc).astimezone(NY).hour
    return "london" if 3 <= h < 8 else "ny_am" if 8 <= h < 12 else "ny_pm" if 12 <= h < 19 else "asia"


def vol_regime(pctile: float) -> str:
    if not np.isfinite(pctile):
        return "mid"
    return "low" if pctile < 1 / 3 else "mid" if pctile < 2 / 3 else "high"


def context(ts: int, htf_bias: str, rv_pctile: float, direction: str) -> dict[str, Any]:
    v, s = vol_regime(rv_pctile), session_bucket(ts)
    hb = {"bullish": 1, "bearish": -1}.get(htf_bias, 0)
    d = 1 if direction == "long" else -1
    row = {f"bias_{b}": float(htf_bias == b) for b in BIASES} | {f"vol_{x}": float(v == x) for x in VOLS} \
        | {f"sess_{x}": float(s == x) for x in SESSIONS}
    row |= {"htf_aligned": float(hb == d), "htf_against": float(hb == -d), "scenario": f"{htf_bias}|{v}|{s}",
            "htf_bias": htf_bias, "vol_regime": v, "session": s}
    return row


def build_rows(instrument: str, bars: Sequence, engine_cfg: EngineConfig, rcfg: ReplayConfig, families: dict[str, str]) -> pd.DataFrame:
    """Replay (conservative_ohlc_v1) and emit one row per resolved trade of the given detectors -> family."""
    res = replay(instrument, bars[0].duration, bars, engine_cfg=engine_cfg, cfg=rcfg, data_label="atlas-feed")
    bf = bar_features(bars, None if instrument.upper().endswith(('USDT', 'USD')) else 'equity', instrument)
    feats = {c.candidate_id: c.features for c in res.candidates}
    out = []
    for t in res.trades:
        if t.detector not in families or t.outcome not in ("target", "stop", "timeout") or t.r_multiple is None:
            continue
        if t.detected_at not in bf.index:
            continue
        x, f = bf.loc[t.detected_at], feats.get(t.candidate_id, {})
        risk = abs(t.entry - t.stop)
        atr = x["atr_bps"] * t.entry / 1e4 if np.isfinite(x["atr_bps"]) else np.nan
        row = {"instrument": instrument, "detector": t.detector, "family": families[t.detector], "candidate_id": t.candidate_id,
               "t": int(t.detected_at), "exit_at": int(t.exit_at), "direction": t.direction, "outcome": t.outcome,
               "r": float(t.r_multiple), "y": int(t.r_multiple > 0), "event_id": f.get("event_id", t.candidate_id)}
        row |= {k: float(x[k]) for k in BAR_FEATURES}
        row |= {"dir_long": float(t.direction == "long"), "reward_risk": abs(t.target - t.entry) / risk if risk else np.nan,
                "cost_r": trade_cost(t, rcfg) / risk if risk else np.nan,
                "risk_atr": risk / atr if atr and np.isfinite(atr) and atr > 0 else np.nan}
        for k in SETUP_NUM[4:]:
            v = f.get(k)
            row[k] = float(v) if isinstance(v, (int, float)) else np.nan
        row |= context(t.detected_at, str(f.get("htf_bias", "insufficient")), float(x.get("rv_pctile_480", np.nan)), t.direction)
        out.append(row)
    df = pd.DataFrame(out)
    return df.sort_values(["t", "candidate_id"]).reset_index(drop=True) if len(df) else df


def _stats(r: np.ndarray) -> dict[str, Any]:
    r = np.asarray(r, float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    eq = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq)) if n else 0.0
    wins, losses = r[r > 0], r[r <= 0]
    se = float(r.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {"n": n, "mean_r": float(r.mean()), "ci95": [float(r.mean() - 1.96 * se), float(r.mean() + 1.96 * se)] if n > 1 else None,
            "win_rate": float((r > 0).mean()), "avg_win": float(wins.mean()) if len(wins) else None,
            "avg_loss": float(losses.mean()) if len(losses) else None,
            "pf": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None,
            "total_r": float(r.sum()), "max_dd_r": dd, "p05_r": float(np.quantile(r, 0.05))}


def evaluate(df: pd.DataFrame, n_folds: int = 4, kinds: tuple[str, ...] = ("logit", "hgb"), min_family_rows: int = 60) -> dict[str, Any]:
    """Purged walk-forward comparison of the selector against simple baselines. Honest: if a family lacks rows the
    fold records why and that family is only available to the baselines."""
    if df.empty:
        return {"n_rows": 0, "verdict": "no data"}
    df = df.sort_values(["t", "candidate_id"]).reset_index(drop=True)
    t, e = df.t.to_numpy(np.int64), df.exit_at.to_numpy(np.int64)
    picks: dict[str, list[pd.DataFrame]] = {k: [] for k in ("take_all", "htf_rule", "scenario_table", "abstain", *[f"sel_{k}" for k in kinds])}
    probs: dict[str, list] = {k: [] for k in kinds}
    folds = []
    for k, tr, te in walk_forward_splits(t, e, n_folds=n_folds, embargo=EMBARGO, min_train=min_family_rows):
        dtr, dte = df.iloc[tr], df.iloc[te]
        rec = {"fold": k, "n_train": len(tr), "n_test": len(te)}
        picks["take_all"].append(dte)
        picks["htf_rule"].append(dte[dte.htf_against == 0])
        tab = dtr.groupby(["scenario", "family"]).r.mean()
        best = {}
        for (sc, fam), m in tab.items():
            if m > 0 and (sc not in best or m > best[sc][1]):
                best[sc] = (fam, m)
        picks["scenario_table"].append(dte[[best.get(sc, (None,))[0] == fam for sc, fam in zip(dte.scenario, dte.family)]])
        for kind in kinds:
            sc = pd.Series(np.nan, index=dte.index)
            pp = pd.Series(np.nan, index=dte.index)
            for fam in sorted(df.family.unique()):
                trf = np.array([i for i in tr if df.family.iat[i] == fam])
                tef = dte.index[dte.family == fam]
                if len(tef) == 0:
                    continue
                if len(trf) < min_family_rows or df.y.iloc[trf].nunique() < 2:
                    rec[f"{kind}_{fam}"] = "insufficient_rows"
                    continue
                try:
                    feats = [f for f in SEL_FEATURES if df[f].iloc[trf].notna().any()]   # drop columns undefined for this family
                    mm = fit_meta(df, trf, kind, feats)
                except (ValueError, ImportError) as exc:      # degenerate fold (e.g. too few distinct values): abstain, recorded
                    rec[f"{kind}_{fam}"] = f"fit_failed: {exc}"
                    continue
                d = mm.decide(df.loc[tef], use_conformal=False)
                pp.loc[tef] = d["p"]
                sc.loc[tef] = np.where(d["take"], d["ev_r"], np.nan)
                rec[f"{kind}_{fam}_calibrator"] = mm.calibrator.kind
            probs[kind].append(pd.DataFrame({"p": pp, "y": dte.y}).dropna())
            ok = dte.assign(score=sc).dropna(subset=["score"])
            ok = ok.sort_values("score", ascending=False).drop_duplicates("t")      # one per decision time
            ok = ok.drop_duplicates("event_id")                                     # shared evidence counted once
            picks[f"sel_{kind}"].append(ok)
        folds.append(rec)
    out: dict[str, Any] = {"n_rows": len(df), "folds": folds, "families": df.family.value_counts().to_dict(), "variants": {}}
    for name, parts in picks.items():
        r = pd.concat(parts).r.to_numpy() if parts and name != "abstain" else np.array([])
        out["variants"][name] = _stats(r)
    for kind, parts in probs.items():
        p = pd.concat(parts) if parts else pd.DataFrame()
        if len(p) >= 20:
            out["variants"][f"sel_{kind}"]["calibration"] = {"n": len(p), "brier": brier(p.p, p.y), "logloss": logloss(p.p, p.y),
                                                            "ece": ece(p.p, p.y), "base_rate": float(p.y.mean()),
                                                            "brier_base": brier(np.full(len(p), p.y.mean()), p.y),
                                                            "reliability": reliability(p.p, p.y)}
    return out
