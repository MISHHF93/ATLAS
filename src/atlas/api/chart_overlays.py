"""GET /api/ai/chart/overlays: ONE read-only payload for the harmonized ATLAS chart.

Aggregates existing research surfaces (feed bars, alt bar types, opportunity markers, evolution OOS predictions,
price-action zones, regimes, dossier conviction, ML registry) so the frontend draws everything on one chart.
Every layer reports its own status; a layer without data says so and is never filled with made-up values.
Advisory only: no orders, execution_permission none (also enforced by the AI-node guard)."""
from __future__ import annotations

import math
import time
from numbers import Real
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from atlas.ai.node import EXECUTION_PERMISSION, enforce_advisory

router = APIRouter(prefix="/api/ai/chart", tags=["ai"])

INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
BAR_TYPES = ("time", "heikin_ashi", "renko_atr", "range_atr", "volume", "dollar", "tick", "kagi_atr", "pnf_atr")
LAYERS = ("ml_markers", "ml_probability", "setups", "zones", "vwap", "volume_profile", "regimes", "conviction", "predictions")
EXTRA_LAYERS = ("marker_details", "forward", "model_prediction", "directional_prediction",
                "conformal_bands", "mtf_confluence", "events", "market_clock", "cross_corr", "vol_cone", "liquidity", "model_disagreement", "account_size", "drift_alert")  # chart-2: additive


def _feed():
    from atlas.api.feeds_api import _feed as f
    return f()


def _raw(feed, sym: str, iv: str, max_rows: int = 3500):
    try:
        if feed is None:
            return []
        res = list(feed.bars(sym, iv))
        return res[-max_rows:] if max_rows and len(res) > max_rows else res
    except Exception:  # unknown instrument etc.
        return []


def _bars_from(feed, sym: str, iv: str, start: int):
    """Lower-timeframe bars at or after ``start``. A feed that only accepts (symbol, interval) is filtered in memory."""
    try:
        if feed is None:
            return []
        try:
            res = list(feed.bars(sym, iv, start, None))
        except TypeError:
            res = [b for b in feed.bars(sym, iv) if int(b.event_time) >= start]
        return res
    except Exception:
        return []


