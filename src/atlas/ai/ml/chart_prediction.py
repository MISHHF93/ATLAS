"""Live model prediction for the chart: latest closed bars -> features (incl. VWAP) -> registered model -> probability.

Differs from ``live_intelligence.generate_live_prediction`` in two deliberate ways, both for research display only:

* A model whose gates did NOT all pass is still scored, and the result is labelled ``research / below gate`` with the
  failed gates attached. It is never promoted and never presented as validated. If no registered model covers the
  exact (instrument, asset class, interval) scope the result is ``no_model`` with a reason; nothing is invented.
* It works on the bars the chart already shows (including lower-timeframe extension) so the prediction is recomputed
  on every new bar on every timeframe, and it is not suppressed when the market is closed (it scores the last
  closed bar and says so via ``as_of_end``).

Probability meaning: calibrated P(target hit before stop) for a default setup in the stated direction (reward:risk 2,
stop 1.5 ATR, heuristic detector) -- both directions are scored and the more probable side is the "direction".
It is not a price forecast and not a trade signal. ``execution_permission`` is always ``none``.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml.costs import VENUE_COSTS, venue_for
from atlas.ai.ml.dataset import DETECTORS, SIGNED
from atlas.ai.ml.features import BAR_FEATURES, bar_features
from atlas.ai.ml.registry import list_models, load_model
from atlas.ai.ml.vwap_features import GOLD_INSTRUMENTS

TORONTO = ZoneInfo("America/Toronto")
NEUTRAL_BAND = 0.02
_CACHE: dict[tuple[str, str], Any] = {}


def asset_group(symbol: str) -> str:
    s = symbol.upper()
    if s in GOLD_INSTRUMENTS:
        return "gold"
    return "crypto" if s.endswith(("USDT", "USD")) and s not in {"EURUSD"} else "equity"


def _gate_summary(man: dict[str, Any]) -> tuple[bool, list[str]]:
    gates = [g for g in (man.get("gates") or []) if isinstance(g, dict)]
    failed = [str(g.get("gate")) for g in gates if g.get("passed") is not True]
    return bool(gates) and not failed and man.get("status") == "eligible", failed


def select_manifest(group: str, instrument: str, reg_path=None) -> tuple[dict[str, Any] | None, str]:
    """Best covering manifest: any all-gates-passed version first, else the newest below-gate one."""
    ac, _, iv = group.rpartition("-")
    cover = []
    for m in list_models(reg_path):
        if m.get("group") != group:
            continue
        if any(isinstance(s, dict) and s.get("instrument") == instrument and s.get("asset_class") == ac and s.get("interval") == iv
               for s in (m.get("series") or [])):
            cover.append(m)
    passed = [m for m in cover if _gate_summary(m)[0]]
    if passed:
        return passed[0], "gate_passed"
    return (cover[0], "research_below_gate") if cover else (None, "no_model")


def _model(version: str, reg_path):
    key = (str(reg_path), version)
    if key not in _CACHE:
        _CACHE[key] = load_model(version, reg_path)
    return _CACHE[key]


def _features_row(last: pd.Series, detector: str, d: float, ac: str) -> dict[str, Any]:
    atr_bps = max(float(last.get("atr_bps", 85.0) or 85.0), 30.0)
    risk_bps = max(atr_bps * 1.5, 45.0)
    cost_bps = min(float(VENUE_COSTS[venue_for(ac)].get("cost_bps", 4.0)), 12.0)
    row: dict[str, Any] = {"detector": detector}
    for k in BAR_FEATURES:                      # NaN stays NaN: HistGradientBoosting treats it natively, as in training rows
        v = float(last.get(k, np.nan))
        row[k] = v if math.isfinite(v) else float("nan")
    row |= {"dir_long": 1.0 if d > 0 else 0.0, "reward_risk": 2.0, "cost_r": round(min(0.25, cost_bps / risk_bps), 4),
            "risk_atr": 1.5, "entry_is_stop": 0.0}
    row |= {f"det_{x}": 1.0 if x == detector else 0.0 for x in DETECTORS}
    row |= {f"{s}_x_dir": (row[s] * d if math.isfinite(row[s]) else float("nan")) for s in SIGNED}
    return row


def _base(symbol: str, interval: str, status: str, gate_status: str, reason: str, **kw: Any) -> dict[str, Any]:
    return {"status": status, "gate_status": gate_status, "reason": reason, "symbol": symbol, "interval": interval,
            "label": {"gate_passed": "model gate passed", "research_below_gate": "research / below gate",
                      "no_model": "no model for this scope"}[gate_status],
            "execution_permission": "none", "orders": "none (read-only)",
            "computed_at": int(time.time()), "computed_at_toronto": datetime.now(TORONTO).strftime("%Y-%m-%d %H:%M:%S %Z"), **kw}


def model_prediction(symbol: str, interval: str, bars: Sequence, *, reg_path=None) -> dict[str, Any]:
    """Score the latest closed bar. ``bars`` are closed ``Bar`` objects, oldest first."""
    ac = asset_group(symbol)
    group = f"{ac}-{interval}"
    man, gate_status = select_manifest(group, symbol, reg_path)
    if man is None:
        return _base(symbol, interval, "no_model", "no_model",
                     f"No registered model was trained on {symbol} {interval} ({group}). Train one with scripts/ml_refresh.py.")
    if len(bars) < 60:
        return _base(symbol, interval, "insufficient_history", gate_status, f"{len(bars)} closed bars; 60 needed for feature warm-up.",
                     model={"version": man.get("version")})
    mdl = _model(str(man["version"]), reg_path)
    if mdl is None:
        return _base(symbol, interval, "model_unavailable", gate_status, f"Model binary missing for {man.get('version')}.",
                     model={"version": man.get("version")})
    bf = bar_features(list(bars)[-600:], ac, symbol)
    last = bf.iloc[-1]
    feats = tuple(getattr(mdl, "features", ()))
    ret_4 = float(last.get("ret_4", 0.0) or 0.0) if math.isfinite(float(last.get("ret_4", np.nan))) else 0.0
    ema = float(last.get("ema20_dist_atr", 0.0)) if math.isfinite(float(last.get("ema20_dist_atr", np.nan))) else 0.0
    detector = "orb_retest" if abs(ema) > 0.6 else ("wick_reversal" if abs(ret_4) > 0.004 else "dual_band_breakout")
    p, take, ev = {}, {}, {}
    for name, d in (("long", 1.0), ("short", -1.0)):
        X = pd.DataFrame([_features_row(last, detector, d, ac)])
        dec = mdl.decide(X, use_conformal=True)
        p[name], take[name], ev[name] = float(np.clip(dec["p"][0], 1e-4, 1 - 1e-4)), bool(dec["take"][0]), float(dec["ev_r"][0])
    if abs(p["long"] - p["short"]) < NEUTRAL_BAND:
        direction = "neutral"
        side = "long" if p["long"] >= p["short"] else "short"
    else:
        side = "long" if p["long"] > p["short"] else "short"
        direction = "up" if side == "long" else "down"
    passed, failed = _gate_summary(man)
    prim = (man.get("metrics") or {}).get("primary") or {}
    last_bar = bars[-1]
    as_of_end = int(last_bar.start + last_bar.duration)
    return _base(
        symbol, interval, "ok", gate_status,
        "Calibrated P(target before stop) from the registered meta-model on the latest closed bar."
        + ("" if passed else " Not every validation gate passed: research display only."),
        direction=direction, side=side, probability=round(p[side], 4), p_long=round(p["long"], 4), p_short=round(p["short"], 4),
        conformal_take=take[side], ev_r=round(ev[side], 4), setup=detector, uncertainty=man.get("qhat"),
        as_of_bar=int(last_bar.start), as_of_end=as_of_end,
        as_of_toronto=datetime.fromtimestamp(as_of_end, TORONTO).strftime("%Y-%m-%d %H:%M %Z"),
        model={"id": f"atlas-meta:{group}", "version": man.get("version"), "group": group, "calibrator": man.get("calibrator"),
               "created_at": man.get("created_at"), "n_features": len(feats), "uses_vwap": any(f.startswith("vwap_") for f in feats),
               "gates_failed": failed, "gates_total": len(man.get("gates") or []), "status": man.get("status"),
               "metrics": {k: prim.get(k) for k in ("brier", "brier_baseline", "auc", "ece", "n_oos")}},
        meaning="P(target before stop) for a default setup (reward:risk 2) in the stated direction; not a price forecast",
    )
