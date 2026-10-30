"""Coverage + prediction orchestration (evo-16 M1).

``coverage(feed)`` answers, for EVERY catalog asset: the last real data time, the last prediction time, the model version and,
when there is no prediction, the exact reason. It reads the store with ONE narrow GROUP BY (never ``store.summary()``).
``sweep(feed)`` runs the research model for every (asset, interval) that has a model and bars, and logs the result.
Predictions are research display only (execution_permission none) and are never written into the bar store."""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterable

from atlas.ai.prediction import log as PL
from atlas.ai.prediction.pools import POOL_LABEL, pool_of

INTERVALS = ("1m", "15m", "1h", "1d")
DUR = {"1m": 60, "15m": 900, "1h": 3600, "1d": 86400}
MIN_BARS = 300
# a real bar older than this many bar-durations is "stale" for a live interval; the daily series gets 4 days (weekends, holidays)
STALE_AFTER = {"1m": 15 * 60, "15m": 3 * 3600, "1h": 6 * 3600, "1d": 4 * 86400}
_LAST_TTL = 60.0
_LAST_CACHE: dict[int, tuple[float, dict]] = {}


def last_real_map(feed, now: float | None = None, fresh: bool = False) -> dict[tuple[str, str], dict[str, Any]]:
    """{(instrument, interval): {"last": newest event_time, "n": revision rows}} from one index-only GROUP BY. Cached 60 s."""
    hit = _LAST_CACHE.get(id(feed))
    mono = time.monotonic()
    if hit and not fresh and mono - hit[0] < _LAST_TTL:
        return hit[1]
    marks = ",".join("?" for _ in INTERVALS)
    rows = feed.store._fetchall(f"SELECT instrument, interval, MAX(event_time), COUNT(*) FROM bar_revisions WHERE interval IN ({marks}) "
                                "GROUP BY instrument, interval", INTERVALS)
    out = {(r[0], r[1]): {"last": int(r[2]), "n": int(r[3])} for r in rows}
    _LAST_CACHE[id(feed)] = (mono, out)
    return out


def model_version(symbol: str, interval: str, root=None) -> str | None:
    """``<group>-<interval>@<data digest>`` of the pooled model that would score this series (``+transfer`` when borrowed), or None."""
    from atlas.ai.ml.directional import live as LV
    man, _b, key, transfer = LV.resolve_model(symbol, interval, root)
    if man is None:
        return None
    return f"{key}@{str(man.get('data_digest') or '')[:8] or 'unversioned'}" + ("+transfer" if transfer else "")


def diagnose(symbol: str, interval: str, n_bars: int, root=None) -> tuple[str, str]:
    """Static preconditions of ``directional_prediction`` without computing anything: (status, reason). ``ready`` means it can run."""
    from atlas.ai.ml.directional import live as LV
    man, bundle, key, transfer = LV.resolve_model(symbol, interval, root)
    if man is None or bundle is None:
        return "no_model", f"No pooled research model for {key} yet, and no donor pool has one."
    if n_bars < MIN_BARS:
        return "insufficient_history", f"{n_bars} stored bars; at least {MIN_BARS} are needed to build the features."
    return "ready", ""


def _fmt_age(s: float | None) -> str:
    if s is None:
        return "no data"
    return f"{int(s)}s" if s < 120 else (f"{int(s // 60)}m" if s < 7200 else (f"{s / 3600:.1f}h" if s < 172800 else f"{s / 86400:.1f}d"))


def _cell(symbol: str, iv: str, last: dict | None, plog: dict, now: float, root) -> dict[str, Any]:
    n = last["n"] if last else 0
    bar_end = (last["last"] + DUR[iv]) if last else None
    age = max(0.0, now - bar_end) if bar_end else None
    ver = model_version(symbol, iv, root)
    lg = plog.get((symbol, iv))
    if not last:
        status, reason = "no_data", f"No stored {iv} bars for {symbol}."
    else:
        status, reason = diagnose(symbol, iv, n, root)
    if lg and lg.get("last_ok_at") and status == "ready":
        status, reason = "predicted", ""
    elif lg and status == "ready":
        status, reason = lg["status"], lg.get("reason") or ""
    elif status == "ready":
        status, reason = "not_yet_run", "A model covers this series; no prediction has been computed yet (run the sweep or open the chart)."
    return {"interval": iv, "bars": n, "last_real_at": last["last"] if last else None, "last_real_bar_end": bar_end,
            "last_real_age_s": age, "last_real_age": _fmt_age(age), "stale": bool(age is not None and age > STALE_AFTER[iv]),
            "model_version": ver, "status": status, "reason": reason,
            "last_prediction_at": (lg or {}).get("last_ok_at"), "direction": (lg or {}).get("direction"), "probability": (lg or {}).get("probability"),
            "label": (lg or {}).get("label")}


