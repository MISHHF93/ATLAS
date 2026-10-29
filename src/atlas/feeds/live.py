"""ATLAS live ingest service.

* Binance combined websocket ``<pair>@kline_1m`` for every crypto instrument: every update upserts ``last_quotes``
  (kind=kline); a closed kline (``k.x``) is ingested as a confirmed 1m bar into ``bar_revisions`` (idempotent).
* Coinbase ``ticker`` channel (<BASE>-USD) and Kraken v2 ``ticker`` (<BASE>/USD): live cross-check quotes in
  ``last_quotes`` (provider coinbase / kraken). They never write bars into the USDT series.
* OKX public ``candle1m`` for every crypto instrument that has an OKX symbol. A confirmed candle is a 1m bar.
  Bybit stays a REST failover. It is not subscribed here.
* Official daily history for the trend book (BTC, ETH, SOL, USD_CAD, EUR_USD) from Alpaca crypto, the Bank of
  Canada, and the ECB. No unofficial chart source writes bars.
* Yahoo spark polling for US equities/ETFs and CME futures is quotes only, labelled ``yahoo`` and ``delayed``.
  It is not a trade bar and it is not an official feed.

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
OKX_WS = "wss://ws.okx.com:8443/ws/v5/business"
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


def parse_okx(msg: dict, now: float, by_inst: dict[str, str]):
    """OKX business candle. ``confirm == 1`` is a closed bar. A partial candle is a quote only."""
    arg = msg.get("arg") or {}
    if not str(arg.get("channel") or "").startswith("candle"):
        return [], []
    iid = by_inst.get(arg.get("instId"))
    if not iid:
        return [], []
    qs, bars = [], []
    for row in msg.get("data") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            start = int(row[0]) // 1000
            price = float(row[4])
        except (TypeError, ValueError):
            continue
        qs.append({"instrument": iid, "provider": "okx", "price": price, "event_time": float(start),
                    "receipt_time": now, "kind": "kline", "provider_symbol": arg.get("instId")})
        if len(row) > 8 and str(row[8]) == "1":
            bars.append(FeedBar(iid, "1m", start, float(row[1]), float(row[2]), float(row[3]), price,
                                float(row[5]), "okx", int(now), True, str(arg.get("instId") or "")))
    return qs, bars


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
        self.stats = {"binance": 0, "coinbase": 0, "kraken": 0, "okx": 0, "yahoo": 0, "bars": 0, "errors": {}}
        crypto = [i for i in self.master.all() if i.asset_class == "crypto" and "binance" in i.provider_symbols]
        self.binance = {i.provider_symbols["binance"].upper(): i.id for i in crypto}
        self.coinbase = {i.provider_symbols["coinbase"]: i.id for i in crypto if "coinbase" in i.provider_symbols}
        self.kraken = {i.provider_symbols["coinbase"].replace("-", "/"): i.id for i in crypto if "coinbase" in i.provider_symbols}
        self.okx = {i.provider_symbols["okx"]: i.id for i in crypto if i.provider_symbols.get("okx")}
        self.yahoo = {i.provider_symbols["yahoo"]: i for i in self.master.all()
                      if i.asset_class in ("equity", "etf", "future", "fx") and "yahoo" in i.provider_symbols}

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
                    rolled = await asyncio.to_thread(self._rollup, b)
                    if rolled:
                        await asyncio.to_thread(self.store.ingest, rolled, "aggregate")
                        self.stats["bars"] += len(rolled)
            except Exception as e:  # noqa: BLE001
                log.warning("flush failed: %r", e)
                self.q_buf[:0], self.b_buf[:0] = q, b

    def _session(self, instrument: str) -> str:
        try:
            return self.master.get(instrument).session
        except KeyError:
            return "24x7"

    def _rollup(self, bars: list[FeedBar]) -> list[FeedBar]:
        """Turn newly closed 1m bars into complete 5m, 15m and 1h bars. A bucket missing a minute is not stored."""
        from .aggregate import aggregate
        from .core import INTERVALS
        now = int(time.time())
        grouped: dict[tuple[str, str], list[FeedBar]] = {}
        for bar in bars:
            if bar.interval == "1m" and bar.confirmed:
                grouped.setdefault((bar.instrument, bar.provider), []).append(bar)
        out: list[FeedBar] = []
        for (inst, prov), mins in grouped.items():
            anchor = 1800 if self._session(inst) == "us_equity_rth" else 0
            for tf in ("5m", "15m", "1h"):
                step = INTERVALS[tf]
                use_anchor = anchor if tf == "1h" else 0
                starts = {(m.event_time - use_anchor) // step * step + use_anchor for m in mins}
                for t0 in sorted(starts):
                    window = self.store.bars(inst, "1m", t0, t0 + step, provider=prov)
                    out.extend(b for b in aggregate(window, tf, now, anchor=use_anchor, require_complete=True) if b.confirmed)
        return out

    def catch_up_rollups(self) -> int:
        """Write higher-timeframe bars for 1m history that arrived after the last stored 5m/15m/1h bar."""
        from .aggregate import aggregate
        from .core import INTERVALS
        now = int(time.time())
        n = 0
        for inst in self.binance.values():
            last1 = self.store.latest_bar(inst, ("1m",))
            if last1 is None:
                continue
            for tf in ("5m", "15m", "1h"):
                step = INTERVALS[tf]
                last = self.store.latest_bar(inst, (tf,))
                start = last.event_time + step if last is not None else last1.event_time
                if start >= last1.bar_end:
                    continue
                mins = self.store.bars(inst, "1m", start, last1.bar_end + 1, provider="binance")
                rolled = [b for b in aggregate(mins, tf, now, require_complete=True) if b.confirmed and b.event_time >= start]
                if rolled:
                    self.store.ingest(rolled, note="aggregate")
                    n += len(rolled)
        return n

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

    def _on_okx(self, msg, now):
        qs, bars = parse_okx(msg, now, self.okx)
        self.q_buf += qs
        self.b_buf += bars
        self.stats["okx"] += len(qs)

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
            asyncio.create_task(self._ws("okx", [OKX_WS], {"op": "subscribe", "args": [
                {"channel": "candle1m", "instId": sym} for sym in self.okx]}, self._on_okx)),
            asyncio.create_task(self._yahoo_loop()),
            asyncio.create_task(self._refresh_bars()),
            asyncio.create_task(self._official_daily()),
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

    async def _refresh_bars(self):  # pragma: no cover - network
        """Roll stored 1m bars up, then fill stale 15m/1h (and crypto 1m) from the provider chain."""
        from atlas.feeds.feed import get_feed
        try:
            n = await asyncio.to_thread(self.catch_up_rollups)
            log.info("rolled stored 1m bars into higher timeframes: %s", n)
        except Exception as e:  # noqa: BLE001
            log.warning("rollup catch-up failed: %r", e)
        feed = get_feed()
        # Equities and futures are not in this loop. Their official providers need a key, and Yahoo is quotes only.
        targets: list[tuple[str, tuple[str, ...]]] = [(iid, ("1m", "15m", "1h")) for iid in dict.fromkeys(self.binance.values())]
        while True:
            fetched = 0
            for iid, intervals in targets:
                for iv in intervals:
                    try:
                        if await asyncio.to_thread(feed.ensure_recent, iid, iv):
                            fetched += 1
                            await asyncio.sleep(1.1)
                    except Exception as e:  # noqa: BLE001
                        self.stats["errors"][f"{iid}:{iv}"] = f"{time.strftime('%H:%M:%S')} {e!r}"[:200]
            await asyncio.sleep(5 if fetched else 30)

    async def _official_daily(self):  # pragma: no cover - network
        """Backfill the trend book from keyless official daily sources. One pass, then every six hours."""
        from atlas.feeds.feed import get_feed
        from atlas.feeds.official import DAILY_LOOKBACK_S, TRADE_DAILY
        feed = get_feed()
        while True:
            for iid in TRADE_DAILY:
                try:
                    wrote = await asyncio.to_thread(
                        feed.ensure_recent, iid, "1d", lookback_s=DAILY_LOOKBACK_S,
                    )
                    if wrote:
                        await asyncio.sleep(1.1)
                except Exception as e:  # noqa: BLE001
                    self.stats["errors"][f"{iid}:1d"] = f"{time.strftime('%H:%M:%S')} {e!r}"[:200]
            await asyncio.sleep(6 * 3600)

    async def _report(self):  # pragma: no cover
        while True:
            await asyncio.sleep(30)
            log.info("live ingest stats %s", json.dumps(self.stats))
