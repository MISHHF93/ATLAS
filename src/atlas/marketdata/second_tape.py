"""One-second bars from Coinbase's public last trade.

Coinbase candles begin at 60 seconds. This tape remembers each new last trade
and folds it into the UTC second it printed. The forming second updates as
soon as a newer trade arrives. A second with no new trade is left empty.
Equities are withheld. Nothing here submits an order.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

KEEP_SECONDS = 90
WATCH_SECONDS = 20.0

_LOCK = threading.Lock()
_BARS: dict[str, dict[int, dict[str, Any]]] = {}
_SEEN: dict[str, datetime] = {}
_WATCHED: dict[str, float] = {}
_MISSES: dict[str, int] = {}


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def note_interest(symbol: str) -> None:
    sym = symbol.strip().upper()
    if not sym.endswith("-USD"):
        return
    with _LOCK:
        _WATCHED[sym] = time.monotonic()


def watched_symbols() -> list[str]:
    now = time.monotonic()
    with _LOCK:
        fresh = [sym for sym, seen in _WATCHED.items() if now - seen <= WATCH_SECONDS]
        fresh.sort(key=lambda sym: _WATCHED[sym], reverse=True)
        return fresh[:3]


def fold_trade(ticker: dict[str, Any]) -> None:
    """Fold one new last trade. The same trade time is ignored."""
    sym = str(ticker.get("symbol") or "").upper()
    observed = ticker.get("observed_at")
    if not sym or not isinstance(observed, str):
        return
    when = _parse_time(observed)
    try:
        price = float(ticker.get("price") or 0)
        size = float(ticker.get("size") or 0)
    except (TypeError, ValueError):
        return
    if when is None or price <= 0:
        return
    second = int(when.timestamp())
    with _LOCK:
        previous = _SEEN.get(sym)
        if previous is not None and when <= previous:
            return
        _SEEN[sym] = when
        _MISSES[sym] = 0
        book = _BARS.setdefault(sym, {})
        bar = book.get(second)
        if bar is None:
            book[second] = {
                "timestamp": datetime.fromtimestamp(second, tz=timezone.utc).isoformat(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": max(size, 0.0),
                "prints": 1,
            }
        else:
            bar["high"] = max(float(bar["high"]), price)
            bar["low"] = min(float(bar["low"]), price)
            bar["close"] = price
            bar["volume"] = float(bar["volume"]) + max(size, 0.0)
            bar["prints"] = int(bar["prints"]) + 1
        stale = [key for key in book if key < second - KEEP_SECONDS]
        for key in stale:
            book.pop(key, None)


def note_miss(symbol: str) -> None:
    sym = symbol.strip().upper()
    with _LOCK:
        _MISSES[sym] = _MISSES.get(sym, 0) + 1


def _rows(symbol: str) -> list[dict[str, Any]]:
    book = _BARS.get(symbol, {})
    rows = [book[key] for key in sorted(book)]
    return rows[-KEEP_SECONDS:]


def snapshot(symbol: str, *, sampling: bool) -> dict[str, Any]:
    """Current one-second bars. Sampling off, or an equity, stays withheld."""
    sym = symbol.strip().upper()
    base = {
        "symbol": sym,
        "bucket_seconds": 1,
        "orders_submitted": 0,
        "execution_permission": "none",
    }
    if not sym.endswith("-USD"):
        return {
            **base,
            "bar_count": 0,
            "candles": [],
            "last_close": None,
            "chart_source": "withheld",
            "feed_origin": "none",
            "prints": 0,
            "notice": (
                "No public 1-second print for this name. "
                "The minute chart is the TradingView picture. Nothing was sent."
            ),
        }
    if not sampling:
        return {
            **base,
            "bar_count": 0,
            "candles": [],
            "last_close": None,
            "chart_source": "withheld",
            "feed_origin": "none",
            "prints": 0,
            "notice": "Public last-trade sampling is off in this process. Nothing was sent.",
        }
    note_interest(sym)
    with _LOCK:
        rows = _rows(sym)
        misses = _MISSES.get(sym, 0)
    prints = sum(int(row.get("prints") or 0) for row in rows)
    if not rows and misses > 0:
        notice = "Coinbase returned no last trade for this symbol. Nothing was sent."
    elif not rows:
        notice = "Waiting for the next public trade. The forming second updates when that trade prints."
    else:
        notice = (
            "Each new Coinbase last trade updates the current second immediately. "
            "A second with no new trade stays empty. This is not every match and not a TradingView bar."
        )
    last = float(rows[-1]["close"]) if rows else None
    return {
        **base,
        "bar_count": len(rows),
        "candles": rows,
        "last_close": last,
        "chart_source": "public_last_trade",
        "feed_origin": "coinbase_exchange_public",
        "prints": prints,
        "notice": notice,
    }