def _unlicensed_reason(feed, instrument_id: str) -> str:
    """Bars exist but every stored provider is outside the free/terms-allowed set (e.g. Yahoo futures): the model cannot use them, and the
    reason must say that rather than blame the model or the bar count."""
    from atlas.feeds.free_sources import allowed
    try:
        provs = [r[0] for r in feed.store._fetchall("SELECT DISTINCT provider FROM bar_revisions WHERE instrument=?", (instrument_id,))]
    except Exception:
        return ""
    if provs and not any(allowed(p) for p in provs):
        return (f"Stored bars for {instrument_id} come only from {', '.join(sorted(provs))}, an unofficial source excluded from the trade series "
                f"(terms), so no model can use them. A permitted provider that carries this instrument is needed.")
    return ""


def coverage(feed, now: float | None = None, root=None, log_path=None, ids: Iterable[str] | None = None, fresh: bool = False) -> dict[str, Any]:
    """One row per catalog asset (the full instrument master, or ``ids``)."""
    from atlas.feeds.status import toronto
    now = now or time.time()
    lm = last_real_map(feed, now, fresh)
    plog = PL.latest(log_path)
    want = set(ids) if ids is not None else None
    rows = []
    for inst in feed.instruments.all():
        if want is not None and inst.id not in want:
            continue
        cells = {iv: _cell(inst.id, iv, lm.get((inst.id, iv)), plog, now, root) for iv in INTERVALS}
        have = [c for c in cells.values() if c["bars"]]
        predicted = [c for c in cells.values() if c["status"] == "predicted"]
        # primary = the interval shown in the table: most recently predicted, else the finest interval with a model, else any with data
        if predicted:
            prim = max(predicted, key=lambda c: c["last_prediction_at"] or 0)
        else:
            ready = [c for c in have if c["status"] in ("not_yet_run", "error")]
            prim = (ready or have or list(cells.values()))[0] if (ready or have) else cells["1d"]
        last_real = max((c["last_real_bar_end"] for c in have), default=None)
        last_pred = max((c["last_prediction_at"] for c in cells.values() if c["last_prediction_at"]), default=None)
        reason, fix = prim["reason"], ""
        if not have:
            fix = _no_data_fix(feed, inst.id)
            reason = f"No stored bars at any interval for {inst.id}." + (f" {fix}" if fix else "")
        status = "predicted" if predicted else ("no_data" if not have else prim["status"])
        if status not in ("predicted", "no_data"):
            lic = _unlicensed_reason(feed, inst.id)
            if lic:
                status, reason = "no_licensed_data", lic
        rows.append({"instrument": inst.id, "asset_class": inst.asset_class, "pool": pool_of(inst.id, inst.asset_class),
                     "description": inst.description, "status": status, "primary_interval": prim["interval"],
                     "last_real_at": last_real, "last_real_toronto": toronto(last_real) if last_real else None,
                     "last_real_age": _fmt_age(max(0.0, now - last_real)) if last_real else "no data",
                     "eod_only": bool(have) and all(c["interval"] == "1d" for c in have),
                     "last_prediction_at": last_pred, "last_prediction_toronto": toronto(last_pred) if last_pred else None,
                     "model_version": (prim["model_version"] if prim["bars"] else None) or next((c["model_version"] for c in cells.values() if c["model_version"]), None),
                     "label": prim["label"], "reason": "" if status == "predicted" else reason, "intervals": cells})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    pools: dict[str, dict[str, Any]] = {}
    for r in rows:
        p = pools.setdefault(r["pool"], {"pool": r["pool"], "label": POOL_LABEL.get(r["pool"], r["pool"]), "assets": 0, "predicted": 0, "with_data": 0})
        p["assets"] += 1
        p["predicted"] += r["status"] == "predicted"
        p["with_data"] += r["last_real_at"] is not None
    return {"as_of": now, "as_of_toronto": toronto(now), "timezone": "America/Toronto", "n_assets": len(rows), "status_counts": counts,
            "pools": sorted(pools.values(), key=lambda p: p["pool"]), "assets": rows, "execution_permission": "none",
            "note": "Predictions are research display only. They are never written into the bar store or used as training labels."}


_PLACEHOLDER = re.compile(r"^(EQ\d{3,}|PERP\d{3,}(-USD|USDT)?)$")


def is_placeholder(symbol: str) -> bool:
    """``EQ####`` / ``PERP###`` ids fill the catalog count. They name no listed security and have no price anywhere."""
    return bool(_PLACEHOLDER.match(str(symbol or "").upper()))


