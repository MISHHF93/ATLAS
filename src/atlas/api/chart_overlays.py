"""GET /api/ai/chart/overlays: ONE read-only payload for the harmonized ATLAS chart.

Aggregates existing research surfaces (feed bars, alt bar types, opportunity markers, evolution OOS predictions,
price-action zones, regimes, dossier conviction, ML registry) so the frontend draws everything on one chart.
Every layer reports its own status; a layer without data says so and is never filled with made-up values.
Advisory only: no orders, execution_permission none (also enforced by the AI-node guard)."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from atlas.ai.node import EXECUTION_PERMISSION, enforce_advisory

router = APIRouter(prefix="/api/ai/chart", tags=["ai"])

INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
BAR_TYPES = ("time", "heikin_ashi", "renko_atr", "range_atr", "volume", "dollar", "tick", "kagi_atr", "pnf_atr")
LAYERS = ("ml_markers", "ml_probability", "setups", "zones", "vwap", "volume_profile", "regimes", "conviction", "predictions")
EXTRA_LAYERS = ("marker_details", "forward")  # chart-2: additive


def _feed():
    from atlas.api.feeds_api import _feed as f
    return f()


def _raw(feed, sym: str, iv: str):
    try:
        return list(feed.bars(sym, iv)) if feed is not None else []
    except Exception:  # unknown instrument etc.
        return []


def _to_bars(rows, dur: int):
    from atlas.features.price_action.bars import Bar
    out, last = [], None
    for b in rows:
        if last is not None and b.event_time <= last:
            continue
        try:
            out.append(Bar(int(b.event_time), dur, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = b.event_time
    return out


def _resample(bars, dur: int, need: int | None = None):
    """Bucket bars into ``dur``. ``need``: required constituent count (drops buckets with gaps, e.g. 4 x 15m per 1h)."""
    from atlas.features.price_action.bars import Bar
    out, cur = [], None

    def _emit(c):
        if need is None or c[6] >= need:
            out.append(Bar(c[0], dur, *c[1:6]))
    for b in bars:
        k = b.start - b.start % dur
        if cur is None or cur[0] != k:
            if cur:
                _emit(cur)
            cur = [k, b.open, b.high, b.low, b.close, b.volume, 1]
        else:
            cur[2] = max(cur[2], b.high); cur[3] = min(cur[3], b.low); cur[4] = b.close; cur[5] += b.volume; cur[6] += 1
    if cur and cur[0] + dur <= int(time.time()):  # only completed buckets
        _emit(cur)
    return out


def load(sym: str, interval: str):
    """Bars + provider info. 4h is built from completed 1h (else 15m) feed bars; 1h uses stored 1h bars, else is
    resampled from complete 15m hours (4 of 4 bars). Resampled series are labelled as such in ``built``."""
    feed = _feed()
    if interval == "1h":
        rows = _raw(feed, sym, "1h")
        if rows:
            return _to_bars(rows, 3600), rows, "feed bars"
        rows = _raw(feed, sym, "15m")
        if rows:
            return _resample(_to_bars(rows, 900), 3600, need=4), rows, "resampled from 15m feed bars (complete hours only)"
        return [], [], "no 1h/15m feed bars"
    if interval == "4h":
        for src in ("1h", "15m"):
            rows = _raw(feed, sym, src)
            if rows:
                return _resample(_to_bars(rows, INTERVALS[src]), 14400), rows, f"resampled from {src} feed bars"
        return [], [], "no 1h/15m feed bars"
    rows = _raw(feed, sym, interval)
    return _to_bars(rows, INTERVALS[interval]), rows, "feed bars"


def provider_info(rows, built: str) -> dict[str, Any]:
    """Provider label from the bar's provider field. Real-time/delayed is read from the bar when the provider
    router supplies it (``realtime``/``delayed``/``delay_s``); otherwise it is reported as not tagged."""
    if not rows:
        return {"provider": None, "providers": [], "realtime": None, "delay_label": "no bars", "built": built}
    last = rows[-1]
    provs = sorted({str(getattr(r, "provider", "") or "") for r in rows[-500:]} - {""})
    rt = getattr(last, "realtime", None)
    delayed = getattr(last, "delayed", None)
    delay_s = getattr(last, "delay_s", None)
    if rt is None and delayed is not None:
        rt = not bool(delayed)
    label = ("real-time" if rt else f"delayed{f' {int(delay_s)}s' if delay_s else ''}") if rt is not None else "not tagged"
    return {"provider": getattr(last, "provider", None), "providers": provs, "realtime": rt, "delay_s": delay_s,
            "delay_label": label, "free_only": True, "built": built}


def _layer(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # each layer fails alone, honestly
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _markers(sym, interval, bars):
    from atlas.intel.data import SPEC
    from atlas.intel.markers import class_summary, from_evolution, from_replay
    from atlas.api.intel_api import _replay_all
    _, _, cpu, _, _ = SPEC.get(sym, ("crypto", 0.01, 0.0, 0.0, 96))
    win = bars[-4000:]  # bounded replay window keeps the chart responsive; markers only shown inside the view anyway
    mk = from_replay(_replay_all(sym, interval, win), INTERVALS[interval], cpu) if len(win) > 60 else []
    ml, meta = from_evolution(sym, interval)
    t0 = bars[0].start
    allm = sorted([m for m in mk + ml if m["time"] >= t0], key=lambda m: m["time"])[-800:]
    n_rule = sum(1 for m in allm if m["source"] == "candidate_engine")
    has_champ = bool((meta or {}).get("has_champion"))
    return allm, class_summary(allm, n_rule, any(m["source"] == "evolution_oos" for m in allm), has_champion=has_champ), meta


def _zones(sym, interval, bars, feed):
    from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
    from atlas.intel.fourbox import BOXES, SESSION_FOR
    from atlas.features.price_action.sessions import PRESETS
    out: list[dict[str, Any]] = []
    tail = bars[-1500:]
    sess = PRESETS.get(SESSION_FOR.get(sym, ""))
    eng = PriceActionEngine(sym, tail[0].duration, EngineConfig(session=sess))
    eng.run_batch(tail, now=tail[-1].start + tail[-1].duration)
    box_of = {b["detector"]: b["box"] for b in BOXES}
    for d in eng.detectors:
        for z in list(getattr(d, "zones", []))[-4:]:
            if z.invalidated_at:
                continue
            kind = "orb" if d.name == "orb_retest" else "fourbox" if d.name in box_of else "sr"
            out.append({"kind": kind, "label": f"{box_of.get(d.name, d.name)} {z.zone_type}".replace("_", " "),
                        "low": z.lower_bound, "high": z.upper_bound, "from": z.confirmed_at or z.formed_at, "direction": str(z.direction)})
    daily = _to_bars(_raw(feed, sym, "1d"), 86400)
    done = [b for b in daily if b.start + 86400 <= tail[-1].start + tail[-1].duration]
    if done:
        p = done[-1]
        out.append({"kind": "prior_day", "label": "Prior-day high", "low": p.high, "high": p.high, "from": p.start + 86400})
        out.append({"kind": "prior_day", "label": "Prior-day low", "low": p.low, "high": p.low, "from": p.start + 86400})
    notes = [] if sess else ["ORB needs a session preset; none for this instrument (24/7 market)"]
    return {"status": "ok", "items": out, "notes": notes}


def _vwap_profile(bars):
    pts, pv, vv, day = [], 0.0, 0.0, None
    for b in bars:
        d = b.start // 86400
        if d != day:
            pv = vv = 0.0; day = d
        tp = (b.high + b.low + b.close) / 3
        pv += tp * b.volume; vv += b.volume
        if vv > 0:
            pts.append({"time": b.start, "value": pv / vv})
    vw = {"status": "ok" if pts else "unavailable", "points": pts, "reset": "UTC day",
          **({} if pts else {"reason": "source bars carry no volume"})}
    tail = bars[-300:]
    lo, hi = min(b.low for b in tail), max(b.high for b in tail)
    n = 24
    if hi <= lo or not any(b.volume for b in tail):
        return vw, {"status": "unavailable", "reason": "no volume or flat range"}
    bins = [0.0] * n
    for b in tail:
        i = min(n - 1, int(((b.high + b.low + b.close) / 3 - lo) / (hi - lo) * n))
        bins[i] += b.volume
    step = (hi - lo) / n
    poc = max(range(n), key=lambda i: bins[i])
    rows = [{"low": lo + i * step, "high": lo + (i + 1) * step, "volume": v} for i, v in enumerate(bins)]
    return vw, {"status": "ok", "bins": rows, "poc": lo + (poc + 0.5) * step, "window_bars": len(tail),
                "method": "typical-price volume histogram over the last 300 bars"}


def _regimes(bars):
    from atlas.intel.regime import classify
    labels = classify(bars[-1500:])
    spans: list[dict[str, Any]] = []
    for x in labels:
        if x["label"] == "warmup":
            continue
        if spans and spans[-1]["trend"] == x["trend"]:
            spans[-1]["to"] = x["t"]
        else:
            spans.append({"from": x["t"], "to": x["t"], "trend": x["trend"], "label": x["label"]})
    return {"status": "ok" if spans else "unavailable", "spans": spans, "current": labels[-1]["label"] if labels else None,
            "method": "causal EMA20/50 spread in ATR units + ATR percentile"}


def _conviction(sym, interval, feed):
    from atlas.ext import dossier
    d = _to_bars(_raw(feed, sym, "1d"), 86400)
    if not d:
        return {"status": "unavailable", "reason": "no daily bars"}
    out = dossier.build_dossier(sym, d, [], None, None)
    c = out.get("conviction") or {}
    return {"status": "ok", "score": c.get("score"), "label": c.get("label"), "components": c.get("components", [])[:8],
            "trade_levels": out.get("trade_levels"), "personas": "persona scorers need EDGAR fundamentals; see Dossier page",
            "source": "atlas.ext.dossier (deterministic, technicals only here)"}


def _ml_panel(sym, interval, markers):
    from atlas.ml.evolution import champion, latest_run
    from atlas.ml.registry import list_models
    run = latest_run()
    panel: dict[str, Any] = {"execution_permission": EXECUTION_PERMISSION, "promoted_to_execution": False}
    if run:
        best = run.get("best_beating_baseline") or run.get("best") or {}
        m = best.get("metrics") or {}
        panel["evolution"] = {"run_id": run["run_id"], "created_at": run.get("created_at"), "decision": run.get("decision"),
                              "no_model_beats_baseline": run.get("no_model_beats_baseline"), "challenger": best.get("genome_id"),
                              "no_model_passes_strict_gate": run.get("no_model_passes_strict_gate"),
                              "strict_gate": {k: (m.get("strict_gate") or {}).get(k) for k in ("passed", "failed", "gate_version")} if m.get("strict_gate") else None,
                              "metrics": {k: m.get(k) for k in ("brier", "brier_baseline", "brier_skill", "auc", "ece", "n_oos", "n_taken", "ev_r_per_opportunity", "beats_baseline")}}
    else:
        panel["evolution"] = None
    panel["champion"] = champion()
    group = f"{'crypto' if sym.endswith(('USDT', 'USD')) else 'equity'}-{interval}"
    reg = [x for x in list_models() if x.get("group") == group][:1]
    if reg:
        x = reg[0]; p = (x.get("metrics") or {}).get("primary") or {}
        panel["current_model"] = {"version": x.get("version"), "status": x.get("status"), "calibrator": x.get("calibrator"),
                                  "brier": p.get("brier"), "brier_baseline": p.get("brier_baseline"), "auc": p.get("auc"), "ece": p.get("ece"),
                                  "gates": [{"gate": g.get("gate"), "passed": g.get("passed")} for g in (x.get("gates") or []) if isinstance(g, dict)]}
    else:
        panel["current_model"] = None
    panel["why"] = [{"id": m["id"], "time": m["time"], "class": m["class"], "strategy": m["strategy"], "direction": m["direction"],
                     "probability": m.get("probability_label"), "ev_r": m.get("ev_r"), "risk": m.get("risk_status"), "model": m.get("model_version")}
                    for m in markers[-12:]]
    return panel


def _enrich(markers, bars):
    from atlas.intel.marker_context import enrich, snapshots
    win = bars[-4000:]
    enrich(markers, win, snapshots(win))
    return {"status": "ok", "n": len(markers), "fields": ["indicators", "threshold", "outcome_label", "why", "setup", "resolution_path"],
            "note": "indicator values are the causal state at each marker's confirmation bar (closed bars only, no lookahead)"}


def _forward(bars, markers):
    from atlas.intel.marker_context import forward_zone, snapshots
    win = bars[-4000:]
    return forward_zone(win, snapshots(win), markers)


def _calib(preds):
    from atlas.intel.marker_context import calibration
    return calibration(preds)


@router.get("/overlays")
def chart_overlays(symbol: str = Query("BTCUSDT", min_length=1), interval: str = Query("15m"), bar_type: str = Query("time"),
                   limit: int = Query(600, ge=50, le=3000)) -> dict[str, Any]:
    if interval not in INTERVALS:
        raise HTTPException(400, "unsupported_interval")
    if bar_type not in BAR_TYPES:
        raise HTTPException(400, "unknown_bar_type")
    sym = symbol.upper().replace("-USD", "USDT") if symbol.upper().endswith("-USD") else symbol.upper()
    bars, rows, built = load(sym, interval)
    now = int(time.time())
    base: dict[str, Any] = {"symbol": sym, "interval": interval, "bar_type": bar_type, "provider": provider_info(rows, built),
                            "execution_permission": EXECUTION_PERMISSION, "orders": "none (read-only)", "computed_at": now}
    if not bars:
        return enforce_advisory({**base, "status": "no_data", "bars": [], "layers": {}, "ml_panel": None}, source="/api/ai/chart/overlays")[0]
    feed = _feed()
    view = bars[-limit:]
    t0 = view[0].start
    out_bars = [{"time": b.start, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in view]
    display: dict[str, Any] = {"status": "ok", "kind": "time"}
    if bar_type != "time":
        from atlas.features.representations import availability, build
        av = availability(bars)[bar_type]
        if av.get("available"):
            alt = [a for a in build(bar_type, bars) if a.completed_at > t0]
            display = {"status": "ok", "kind": bar_type, "bars": [{"time": a.completed_at, "start": a.start, "open": a.open, "high": a.high, "low": a.low,
                                                                   "close": a.close, "volume": a.volume} for a in alt],
                       "note": "display only; drawn when each bar completed; fills and P&L use real time bars"}
        else:
            display = {"status": "unavailable", "kind": bar_type, "reason": av.get("reason", "unavailable")}
    mk = _layer(_markers, sym, interval, bars)
    if isinstance(mk, dict):
        markers, classes, evo = [], {}, None
        mstat = mk
    else:
        markers, classes, evo = mk
        mstat = {"status": "ok"}
    markers = [m for m in markers if m["time"] >= t0]
    details = _layer(_enrich, markers, bars)
    ml = [m for m in markers if m["source"] == "evolution_oos"]
    vw, vp = _layer(_vwap_profile, view) if any(b.volume for b in view) else ({"status": "unavailable", "reason": "no volume"},) * 2
    preds = [{"time": m["time"], "p": m["probability"], "take": m["class"] == "ml_suggested", "outcome": m["outcome"], "r": m["r"],
              "hit": (None if m["outcome"] not in ("target", "stop", "timeout") else bool((m.get("r") or 0) > 0)), "id": m["id"],
              "calibrator": (m.get("probability_label") or "").split("OOS, ")[-1].rstrip(")")} for m in ml if m.get("probability") is not None]
    panel = _layer(_ml_panel, sym, interval, markers)
    em = (panel.get("evolution") or {}).get("metrics") if isinstance(panel, dict) and panel.get("evolution") else None
    layers = {
        "ml_markers": {**mstat, "items": ml, "evolution": evo, **({} if ml else {"note": "no OOS predictions for this symbol/interval in the latest evolution run"})},
        "ml_probability": {"status": "ok" if preds else "unavailable", "points": [{"time": p["time"], "value": p["p"], "take": p["take"]} for p in preds]},
        "setups": {**mstat, "items": [m for m in markers if m["source"] != "evolution_oos"], "classes": classes,
                   "categories": {"taken": "ml_suggested", "skipped_by_ml": "ml_skip", "rejected_by_risk": "risk_rejected", "rule_only": "rule_only"}},
        "zones": _layer(_zones, sym, interval, bars, feed),
        "vwap": vw, "volume_profile": vp,
        "regimes": _layer(_regimes, bars),
        "conviction": _layer(_conviction, sym, interval, feed),
        "predictions": {"status": "ok" if preds else "unavailable", "items": preds[-200:],
                        "calibration": {k: em.get(k) for k in ("brier", "brier_baseline", "ece", "auc")} if em else None,
                        "note": "out-of-sample walk-forward probabilities from the latest evolution run; research only",
                        "running_calibration": _layer(_calib, preds)},
        "marker_details": details,
        "forward": _layer(_forward, bars, markers),
    }
    return enforce_advisory({**base, "status": "ok", "bars": out_bars, "display": display, "layers": layers, "ml_panel": panel},
                            source="/api/ai/chart/overlays")[0]
