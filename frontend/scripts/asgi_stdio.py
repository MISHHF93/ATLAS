"""Serve ASGI messages over stdio for the single-port Node host; opens no sockets."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from urllib.parse import urlsplit, unquote

# Reserve stdout for protocol frames. Application prints belong on stderr.
wire = sys.stdout
sys.stdout = sys.stderr
from pathlib import Path  # noqa: E402

from atlas.envfile import load_env_file  # noqa: E402

load_env_file(Path(__file__).resolve().parents[2] / ".env")   # keys added to .env take effect on restart
from atlas.api.app import app  # noqa: E402


async def main() -> None:
    queues: dict[str, asyncio.Queue] = {}
    tasks: dict[str, asyncio.Task] = {}

    async def emit(identifier: str, message: dict) -> None:
        packet = {"id": identifier, **message}
        if "body" in packet:
            packet["body"] = base64.b64encode(packet["body"]).decode()
        if packet.get("bytes") is not None:
            packet["bytes"] = base64.b64encode(packet["bytes"]).decode()
        if "headers" in packet:
            packet["headers"] = [[k.decode("latin1"), v.decode("latin1")] for k, v in packet["headers"]]
        wire.write(json.dumps(packet, allow_nan=False) + "\n")
        wire.flush()

    async def serve(packet: dict) -> None:
        identifier = packet["id"]
        url = urlsplit(packet["url"])
        kind = packet["type"]
        scope = {
            "type": kind, "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "scheme": "ws" if kind == "websocket" else "http",
            "path": unquote(url.path), "raw_path": url.path.encode(),
            "query_string": url.query.encode(), "root_path": "",
            "headers": [(k.encode("latin1"), str(v).encode("latin1")) for k, v in packet.get("headers", {}).items()],
            "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 3000),
        }
        if kind == "http":
            scope["method"] = packet.get("method", "GET")
            queues[identifier].put_nowait({"type": "http.request", "body": base64.b64decode(packet.get("body", "")), "more_body": False})
        else:
            scope["subprotocols"] = []
            queues[identifier].put_nowait({"type": "websocket.connect"})
        try:
            await app(scope, queues[identifier].get, lambda message: emit(identifier, message))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"ASGI request failed: {type(exc).__name__}", file=sys.stderr)
            await emit(identifier, {"type": "bridge.error"})
        finally:
            queues.pop(identifier, None)
            tasks.pop(identifier, None)

    async with app.router.lifespan_context(app):
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                packet = json.loads(line)
                identifier = packet["id"]
                if packet["type"] in ("http", "websocket"):
                    if len(tasks) >= 256:
                        await emit(identifier, {"type": "bridge.error"})
                        continue
                    queues[identifier] = asyncio.Queue(maxsize=64)
                    tasks[identifier] = asyncio.create_task(serve(packet))
                elif packet["type"] == "cancel":
                    if task := tasks.get(identifier):
                        task.cancel()
                elif identifier in queues:
                    queues[identifier].put_nowait({k: v for k, v in packet.items() if k != "id"})
            except (ValueError, KeyError, asyncio.QueueFull):
                print("Invalid or overloaded ASGI channel", file=sys.stderr)
        for task in list(tasks.values()):
            task.cancel()
        await asyncio.gather(*list(tasks.values()), return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