def extend_from_lower(feed, sym: str, interval: str, bars):
    """Append higher-timeframe buckets built from confirmed lower bars that start after the stored series.

    Live ingest writes 1m crypto bars. Stored 15m/1h series stop at the last backfill, so a chart that
    reads only those series looks frozen while the minutes are already in the store. A partial current
    bucket is kept so the forming candle is on the chart. Incomplete buckets in the middle are not invented.
    """
    sources = {"5m": ("1m",), "15m": ("1m",), "1h": ("1m", "15m"), "4h": ("1h", "15m", "1m")}.get(interval)
    if not sources or feed is None:
        return bars, None
    step = INTERVALS[interval]
    last = bars[-1].start if bars else None
    start = (last + step) if last is not None else int(time.time()) - 3 * 86400
    anchor = 0
    if interval == "1h":
        try:
            if feed.instruments.get(sym).session == "us_equity_rth":
                anchor = 1800
        except Exception:
            anchor = 0
    from atlas.feeds.aggregate import aggregate
    from atlas.feeds.core import FeedBar
    for src in sources:
        raw = _bars_from(feed, sym, src, start)
        if not raw:
            continue
        feed_bars = []
        for b in raw:
            et = int(b.event_time)
            feed_bars.append(FeedBar(
                sym, src, et, float(b.open), float(b.high), float(b.low), float(b.close), float(getattr(b, "volume", 0) or 0),
                str(getattr(b, "provider", "") or ""), int(getattr(b, "receipt_time", et) or et),
                bool(getattr(b, "confirmed", True)), str(getattr(b, "provider_symbol", "") or "")))
        agg = aggregate(feed_bars, interval, int(time.time()), anchor=anchor, require_complete=True)
        extra = [b for b in agg if (last is None or b.event_time > last) and (b.confirmed or b is agg[-1])]
        added = _to_bars(extra, step)
        if not added:
            continue
        return bars + added, f"extended from {src} ({len(added)} bars)"
    return bars, None


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
    resampled from complete 15m hours (4 of 4 bars). A stale intraday series is refreshed from the provider chain,
    then extended with any newer lower-timeframe bars already in the store. Resampled series are labelled as such."""
    feed = _feed()
    ensure = getattr(feed, "ensure_recent", None)
    if ensure is not None and interval in INTERVALS:
        try:
            ensure(sym, interval)
        except Exception:
            pass
    if interval == "1h":
        rows = _raw(feed, sym, "1h")
        if rows:
            base, built = _to_bars(rows, 3600), "feed bars"
        else:
            rows = _raw(feed, sym, "15m")
            if rows:
                base, built = _resample(_to_bars(rows, 900), 3600, need=4), "resampled from 15m feed bars (complete hours only)"
            else:
                return [], [], "no 1h/15m feed bars"
    elif interval == "4h":
        base, rows, built = [], [], "no 1h/15m feed bars"
        for src in ("1h", "15m"):
            rows = _raw(feed, sym, src)
            if rows:
                base, built = _resample(_to_bars(rows, INTERVALS[src]), 14400), f"resampled from {src} feed bars"
                break
        else:
            return [], [], built
    else:
        rows = _raw(feed, sym, interval)
        base, built = _to_bars(rows, INTERVALS[interval]), "feed bars"
    extended, note = extend_from_lower(feed, sym, interval, base)
    if note:
        built = f"{built}; {note}"
    return extended, rows, built


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
    if rt is False and delay_s and int(delay_s) >= 86400:
        label = "delayed · end-of-day (previous session)"     # not "86400s": say what it means
    from atlas.feeds.massive_live import delay_note_for
    note = delay_note_for(getattr(last, "provider", None))
    return {"provider": getattr(last, "provider", None), "providers": provs, "realtime": rt, "delay_s": delay_s,
            "delay_label": label, "delay_note": note, "free_only": True, "built": built}


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
    win = bars[-1500:]  # bounded replay window keeps the chart responsive; markers only shown inside the view anyway
    mk = from_replay(_replay_all(sym, interval, win), INTERVALS[interval], cpu) if len(win) > 60 else []
    ml, meta = from_evolution(sym, interval, bars=win, rule_markers=mk)
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


def _swing_anchor(bars, n: int = 5):
    """Latest confirmed swing pivot (n bars each side). Returns (index, kind, confirmed_index) or None.
    A pivot is only known n bars later, so the anchor is never used before it is confirmed."""
    last = None
    for i in range(n, len(bars) - n):
        hi, lo = bars[i].high, bars[i].low
        if all(hi > bars[j].high for j in range(i - n, i)) and all(hi >= bars[j].high for j in range(i + 1, i + n + 1)):
            last = (i, "swing_high", i + n) if last is None or i >= last[0] else last
        if all(lo < bars[j].low for j in range(i - n, i)) and all(lo <= bars[j].low for j in range(i + 1, i + n + 1)):
            last = (i, "swing_low", i + n) if last is None or i >= last[0] else last
    return last


def _vwap_profile(bars, sym: str = "", full=None):
    """Session VWAP (reset per session: UTC day / US RTH / CME day), anchored VWAP from the latest confirmed swing
    pivot, session spans for shading, and the volume profile. Bar-approximated VWAP (typical price x volume)."""
    from atlas.ai.ml.chart_prediction import asset_group
    from atlas.ai.ml.vwap_features import _session_vwap, anchored_vwap, session_key, session_kind_for
    import pandas as pd
    view0 = bars[0].start
    bars, view = (full or bars), bars          # VWAP accumulates over every loaded bar so the first visible session is complete
    dur = bars[0].duration
    kind = session_kind_for(asset_group(sym) if sym else None, sym or None)
    pts, spans = [], []
    anchored: dict[str, Any] = {"status": "unavailable", "reason": "no confirmed swing pivot in view"}
    has_vol = any(b.volume for b in view)
    if dur < 86400:
        keys = [session_key(b.start, kind) for b in bars]
        df = pd.DataFrame({"high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars],
                           "volume": [b.volume for b in bars]})
        vwap, _, _ = _session_vwap(df, keys)
        pts = [{"time": b.start, "value": float(v), "session": (None if keys[i] is None else int(keys[i]))}
               for i, (b, v) in enumerate(zip(bars, vwap)) if math.isfinite(v) and b.start >= view0]
        for i, b in enumerate(bars):
            if keys[i] is None or b.start < view0:
                continue
            if spans and spans[-1]["key"] == int(keys[i]):
                spans[-1]["to"] = b.start + b.duration
            else:
                spans.append({"key": int(keys[i]), "from": b.start, "to": b.start + b.duration})
        for n_, sp in enumerate(spans):
            sp["shade"] = n_ % 2
    if has_vol:
        piv = _swing_anchor(view)
        if piv is not None:
            i, pk, ci = piv
            bars_v = view
            av = anchored_vwap(bars_v, [bars_v[i].start])
            apts = [{"time": b.start, "value": float(v)} for b, v in zip(bars_v[i:], av[i:]) if math.isfinite(v)]
            if apts:
                anchored = {"status": "ok", "points": apts, "anchor": {"time": bars_v[i].start, "kind": pk, "price": bars_v[i].high if pk == "swing_high" else bars_v[i].low,
                                                                        "confirmed_at": bars_v[ci].start + bars_v[ci].duration},
                            "method": "VWAP accumulated from the latest swing pivot (5 bars each side). The pivot is only known 5 bars later; "
                                      "no macro-release anchors: the repo has no free economic calendar."}
    label = {"utc_day": "UTC day", "us_rth": "US cash session (09:30-16:00 ET)", "cme_globex": "CME day (18:00 ET)"}[kind]
    unavailable_reason = ("daily bars have no intraday session" if dur >= 86400 else "source bars carry no volume")
    vw = {"status": "ok" if pts else "unavailable", "points": pts, "reset": label, "session_kind": kind, "anchored": anchored,
          "sessions": {"status": "ok" if spans else "unavailable", "spans": spans, "kind": kind, "label": label},
          **({} if pts else {"reason": unavailable_reason})}
    tail = view[-300:]
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


def _ml_panel(sym, interval, markers, evo_meta=None):
    from atlas.ml.evolution import champion, latest_run, research_hand
    from atlas.ml.market_islands import desk_attention
    from atlas.ml.registry import list_models
    run = latest_run()
    hand = research_hand()
    panel: dict[str, Any] = {
        "execution_permission": EXECUTION_PERMISSION,
        "promoted_to_execution": False,
        "can_buy": False,
        "can_sell": False,
        "orders": "none",
        "research_hand": hand,
        "market_attention": desk_attention(),
    }
    live_m = (evo_meta or {}).get("live_metrics") if isinstance(evo_meta, dict) else None
    metric_keys = (
        "brier",
        "brier_baseline",
        "brier_skill",
        "auc",
        "ece",
        "n_oos",
        "n_taken",
        "ev_r_per_opportunity",
        "take_all_ev",
        "mean_r_taken",
        "stability",
        "fitness",
        "beats_baseline",
    )
    if hand.get("linked"):
        m = dict(hand.get("metrics") or {})
        if live_m:
            for k, v in live_m.items():
                if m.get(k) is None:
                    m[k] = v
        panel["evolution"] = {
            "run_id": hand.get("source"),
            "created_at": hand.get("created_at"),
            "decision": hand.get("stance") or "abstain",
            "no_model_beats_baseline": not hand.get("beats_baseline"),
            "challenger": hand.get("genome_id"),
            "no_model_passes_strict_gate": not hand.get("strict_gate_passed"),
            "strict_gate": {
                "passed": hand.get("strict_gate_passed"),
                "failed": hand.get("strict_gate_failed") or [],
                "gate_version": "evo8-strict-1",
            },
            "metrics": {k: m.get(k) for k in metric_keys},
            "symbol_live_metrics": live_m,
        }
    elif run:
        best = run.get("best_beating_baseline") or run.get("best") or {}
        m = dict(best.get("metrics") or {})
        if live_m:
            for k, v in live_m.items():
                if m.get(k) is None:
                    m[k] = v
        panel["evolution"] = {"run_id": run["run_id"], "created_at": run.get("created_at"), "decision": run.get("decision"),
                              "no_model_beats_baseline": run.get("no_model_beats_baseline"), "challenger": best.get("genome_id"),
                              "no_model_passes_strict_gate": run.get("no_model_passes_strict_gate"),
                              "strict_gate": {k: (m.get("strict_gate") or {}).get(k) for k in ("passed", "failed", "gate_version")} if m.get("strict_gate") else None,
                              "metrics": {k: m.get(k) for k in metric_keys},
                              "symbol_live_metrics": live_m}
    else:
        panel["evolution"] = None
    stored = champion()
    panel["champion"] = stored if ((stored or {}).get("metrics") or {}).get("strict_gate", {}).get("passed") else None
    from atlas.ai.ml.chart_prediction import asset_group
    group = f"{asset_group(sym)}-{interval}"
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


def _model_prediction(sym, interval, bars, now):
    """Live model read on the latest CLOSED bar (a forming bucket is dropped), recomputed on every request."""
    from atlas.ai.ml.chart_prediction import model_prediction
    closed = [b for b in bars if b.start + b.duration <= now]
    return model_prediction(sym, interval, closed)


def _economic_events(now):
    """Scheduled releases (BLS/Treasury) for the events layer and the model's ev_* features; cached by the keyless source layer."""
    from atlas.ext.keyless_context import economic_calendar
    return economic_calendar(now, days=30, lookback_days=30)


