"""ATLAS live ingest service (Coinbase and Kraken only: the crypto venues open to Canadian residents).

* Kraken v2 ``ohlc`` (interval 1) for every crypto instrument with a Kraken symbol: every update upserts ``last_quotes``
  (kind=ohlc); a candle that a newer minute has replaced is ingested as a confirmed 1m bar (provider ``kraken``, idempotent).
* Kraken v2 ``ticker`` and Coinbase ``ticker`` (<BASE>-USD): live quotes in ``last_quotes`` (provider kraken / coinbase).
  Coinbase 1m/15m/1h bars come from the REST candle endpoint through the provider chain (``_refresh_bars``).
* Kraken v2 ``trade`` and Coinbase ``matches`` are aggregated into 1-second trade bars (``feeds.trades1s``) in their own
  sqlite (``var/feeds/atlas_1s.sqlite``), 7-day retention for 1s, a 90-day per-minute flow roll-up, 2 GB budget. A second with
  no trade has no row (no forward fill). Not written to the point-in-time feed store.
* Symbols come from ``feeds.crypto_venues`` (USD pairs, the ``kraken_ca`` blocklist respected). An asset with no listing is
  not subscribed and has an empty provider chain, so the UI shows an empty state, never a made-up price.
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
import os
import time
from pathlib import Path
from typing import Iterable

from .core import FeedBar
from .crypto_venues import ws_symbol_from_pair
from .instruments import InstrumentMaster
from .status import market_open
from .trades1s import SecondAggregator, TradeBarStore, parse_coinbase_match, parse_kraken_trades
from .store import FeedStore

log = logging.getLogger("atlas.feeds.live")
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
KRAKEN_WS = "wss://ws.kraken.com/v2"
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark"


# ---------------------------------------------------------------- pure parsers (unit-tested)
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


class KrakenBars:
    """Assemble confirmed 1m bars from Kraken v2 ``ohlc`` messages.

    Kraken streams the still-forming candle on every update. A candle is final only once a newer ``interval_begin`` arrives
    for the same symbol, so the previous one is emitted then (a snapshot's older candles are closed bars and emit at once).
    """

    def __init__(self):
        self.cur: dict[str, dict] = {}

    def feed(self, msg: dict, now: float, by_symbol: dict[str, str]):
        if msg.get("channel") != "ohlc" or msg.get("type") not in ("snapshot", "update"):
            return [], []
        from datetime import datetime
        qs, bars = [], []
        rows = []
        for d in msg.get("data") or []:
            try:
                rows.append((int(datetime.fromisoformat(str(d["interval_begin"]).replace("Z", "+00:00")).timestamp()), d))
            except (KeyError, ValueError):
                continue
        for begin, d in sorted(rows, key=lambda x: x[0]):
            sym = d.get("symbol")
            iid = by_symbol.get(sym)
            if not iid:
                continue
            c = {"begin": begin, "o": float(d["open"]), "h": float(d["high"]), "l": float(d["low"]), "c": float(d["close"]),
                 "v": float(d.get("volume") or 0.0)}
            old = self.cur.get(sym)
            if old is not None and begin < old["begin"]:
                continue   # stale
            if old is not None and begin > old["begin"]:
                bars.append(FeedBar(iid, "1m", old["begin"], old["o"], old["h"], old["l"], old["c"], old["v"], "kraken", int(now), True, sym))
            self.cur[sym] = c
            qs.append({"instrument": iid, "provider": "kraken", "price": c["c"], "event_time": float(now), "receipt_time": now,
                       "kind": "ohlc", "provider_symbol": sym})
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
        self.stats = {"coinbase": 0, "kraken": 0, "yahoo": 0, "bars": 0, "errors": {}}
        crypto = [i for i in self.master.all() if i.asset_class == "crypto"]
        self.coinbase = {i.provider_symbols["coinbase"]: i.id for i in crypto if "coinbase" in i.provider_symbols}
        self.kraken = {ws_symbol_from_pair(i.provider_symbols["kraken"]): i.id for i in crypto if "kraken" in i.provider_symbols}
        self.crypto_ids = tuple(dict.fromkeys([*self.coinbase.values(), *self.kraken.values()]))
        self.kraken_bars = KrakenBars()
        # 1s trade bars (kraken `trade`, coinbase `matches`) live in their own sqlite next to the feed store, never in it.
        self.trades = SecondAggregator()
        self.trade_store: TradeBarStore | None = None
        if store.path != ":memory:":
            self.trade_store = TradeBarStore(os.environ.get("ATLAS_1S_DB") or Path(store.path).with_name("atlas_1s.sqlite"),
                                             retain_1s_days=float(os.environ.get("ATLAS_1S_RETAIN_DAYS", 7)),
                                             retain_flow_days=float(os.environ.get("ATLAS_FLOW_RETAIN_DAYS", 90)),
                                             max_db_mb=float(os.environ.get("ATLAS_1S_MAX_MB", 2048)))
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
        for inst in self.crypto_ids:
            last1 = self.store.latest_bar(inst, ("1m",))
            if last1 is None:
                continue
            for tf in ("5m", "15m", "1h"):
                step = INTERVALS[tf]
                last = self.store.latest_bar(inst, (tf,))
                start = last.event_time + step if last is not None else last1.event_time
                if start >= last1.bar_end:
                    continue
                for prov in ("kraken", "coinbase"):
                    mins = self.store.bars(inst, "1m", start, last1.bar_end + 1, provider=prov)
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
                    for sub in ([] if not subscribe else subscribe if isinstance(subscribe, list) else [subscribe]):
                        await ws.send(json.dumps(sub))
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

    def _on_coinbase(self, msg, now):
        for tr in parse_coinbase_match(msg, self.coinbase):
            self.trades.add(tr, now)
        qs = parse_coinbase(msg, now, self.coinbase)
        self.q_buf += qs
        self.stats["coinbase"] += len(qs)

    def _on_kraken(self, msg, now):
        for tr in parse_kraken_trades(msg, self.kraken):
            self.trades.add(tr, now)
        qs = parse_kraken(msg, now, self.kraken)
        oq, bars = self.kraken_bars.feed(msg, now, self.kraken)
        self.q_buf += qs + oq
        self.b_buf += bars
        self.stats["kraken"] += len(qs) + len(oq)

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

    async def _massive_loop(self):  # pragma: no cover - network
        """US stocks via Massive: an end-of-day refresh on the free plan, a polled snapshot on a paid plan (see feeds/massive_live.py)."""
        from atlas.integrations.registry import load_env
        from atlas.accounts.credentials import effective_environ
        from . import massive_live as ML
        from .feed import AtlasFeed
        feed = AtlasFeed(self.store)
        last_refresh = 0.0
        while True:
            try:
                env = dict(load_env(environ=dict(effective_environ())))
                if ML.has_key(env):
                    ids = ML.stock_instruments(feed)
                    if ML.is_paid(env):
                        r = await asyncio.to_thread(ML.poll_snapshot, feed, env, ids)
                        self.stats["massive"] = r.get("quotes", 0)
                    if time.time() - last_refresh >= ML.REFRESH_EVERY_S:
                        last_refresh = time.time()
                        await asyncio.to_thread(ML.refresh, feed, env, ids)
            except Exception as e:  # noqa: BLE001
                self.stats["errors"]["massive"] = f"{time.strftime('%H:%M:%S')} {type(e).__name__}"[:200]
            await asyncio.sleep(ML.SNAPSHOT_EVERY_S)

    async def run(self, duration: float | None = None):  # pragma: no cover - network
        tasks = [
            asyncio.create_task(self._flush_loop()),
            asyncio.create_task(self._ws("coinbase", [COINBASE_WS], {"type": "subscribe", "product_ids": list(self.coinbase),
                                                                    "channels": ["ticker", "matches"]}, self._on_coinbase) if self.coinbase else asyncio.sleep(0)),
            asyncio.create_task(self._ws("kraken", [KRAKEN_WS], [
                {"method": "subscribe", "params": {"channel": "ticker", "symbol": list(self.kraken)}},
                {"method": "subscribe", "params": {"channel": "ohlc", "symbol": list(self.kraken), "interval": 1}},
                {"method": "subscribe", "params": {"channel": "trade", "symbol": list(self.kraken), "snapshot": False}}],
                self._on_kraken) if self.kraken else asyncio.sleep(0)),
            asyncio.create_task(self._yahoo_loop()),
            asyncio.create_task(self._massive_loop()),
            asyncio.create_task(self._refresh_bars()),
            asyncio.create_task(self._official_daily()),
            asyncio.create_task(self._trades_loop()),
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
        targets: list[tuple[str, tuple[str, ...]]] = [(iid, ("1m", "15m", "1h")) for iid in self.crypto_ids]
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

    async def _trades_loop(self):  # pragma: no cover - network
        """Write closed 1s bars every second, roll complete minutes into flow_1m, prune on the retention window every 10 minutes."""
        if self.trade_store is None:
            return
        last_prune = 0.0
        while True:
            await asyncio.sleep(1)
            try:
                rows = self.trades.drain()
                if rows:
                    await asyncio.to_thread(self.trade_store.write_bars, rows)
                if time.time() - last_prune >= 600:
                    last_prune = time.time()
                    self.stats["trade_store"] = await asyncio.to_thread(self.trade_store.prune)
            except Exception as e:  # noqa: BLE001
                self.stats["errors"]["trades1s"] = f"{time.strftime('%H:%M:%S')} {e!r}"[:200]

    async def _report(self):  # pragma: no cover
        while True:
            await asyncio.sleep(30)
            self.stats["trades1s"] = dict(self.trades.stats)
            log.info("live ingest stats %s", json.dumps(self.stats))
