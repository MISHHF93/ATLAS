"""Shared websocket loop: connect, subscribe, parse, reconnect with jittered exponential backoff."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Iterable

from ..core import backoff_delays


async def ws_loop(adapter, url: str, on_open: Callable[[Any], Awaitable[None]],
                  parse: Callable[[Any, int], Iterable[Any]], max_reconnects: int | None = None):  # pragma: no cover - network
    import websockets
    h = adapter.health()
    n = 0
    delays = backoff_delays(attempts=10**9)
    while max_reconnects is None or n <= max_reconnects:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                h.stream_connected = True
                await on_open(ws)
                delays = backoff_delays(attempts=10**9)  # reset after a good connect
                async for raw in ws:
                    now = int(time.time())
                    h.last_message_at = now
                    msg = json.loads(raw)
                    for item in parse(msg, now):
                        yield item
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any disconnect -> backoff + reconnect
            h.last_error, h.last_error_at = f"ws: {e!r}"[:200], int(time.time())
        h.stream_connected = False
        h.reconnects += 1
        n += 1
        await asyncio.sleep(next(delays, 60.0))