def _account_snapshot():
    from atlas.accounts.credentials import effective_environ
    from atlas.broker_state.service import get_snapshot
    from atlas.integrations.registry import load_env
    return get_snapshot("paper_sim", load_env(environ=dict(effective_environ())))


_REF_TTL, _REF_MAX = 120.0, 48
_REF_CACHE: dict[tuple[int, str, str], tuple[float, list, Any]] = {}
_REF_LOCK = __import__("threading").Lock()


def cached_ref_bars(feed, sym: str, interval: str) -> list:
    """Closed reference-series bars (DXY/GLD/BTC/SPY ...) memoised for 120 s. The overlay builds the correlation
    context and the directional read in one request and both need the same ~8 series; loading each from the store
    twice made AAPL 15m take ~60 s under ingest load. Reference bars only change when a bar closes, so 120 s is safe."""
    key, now = (id(feed), sym, interval), time.monotonic()
    with _REF_LOCK:
        hit = _REF_CACHE.get(key)
        if hit is not None and hit[2] is feed and now - hit[0] < _REF_TTL:
            return hit[1]
    from atlas.ai.ml.dataset import load_series
    bars = load_series(feed, sym, interval).bars
    with _REF_LOCK:
        if len(_REF_CACHE) >= _REF_MAX:
            _REF_CACHE.pop(min(_REF_CACHE, key=lambda k: _REF_CACHE[k][0]), None)
        _REF_CACHE[key] = (now, bars, feed)
    return bars


