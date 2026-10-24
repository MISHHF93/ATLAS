"""ATLAS live ingest service.

* Binance combined websocket ``<pair>@kline_1m`` for every crypto instrument: every update upserts ``last_quotes``
  (kind=kline); a closed kline (``k.x``) is ingested as a confirmed 1m bar into ``bar_revisions`` (idempotent).
* Coinbase ``ticker`` channel (<BASE>-USD) and Kraken v2 ``ticker`` (<BASE>/USD): live cross-check quotes in
  ``last_quotes`` (provider coinbase / kraken). They never write bars into the USDT series.
* Yahoo spark polling for US equities/ETFs and CME futures: every ``open_poll`` s while that market is open, every
  ``closed_poll`` s when closed (to pick up the official close). Labelled ``yahoo`` -> status ``delayed`` when open.

Writes are buffered and flushed every second in one transaction. The API/UI read the same SQLite (WAL) store and push
updates over SSE (``/api/feeds/stream``). Run with ``python scripts/run_live_ingest.py``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Iterable

from .core import FeedBar
from .instruments import InstrumentMaster
from .status import market_open
from .store import FeedStore

log = logging.getLogger("atlas.feeds.live")
BINANCE_WS = ("wss://data-stream.binance.vision/stream", "wss://stream.binance.com:9443/stream")
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
KRAKEN_WS = "wss://ws.kraken.com/v2"
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark"


# ---------------------------------------------------------------- pure parsers (unit-tested)
def parse_binance(msg: dict, now: float, by_pair: dict[str, str]):
    d = msg.get("data") or msg
    k = d.get("k") if isinstance(d, dict) else None
    if not k:
        return [], []
    iid = by_pair.get(k["s"].upper())
    if not iid:
        return [], []
    q = {"instrument": iid, "provider": "binance", "price": float(k["c"]), "event_time": d.get("E", k["T"]) / 1000,
         "receipt_time": now, "kind": "kline", "provider_symbol": k["s"]}
    bars = []
    if k.get("x"):
        bars.append(FeedBar(iid, "1m", int(k["t"] // 1000), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]),
                            float(k["v"]), "binance", int(now), True, k["s"]))
    return [q], bars


def parse_coinbase(msg: dict, now: float, by_product: dict[str, str]):
    if msg.get("type") != "ticker" or msg.get("product_id") not in by_product:
        return []
    from datetime import datetime
    t = msg.get("time")
    et = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() if t else now
    return [{"instrument": by_product[msg["product_id"]], "provider": "coinbase", "price": float(msg["price"]),
             "event_time": et, "receipt_time": now, "prev_close": float(msg["open_24h"]) if msg.get("open_24h") else None,
             "kind": "ticker", "provider_symbol": msg["product_id"]}]


def parse_kraken(msg: dict, now: float, by_symbol: dict[str, str]):
    if msg.get("channel") != "ticker" or msg.get("type") not in ("snapshot", "update"):
        return []
    out = []
    for d in msg.get("data") or []:
        iid = by_symbol.get(d.get("symbol"))
        if iid and d.get("last"):
            # Kraken v2 ticker has no event timestamp: receipt time is the honest observation time.
            out.append({"instrument": iid, "provider": "kraken", "price": float(d["last"]), "event_time": now,
                        "receipt_time": now, "kind": "ticker", "provider_symbol": d["symbol"]})
    return out


def parse_spark(js: dict, now: float, by_yahoo: dict[str, str]):
    out = []
    for r in (js.get("spark") or {}).get("result") or []:
        iid = by_yahoo.get(r.get("symbol"))
        resp = (r.get("response") or [None])[0] or {}
        m = resp.get("meta") or {}
        p, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
        if iid and p and t:
            out.append({"instrument": iid, "provider": "yahoo", "price": float(p), "event_time": float(t), "receipt_time": now,
                        "prev_close": m.get("previousClose") or m.get("chartPreviousClose"), "kind": "spark",
                        "provider_symbol": r["symbol"]})
    return out


# ---------------------------------------------------------------- service
class LiveIngest:
    def __init__(self, store: FeedStore, master: InstrumentMaster | None = None, open_poll: float = 30, closed_poll: float = 900):
        self.store, self.master = store, master or InstrumentMaster()
        self.open_poll, self.closed_poll = open_poll, closed_poll
        self.q_buf: list[dict] = []
        self.b_buf: list[FeedBar] = []
        self.stats = {"binance": 0, "coinbase": 0, "kraken": 0, "yahoo": 0, "bars": 0, "errors": {}}
        crypto = [i for i in self.master.all() if i.asset_class == "crypto" and "binance" in i.provider_symbols]
        self.binance = {i.provider_symbols["binance"].upper(): i.id for i in crypto}
        self.coinbase = {i.provider_symbols["coinbase"]: i.id for i in crypto if "coinbase" in i.provider_symbols}
        self.kraken = {i.provider_symbols["coinbase"].replace("-", "/"): i.id for i in crypto if "coinbase" in i.provider_symbols}
        self.yahoo = {i.provider_symbols["yahoo"]: i for i in self.master.all()
                      if i.asset_class in ("equity", "etf", "future") and "yahoo" in i.provider_symbols}

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(1)
            q, b = self.q_buf, self.b_buf
            self.q_buf, self.b_buf = [], []
            try:
                if q:
                    await asyncio.to_thread(self.store.upsert_quotes, q)
                if b:
                    await asyncio.to_thread(self.store.ingest, b, "live_ws")
                    self.stats["bars"] += len(b)
            except Exception as e:  # noqa: BLE001
                log.warning("flush failed: %r", e)
                self.q_buf[:0], self.b_buf[:0] = q, b

    async def _ws(self, name, urls, subscribe, handle):  # pragma: no cover - network
        import websockets
        delay, i = 1.0, 0
        while True:
            url = urls[i % len(urls)]
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                    if subscribe:
                        await ws.send(json.dumps(subscribe))
                    log.info("%s connected %s", name, url[:80])
                    delay = 1.0
                    async for raw in ws:
                        handle(json.loads(raw), time.time())
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.stats["errors"][name] = f"{time.strftime('%H:%M:%S')} {e!r}"[:200]
                log.warning("%s disconnected: %r (retry in %.0fs)", name, e, delay)
            i += 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    def _on_binance(self, msg, now):
        qs, bars = parse_binance(msg, now, self.binance)
        self.q_buf += qs
        self.b_buf += bars
        self.stats["binance"] += len(qs)

    def _on_coinbase(self, msg, now):
        qs = parse_coinbase(msg, now, self.coinbase)
        self.q_buf += qs
        self.stats["coinbase"] += len(qs)

    def _on_kraken(self, msg, now):
        qs = parse_kraken(msg, now, self.kraken)
        self.q_buf += qs
        self.stats["kraken"] += len(qs)

    async def _yahoo_loop(self):  # pragma: no cover - network
        import httpx
        syms = list(self.yahoo)
        by = {s: i.id for s, i in self.yahoo.items()}
        last_poll: dict[str, float] = {}
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as c:
            while True:
                now = time.time()
                due = [s for s in syms if now - last_poll.get(s, 0) >=
                       (self.open_poll if market_open(self.yahoo[s].session, now) else self.closed_poll)]
                for k in range(0, len(due), 20):
                    chunk = due[k:k + 20]
                    try:
                        r = await c.get(SPARK, params={"symbols": ",".join(chunk), "range": "1d", "interval": "5m"})
                        r.raise_for_status()
                        qs = parse_spark(r.json(), time.time(), by)
                        self.q_buf += qs
                        self.stats["yahoo"] += len(qs)
                        for s in chunk:
                            last_poll[s] = now
                    except Exception as e:  # noqa: BLE001
                        self.stats["errors"]["yahoo"] = f"{time.strftime('%H:%M:%S')} {e!r}"[:200]
                    await asyncio.sleep(1.0)  # <= 1 req/s to Yahoo
                await asyncio.sleep(5)

    async def run(self, duration: float | None = None):  # pragma: no cover - network
        streams = "/".join(f"{p.lower()}@kline_1m" for p in self.binance)
        tasks = [
            asyncio.create_task(self._flush_loop()),
            asyncio.create_task(self._ws("binance", [f"{u}?streams={streams}" for u in BINANCE_WS], None, self._on_binance)),
            asyncio.create_task(self._ws("coinbase", [COINBASE_WS], {"type": "subscribe", "product_ids": list(self.coinbase),
                                                                    "channels": ["ticker"]}, self._on_coinbase)),
            asyncio.create_task(self._ws("kraken", [KRAKEN_WS], {"method": "subscribe", "params": {
                "channel": "ticker", "symbol": list(self.kraken)}}, self._on_kraken)),
            asyncio.create_task(self._yahoo_loop()),
            asyncio.create_task(self._report()),
        ]
        try:
            if duration:
                await asyncio.sleep(duration)
            else:
                await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()

    async def _report(self):  # pragma: no cover
        while True:
            await asyncio.sleep(30)
            log.info("live ingest stats %s", json.dumps(self.stats))
