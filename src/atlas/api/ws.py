"""FastAPI WebSocket Market Stream Broadcaster (`ws.py`).

Implements `/ws/market-stream` and `/api/market/live-stream` with bounded per-client
queues and non-blocking backpressure frame dropping so slow UI visual consumers
never block internal risk or microstructure calculation loops.

All broadcast frames carry `execution_permission = "none"`.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from atlas.marketdata.live_stream import LiveMarketDataGateway, LiveTickFrame


class MarketStreamBroadcaster:
    """High-throughput tick broadcaster with non-blocking backpressure frame dropping."""

    def __init__(self, max_client_queue_size: int = 32) -> None:
        self.max_client_queue_size = max(1, max_client_queue_size)
        self._client_queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self.dropped_frames_count: int = 0
        self.broadcast_frames_count: int = 0

    def register_client_queue(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.max_client_queue_size)
        self._client_queues.add(queue)
        return queue

    def unregister_client_queue(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._client_queues.discard(queue)

    def broadcast_non_blocking(self, frame: LiveTickFrame | dict[str, Any]) -> dict[str, int]:
        """Pushes a normalized tick payload to all connected client queues without blocking.

        If a client queue is full (lagging visual consumer), drops the oldest buffered frame
        and enqueues the newest tick frame immediately.
        """
        payload = frame.to_payload() if isinstance(frame, LiveTickFrame) else dict(frame)
        payload["execution_permission"] = "none"
        delivered = 0
        dropped = 0
        for q in list(self._client_queues):
            if q.full():
                try:
                    q.get_nowait()
                    dropped += 1
                    self.dropped_frames_count += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(payload)
                delivered += 1
                self.broadcast_frames_count += 1
            except asyncio.QueueFull:
                dropped += 1
                self.dropped_frames_count += 1
        return {"delivered": delivered, "dropped": dropped}


def register_market_stream_ws(
    app: FastAPI,
    gateway: LiveMarketDataGateway,
    broadcaster: MarketStreamBroadcaster | None = None,
) -> MarketStreamBroadcaster:
    stream_broadcaster = broadcaster or MarketStreamBroadcaster(max_client_queue_size=32)
    gateway.add_listener(stream_broadcaster.broadcast_non_blocking)

    @app.get("/api/market/live-stream", include_in_schema=False)
    def get_live_stream_status(symbol: str = "BTC-USD") -> dict[str, Any]:
        sym = symbol.upper()
        latest = gateway.ring_buffer.latest(sym)
        if latest is None and gateway.demo_mode:
            default_price = 67840.75 if sym == "BTC-USD" else 584.20 if sym == "SPY" else 138.60
            latest = gateway.ingest_tick(
                symbol=sym,
                price=default_price,
                size=1.25,
                side="buy",
                spread=0.04,
            )
        return {
            "status": "ok",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "tick": latest.to_payload() if latest else None,
            "gateway": gateway.status_snapshot(),
            "broadcaster": {
                "active_clients": len(stream_broadcaster._client_queues),
                "broadcast_frames_count": stream_broadcaster.broadcast_frames_count,
                "dropped_frames_count": stream_broadcaster.dropped_frames_count,
            },
            "execution_permission": "none",
        }

    @app.get("/api/market/module02-snapshot", include_in_schema=False)
    def get_module02_dual_track_snapshot(track: str = "all") -> dict[str, Any]:
        """Returns real-time streaming tick snapshots across all 9 Module 02 dual-track listings
        (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`, `BTC-USD`, `ETH-USD`, `SOL-USD`) along with
        the deterministic Remaining-Room HUD from `ActionableControlPlaneEngine`.
        """
        universe = gateway.ingest_dual_track_universe_snapshot()
        for pkt in universe:
            stream_broadcaster.broadcast_non_blocking(pkt)
        filtered = (
            [u for u in universe if u["track"] == track]
            if track in ("open_market", "competition")
            else universe
        )
        hud = (
            gateway.control_engine.get_remaining_room_hud(
                track=track if track in ("open_market", "competition") else "competition"  # type: ignore[arg-type]
            )
            if gateway.control_engine is not None
            else None
        )
        return {
            "status": "ok",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "track_filter": track,
            "listings": filtered,
            "remaining_room_hud": hud,
            "gateway": gateway.status_snapshot(),
            "broadcaster": {
                "active_clients": len(stream_broadcaster._client_queues),
                "broadcast_frames_count": stream_broadcaster.broadcast_frames_count,
                "dropped_frames_count": stream_broadcaster.dropped_frames_count,
            },
            "execution_permission": "none",
        }

    @app.websocket("/ws/market-stream")
    async def websocket_market_stream(websocket: WebSocket, symbol: str = "BTC-USD") -> None:
        await websocket.accept()
        client_id = uuid4().hex
        subscribed = {symbol.upper()}
        gateway.subscribe(list(subscribed), client_id)
        if gateway.demo_mode and gateway.ring_buffer.latest(symbol) is None:
            gateway.ingest_dual_track_universe_snapshot()
        queue = stream_broadcaster.register_client_queue()
        latest = gateway.ring_buffer.latest(symbol)
        await websocket.send_json(latest.to_payload() if latest else {
            "event": "awaiting_data", "symbol": symbol.upper(), "execution_permission": "none"
        })

        async def send_frames() -> None:
            while True:
                payload = await queue.get()
                if payload.get("symbol") in subscribed:
                    await asyncio.wait_for(websocket.send_json(payload), timeout=5)

        async def receive_commands() -> None:
            while True:
                raw = await websocket.receive_text()
                if raw.lower() == "close":
                    return
                if raw.lower() == "ping":
                    latest = gateway.ring_buffer.latest(symbol)
                    await websocket.send_json(latest.to_payload() if latest else {
                        "event": "heartbeat", "symbol": symbol.upper(), "execution_permission": "none"
                    })
                    continue
                try:
                    command = json.loads(raw)
                    if not isinstance(command, dict):
                        raise ValueError("Expected a command object")
                    action = command.get("action")
                    if action == "close":
                        return
                    symbols = command.get("symbols", [])
                    if not isinstance(symbols, list) or len(symbols) > 100 or not all(isinstance(x, str) for x in symbols):
                        raise ValueError("Expected up to 100 symbol strings")
                    if action == "subscribe":
                        result = gateway.subscribe(symbols, client_id)
                        subscribed.update(result["subscribed_symbols"])
                    elif action == "unsubscribe":
                        result = gateway.unsubscribe(symbols, client_id)
                        subscribed.difference_update(result["unsubscribed_symbols"])
                    else:
                        raise ValueError("Unknown action")
                    await websocket.send_json({"event": "subscription_update", "action": action, **result})
                except (ValueError, TypeError) as exc:
                    await websocket.send_json({"event": "error", "detail": str(exc), "execution_permission": "none"})

        tasks = [asyncio.create_task(send_frames()), asyncio.create_task(receive_commands())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError):
            return
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            stream_broadcaster.unregister_client_queue(queue)
            gateway.unsubscribe_client_all(client_id)

    return stream_broadcaster
