"""Score the latest closed bar with the evo-14 directional research model (read-only, execution_permission none)."""
from __future__ import annotations

import json
import math
import os
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from atlas.ai.ml.directional import labels as L
from atlas.ai.ml.directional.features import build_features
from atlas.ai.ml.directional import pipeline as P

ROOT_DEFAULT = "var/ml/directional"
TORONTO = ZoneInfo("America/Toronto")
NEUTRAL_BAND = 0.02
_CACHE: dict[str, tuple[float, Any]] = {}


def root_path(root=None) -> Path:
    return Path(root or os.environ.get("ATLAS_ML_DIRECTIONAL", ROOT_DEFAULT))


def _load(group: str, root) -> tuple[dict | None, Any]:
    d = root_path(root) / group
    man_p, mdl_p = d / "manifest.json", d / "model.pkl"
    if not man_p.exists():
        return None, None
    key = str(d)
    mt = mdl_p.stat().st_mtime if mdl_p.exists() else 0.0
    hit = _CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    man = json.loads(man_p.read_text())
    bundle = pickle.loads(mdl_p.read_bytes()) if mdl_p.exists() else None
    _CACHE[key] = (mt, (man, bundle))
    return man, bundle


def resolve_model(symbol: str, interval: str, root=None) -> tuple[dict | None, Any, str, dict | None]:
    """(manifest, bundle, model key, transfer) for the model that scores ``symbol``.

    ``transfer`` is None when the symbol was in the model's training pool. Otherwise it says how the model was borrowed:
    ``pool_member_not_trained`` (the symbol's own pool model exists but this asset was not in its training set) or
    ``cross_pool`` (its pool has no model; the nearest donor pool's model is applied). Features are asset-agnostic
    (returns, z-scores, ratios), so transfer is mechanically valid; it is not validated on this asset and is labelled so."""
    from atlas.ai.prediction.pools import TRANSFER_DONORS
    pool = P.group_of(symbol)
    key = f"{pool}-{interval}"
    man, b = _load(key, root)
    if man is not None and b is not None:
        if symbol in (man.get("instruments") or []):
            return man, b, key, None
        return man, b, key, {"kind": "pool_member_not_trained", "from": key,
                             "note": f"{symbol} was not in the training set of {key}; the pool model is applied to it unvalidated"}
    for donor in TRANSFER_DONORS.get(pool, ()):
        dk = f"{donor}-{interval}"
        man, b = _load(dk, root)
        if man is not None and b is not None:
            return man, b, dk, {"kind": "cross_pool", "from": dk,
                                "note": f"no {key} model; {symbol} is scored by the {dk} model (cross-asset transfer, unvalidated on this asset)"}
    return None, None, key, None


def _base(symbol: str, interval: str, status: str, reason: str, label: str, **kw) -> dict[str, Any]:
    return {"status": status, "reason": reason, "label": label, "symbol": symbol, "interval": interval, "execution_permission": "none",
            "orders": "none (read-only)", "computed_at": int(time.time()), "kind": "directional_research_v1", **kw}


def _news(symbol: str):
    """Point-in-time news input for the live bar, or None (NaN features) when the instrument has none. Never raises."""
    try:
        from atlas.news.features import news_input, ticker_of
        return news_input(ticker_of(symbol))
    except Exception:
        return None


