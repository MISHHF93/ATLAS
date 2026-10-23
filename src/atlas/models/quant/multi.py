"""Multi-model weekly retrain + routing stage. One registry per model kind under a root dir:
  <root>/scorer_core_etf, scorer_active_equity, scorer_crypto, regime, vol, cost, anomaly.
Every retrain registers a CHALLENGER (never champion) with a model card and a drift reference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.models.quant.registry import ModelRegistry
from atlas.models.quant.sleeves import POLICY_TO_SCORER, SLEEVES, card_for, train_sleeve


def registry_for(root: str | Path, kind: str, audit=None):
    from atlas.models.quant import zoo
    return ModelRegistry(Path(root) / kind, audit=audit, model_cls=zoo.MODEL_CLASSES[kind], kind=kind)


def _hash(bars: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(bars):
        h.update(k.encode()); h.update(pd.util.hash_pandas_object(bars[k], index=True).values.tobytes())
    return h.hexdigest()


def _trials(reg) -> list:
    """Full trial history for DSR: legacy trials.json + append-only trials.jsonl (TrialLog)."""
    from atlas.models.quant.validation import TrialLog
    p = reg.root / "trials.json"
    legacy = json.loads(p.read_text()) if p.exists() else []
    return legacy + TrialLog(reg.root / "trials.jsonl").srs()


def retrain_scorers(bars_by_sleeve: dict[str, dict[str, pd.DataFrame]], root, audit=None, n_splits: int = 4) -> dict:
    out = {}
    for sleeve, bars in bars_by_sleeve.items():
        reg = registry_for(root, f"scorer_{sleeve}", audit)
        from atlas.models.quant.stack2 import all_trial_srs
        trials = all_trial_srs(root)      # deflate by EVERY trial in the models root, not just this kind
        scorer, rep, X = train_sleeve(sleeve, bars, n_splits=n_splits, prior_trials=trials)
        from atlas.models.quant.validation import TrialLog
        TrialLog(reg.root / "trials.jsonl").append(f"scorer_{sleeve}", {"n_splits": n_splits, **SLEEVES[sleeve]}, rep["trial_sr"], rep["n_oos"])
        mid = reg.register(scorer, rep, _hash(bars), card=card_for(sleeve), reference=X.sample(min(2000, len(X)), random_state=0))
        reg.make_challenger(mid)
        out[sleeve] = {"model_id": mid, "oos": rep["oos"], "dsr": rep["deflated_sharpe"]["dsr"]}
    return out


class MultiSleeveStage:
    """Routes each candidate to its sleeve's CHAMPION scorer. No champion / error => policy fallback
    (rules-only half size, or halt). Output is a subset with qty <= input."""

    def __init__(self, root, cfg, audit=None, scorers: dict | None = None):
        self.cfg, self.audit = cfg, audit
        self.scorers = scorers if scorers is not None else {}
        if scorers is None:
            for s in SLEEVES:
                reg = registry_for(root, f"scorer_{s}")
                if reg.champion:
                    self.scorers[s] = reg.load(reg.champion)

    def apply(self, candidates):
        out = []
        for intent, X in candidates:
            sk = POLICY_TO_SCORER.get(intent.sleeve)
            sc = self.scorers.get(sk)
            try:
                if sc is None:
                    raise RuntimeError(f"no champion scorer for sleeve {intent.sleeve}")
                p = float(sc.p_hit(X)[0])
                if not np.isfinite(p):
                    raise ValueError("non-finite score")
            except Exception as e:  # noqa: BLE001
                if self.audit:
                    self.audit.append("ml.fallback", {"sleeve": intent.sleeve, "error": str(e)})
                if self.cfg.fallback != "halt":
                    out.append({"intent": intent.model_copy(update={"qty": intent.qty * 0.5}), "p_hit": None, "shap_top": [],
                                "fallback": "rules_only_half_size", "scorer": sk})
                continue
            thr = max(self.cfg.min_p_hit, SLEEVES[sk]["min_p_hit"])
            if p >= thr:
                out.append({"intent": intent, "p_hit": p, "shap_top": sc.explain(X)[0], "fallback": None, "scorer": sk})
        return sorted(out, key=lambda r: -(r["p_hit"] or 0))


def retrain_regime(index_close: pd.Series, root, universe: pd.DataFrame | None = None, audit=None) -> dict:
    from atlas.models.quant.regime import RegimeModel, regime_card, regime_features
    F = regime_features(index_close, universe)
    m = RegimeModel.fit(F)
    mult = m.risk_multiplier(F)
    rep = {"n": int(len(F)), "backend": m.backend, "mean_mult": float(mult.mean()), "min_mult": float(mult.min()),
           "state_share": m.filtered_proba(F).idxmax(axis=1).value_counts(normalize=True).round(3).to_dict(),
           "feature_importance_stability_spearman": 1.0}
    reg = registry_for(root, "regime", audit)
    mid = reg.register(m, rep, _hash({"idx": index_close.to_frame()}), card=regime_card(), reference=F)
    reg.make_challenger(mid)
    return {"model_id": mid, **rep}


def retrain_vol(returns: pd.Series, root, audit=None) -> dict:
    """One pooled vol model (fit on the index); its HAR/GARCH parameters are applied per instrument."""
    from atlas.models.quant.vol import VolModel, vol_card
    m = VolModel.select(returns)
    rep = dict(m.report) | {"feature_importance_stability_spearman": 1.0}
    reg = registry_for(root, "vol", audit)
    rv = (returns ** 2).to_frame("rv")
    mid = reg.register(m, rep, _hash({"r": returns.to_frame()}), card=vol_card(), reference=rv)
    reg.make_challenger(mid)
    return {"model_id": mid, **rep}


def retrain_cost(fills: pd.DataFrame, root, audit=None) -> dict:
    from atlas.models.quant.costmodel import COLS, CostModel, cost_card
    m = CostModel.fit(fills)
    reg = registry_for(root, "cost", audit)
    mid = reg.register(m, m.report, _hash({"f": fills}), card=cost_card(), reference=fills[COLS])
    reg.make_challenger(mid)
    return {"model_id": mid, **m.report}


def retrain_anomaly(X: pd.DataFrame, root, audit=None) -> dict:
    from atlas.models.quant.anomaly_ml import ANOMALY_FEATURES, AnomalyModel, anomaly_card
    m = AnomalyModel.fit(X)
    reg = registry_for(root, "anomaly", audit)
    mid = reg.register(m, m.report, _hash({"x": X}), card=anomaly_card(), reference=X[ANOMALY_FEATURES])
    reg.make_challenger(mid)
    return {"model_id": mid, **m.report}


def _reg_new(root, kind, model, rep, data, audit, reference=None):
    from atlas.models.quant.stack2 import card
    reg = registry_for(root, kind, audit)
    mid = reg.register(model, rep, _hash(data), card=card(kind), reference=reference)
    reg.make_challenger(mid)
    return {"model_id": mid, "dsr": (rep.get("validation") or {}).get("dsr"), "n_trials": (rep.get("validation") or {}).get("n_trials")}


def retrain_meta(bars: dict, root, audit=None, vol_model=None, news_veto=None) -> dict:
    from atlas.models.quant.meta import META_FEATURES
    from atlas.models.quant.stack2 import train_meta_with_grid
    m, rep, ds = train_meta_with_grid(bars, root, vol_model=vol_model, news_veto=news_veto)
    return _reg_new(root, "meta_label", m, rep, bars, audit, reference=ds[META_FEATURES].tail(2000)) | {"pt": rep["pt"], "sl": rep["sl"]}


def retrain_factor(close: pd.DataFrame, root, sectors=None, audit=None) -> dict:
    from atlas.models.quant.stack2 import train_factor_sleeve
    m, rep = train_factor_sleeve(close, root, sectors)
    return _reg_new(root, "factor_sleeve", m, rep, {"close": close}, audit) | {"weights": rep["weights"]}


def retrain_portfolio(returns: pd.DataFrame, root, audit=None) -> dict:
    from atlas.models.quant.stack2 import train_portfolio
    m, rep = train_portfolio(returns, root)
    return _reg_new(root, "portfolio", m, rep, {"r": returns}, audit) | {"chosen": rep["chosen"]}


def retrain_conformal(bars: dict, root, audit=None, pt=1.0, sl=1.0) -> dict:
    from atlas.models.quant.meta import META_FEATURES, meta_dataset, momentum_primary
    from atlas.models.quant.stack2 import train_conformal
    ds = meta_dataset(bars, momentum_primary, pt, sl)
    m, rep = train_conformal(ds, root, META_FEATURES)
    return _reg_new(root, "conformal", m, rep, bars, audit, reference=ds[META_FEATURES].tail(2000)) | {"confidence": rep["chosen_confidence"]}


def retrain_execution(fills, root, audit=None) -> dict:
    from atlas.models.quant.stack2 import calibrate_execution
    m, rep = calibrate_execution(fills, root)
    return _reg_new(root, "execution", m, rep, {"f": fills if fills is not None else pd.DataFrame({"x": [0]})}, audit)


KINDS = ["scorer_core_etf", "scorer_active_equity", "scorer_crypto", "regime", "vol", "cost", "anomaly",
         "meta_label", "factor_sleeve", "portfolio", "conformal", "execution"]


def models_overview(root) -> list[dict]:
    """Dashboard/MCP read-only view of every model kind: champion, challenger, last retrain, last drift, card."""
    from pathlib import Path
    out = []
    for k in KINDS:
        d = Path(root) / k
        if not (d / "index.json").exists():
            out.append({"kind": k, "status": "not trained", "champion": None, "challenger": None, "last_retrain": None, "drift": None})
            continue
        reg = registry_for(root, k)
        s = reg.summary()
        ld = s["last_drift"] or {}
        ch = s["challenger"]
        weeks = len(reg.idx["models"][ch]["shadow"]) if ch else 0
        out.append({"kind": k, "status": "champion" if s["champion"] else ("shadow" if ch else "no model"),
                    "champion": s["champion"], "challenger": ch, "shadow_weeks": weeks, "n_models": s["n_models"],
                    "last_retrain": s["last_retrain"], "drift": ld.get("status") or ("demoted" if ld.get("event") == "demote" else None),
                    "max_psi": ld.get("max_psi"),
                    "card": f"{k}/{s['champion'] or ch}/model_card.md" if (s["champion"] or ch) else None})
    return out


def weekly_retrain_all(root, bars_by_sleeve: dict, index_close, fills=None, ops_features=None, audit=None) -> dict:
    out = {"scorers": retrain_scorers(bars_by_sleeve, root, audit)}
    import numpy as np
    out["regime"] = retrain_regime(index_close, root, audit=audit)
    out["vol"] = retrain_vol(np.log(index_close).diff().dropna(), root, audit=audit)
    if fills is not None and len(fills) >= 200:
        out["cost"] = retrain_cost(fills, root, audit)
    if ops_features is not None and len(ops_features) >= 200:
        out["anomaly"] = retrain_anomaly(ops_features, root, audit)
    # second wave: meta-labeler (barrier grid), factor sleeve, allocator, conformal sizer, execution params
    all_bars = {s: b for bs in bars_by_sleeve.values() for s, b in bs.items()}
    try:
        out["meta_label"] = retrain_meta(all_bars, root, audit)
        out["conformal"] = retrain_conformal(all_bars, root, audit, out["meta_label"]["pt"], out["meta_label"]["sl"])
    except ValueError as e:
        out["meta_label"] = {"skipped": str(e)}
    close = pd.DataFrame({s: b["close"] for s, b in all_bars.items()}).dropna()
    eq = bars_by_sleeve.get("active_equity") or {}
    if len(eq) >= 3:
        out["factor_sleeve"] = retrain_factor(close[list(eq)], root, audit=audit)
    if close.shape[1] >= 2:
        out["portfolio"] = retrain_portfolio(close.pct_change().dropna(), root, audit)
    exec_fills = fills if fills is not None and {"participation", "daily_vol_bps", "half_spread_bps", "realized_bps"} <= set(fills.columns) else None
    out["execution"] = retrain_execution(exec_fills, root, audit)
    return out
