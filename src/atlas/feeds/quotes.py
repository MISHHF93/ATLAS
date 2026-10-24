"""Latest quote per instrument from the ATLAS feed store, with source, Toronto timestamp and status.

Sources, freshest first: ``last_quotes`` (live websocket ticks / Yahoo spark polls written by the live-ingest service)
and the newest stored bar (backfill / confirmed klines). A quote never carries a price that did not come from a stored
provider print; with nothing stored it is ``no_data`` with ``price: None``.
"""
from __future__ import annotations

import time as _time

from .instruments import InstrumentMaster
from .status import NO_DATA, classify, last_nyse_close, nyse_open, toronto
from .store import FeedStore
from .universe import resolve


def _change_ref(store: FeedStore, inst, price_time: float, prev_close_hint: float | None) -> float | None:
    if inst.session == "24x7":  # 24h change from the stored bar ~24h before the print
        target = price_time - 86400
        for iv in ("1m", "15m", "1h"):
            bars = store.bars(inst.id, iv, start=int(target) - 3600, end=int(target) + 60)
            if bars:
                return bars[-1].close
        return prev_close_hint
    if prev_close_hint:
        return prev_close_hint
    from datetime import datetime, timezone
    from .status import NY
    day = datetime.fromtimestamp(price_time, timezone.utc).astimezone(NY).date()
    for t, c in store.daily_closes(inst.id, 5):
        if datetime.fromtimestamp(t, timezone.utc).astimezone(NY).date() < day:
            return c
    return None


def quote(store: FeedStore, master: InstrumentMaster, symbol: str, now: float | None = None) -> dict:
    now = now or _time.time()
    iid = resolve(symbol) or symbol.upper()
    base = {"symbol": symbol, "instrument": iid, "price": None, "change_pct": None, "source": None, "kind": None,
            "observed_at": None, "observed_at_toronto": None, "age_seconds": None, "status": NO_DATA}
    try:
        inst = master.get(iid)
    except KeyError:
        return {**base, "reason": "symbol not in the ATLAS feed universe"}
    cands = []
    for q in store.last_quotes(iid):
        cands.append((min(q["event_time"], q["receipt_time"]), q["provider"], q["price"], q["kind"], q.get("prev_close")))
    bar = store.latest_bar(iid)
    if bar is not None:
        bt = min(bar.bar_end, bar.receipt_time)
        if inst.session == "us_equity_rth" and not nyse_open(bt):
            bt = min(bt, max(bar.event_time, last_nyse_close(bt)))  # a bar spanning the close was last priced at the close
        cands.append((bt, bar.provider, bar.close, f"bar_{bar.interval}", None))
    if not cands:
        return {**base, "session": inst.session, "reason": "no stored provider print (run backfill / live ingest)"}
    rank = {p: i for i, p in enumerate(inst.provider_priority)}
    # Freshest print wins; within 2s prefer the instrument's primary providers (exact USDT pair over USD cross-checks).
    cands.sort(key=lambda c: (-int(c[0] // 2), rank.get(c[1], 99)))
    t, provider, price, kind, prev = cands[0]
    ref = _change_ref(store, inst, t, prev)
    return {**base, "price": price, "change_pct": round((price / ref - 1) * 100, 3) if ref else None,
            "reference_price": ref, "source": provider, "kind": kind, "observed_at": t, "observed_at_toronto": toronto(t),
            "age_seconds": round(now - t, 1), "status": classify(inst.session, provider, t, now), "session": inst.session,
            "quote_currency": inst.currency}


def quotes(store: FeedStore, master: InstrumentMaster, symbols, now: float | None = None) -> dict[str, dict]:
    now = now or _time.time()
    return {s: quote(store, master, s, now) for s in symbols}
