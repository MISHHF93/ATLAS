from __future__ import annotations

from ..core import INTERVALS, Capabilities, FeedTrade, ProviderAdapter
from ._ws import ws_loop

GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


class CoinbaseAdapter(ProviderAdapter):
    symbol_map = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD"}
    caps = Capabilities(
        name="coinbase", title="Coinbase Exchange public market data", status="working",
        asset_classes=("crypto",), schemas=("bars", "trades", "quotes"), intervals=tuple(GRAN),
        history_depth="Multi-year; max 300 candles per request (GET /products/{id}/candles)",
        live_stream="websocket: wss://ws-feed.exchange.coinbase.com (matches/ticker channels; no candle channel)",
        rate_limits="Public REST ~10 req/s per IP (burst 15); 429 on excess",
        auth_env=(),
        official_docs=("https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
                       "https://docs.cdp.coinbase.com/exchange/websocket-feed/channels",
                       "https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits"),
        terms_url="https://www.coinbase.com/legal/user_agreement",
        notes="Quote currency is USD. ATLAS keeps the legacy series id BTCUSDT and maps it to BTC-USD (Coinbase is the primary crypto venue for Canadian users).")

    def _history(self, instrument, interval, start, end, now):
        g, sym = GRAN[interval], self.provider_symbol(instrument)
        out, t = [], start
        import datetime as dt
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        while t < end:
            e = min(end, t + 300 * g)
            rows = self.get_json(f"https://api.exchange.coinbase.com/products/{sym}/candles",
                                 {"granularity": g, "start": iso(t), "end": iso(e - 1)})
            for r in rows:  # [time, low, high, open, close, volume], newest first
                out.append(self._bar(instrument, interval, r[0], r[3], r[2], r[1], r[4], r[5], now))
            t = e
        return out

    async def stream(self, instruments, interval):  # pragma: no cover - network
        import json
        rev = {self.provider_symbol(i): i for i in instruments}

        async def on_open(ws):
            await ws.send(json.dumps({"type": "subscribe", "product_ids": list(rev), "channels": ["matches"]}))

        def parse(m, now):
            if m.get("type") in ("match", "last_match"):
                import datetime as dt
                t = dt.datetime.fromisoformat(m["time"].replace("Z", "+00:00")).timestamp()
                yield FeedTrade(rev.get(m["product_id"], m["product_id"]), t, float(m["price"]), float(m["size"]),
                                self.name, now, m.get("side"))
        async for x in ws_loop(self, "wss://ws-feed.exchange.coinbase.com", on_open, parse):
            yield x
