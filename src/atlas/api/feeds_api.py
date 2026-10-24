"""ATLAS feed quotes / health / SSE.

* ``GET /api/feeds/quotes?symbols=AAPL,BTC-USD`` latest stored quote per symbol (default: the whole UI universe) with
  source, Toronto timestamp and status (live | delayed | market_closed | stale | no_data). Never a synthetic price.
* ``GET /api/feeds/health`` per-symbol provider, last bar time, lag and flags + provider snapshot + live-ingest state.
* ``GET /api/feeds/stream?symbols=...`` Server-Sent Events: a ``quotes`` event whenever any symbol's quote changes
  (polled from the store the live-ingest service writes). The stream ends itself after ``max_seconds`` (default 50 s,
  under the Node bridge's 60 s request timeout); EventSource reconnects automatically.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()


def _feed():
    from atlas.feeds import feed as feed_mod
    if feed_mod._DEFAULT is not None:
        return feed_mod._DEFAULT
    if "PYTEST_CURRENT_TEST" in os.environ and not os.environ.get("ATLAS_FEED_DB"):
        return None  # tests never read the developer's on-disk store implicitly (install a feed or set ATLAS_FEED_DB)
    if not os.path.exists(feed_mod.DEFAULT_STORE):
        return None
    return feed_mod.get_feed()


def _symbols(symbols: str | None) -> list[str]:
    from atlas.feeds.universe import ui_symbols
    return [s.strip() for s in symbols.split(",") if s.strip()] if symbols else ui_symbols()


def feed_quotes(symbols: list[str], now: float | None = None) -> dict[str, dict]:
    """Quotes for UI symbols. Without a feed store every symbol is ``no_data`` (price None) - never a fixture."""
    from atlas.feeds.quotes import quote
    from atlas.feeds.status import NO_DATA
    feed = _feed()
    if feed is None:
        return {s: {"symbol": s, "price": None, "source": None, "status": NO_DATA, "observed_at": None,
                    "observed_at_toronto": None, "reason": "feed store missing (run scripts/backfill_feeds.py)"} for s in symbols}
    now = now or time.time()
    return {s: quote(feed.store, feed.instruments, s, now) for s in symbols}


@router.get("/api/feeds/quotes")
def api_feed_quotes(symbols: str | None = Query(default=None)) -> dict[str, Any]:
    now = time.time()
    q = feed_quotes(_symbols(symbols), now)
    counts: dict[str, int] = {}
    for v in q.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {"as_of": now, "timezone": "America/Toronto", "status_counts": counts, "quotes": q}


def _live_ingest_state() -> dict[str, Any]:
    from atlas.feeds import feed as feed_mod
    pid_file = Path(feed_mod.DEFAULT_STORE).parent / "live_ingest.pid"
    pid = int(pid_file.read_text()) if pid_file.exists() and pid_file.read_text().strip().isdigit() else None
    from atlas.ops.procutil import pid_alive
    alive = pid_alive(pid)
    return {"pid": pid, "running": alive, "command": "PYTHONPATH=src python scripts/run_live_ingest.py"}


def _bar_label(bar, now: float) -> str:
    """Daily bars are labelled by their session date (their nominal bar_end can lie in the future); intraday bars by
    their end time in Toronto, capped at now for a still-forming bar."""
    from datetime import datetime
    from atlas.feeds.status import NY, toronto
    if bar.interval == "1d":
        return datetime.fromtimestamp(bar.event_time, NY).strftime("%Y-%m-%d") + " session"
    return toronto(min(bar.bar_end, now))


HEALTH_TTL_SECONDS = 5.0
_health_cache: dict[str | None, tuple[float, dict]] = {}


def feed_health(symbols: str | None = None) -> dict[str, Any]:
    from atlas.feeds.quotes import quote
    from atlas.feeds.status import NO_DATA, toronto
    from atlas.feeds.universe import resolve
    now = time.time()
    feed = _feed()
    rows = []
    for sym in _symbols(symbols):
        last_bar = None
        if feed is None:
            v = feed_quotes([sym], now)[sym]
        else:
            iid = resolve(sym) or sym.upper()
            try:
                feed.instruments.get(iid)
                last_bar = feed.store.latest_bar(iid)  # read once, shared with the quote
            except KeyError:
                pass
            v = quote(feed.store, feed.instruments, sym, now, bar=last_bar)
        flags = []
        if v["status"] in ("stale", NO_DATA):
            flags.append(v["status"])
        if v.get("source") == "yahoo":
            flags.append("unofficial_delayed_source")
        if v.get("reason"):
            flags.append(v["reason"])
        rows.append({"symbol": sym, "instrument": v.get("instrument"), "provider": v.get("source"), "status": v["status"],
                     "last_price": v.get("price"), "last_quote_at": v.get("observed_at_toronto"),
                     "lag_seconds": v.get("age_seconds"), "last_bar_interval": last_bar.interval if last_bar else None,
                     "last_bar_provider": last_bar.provider if last_bar else None,
                     "last_bar_end": _bar_label(last_bar, now) if last_bar else None, "flags": flags})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    providers = feed.registry.snapshot() if feed is not None else []
    return {"as_of": now, "as_of_toronto": toronto(now), "timezone": "America/Toronto", "store_present": feed is not None,
            "live_ingest": _live_ingest_state(), "status_counts": counts, "symbols": rows, "providers": providers}


@router.get("/api/feeds/health")
def api_feed_health(symbols: str | None = Query(default=None), fresh: bool = Query(default=False)) -> dict[str, Any]:
    """Cached for HEALTH_TTL_SECONDS (dashboards poll it); ``fresh=true`` bypasses the cache."""
    hit = _health_cache.get(symbols)
    if not fresh and hit and time.monotonic() - hit[0] < HEALTH_TTL_SECONDS and "PYTEST_CURRENT_TEST" not in os.environ:
        return hit[1]
    out = feed_health(symbols)
    _health_cache[symbols] = (time.monotonic(), out)
    return out


@router.get("/api/feeds/stream")
async def api_feed_stream(symbols: str | None = Query(default=None), max_seconds: float = Query(default=50, le=55),
                          interval: float = Query(default=1.0, ge=0.25)):
    syms = _symbols(symbols)

    async def gen():
        last: dict[str, tuple] = {}
        end = time.monotonic() + max_seconds
        yield "retry: 1000\n\n"
        while time.monotonic() < end:
            q = await asyncio.to_thread(feed_quotes, syms)
            changed = {s: v for s, v in q.items() if last.get(s) != (v.get("price"), v.get("observed_at"), v["status"])}
            for s, v in changed.items():
                last[s] = (v.get("price"), v.get("observed_at"), v["status"])
            if changed:
                yield f"event: quotes\ndata: {json.dumps({'as_of': time.time(), 'quotes': changed}, default=str)}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(interval)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
