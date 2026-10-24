"""/api/intel/*: research lab, regimes, portfolio risk, track rules, grounded assistant, memory/attribution/governance,
microstructure tiers, Four-Box and contract holidays. Read-only research surfaces (execution_permission none) except
POST /lab/run, which only appends an experiment record under var/lab. Every payload carries a freshness label."""
from __future__ import annotations

import time
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from atlas.api.feeds_api import _feed
from atlas.intel import EXECUTION_PERMISSION
from atlas.intel.data import SPEC, TF_SECONDS, freshness_for, load_bars

router = APIRouter()
_CACHE: dict[tuple, Any] = {}


def _bars(sym: str, tf: str):
    if tf not in TF_SECONDS:
        raise HTTPException(status_code=400, detail="unsupported_timeframe")
    return load_bars(_feed(), sym.upper(), tf)


def _daily(sym: str):
    f = _feed()
    return tuple((int(b.event_time), b.high, b.low, b.close) for b in f.bars(sym, "1d")) if f is not None else ()


def _replay_all(sym: str, tf: str, bars):
    """One replay with the default engine + every suite toggle on (cached per last bar)."""
    key = ("replay", sym, tf, bars[-1].start if bars else None, len(bars))
    if key in _CACHE:
        return _CACHE[key]
    from atlas.features.price_action.replay import ReplayConfig, replay
    from atlas.intel.lab import _variant_engine
    _, _, cpu, cbps, hold = SPEC.get(sym, ("crypto", 0.01, 0.0, 0.0, 96))
    res = replay(sym, bars[0].duration, bars, engine_cfg=_variant_engine(sym, bars, {"sfp": True, "gold_snapback": True, "gold_orb_breakout": True}, _daily(sym)),
                 cfg=ReplayConfig(entry_window=3, max_hold_bars=hold, cost_per_unit=cpu, cost_bps=cbps), data_label="real:atlas_feed")
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = res
    return res


def _wrap(bars, body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "freshness": freshness_for(bars), "execution_permission": EXECUTION_PERMISSION}


