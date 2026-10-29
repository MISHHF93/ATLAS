"""Massive (ex-Polygon) in ATLAS's live loop for US stocks and ETFs, with an honest statement of how fresh the data is.

What the FREE plan (Stocks Basic) allows, measured against a live Basic key on 2026-10-29 and from Massive's published plan tiers:
bars up to the previous completed New York session only (today's date returns HTTP 403 NOT_AUTHORIZED until midnight ET); no websocket (auth is refused on both delayed.massive.com and socket.massive.com);
no snapshot or last-trade (403 NOT_AUTHORIZED); no real-time and no 15-minute-delayed intraday feed (those start on paid plans). So on the free plan the "live" job is an end-of-day
refresh: after each ET midnight it pulls the newly completed session (15m + daily) and the 1h built from it, then the ML scores the newest
closed bar. The UI says exactly that ("end-of-day lag"), never "live".

With ``ATLAS_POLYGON_PLAN=paid`` (owner opt-in after buying a plan) the loop also polls the stock snapshot every ``SNAPSHOT_EVERY_S`` seconds
and writes delayed quotes (labelled ``polygon``, kind ``snapshot``). That path is unit-tested against recorded payloads only: it has NOT been
run against a paid account. The websocket (``delayed.massive.com`` / ``socket.massive.com``) is not wired.

Read-only. Nothing here places an order or sets a key. Licence: the Basic plan is individual, personal and non-commercial; keep the data private.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
SNAPSHOT_EVERY_S = 30
REFRESH_EVERY_S = 900          # free plan: only the ET-midnight rollover adds bars; polling is a cheap no-op (zero calls) in between
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
FREE_TEXT = ("Massive free plan (Stocks Basic): bars end at the previous completed New York session, 15m and daily. "
             "There is no websocket (auth is refused: \"plan doesn't include websocket access\") and the snapshot and last-trade endpoints return 403 "
             "NOT_AUTHORIZED, so there is no real-time or 15-minute-delayed intraday on this plan (those are paid). "
             "ATLAS refreshes after each ET midnight, so the newest bar is from the last completed session.")
PAID_TEXT = ("Massive paid plan (ATLAS_POLYGON_PLAN=paid): ATLAS polls the stock snapshot every 30 s; the delay is whatever your plan includes "
             "(15 minutes on Starter, real time on Advanced). Untested against a paid account; the websocket is not wired.")


def is_paid(env: Mapping[str, str]) -> bool:
    return (env.get("ATLAS_POLYGON_PLAN") or "").strip().lower() == "paid"


def has_key(env: Mapping[str, str]) -> bool:
    v = (env.get("POLYGON_API_KEY") or env.get("MASSIVE_API_KEY") or "").strip()
    return bool(v) and not v.startswith("<")


def capability(env: Mapping[str, str]) -> dict[str, Any]:
    """How fresh Massive stock data can be right now. Names and booleans only."""
    if not has_key(env):
        return {"provider": "polygon", "mode": "off", "realtime": False, "delay_s": None, "websocket": False, "key_present": False,
                "label": "Massive not configured", "detail": "Enter the Massive key in Settings → Setup and press Verify.", "paper_path_tested": None}
    if is_paid(env):
        return {"provider": "polygon", "mode": "delayed_poll", "realtime": False, "delay_s": None, "websocket": False, "key_present": True,
                "label": "Polled snapshot (delay set by your plan)", "detail": PAID_TEXT, "poll_every_s": SNAPSHOT_EVERY_S, "paid_path_tested": False}
    return {"provider": "polygon", "mode": "eod_lag", "realtime": False, "delay_s": 86400, "websocket": False, "key_present": True,
            "label": "End-of-day lag (previous completed session)", "detail": FREE_TEXT, "refresh_every_s": REFRESH_EVERY_S, "paid_path_tested": None}


def delay_note_for(provider: str | None, env: Mapping[str, str] | None = None) -> str | None:
    """One line for the chart footer: how old the plotted stock bars can be. None for providers this module does not describe."""
    if provider != "polygon":
        return None
    import os
    cap = capability(env if env is not None else os.environ)
    return None if cap["mode"] == "off" else f"{cap['label']}. {cap['detail']}"


def parse_snapshot(js: Mapping[str, Any], now: float, by_symbol: Mapping[str, str]) -> list[dict]:
    """Rows for ``FeedStore.upsert_quotes`` from a /v2/snapshot response. Prices only from the vendor payload; nothing is invented."""
    out = []
    for r in (js.get("tickers") or []):
        iid = by_symbol.get(str(r.get("ticker") or "").upper())
        lt, mn, day, prev = r.get("lastTrade") or {}, r.get("min") or {}, r.get("day") or {}, r.get("prevDay") or {}
        price = lt.get("p") or mn.get("c") or day.get("c")
        t_ns = lt.get("t") or r.get("updated")
        t = (float(t_ns) / 1e9) if t_ns and float(t_ns) > 1e14 else (float(t_ns) / 1000 if t_ns else None)
        if not iid or not price or not t:
            continue
        out.append({"instrument": iid, "provider": "polygon", "price": float(price), "event_time": t, "receipt_time": now,
                    "prev_close": prev.get("c"), "kind": "snapshot", "provider_symbol": r.get("ticker")})
    return out


def poll_snapshot(feed, env: Mapping[str, str], instruments: Iterable[str], now: float | None = None, transport=None) -> dict[str, Any]:
    """Paid plans only: one snapshot call for all tickers, stored as delayed quotes. Free plans never call it (it is not authorised there)."""
    now = time.time() if now is None else now
    if not is_paid(env) or not has_key(env):
        return {"status": "skipped", "reason": "free plan has no snapshot access" if has_key(env) else "no key", "quotes": 0}
    a = feed.registry.get("polygon")
    if a is None and transport is None:
        return {"status": "skipped", "reason": "polygon provider not registered", "quotes": 0}
    by = {}
    for iid in instruments:
        ins = feed.instruments.get(iid)
        sym = (getattr(ins, "provider_symbols", None) or {}).get("polygon") if ins else None
        if sym:
            by[sym.upper()] = iid
    if not by:
        return {"status": "skipped", "reason": "no instrument has a polygon symbol", "quotes": 0}
    try:
        if transport is not None:
            js = transport(sorted(by))
        else:
            base = env.get("POLYGON_BASE_URL") or env.get("MASSIVE_BASE_URL") or "https://api.massive.com"
            key = env.get("POLYGON_API_KEY") or env.get("MASSIVE_API_KEY") or ""
            js = a.get_json(f"{base}{SNAPSHOT_PATH}", {"tickers": ",".join(sorted(by))}, headers={"Authorization": f"Bearer {key}"})
    except Exception as ex:  # never echo headers
        return {"status": "error", "reason": type(ex).__name__, "quotes": 0}
    rows = parse_snapshot(js or {}, now, by)
    n = feed.store.upsert_quotes(rows) if rows else 0
    return {"status": "ok", "quotes": n, "delay": capability(env)["label"]}


def refresh(feed, env: Mapping[str, str], instruments: Iterable[str], now: float | None = None) -> list[dict]:
    """Free-plan refresh: for each instrument, fetch only the completed sessions the store is missing (15m + daily) and rebuild 1h.
    Costs zero API calls when the store is already up to the last completed ET day."""
    from atlas.feeds import massive_backfill as MB
    if not has_key(env):
        return []
    return MB.run(feed, list(instruments), "ABC", now=now)


def stock_instruments(feed) -> list[str]:
    ids = [i.id for i in feed.instruments.all() if i.asset_class in ("equity", "etf") and "polygon" in (i.provider_symbols or {})]
    from atlas.feeds.massive_backfill import PRIORITY
    return [i for i in PRIORITY if i in ids] + [i for i in ids if i not in PRIORITY]


def status_for(feed, symbol: str, env: Mapping[str, str], now: float | None = None) -> dict[str, Any]:
    """Latest stored Massive bar for a symbol, its age, and the plain-language delay."""
    now = time.time() if now is None else now
    cap = capability(env)
    out: dict[str, Any] = {"symbol": symbol, "capability": cap, "last_bar": None, "execution_permission": "none"}
    for iv in ("15m", "1d"):
        bars = feed.store.bars(symbol, iv, provider="polygon")
        if bars:
            b = bars[-1]
            out["last_bar"] = {"interval": iv, "bar_end": int(b.bar_end), "bar_end_toronto": datetime.fromtimestamp(b.bar_end, TORONTO).strftime("%Y-%m-%d %H:%M %Z"),
                               "age_hours": round((now - b.bar_end) / 3600, 1), "close": b.close, "count": len(bars)}
            break
    return out


def live_predictions(feed, symbols: Iterable[str], env: Mapping[str, str], now: float | None = None) -> list[dict]:
    """The directional research model on the newest closed bar for each symbol on a 15m timeframe (crypto pools are trained at 15m/1h/1d; stocks: the finest the
    free plan serves). Research display only: execution_permission none. A symbol with no model or too little history says so."""
    from atlas.ai.ml.dataset import load_series
    from atlas.ai.ml.directional.live import directional_prediction
    now = time.time() if now is None else now
    rows = []
    from atlas.feeds.universe import resolve
    for raw in symbols:
        up = str(raw).upper()
        sym = resolve(raw) or (up.replace("-USD", "USDT") if up.endswith("-USD") else up)   # same symbol mapping as the chart overlays
        crypto = sym.endswith("USDT")
        iv = "15m"   # crypto's live tape is 1m but the directional pools are trained at 15m/1h/1d; stocks: 15m is the finest the free plan serves
        try:
            bars = list(load_series(feed, sym, iv).bars)
            closed = [b for b in bars if b.start + b.duration <= now]
            p = directional_prediction(sym, iv, closed, ref_loader=lambda r, i: load_series(feed, r, i).bars)
        except Exception as ex:
            p = {"status": "error", "reason": type(ex).__name__ + ": " + str(ex)[:160], "label": "no prediction"}
        delay = ("live tape (public crypto feeds)" if crypto else capability(env)["label"])
        rows.append({"symbol": sym, "asset": "crypto" if crypto else "stock", "interval": iv, "delay": delay,
                     "status": p.get("status"), "label": p.get("label"), "reason": p.get("reason"), "direction": p.get("direction"),
                     "probability": p.get("probability"), "as_of_toronto": p.get("as_of_toronto"), "horizon_bars": p.get("horizon_bars"),
                     "take": p.get("take"), "execution_permission": "none"})
    return rows
