from __future__ import annotations

import json

from ..core import Capabilities, ProviderAdapter
from ._ws import ws_loop

MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class KrakenAdapter(ProviderAdapter):
    symbol_map = {"BTCUSDT": "XBTUSDT", "ETHUSDT": "ETHUSDT", "BTCUSD": "XBTUSD", "ETHUSD": "ETHUSD"}
    ws_map = {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT", "BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD"}
    caps = Capabilities(
        name="kraken", title="Kraken Spot public market data", status="working",
        asset_classes=("crypto",), schemas=("bars", "trades", "quotes"), intervals=tuple(MIN),
        history_depth="OHLC endpoint returns only the most recent 720 bars per interval (older data via Trades/downloadable CSV)",
        live_stream="websocket: wss://ws.kraken.com/v2 (ohlc, trade, ticker channels)",
        rate_limits="Public REST ~1 req/s per IP recommended (counter-based limits); EGeneral:Too many requests on excess",
        auth_env=(),
        official_docs=("https://docs.kraken.com/api/docs/rest-api/get-ohlc-data",
                       "https://docs.kraken.com/api/docs/websocket-v2/ohlc",
                       "https://docs.kraken.com/api/docs/guides/spot-rest-ratelimits"),
        terms_url="https://www.kraken.com/legal")

    def _history(self, instrument, interval, start, end, now):
        sym = self.provider_symbol(instrument)
        js = self.get_json("https://api.kraken.com/0/public/OHLC", {"pair": sym, "interval": MIN[interval], "since": start - 1})
        if js.get("error"):
            from ..core import ProviderError
            raise ProviderError(f"kraken: {js['error']}", retryable="Too many" in str(js["error"]))
        rows = next(v for k, v in js["result"].items() if k != "last")
        # [time, open, high, low, close, vwap, volume, count]; last row is the still-forming bar
        return [self._bar(instrument, interval, r[0], r[1], r[2], r[3], r[4], r[6], now) for r in rows]

    async def stream(self, instruments, interval):  # pragma: no cover - network
        rev = {self.ws_map.get(i, i): i for i in instruments}

        async def on_open(ws):
            await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ohlc", "symbol": list(rev), "interval": MIN[interval]}}))

        def parse(m, now):
            yield from parse_ohlc_ws(m, now, rev, interval, self)
        async for x in ws_loop(self, "wss://ws.kraken.com/v2", on_open, parse):
            yield x


def parse_ohlc_ws(m, now, rev, interval, adapter):
    import datetime as dt
    if m.get("channel") != "ohlc":
        return
    for d in m.get("data", []):
        t = dt.datetime.fromisoformat(d["interval_begin"].replace("Z", "+00:00")).timestamp()
        yield adapter._bar(rev.get(d["symbol"], d["symbol"]), interval, t, d["open"], d["high"], d["low"], d["close"], d["volume"], now)
