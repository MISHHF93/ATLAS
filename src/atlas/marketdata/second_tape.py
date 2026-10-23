"""One-second bars from Coinbase's public last trade.

Coinbase candles begin at 60 seconds. This tape remembers each new last trade
and folds it into the UTC second it printed. The forming second updates as
soon as a newer trade arrives. A second with no new trade is left empty.
Equities are withheld. Nothing here submits an order.
"""

from __future__ import annotations

import threading
import time
import math
from datetime import datetime, timezone
from typing import Any

KEEP_SECONDS = 90
WATCH_SECONDS = 20.0

_LOCK = threading.Lock()
_BARS: dict[str, dict[int, dict[str, Any]]] = {}
_SEEN: dict[str, datetime] = {}
_WATCHED: dict[str, float] = {}
_MISSES: dict[str, int] = {}
_LAST_IDS: dict[str, int] = {}
_GAPS: dict[str, set[int]] = {}


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


def latest_trade_time(symbol: str) -> datetime | None:
    """Last event time, or the last retained bar's second after a restart."""
    with _LOCK:
        if symbol in _SEEN:
            return _SEEN[symbol]
        book = _BARS.get(symbol)
        return datetime.fromtimestamp(max(book), tz=timezone.utc) if book else None


def _flag_bar(bar: dict[str, Any], second: int, gaps: set[int]) -> None:
    bar['incomplete'] = True
    end = second
    while end + 1 in gaps:
        end += 1
    # Persist the window with the received candle so a future heartbeat gap
    # cannot disappear when the process restarts before its next match.
    bar['incomplete_through'] = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()


def mark_gap(symbol: str, start: str | datetime, end: str | datetime) -> set[str]:
    """Flag received candles across a known missing-event window.

    Keep the received prices visible, but never imply that their OHLC includes
    the missing events. The bounded second set also flags bars arriving later
    within this window, without manufacturing candles for empty seconds.
    """
    beginning = _parse_time(start) if isinstance(start, str) else start
    ending = _parse_time(end) if isinstance(end, str) else end
    if beginning is None or ending is None:
        return set()
    first, last = sorted((int(beginning.timestamp()), int(ending.timestamp())))
    with _LOCK:
        book = _BARS.get(symbol, {})
        seconds = _GAPS.setdefault(symbol, set())
        latest = max(last, max(book, default=last), max(seconds, default=last))
        cutoff = latest - KEEP_SECONDS
        seconds.intersection_update(range(cutoff, latest + 1))
        seconds.update(range(max(first, cutoff), last + 1))
        changed = set()
        for second, bar in book.items():
            if second in seconds:
                _flag_bar(bar, second, seconds)
                changed.add(str(bar['timestamp']))
        return changed


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
    if when is None or not math.isfinite(price) or not math.isfinite(size) or price <= 0:
        return
    second = int(when.timestamp())
    with _LOCK:
        previous = _SEEN.get(sym)
        trade_id = ticker.get("trade_id")
        if trade_id is not None:
            trade_id = int(trade_id)
            if trade_id <= _LAST_IDS.get(sym, -1) or (previous is not None and when < previous):
                return
            _LAST_IDS[sym] = trade_id
        elif previous is not None and when <= previous:
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
        gaps = _GAPS.get(sym)
        if gaps is not None:
            gaps.intersection_update(range(second - KEEP_SECONDS, second + KEEP_SECONDS + 1))
            if second in gaps:
                _flag_bar(book[second], second, gaps)
            if not gaps:
                _GAPS.pop(sym, None)
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
    return [dict(row) for row in rows[-KEEP_SECONDS:]]


def snapshot(symbol: str, *, sampling: bool, register_interest: bool = True) -> dict[str, Any]:
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
                "No connected one-second trade feed for this listing. "
                "The native live viewer can use available API candles at their actual resolution."
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
    if register_interest:
        note_interest(sym)
    health = _feed_health(sym)
    if health.get("supported") is False:
        return {**base, "bar_count": 0, "candles": [], "last_close": None,
                "chart_source": "withheld", "feed_origin": "none", "prints": 0,
                "feed_health": health, "notice": health.get("reason", "No connected real-time feed for this symbol.")}
    from atlas.marketdata.live_artifacts import artifact_store
    store = artifact_store()
    if store is not None:
        with _LOCK:
            if sym not in _BARS:
                restored = store.recent_bars(sym)
                _BARS[sym] = {int(datetime.fromisoformat(row["timestamp"]).timestamp()): row for row in restored}
                for second, row in _BARS[sym].items():
                    through = _parse_time(str(row.get('incomplete_through', '')))
                    if row.get('incomplete') and through is not None:
                        end = int(through.timestamp())
                        _GAPS.setdefault(sym, set()).update(range(max(second, end - KEEP_SECONDS), end + 1))
                gaps = _GAPS.get(sym)
                if gaps:
                    gaps.intersection_update(range(max(gaps) - KEEP_SECONDS, max(gaps) + 1))
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
            "Coinbase WebSocket matches update the forming second. "
            "Seconds without trades stay empty. Known feed gaps are recorded; complete exchange coverage is not guaranteed. This is not a TradingView bar."
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
        "feed_health": _feed_health(sym),
    }


def _feed_health(symbol: str) -> dict[str, Any]:
    from atlas.marketdata.public_stream import feed_health
    return feed_health(symbol)