def _market_extra(feed):
    """Breadth + VIX context shared by the chart layers and the live model (one hourly build, see context27.shared_context)."""
    from atlas.ai.ml.dataset import load_series
    from atlas.ai.ml.directional import context27 as C27
    return C27.shared_context(lambda s: load_series(feed, s, "1d").bars, lambda: C27.stored_daily_symbols(feed))


def _directional_prediction(sym, interval, bars, now, feed, events=None, extra=None):
    """evo-14 directional research model read on the latest closed bar (labelled research / below gate unless every offline gate passed)."""
    from atlas.ai.ml.directional.live import directional_prediction
    closed = [b for b in bars if b.start + b.duration <= now]
    return directional_prediction(sym, interval, closed, ref_loader=lambda r, iv: cached_ref_bars(feed, r, iv), events=events, extra=extra)


def _enrich_and_forward(markers, bars):
    from atlas.intel.marker_context import enrich, forward_zone, snapshots
    win = bars[-1500:]
    snaps = snapshots(win)
    enrich(markers, win, snaps)
    details = {"status": "ok", "n": len(markers), "fields": ["indicators", "threshold", "outcome_label", "why", "setup", "resolution_path"],
               "note": "indicator values are the causal state at each marker's confirmation bar (closed bars only, no lookahead)"}
    out = forward_zone(win, snaps, markers)
    if isinstance(out, dict) and out.get("status") == "ok":
        ml_recent = [m for m in markers if m.get("source") == "evolution_oos" and m.get("probability") is not None]
        if ml_recent:
            last_ml = ml_recent[-1]
            cands = out.get("active_candidates") or []
            for c in cands:
                if c.get("p_win") is None:
                    c["p_win"] = last_ml.get("probability")
                    c["calibrated"] = True
                    c["threshold"] = last_ml.get("threshold", 0.42)
                    c["ev_r"] = last_ml.get("ev_r")
            if not cands:
                out["active_candidates"] = [
                    {
                        "id": last_ml["id"],
                        "setup": str(last_ml.get("strategy", "walk_forward_barrier")).replace("_", " "),
                        "direction": last_ml.get("direction", "long"),
                        "class": last_ml.get("class", "ml_suggested"),
                        "p_win": last_ml.get("probability"),
                        "calibrated": True,
                        "threshold": last_ml.get("threshold", 0.42),
                        "ev_r": last_ml.get("ev_r"),
                    }
                ]
                out["no_active_candidate"] = None
    return details, out