def no_data_cause(feed, symbol: str) -> dict[str, str]:
    """Why an asset has nothing to chart or forecast, in one machine-readable ``cause`` and one plain sentence. Never raises."""
    if is_placeholder(symbol):
        return {"cause": "placeholder", "reason": f"{symbol} is a directory placeholder id, not a listed security: no exchange, no quote and no bars exist for it, "
                                                  "so there is no real price to chart or to anchor a forecast on."}
    try:
        from atlas.feeds.coverage import asset_coverage
        c = asset_coverage(feed, symbol)
    except KeyError:
        return {"cause": "not_in_master", "reason": f"{symbol} is not in the instrument master, so no provider is mapped to it."}
    except Exception:
        return {"cause": "unknown", "reason": ""}
    unl = _unlicensed_reason(feed, symbol)
    st = c.get("status") or "unknown"
    if unl:
        return {"cause": "unofficial_only", "reason": unl}
    fix = (c.get("fix") or "").strip()
    if st == "ok" and not fix:
        # Coverage is fine (a permitted provider is serving bars) but too few are stored to chart or forecast: say so.
        return {"cause": "building_history", "reason": f"{symbol} has a permitted provider and its first bars have arrived, but there is not enough "
                                                      "stored history yet to chart or forecast it. History fills in as the feed backfills."}
    text = {"policy_blocked": "Every provider mapped to this instrument is outside the free/terms-allowed set, so no bars are stored. ",
            "needs_key": "A permitted provider is mapped but its key is not set, so no bars are stored. ",
            "awaiting_data": "A permitted provider is mapped; its first bars have not arrived yet. ",
            "no_provider": "No provider is mapped to this instrument. "}.get(st, "")
    return {"cause": st, "reason": (text + fix).strip()}


def _no_data_fix(feed, instrument_id: str) -> str:
    try:
        from atlas.feeds.coverage import asset_coverage
        c = asset_coverage(feed, instrument_id)
        return (f"[{c['status']}] " + (c.get("fix") or "")).strip()
    except Exception:
        return ""


def predict_asset(feed, symbol: str, interval: str, now: float | None = None, root=None, log_path=None) -> dict[str, Any]:
    """Compute and log one research prediction on the latest closed bar. Never raises: errors become status ``error`` with the reason."""
    now = now or time.time()
    try:
        from atlas.ai.ml.dataset import load_series
        from atlas.api import chart_overlays as CO
        bars = load_series(feed, symbol, interval).bars
        cal = CO._economic_events(now)
        ev = [e["ts"] for e in cal["events"]] if isinstance(cal, dict) and cal.get("events") else None
        extra = CO._market_extra(feed)
        extra = extra if isinstance(extra, dict) and "status" not in extra else {}
        closed = [b for b in bars if b.start + b.duration <= now]
        from atlas.ai.ml.directional.live import directional_prediction
        res = directional_prediction(symbol, interval, closed, ref_loader=lambda r, iv: CO.cached_ref_bars(feed, r, iv), root=root, events=ev, extra=extra)
    except Exception as e:
        res = {"status": "error", "reason": f"{type(e).__name__}: {str(e)[:200]}", "symbol": symbol, "interval": interval, "computed_at": int(now),
               "label": "prediction failed", "execution_permission": "none"}
    PL.record(res, model_version(symbol, interval, root), log_path)
    return res


def sweep(feed, symbols: Iterable[str] | None = None, intervals: Iterable[str] = INTERVALS, now: float | None = None, root=None, log_path=None,
          predictor: Callable[..., dict] | None = None, budget_s: float | None = None) -> dict[str, Any]:
    """Run every (asset, interval) that diagnoses as ready; log the diagnosis for the rest. Returns counts."""
    now = now or time.time()
    lm = last_real_map(feed, now, fresh=True)
    want = set(symbols) if symbols is not None else None
    run = predictor or predict_asset
    t0 = time.monotonic()
    done = ok = skipped = failed = 0
    for inst in feed.instruments.all():
        if want is not None and inst.id not in want:
            continue
        for iv in intervals:
            last = lm.get((inst.id, iv))
            if not last:
                continue
            status, _ = diagnose(inst.id, iv, last["n"], root)
            if status != "ready":
                skipped += 1
                continue
            if budget_s is not None and time.monotonic() - t0 > budget_s:
                return {"done": done, "ok": ok, "skipped": skipped, "failed": failed, "stopped": "time budget"}
            res = run(feed, inst.id, iv, now=now, root=root, log_path=log_path)
            done += 1
            ok += res.get("status") == "ok"
            failed += res.get("status") == "error"
    return {"done": done, "ok": ok, "skipped": skipped, "failed": failed, "stopped": None}
