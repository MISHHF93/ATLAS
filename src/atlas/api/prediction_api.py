"""Prediction service endpoints (evo-16): coverage/health for every catalog asset and the sweep. Research display only."""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/ai/predictions", tags=["ai"])
_TTL = 30.0
_cache: dict[str, Any] = {"t": 0.0, "v": None}
_sweep: dict[str, Any] = {"running": False, "started_at": None, "finished_at": None, "result": None, "error": None}
_lock = threading.Lock()


def _feed():
    from atlas.api.feeds_api import _feed as f
    return f()


@router.get("/coverage")
def api_coverage(fresh: bool = Query(default=False), symbols: str | None = Query(default=None)) -> dict[str, Any]:
    """Every catalog asset: last real data, last prediction, model version, and the reason when there is no prediction. Cached 30 s."""
    import os
    from atlas.ai.prediction import service as S
    if symbols is None and not fresh and _cache["v"] is not None and time.monotonic() - _cache["t"] < _TTL and "PYTEST_CURRENT_TEST" not in os.environ:
        return _cache["v"]
    feed = _feed()
    if feed is None:
        from atlas.feeds.feed import AtlasFeed
        from atlas.feeds.store import FeedStore
        feed = AtlasFeed(FeedStore(":memory:"))
    ids = [x.strip() for x in symbols.split(",") if x.strip()] if symbols else None
    out = S.coverage(feed, ids=ids, fresh=fresh)
    out["store_present"] = _feed() is not None
    out["sweep"] = dict(_sweep)
    if symbols is None:
        _cache.update(t=time.monotonic(), v=out)
    return out


def _run_sweep(feed, symbols, intervals):
    from atlas.ai.prediction import service as S
    try:
        res = S.sweep(feed, symbols=symbols, intervals=intervals)
        _sweep.update(result=res, error=None)
    except Exception as e:
        _sweep.update(result=None, error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        _sweep.update(running=False, finished_at=time.time())
        _cache["v"] = None


@router.post("/sweep")
def api_sweep(symbols: str | None = Query(default=None), intervals: str | None = Query(default=None)) -> dict[str, Any]:
    """Start a background sweep (one at a time). Computes research predictions only; nothing is traded or stored as market data."""
    from atlas.ai.prediction.service import INTERVALS
    feed = _feed()
    if feed is None:
        raise HTTPException(409, "no_feed_store")
    ivs = tuple(x.strip() for x in intervals.split(",") if x.strip()) if intervals else INTERVALS
    if any(i not in INTERVALS for i in ivs):
        raise HTTPException(400, "unsupported_interval")
    syms = [x.strip() for x in symbols.split(",") if x.strip()] if symbols else None
    with _lock:
        if _sweep["running"]:
            return {"started": False, **_sweep}
        _sweep.update(running=True, started_at=time.time(), finished_at=None, result=None, error=None)
    threading.Thread(target=_run_sweep, args=(feed, syms, ivs), daemon=True, name="prediction-sweep").start()
    return {"started": True, **_sweep}


@router.get("/sweep")
def api_sweep_status() -> dict[str, Any]:
    return dict(_sweep)


# ----------------------------------------------------------------------------- nowcast (M3)
_NC: dict[tuple, tuple[float, dict]] = {}
_NC_TTL = 10.0


@router.get("/nowcast")
def api_nowcast(symbol: str = Query(...), interval: str = Query(default="15m"), horizon: int | None = Query(default=None, ge=1, le=300)) -> dict[str, Any]:
    """Predicted path + conformal band for one asset on one timeframe. A forecast, labelled 'Predicted (not market data)'; read-only."""
    import os
    from atlas.ai.prediction import nowcast as NC, nowcast_log as NL
    from atlas.ai.prediction.pools import pool_for_symbol
    feed = _feed()
    if feed is None:
        raise HTTPException(409, "no_feed_store")
    key = (symbol, interval, horizon)
    hit = _NC.get(key)
    if hit and time.monotonic() - hit[0] < _NC_TTL and "PYTEST_CURRENT_TEST" not in os.environ:
        return hit[1]
    out = NC.nowcast(feed, symbol, interval, horizon=horizon, live_scale=NL.live_scale(pool_for_symbol(symbol), interval))
    if len(_NC) > 400:
        _NC.clear()
    _NC[key] = (time.monotonic(), out)
    return out


@router.get("/nowcast/calibration")
def api_nowcast_calibration(pool: str | None = Query(default=None), interval: str | None = Query(default=None)) -> dict[str, Any]:
    from atlas.ai.prediction import nowcast_log as NL
    return NL.calibration(pool=pool, interval=interval)


@router.get("/nowcast/status")
def api_nowcast_status() -> dict[str, Any]:
    from atlas.ai.prediction import clock as CK
    return CK.status()


@router.post("/nowcast/tick")
def api_nowcast_tick(symbols: str | None = Query(default=None)) -> dict[str, Any]:
    """Run one clock tick now (the background clock does this every minute)."""
    from atlas.ai.prediction import clock as CK
    feed = _feed()
    if feed is None:
        raise HTTPException(409, "no_feed_store")
    return CK.tick(feed, symbols=[x.strip() for x in symbols.split(",") if x.strip()] if symbols else None)


def start_clock() -> bool:
    """Start the 1-minute nowcast clock (not under pytest; disable with ATLAS_NOWCAST_CLOCK=0)."""
    import os
    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("ATLAS_NOWCAST_CLOCK") == "0":
        return False
    from atlas.ai.prediction import clock as CK
    return CK.start(_feed)
