"""Coinbase public matches and heartbeat capture, with explicit gap telemetry."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import math
import threading
import time
from typing import Any

from atlas.marketdata.live_artifacts import artifact_store
from atlas.marketdata.second_tape import fold_trade, latest_trade_time, mark_gap, snapshot, watched_symbols

_LOCK = threading.Lock()
_HEALTH: dict[str, dict[str, Any]] = {}
_STATE: dict[str, Any] = {"transport": "websocket", "connection": "connecting", "reconnects": 0}
_IDS: dict[str, int] = {}
_INTERRUPTED: set[str] = set()
CORE_SYMBOLS = ("BTC-USD", "ETH-USD", "SOL-USD")
_AVAILABLE: set[str] | None = None


def refresh_products() -> None:
    from atlas.marketdata.public_quotes import _get_json
    global _AVAILABLE
    products = _get_json("https://api.exchange.coinbase.com/products")
    if not isinstance(products, list):
        raise ValueError("Invalid provider product registry")
    available = {str(row["id"]) for row in products if row.get("quote_currency") == "USD" and row.get("status") == "online" and not row.get("trading_disabled")}
    with _LOCK:
        _AVAILABLE = available
    store = artifact_store()
    from atlas.marketdata.data_rights import check_data_use
    if store and any(check_data_use("coinbase_exchange_public", symbol, 1, "retention")["allowed"] for symbol in CORE_SYMBOLS):
        stamp = datetime.now(timezone.utc).isoformat()
        store.record([("product_registry", "", stamp, {"products": products, "received_at": stamp})])


def eligible_symbols(requested: set[str]) -> set[str]:
    with _LOCK:
        available = set(_AVAILABLE) if _AVAILABLE is not None else set(CORE_SYMBOLS)
    return requested & available


def feed_health(symbol: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with _LOCK:
        result = {**_STATE, **_HEALTH.get(symbol, {})}
        supported = symbol in (_AVAILABLE if _AVAILABLE is not None else CORE_SYMBOLS)
    result["supported"] = supported
    if not supported:
        result.update(connection="unavailable", reason="No verified active USD product on the connected Coinbase feed. Use the candle chart or connect an entitled provider for this listing.")
    for source, target in (("last_received_at", "receive_age_seconds"), ("last_exchange_at", "trade_age_seconds"), ("heartbeat_at", "heartbeat_age_seconds")):
        stamp = result.get(source)
        result[target] = max(0, (now - datetime.fromisoformat(stamp)).total_seconds()) if stamp else None
    return result


def note_stream_interruption() -> None:
    """The next received match must bound the disconnected time window."""
    with _LOCK:
        _INTERRUPTED.update(_IDS)


def process_batch(messages: list[tuple[dict[str, Any], str]]) -> None:
    store = artifact_store()
    artifacts = []
    changed: dict[str, set[str]] = {}
    for message, received in messages:
        kind = str(message.get("type", "unknown"))
        symbol = str(message.get("product_id", ""))
        key = str(message.get("trade_id", received)) if kind in {"match", "last_match"} else received
        artifacts.append(("raw_" + kind, symbol, key, {"message": message, "received_at": received}))
        if kind == "error":
            raise ValueError("Provider subscription rejected: " + str(message.get("message", "unknown")))
        if kind == "heartbeat":
            with _LOCK:
                _HEALTH.setdefault(symbol, {})["heartbeat_at"] = received
            last = _IDS.get(symbol)
            if last is not None and int(message.get("last_trade_id", last)) > last:
                artifacts.append(("gap", symbol, "heartbeat:" + received, {"reason": "heartbeat_ahead_of_received_matches", "last_received_trade_id": last, "heartbeat_trade_id": message.get("last_trade_id")}))
                with _LOCK:
                    _HEALTH.setdefault(symbol, {})["coverage"] = "gap_detected"
                previous = latest_trade_time(symbol)
                if previous is not None:
                    changed.setdefault(symbol, set()).update(mark_gap(symbol, previous, str(message.get("time") or received)))
        if kind != "match":
            continue
        try:
            trade_id = int(message["trade_id"])
            exchange = datetime.fromisoformat(str(message["time"]).replace("Z", "+00:00"))
            price, size = float(message["price"]), float(message["size"])
            if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size < 0:
                raise ValueError("Invalid price or size")
        except (KeyError, ValueError, TypeError):
            artifacts.append(("rejected", symbol, received, {"reason": "invalid_match", "message": message}))
            continue
        last = _IDS.get(symbol)
        if last is not None and trade_id <= last:
            continue
        # Restore retained bars before folding the first new event. Otherwise a
        # process restart could silently replace the prior bar with a clean one.
        if last is None and latest_trade_time(symbol) is None:
            snapshot(symbol, sampling=True, register_interest=False)
        previous = latest_trade_time(symbol)
        with _LOCK:
            interrupted = symbol in _INTERRUPTED
            _INTERRUPTED.discard(symbol)
        discontinuity = last is not None and trade_id != last + 1
        if discontinuity:
            artifacts.append(("gap", symbol, str(trade_id), {"after_trade_id": last, "before_trade_id": trade_id, "reason": "nonconsecutive_trade_ids"}))
            with _LOCK:
                _HEALTH.setdefault(symbol, {})["coverage"] = "gap_detected"
        if previous is not None and (discontinuity or interrupted or last is None):
            changed.setdefault(symbol, set()).update(mark_gap(symbol, previous, exchange))
            if not discontinuity:
                artifacts.append(("gap", symbol, "resume:" + str(trade_id), {
                    "reason": "capture_resumed_without_continuous_coverage",
                    "from": previous.isoformat(), "through": exchange.isoformat()}))
                with _LOCK:
                    _HEALTH.setdefault(symbol, {})["coverage"] = "gap_detected"
        _IDS[symbol] = trade_id
        fold_trade({"symbol": symbol, "price": price, "size": size, "observed_at": exchange.isoformat(), "trade_id": trade_id})
        changed.setdefault(symbol, set()).add(exchange.replace(microsecond=0).isoformat())
        with _LOCK:
            row = _HEALTH.setdefault(symbol, {})
            row.update({"last_received_at": received, "last_exchange_at": exchange.isoformat(),
                        "exchange_to_receive_ms": (datetime.fromisoformat(received) - exchange).total_seconds() * 1000,
                        "last_trade_id": trade_id, "matches_received": int(row.get("matches_received", 0)) + 1})
            row.setdefault("coverage", "received_stream_only")
    if store:
        for symbol, stamps in changed.items():
            tape = snapshot(symbol, sampling=True, register_interest=False)
            artifacts.extend(("bar", symbol, str(bar["timestamp"]), bar) for bar in tape["candles"] if bar["timestamp"] in stamps)
        from atlas.marketdata.data_rights import check_data_use
        admitted = {symbol for _, symbol, _, _ in artifacts
                    if symbol and check_data_use("coinbase_exchange_public", symbol, 1, "retention")["allowed"]}
        retained = [row for row in artifacts if row[1] in admitted]
        if retained:
            store.record(retained)


async def run_public_stream(stop: asyncio.Event) -> None:
    import websockets

    delay = 1.0
    try:
        await asyncio.to_thread(refresh_products)
    except Exception:
        pass  # Core products can connect; unverified additional symbols cannot.
    product_refresh = time.monotonic()
    store = artifact_store()
    if store and store.manifest()["counts"]:
        stamp = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(store.record, [("connection_gap", "", stamp, {"reason": "capture_process_restarted", "at": stamp})])
    while not stop.is_set():
        batch: list[tuple[dict[str, Any], str]] = []
        try:
            async with websockets.connect("wss://ws-feed.exchange.coinbase.com", open_timeout=10,
                                          ping_interval=20, ping_timeout=10, max_queue=4096) as ws:
                subscribed = eligible_symbols(set(CORE_SYMBOLS) | set(watched_symbols()))
                await ws.send(json.dumps({"type": "subscribe", "product_ids": sorted(subscribed), "channels": ["matches", "heartbeat"]}))
                with _LOCK:
                    _STATE.update(connection="connected", last_error=None)
                delay = 1.0
                flushed = time.monotonic()
                checked = flushed
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                        batch.append((json.loads(raw), datetime.now(timezone.utc).isoformat()))
                    except TimeoutError:
                        # Ping verifies the socket independently of trading activity.
                        pong = await ws.ping()
                        await asyncio.wait_for(pong, timeout=5)
                    now = time.monotonic()
                    if batch and (now - flushed >= .05 or len(batch) >= 200):
                        await asyncio.to_thread(process_batch, batch)
                        batch = []
                        flushed = now
                    if now - checked >= 1:
                        if now - product_refresh >= (3600 if _AVAILABLE is not None else 60):
                            try:
                                await asyncio.to_thread(refresh_products)
                            except Exception:
                                pass
                            product_refresh = now
                        desired = eligible_symbols(set(CORE_SYMBOLS) | set(watched_symbols()))
                        for action, products in (("subscribe", desired - subscribed), ("unsubscribe", subscribed - desired)):
                            if products:
                                await ws.send(json.dumps({"type": action, "product_ids": sorted(products), "channels": ["matches", "heartbeat"]}))
                        subscribed = desired
                        checked = now
                if batch:
                    await asyncio.to_thread(process_batch, batch)
        except asyncio.CancelledError:
            if batch:
                await asyncio.to_thread(process_batch, batch)
            raise
        except Exception as exc:
            if batch:
                # Preserve the messages already received before reconnecting.
                try:
                    await asyncio.to_thread(process_batch, batch)
                except Exception:
                    pass  # The connection-gap record below exposes this failure.
            note_stream_interruption()
            with _LOCK:
                _STATE.update(connection="reconnecting", last_error=type(exc).__name__, reconnects=int(_STATE["reconnects"]) + 1)
            store = artifact_store()
            if store:
                stamp = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(store.record, [("connection_gap", "", stamp, {"error": type(exc).__name__, "at": stamp})])
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(30, delay * 2)