def _calib(preds):
    from atlas.intel.marker_context import calibration
    return calibration(preds)


def _probability_layer(preds: list[dict[str, Any]]) -> dict[str, Any]:
    """A line has one value per bar; candidate-level predictions remain separate."""
    by_time: dict[int, dict[str, Any]] = {}
    for prediction in preds:
        timestamp, probability = prediction.get("time"), prediction.get("p")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in (timestamp, probability)):
            continue
        try:
            t, p = float(timestamp), float(probability)
        except (OverflowError, ValueError):
            continue
        if not (math.isfinite(t) and t.is_integer() and abs(t) <= 2**53 - 1 and math.isfinite(p) and 0 <= p <= 1):
            continue
        # Input order is the stable candidate order; a later valid candidate wins
        # only for rendering. Never average probabilities for different setups.
        by_time[int(t)] = {"time": int(t), "value": p, "take": bool(prediction.get("take"))}
    points = [by_time[t] for t in sorted(by_time)]
    return {
        "status": "ok" if points else "unavailable",
        "points": points,
        "selection": "last_valid_prediction_per_timestamp",
        "note": "One display point per bar: the last valid prediction in candidate order. All candidate predictions, markers, and calibration samples remain separate.",
    }


@router.get("/overlays")
def chart_overlays(symbol: str = Query("BTCUSDT", min_length=1), interval: str = Query("15m"), bar_type: str = Query("time"),
                   limit: int = Query(600, ge=50, le=3000), tz: str = Query("America/Toronto", max_length=40)) -> dict[str, Any]:
    if interval not in INTERVALS:
        raise HTTPException(400, "unsupported_interval")
    if bar_type not in BAR_TYPES:
        raise HTTPException(400, "unknown_bar_type")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(400, "unknown_timezone")
    from atlas.feeds.universe import resolve
    # BTC-USD is the crypto book. EUR-USD is the ECB pair, not a USDT coin.
    sym = resolve(symbol) or (symbol.upper().replace("-USD", "USDT") if symbol.upper().endswith("-USD") else symbol.upper())
    bars, rows, built = load(sym, interval)
    now = int(time.time())
    from atlas.market.sessions import get_market_sessions_status
    sess_info = get_market_sessions_status(symbols=[sym])["by_symbol"].get(sym)
    base: dict[str, Any] = {"symbol": sym, "interval": interval, "bar_type": bar_type, "provider": provider_info(rows, built),
                            "market_session": sess_info, "execution_permission": EXECUTION_PERMISSION, "orders": "none (read-only)", "computed_at": now}
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
    from atlas.api import chart_layers25 as _C25
    _layer(_C25.attach_reviews, markers)   # LLM Reviewer verdicts into marker details (no-op without reviews)
    ef = _layer(_enrich_and_forward, markers, bars)
    if isinstance(ef, tuple) and len(ef) == 2:
        details, fwd_out = ef
    else:
        details, fwd_out = ef, ef
    ml = [m for m in markers if m["source"] == "evolution_oos"]
    vw, vp = _layer(_vwap_profile, view, sym, bars) if any(b.volume for b in view) else ({"status": "unavailable", "reason": "no volume"},) * 2
    preds = [{"time": m["time"], "p": m["probability"], "take": m["class"] == "ml_suggested", "outcome": m["outcome"], "r": m["r"],
              "hit": (None if m["outcome"] not in ("target", "stop", "timeout") else bool((m.get("r") or 0) > 0)), "id": m["id"],
              "calibrator": (m.get("probability_label") or "").split("OOS, ")[-1].rstrip(")")} for m in ml if m.get("probability") is not None]
    panel = _layer(_ml_panel, sym, interval, markers, evo)
    em = ((panel.get("evolution") or {}).get("symbol_live_metrics") or (panel.get("evolution") or {}).get("metrics")) if isinstance(panel, dict) and panel.get("evolution") else None
    from atlas.api import chart_layers25 as C25
    from atlas.api import chart_layers27 as C27
    cal = _layer(_economic_events, now)
    cal_ok = isinstance(cal, dict) and bool(cal.get("events"))
    ev_ts = [e["ts"] for e in cal["events"]] if cal_ok else None
    mp_layer = _layer(_model_prediction, sym, interval, bars, now)
    extra = _layer(_market_extra, feed)
    extra_ok = extra if isinstance(extra, dict) and "status" not in extra else {}
    dp_layer = _layer(_directional_prediction, sym, interval, bars, now, feed, ev_ts, extra_ok)
    snap = _layer(_account_snapshot)
    ctx = _layer(C25.build_ctx, sym, interval, bars, now, feed, tz, mp_layer, dp_layer, ev_ts, cal_ok, cached_ref_bars, extra_ok)
    if isinstance(ctx, dict):   # building the shared context failed: every new layer says so, none is hidden
        l25 = {k: dict(ctx) for k in (*C25.IDS, *C27.IDS)}
    else:
        l25 = {"conformal_bands": _layer(C25.conformal_bands, ctx), "mtf_confluence": _layer(C25.mtf_confluence, ctx), "events": _layer(C25.events, ctx, cal),
               "market_clock": _layer(C25.market_clock, ctx), "cross_corr": _layer(C25.cross_corr, ctx), "vol_cone": _layer(C25.vol_cone, ctx),
               "liquidity": _layer(C25.liquidity, ctx), "model_disagreement": _layer(C25.model_disagreement, ctx),
               "account_size": _layer(C25.account_size, ctx, snap if isinstance(snap, dict) and "snapshot" in snap else None), "drift_alert": _layer(C25.drift_alert, ctx),
               **{k: _layer(getattr(C27, k), ctx) for k in C27.IDS}}
    l25["news"] = _layer(C25.news_layer, sym, now, t0)
    layers = {
        "ml_markers": {**mstat, "items": ml, "evolution": evo, **({} if ml else {"note": "no OOS predictions for this symbol/interval in the latest evolution run"})},
        "ml_probability": _probability_layer(preds),
        "setups": {**mstat, "items": [m for m in markers if m["source"] != "evolution_oos"], "classes": classes,
                   "categories": {"taken": "ml_suggested", "skipped_by_ml": "ml_skip", "rejected_by_risk": "risk_rejected", "rule_only": "rule_only"}},
        "zones": _layer(_zones, sym, interval, bars, feed),
        "vwap": vw, "volume_profile": vp,
        "anchored_vwap": (vw.get("anchored") if isinstance(vw, dict) and vw.get("anchored") else {"status": "unavailable", "reason": (vw.get("reason") if isinstance(vw, dict) and vw.get("status") != "ok" else None) or "no anchor was found in the visible window"}),
        "sessions": (vw.get("sessions") if isinstance(vw, dict) and vw.get("sessions") else {"status": "unavailable", "reason": (vw.get("reason") if isinstance(vw, dict) and vw.get("status") != "ok" else None) or "no session spans for this instrument at this interval"}),
        "regimes": _layer(_regimes, bars),
        "conviction": _layer(_conviction, sym, interval, feed),
        "predictions": {"status": "ok" if preds else "unavailable", "items": preds[-200:],
                        "calibration": {k: em.get(k) for k in ("brier", "brier_baseline", "brier_skill", "ece", "auc", "ev_r_per_opportunity", "take_all_ev", "mean_r_taken", "stability", "fitness")} if em else None,
                        "note": "out-of-sample walk-forward probabilities from the latest evolution run; research only",
                        "running_calibration": _layer(_calib, preds)},
        "marker_details": details,
        "forward": fwd_out,
        "model_prediction": mp_layer,
        "directional_prediction": dp_layer,
        **l25,
    }
    return enforce_advisory({**base, "status": "ok", "bars": out_bars, "display": display, "layers": layers, "ml_panel": panel},
                            source="/api/ai/chart/overlays")[0]
