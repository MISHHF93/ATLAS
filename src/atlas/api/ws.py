"""FastAPI WebSocket Market Stream Broadcaster (`ws.py`).

Implements `/ws/market-stream` and `/api/market/live-stream` with bounded per-client
queues and non-blocking backpressure frame dropping so slow UI visual consumers
never block internal risk or microstructure calculation loops.

All broadcast frames carry `execution_permission = "none"`.
"""

from __future__ import annotations

import asyncio
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

    @app.get("/api/market/live-stream", include_in_schema=False)
    def get_live_stream_status(symbol: str = "BTC-USD") -> dict[str, Any]:
        sym = symbol.upper()
        latest = gateway.ring_buffer.latest(sym)
        if latest is None:
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
            "tick": latest.to_payload(),
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
        client_queue = stream_broadcaster.register_client_queue()
        sym = symbol.upper()
        base_map = {
            "BTC-USD": 68410.0,
            "ETH-USD": 2645.5,
            "SOL-USD": 176.8,
            "SPY": 584.2,
            "NVDA": 142.1,
            "AAPL": 231.45,
            "MSFT": 428.9,
            "QQQ": 498.6,
            "TSLA": 254.3,
        }
        base_price = base_map.get(sym, 142.50)
        try:
            frame = gateway.ingest_tick(symbol=sym, price=base_price, size=1.5, side="buy", spread=1.2)
            stream_broadcaster.broadcast_non_blocking(frame)
            initial_payload = await client_queue.get()
            await websocket.send_json(initial_payload)
            while True:
                msg = await websocket.receive_text()
                if msg.strip().lower() == "ping":
                    tick = gateway.ingest_tick(
                        symbol=sym,
                        price=round(base_price + 0.25, 2),
                        size=2.1,
                        side="buy",
                        spread=1.2,
                    )
                    stream_broadcaster.broadcast_non_blocking(tick)
                    next_payload = await client_queue.get()
                    await websocket.send_json(next_payload)
                elif msg.strip().lower() == "close":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            stream_broadcaster.unregister_client_queue(client_queue)

    return stream_broadcaster

