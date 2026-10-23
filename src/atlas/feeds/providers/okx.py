from __future__ import annotations

import json

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError
from ._ws import ws_loop

BAR = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}


class OKXAdapter(ProviderAdapter):
    symbol_map = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}
    caps = Capabilities(
        name="okx", title="OKX public market data", status="working",
        asset_classes=("crypto",), schemas=("bars", "trades", "quotes"), intervals=tuple(BAR),
        history_depth="/market/candles: recent 1440 bars; /market/history-candles: multi-year, 100 bars/request",
        live_stream="websocket: wss://ws.okx.com:8443/ws/v5/business (candle<bar> channels)",
        rate_limits="market/candles 40 req/2s, history-candles 20 req/2s per IP",
        auth_env=(),
        official_docs=("https://www.okx.com/docs-v5/en/#public-data-rest-api-get-candlesticks-history",
                       "https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-candlesticks-channel"),
        terms_url="https://www.okx.com/help/terms-of-service")

    def _history(self, instrument, interval, start, end, now):
        sym, out, after = self.provider_symbol(instrument), [], end * 1000
        while True:
            js = self.get_json("https://www.okx.com/api/v5/market/history-candles",
                               {"instId": sym, "bar": BAR[interval], "after": after, "limit": 100})
            if js.get("code") != "0":
                raise ProviderError(f"okx: {js.get('msg')}", retryable=js.get("code") == "50011")
            rows = js["data"]  # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm], newest first
            if not rows:
                break
            for r in rows:
                out.append(self._bar(instrument, interval, int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5], now, final=r[8] == "1"))
            after = int(rows[-1][0])
            if after // 1000 <= start:
                break
        return out

    async def stream(self, instruments, interval):  # pragma: no cover - network
        rev = {self.provider_symbol(i): i for i in instruments}

        async def on_open(ws):
            await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "candle" + BAR[interval], "instId": s} for s in rev]}))

        def parse(m, now):
            for r in m.get("data", []) if "arg" in m else []:
                yield self._bar(rev.get(m["arg"]["instId"]), interval, int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5], now, final=r[8] == "1")
        async for x in ws_loop(self, "wss://ws.okx.com:8443/ws/v5/business", on_open, parse):
            yield x