def directional_prediction(symbol: str, interval: str, bars: Sequence, ref_loader: Callable[[str, str], Sequence] | None = None, root=None,
                           events: Sequence[float] | None = None, news: dict | None = None, extra: dict | None = None) -> dict[str, Any]:
    group = P.group_of(symbol)
    fam = P.family_of(group)
    man, b, key, transfer = resolve_model(symbol, interval, root)
    if man is None or b is None:
        return _base(symbol, interval, "no_model", f"No directional research model for {key}. Run scripts/ml_directional.py --run.", "no directional model for this scope")
    label = man.get("label") or P.LABEL_BELOW
    if transfer:
        label = f"{label} · transfer from {transfer['from']}"
    if len(bars) < 300:
        return _base(symbol, interval, "insufficient_history", f"{len(bars)} closed bars; at least 300 needed.", label)
    bars = list(bars)[-1500:]
    refs = {}
    for r in P.REFS.get(key.rpartition("-")[0], ()):
        if r != symbol and ref_loader is not None:
            try:
                rb = list(ref_loader(r, interval))
                if rb:
                    refs[r] = (np.array([x.end for x in rb]), np.array([x.close for x in rb]))
            except Exception:
                pass
    from atlas.ai.ml.directional.layers25 import CORR_ROLES
    corr = {}
    for cands in CORR_ROLES.values():
        for r in cands:
            if r != symbol and r != "USD_PROXY" and ref_loader is not None:
                try:
                    rb = list(ref_loader(r, interval))
                    if len(rb) >= 300:
                        corr[r] = (np.array([x.end for x in rb]), np.array([x.close for x in rb]))
                except Exception:
                    pass
    if ref_loader is not None:
        from atlas.ai.ml.directional import context27 as C27
        px = C27.usd_proxy_series(lambda s: ref_loader(s, interval))
        if px is not None:
            corr[C27.USD_PROXY] = px
    f = build_features(bars, interval, fam, symbol, group == "crypto", refs, P.horizon_for(interval, group), P.cost_bps(group), corr, events, news if news is not None else _news(symbol), extra).reindex(columns=b["features"])
    x = f.iloc[[-1]].to_numpy(float)
    for i in b.get("dead_cols") or []:
        x[:, i] = 0.0
    p = float(b["calibrator"](b["hgb"].predict_proba(x)[:, 1])[0])
    m = P.CONFIG["margin"]
    direction = "up" if p > 0.5 + m else ("down" if p < 0.5 - m else "neutral")
    scores = np.sort(np.asarray(b["init_scores"], float))
    n = len(scores)
    alpha = float(b["config"]["alpha"])
    k = math.ceil((n + 1) * (1 - alpha))
    qhat = float(scores[min(k, n) - 1]) if n else 1.0
    pset = [lab for lab, pl in ((0, 1 - p), (1, p)) if 1 - pl <= qhat] if n else [0, 1]
    last = bars[-1]
    close = np.array([x_.close for x_ in bars])
    sig = float(L.ewma_sigma(close, b["config"]["sigma_span"])[-1])
    H = P.horizon_for(interval, group)
    qs = {tau: float(mdl.predict(x)[0]) for tau, mdl in b["quant"].items()}
    scale = sig * math.sqrt(H)
    band = {f"p{int(t * 100)}": float(last.close * math.exp(q * scale)) for t, q in qs.items()}
    end = int(last.start + last.duration)
    return _base(
        symbol, interval, "ok", "Calibrated P(up-move first) from the evo-14 research model on the latest closed bar; research display only.", label,
        direction=direction, probability=round(p, 4), conformal_set=sorted(pset), conformal_alpha=alpha,
        conformal_note="split-conformal set from the held-out block at the last retrain (not the adaptive stream used in validation)",
        take=bool(direction != "neutral" and ((direction == "up" and pset == [1]) or (direction == "down" and pset == [0]))),
        horizon_bars=H, band=band, band_nominal=P.CONFIG["quantiles"][-1] - P.CONFIG["quantiles"][0],
        as_of_bar=int(last.start), as_of_end=end, as_of_toronto=datetime.fromtimestamp(end, TORONTO).strftime("%Y-%m-%d %H:%M %Z"),
        gates=[{"gate": g["gate"], "passed": g["passed"]} for g in (man.get("gates") or [])],
        metrics={"n_oos": (man.get("prob") or {}).get("hgb", {}).get("n_oos"), "brier": (man.get("prob") or {}).get("hgb", {}).get("brier"),
                 "brier_baseline": (man.get("prob") or {}).get("hgb", {}).get("brier_baseline"), "auc": (man.get("prob") or {}).get("hgb", {}).get("auc")},
        trained_at=man.get("created_at"), pool=man.get("instruments"), model_group=key, transfer=transfer,
        meaning="P(price reaches the upper volatility barrier before the lower one within the horizon); not a price target and not a profit claim",
    )
