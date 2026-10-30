"""The 1-minute nowcast clock (evo-16 M3): issue a nowcast for every asset/interval that has real bars, then grade the ones whose bar closed.

Nothing here writes to the bar store. Issued forecasts live in ``nowcast.sqlite`` and are never used as labels."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from atlas.ai.prediction import nowcast as NC, nowcast_log as NL, service as S

STALE_DAYS = 20
_state: dict[str, Any] = {"running": False, "last_tick_at": None, "last": None, "ticks": 0, "error": None}
_thread: threading.Thread | None = None
_stop = threading.Event()


def real_bar_close(feed) -> Callable[[str, str, int], float | None]:
    def f(symbol: str, interval: str, start: int):
        r = feed.store._fetchone("SELECT close FROM bar_revisions WHERE instrument=? AND interval=? AND event_time=? AND confirmed=1 "
                                 "ORDER BY receipt_time DESC LIMIT 1", (symbol, interval, int(start)))
        return float(r[0]) if r else None
    return f


def tick(feed, now: float | None = None, symbols: list[str] | None = None, log_path: str | None = None, budget_s: float = 40.0,
         intervals: tuple[str, ...] = NC.INTERVALS, hz: bool = True) -> dict[str, Any]:
    """One clock tick: nowcast + issue, then score what is due. Never raises; reports per-status counts."""
    t0 = time.monotonic()
    now = float(time.time() if now is None else now)
    lmap = S.last_real_map(feed, now, fresh=True)
    ids = symbols or sorted({s for (s, _iv) in lmap})
    issued, counts, errors, sample = [], {}, 0, None
    scale_cache: dict[tuple[str, str], float] = {}
    # a tick that runs out of budget resumes from where it stopped, so no asset is starved by its position in the list
    cur = int(_state.get("cursor", 0)) % max(1, len(ids)) if not symbols else 0
    order = ids[cur:] + ids[:cur]
    _state["cursor"] = 0
    for pos, sym in enumerate(order):
        if time.monotonic() - t0 > budget_s:
            counts["budget_exhausted"] = len(order) - pos
            _state["cursor"] = (cur + pos) % len(ids)
            break
        for iv in intervals:
            info = lmap.get((sym, iv))
            if not info or info["n"] < NC.MIN_BASE_BARS or now - (info["last"] + NC.DUR[iv]) > STALE_DAYS * 86400:
                continue
            try:
                from atlas.ai.prediction.pools import pool_for_symbol
                pool = pool_for_symbol(sym)
                sc = scale_cache.setdefault((pool, iv), NL.live_scale(pool, iv, log_path))
                nc = NC.nowcast(feed, sym, iv, now=now, horizon=1, lmap=lmap, live_scale=sc)
                counts[nc["status"]] = counts.get(nc["status"], 0) + 1
                if nc["status"] != "ok":
                    continue
                tgt = next((p for p in nc["path"] if p["t_end"] > now), None)
                if tgt is None:
                    continue
                issued.append({"symbol": sym, "interval": iv, "target_start": tgt["t"], "target_end": tgt["t_end"], "anchor_t": nc["anchor"]["t"],
                               "anchor_px": nc["anchor"]["price"], "mid": tgt["mid"], "lo": tgt["lo"], "hi": tgt["hi"], "k": tgt["k"], "pool": pool,
                               "mode": nc["mode"], "scale": sc})
            except Exception as exc:  # noqa: BLE001
                errors += 1
                sample = sample or f"{sym} {iv}: {type(exc).__name__}: {str(exc)[:120]}"
    n_issued = NL.issue(issued, now, log_path)
    sc_res = NL.score_due(real_bar_close(feed), now, log_path)
    hz_res = _hz_tick(feed, now, symbols) if hz else None
    out = {"at": int(now), "horizons": hz_res, "assets": len(ids), "issued": n_issued, "statuses": counts, "errors": errors, "error_sample": sample, **sc_res,
           "elapsed_s": round(time.monotonic() - t0, 2)}
    _state.update(last_tick_at=now, last=out, ticks=_state["ticks"] + 1)
    return out


_HZ_CTX: dict[str, Any] = {"at": 0.0}


def _hz_tick(feed, now: float, symbols) -> dict[str, Any]:
    """evo-17 research ensemble: issue next-bar forecasts for fresh bars and score due ones. Own try/except: it must never break the nowcast clock."""
    try:
        from atlas.ai.prediction import horizons as HZ
        if now - _HZ_CTX["at"] > 600 and "PYTEST_CURRENT_TEST" not in __import__("os").environ:   # calendar + market extras change slowly
            try:
                from atlas.api import chart_overlays as CO
                cal = CO._economic_events(now)
                ex = CO._market_extra(feed)
                _HZ_CTX.update(at=now, events=[e["ts"] for e in cal["events"]] if isinstance(cal, dict) and cal.get("events") else None,
                               extra=ex if isinstance(ex, dict) and "status" not in ex else {},
                               loader=lambda r, iv: CO.cached_ref_bars(feed, r, iv))
            except Exception:
                _HZ_CTX.update(at=now, events=None, extra={}, loader=None)
        return HZ.tick(feed, now, symbols, budget_s=20.0, ref_loader=_HZ_CTX.get("loader"), events=_HZ_CTX.get("events"), extra=_HZ_CTX.get("extra"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def status() -> dict[str, Any]:
    return dict(_state)


def start(feed_getter: Callable[[], Any], period_s: float = 60.0) -> bool:
    """Start the background clock once (daemon thread). Returns False when it is already running."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()

    def loop():
        _state["running"] = True
        while not _stop.is_set():
            t = time.monotonic()
            try:
                feed = feed_getter()
                if feed is not None:
                    tick(feed)
                    _state["error"] = None
            except Exception as exc:  # noqa: BLE001
                _state["error"] = f"{type(exc).__name__}: {exc}"
            _stop.wait(max(5.0, period_s - (time.monotonic() - t)))
        _state["running"] = False

    _thread = threading.Thread(target=loop, name="nowcast-clock", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