# ---- research lab ----
@router.get("/lab/runs")
def lab_runs(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    from atlas.intel.lab import list_runs
    runs = list_runs(limit)
    slim = [{k: r.get(k) for k in ("report_id", "name", "instrument", "timeframe_s", "bars", "created_at", "code_sha", "seed",
                                    "deflated_sharpe", "pbo", "pbo_note", "last_bar_end")} | {"variants": r.get("variants")} for r in runs]
    newest = max((r.get("last_bar_end") or 0 for r in slim), default=0) or None
    now = int(time.time())
    fresh = {"label": "historical" if slim else "unavailable", "last_bar_end": newest, "age_s": (now - newest) if newest else None,
             "source": "recorded lab experiments (fixed data snapshot per run)", "computed_at": now}
    return {"runs": slim, "n": len(slim), "freshness": fresh, "execution_permission": EXECUTION_PERMISSION}


@router.post("/lab/run")
def lab_run(symbol: str = Query("GC"), tf: str = Query("15m"), seed: int = Query(7)) -> dict[str, Any]:
    from atlas.intel.lab import run_experiment
    sym = symbol.upper()
    bars = _bars(sym, tf)
    if not bars:
        return _wrap(bars, {"status": "no_data", "instrument": sym})
    return _wrap(bars, run_experiment(sym, bars, daily=_daily(sym), seed=seed))


# ---- regimes ----
@router.get("/regimes")
def regimes(symbol: str = Query("GC"), tf: str = Query("15m")) -> dict[str, Any]:
    from atlas.intel.regime import classify, distribution, strategy_by_regime
    sym = symbol.upper(); bars = _bars(sym, tf)
    if not bars:
        return _wrap(bars, {"status": "no_data", "instrument": sym})
    labels = classify(bars)
    res = _replay_all(sym, tf, bars)
    return _wrap(bars, {"status": "ok", "instrument": sym, "timeframe": tf, "current": labels[-1], "distribution": distribution(labels),
                        "recent": labels[-40:], "by_strategy": strategy_by_regime(res.trades, labels),
                        "method": "causal rule-based: EMA20/50 spread in ATR units + ATR(14) percentile over 200 bars"})


# ---- portfolio ----
@router.get("/portfolio")
def portfolio() -> dict[str, Any]:
    from atlas.api.app import control_engine
    from atlas.intel.portfolio import report
    pos = [p.model_dump(mode="json") for p in control_engine.open_positions]
    universe = ["GC", "SI", "ES", "SPY", "BTCUSDT", "ETHUSDT"]
    out = report(_feed(), pos, universe)
    out["positions_source"] = ("control-plane in-memory paper state; pos-001 is the engine's seeded demo position "
                               "(instrument id not in the feed master, so it is unpriced)")
    bars = _bars("SPY", "1d") or _bars("GC", "1d")
    return _wrap(bars, out)


# ---- tracks ----
@router.get("/tracks")
def tracks() -> dict[str, Any]:
    from atlas.api.app import control_engine
    from atlas.control.tracks import probe, rulebooks
    return {**rulebooks(control_engine), "probes": probe(), "execution_permission": EXECUTION_PERMISSION,
            "note": "probes run on throwaway in-memory paper engines; nothing is persisted or routed",
            "freshness": {"label": "unavailable", "source": "control_plane_config (rule configuration, not market data)", "computed_at": int(time.time())}}


# ---- assistant ----
@router.get("/assistant")
def assistant(q: str = Query(min_length=2, max_length=400), k: int = Query(5, ge=1, le=10)) -> dict[str, Any]:
    from atlas.intel.assistant import ask
    out = ask(q, k=k)
    return {**out, "execution_permission": EXECUTION_PERMISSION,
            "freshness": {"label": "historical", "source": "docs+lab_reports corpus", "computed_at": int(time.time())}}


# ---- memory / attribution / governance ----
@router.get("/memory")
def memory(symbol: str = Query("GC"), tf: str = Query("15m"), k: int = Query(5, ge=1, le=20)) -> dict[str, Any]:
    from atlas.research.memory import analogues, attribution, build_memory, governance
    from atlas.intel.regime import classify
    sym = symbol.upper(); bars = _bars(sym, tf)
    gov = governance()
    if not bars:
        return _wrap(bars, {"status": "no_data", "instrument": sym, "governance": gov})
    res = _replay_all(sym, tf, bars)
    mem = build_memory(res.trades, classify(bars))
    latest = max(res.candidates, key=lambda c: c.detected_at, default=None) if res.candidates else None
    an = None
    if latest is not None:
        qf = {k2: float(v) for k2, v in (latest.features or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        an = {"query_candidate": latest.candidate_id, "detector": latest.detector,
              **analogues(mem, qf, as_of=latest.detected_at, k=k, detector=latest.detector)}
    return _wrap(bars, {"status": "ok", "instrument": sym, "n_memory": len(mem), "attribution": attribution(mem),
                        "latest_analogues": an, "governance": gov})


# ---- microstructure ----
@router.get("/microstructure")
def microstructure(symbol: str = Query("GC"), tf: str = Query("15m")) -> dict[str, Any]:
    from atlas.intel.microstructure import report
    sym = symbol.upper(); bars = _bars(sym, tf); f = _feed()
    quotes = f.store.last_quotes(sym) if f is not None else []
    return _wrap(bars, report(sym, bars, quotes))


# ---- Four-Box ----
@router.get("/fourbox")
def fourbox(symbol: str = Query("GC"), tf: str = Query("15m")) -> dict[str, Any]:
    from atlas.intel.fourbox import scan
    sym = symbol.upper(); bars = _bars(sym, tf)
    out = scan(sym, bars[-3000:])
    if sym in ("GC", "MGC", "SI"):
        out["session_note"] = "metals use the US equity RTH open as the opening box (approximation)"
    return _wrap(bars, out)


# ---- holidays ----
@router.get("/holidays")
def holidays(symbol: str = Query("GC")) -> dict[str, Any]:
    from atlas.feeds.contracts import _sessions, contract_for, front_contract, holiday_source
    spec = contract_for(symbol.upper())
    if spec is None:
        raise HTTPException(status_code=404, detail="no_contract_spec")
    today = date.today()
    code, lt, roll = front_contract(spec, today)
    ses = _sessions(spec.calendar, today.year, today.year + 1)
    upcoming = []
    if ses is not None:
        from datetime import timedelta
        d = today
        while len(upcoming) < 6 and d.year <= today.year + 1:
            d += timedelta(days=1)
            if d.weekday() < 5 and d not in ses:
                upcoming.append(d.isoformat())
    return {"instrument": spec.instrument_id, "front": code, "last_trade": lt.isoformat(), "roll_date": roll.isoformat(),
            "holiday_source": holiday_source(spec, today.year), "upcoming_weekday_closures": upcoming, "verified": spec.verified,
            "freshness": {"label": "historical", "source": "exchange_calendars", "computed_at": int(time.time())}}


# ---- model evolution (research; never promotes to execution) ----
@router.get("/evolution")
def evolution() -> dict[str, Any]:
    from atlas.ml.evolution import GENES, champion, latest_run
    run = latest_run()
    now = int(time.time())
    if not run:
        return {"status": "no_runs", "genes": GENES, "execution_permission": EXECUTION_PERMISSION,
                "note": "run scripts/evolve_models.py or POST /api/intel/evolution/run",
                "freshness": {"label": "unavailable", "last_bar_end": None, "age_s": None, "source": "ml registry/evolution", "computed_at": now}}
    last = max((s.get("last_bar_end") or 0 for s in run["data"].get("series", [])), default=0) or None
    lb = [{k: v.get(k) for k in ("genome_id", "genome", "generation", "parent", "mutation", "eval_seconds")}
          | {"metrics": {k: x for k, x in (v.get("metrics") or {}).items() if k != "folds"}} for v in run["leaderboard"]]
    return {"status": "ok", "run_id": run["run_id"], "created_at": run["created_at"], "code_sha": run.get("code_sha"),
            "decision": run["decision"], "no_model_beats_baseline": run["no_model_beats_baseline"], "by_bar_type": run["by_bar_type"],
            "folds": run["folds"], "data": run["data"], "leaderboard": lb, "champion": champion(), "genes": GENES,
            "promoted_to_execution": False, "execution_permission": EXECUTION_PERMISSION,
            "freshness": {"label": "historical", "last_bar_end": last, "age_s": (now - last) if last else None,
                          "source": "walk-forward OOS on a fixed feed snapshot", "computed_at": now}}


@router.post("/evolution/run")
def evolution_run(generations: int = Query(3, ge=1, le=6), seed: int = Query(11)) -> dict[str, Any]:
    from atlas.ml import evolution as E
    data, meta = E.build_population_data(_feed())
    if not len(data):
        return {"status": "no_data", "meta": meta, "execution_permission": EXECUTION_PERMISSION}
    res = E.evolve(data, meta, generations=generations, seed=seed, log=lambda s: None)
    best = res["best_beating_baseline"] or res["best"]
    run = E.record(res, oos=E.oos_predictions(data, best["genome"]) if best else None)
    return {"status": "ok", "run_id": run["run_id"], "decision": run["decision"], "no_model_beats_baseline": run["no_model_beats_baseline"],
            "execution_permission": EXECUTION_PERMISSION}


# ---- chart opportunity markers ----
@router.get("/markers")
def markers(symbol: str = Query("GC"), tf: str = Query("15m"), limit: int = Query(400, ge=1, le=2000)) -> dict[str, Any]:
    from atlas.intel.markers import DISCLAIMER, class_summary, from_evolution, from_replay
    sym = symbol.upper(); bars = _bars(sym, tf)
    if not bars:
        return _wrap(bars, {"status": "no_data", "markers": [], "disclaimer": DISCLAIMER})
    _, _, cpu, _, _ = SPEC.get(sym, ("crypto", 0.01, 0.0, 0.0, 96))
    mk = from_replay(_replay_all(sym, tf, bars), TF_SECONDS[tf], cpu)
    ml, ml_meta = from_evolution(sym, tf)
    t0 = bars[0].start
    allm = sorted([m for m in mk + ml if m["time"] >= t0], key=lambda m: m["time"])[-limit:]
    classes = class_summary(allm, sum(1 for m in allm if m["source"] == "candidate_engine"), any(m["source"] == "evolution_oos" for m in allm))
    counts = {k: v["count"] for k, v in classes.items()}
    return _wrap(bars, {"status": "ok", "symbol": sym, "tf": tf, "markers": allm, "counts": counts, "classes": classes, "evolution": ml_meta,
                        "disclaimer": DISCLAIMER, "anchoring": "time = start of the confirmation bar (detected_at - tf); price = real entry reference"})


# ---- alternative bar representations (display) ----
@router.get("/bars_alt")
def bars_alt(symbol: str = Query("GC"), tf: str = Query("15m"), kind: str = Query("heikin_ashi"), limit: int = Query(600, ge=10, le=5000)) -> dict[str, Any]:
    from atlas.features.representations import BAR_TYPES, availability, build
    if kind not in BAR_TYPES:
        raise HTTPException(status_code=400, detail="unknown_bar_type")
    sym = symbol.upper(); bars = _bars(sym, tf)
    av = availability(bars)
    if not bars or not av[kind]["available"]:
        return _wrap(bars, {"status": "unavailable", "kind": kind, "reason": av.get(kind, {}).get("reason", "no data"), "bars": [], "availability": av})
    alt = build(kind, bars)[-limit:]
    rows = [{"start": a.start, "completed_at": a.completed_at, "open": a.open, "high": a.high, "low": a.low, "close": a.close,
             "volume": a.volume, "direction": a.direction, "n_src": a.n_src} for a in alt]
    return _wrap(bars, {"status": "ok", "kind": kind, "source_tf": tf, "bars": rows, "availability": av,
                        "note": "display/features only; HA prices are synthetic; fills and P&L always use real time bars",
                        "time_axis": "each bar is plotted at its completed_at (real time it became known)"})
