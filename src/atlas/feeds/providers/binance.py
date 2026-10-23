from __future__ import annotations

import json
import os

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError
from ._ws import ws_loop

DEFAULT_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")


class BinanceAdapter(ProviderAdapter):
    caps = Capabilities(
        name="binance", title="Binance Spot public market data", status="working",
        asset_classes=("crypto",), schemas=("bars", "trades"), intervals=("1m", "5m", "15m", "1h", "4h", "1d"),
        history_depth="Full listing history via /api/v3/klines (1000 bars/request)",
        live_stream="websocket: wss://data-stream.binance.vision/ws/<symbol>@kline_<interval>",
        rate_limits="Request weight 6000/min per IP (klines weight 2); HTTP 429 then 418 ban on abuse; honor Retry-After",
        auth_env=(),
        official_docs=("https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints",
                       "https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams",
                       "https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only"),
        terms_url="https://www.binance.com/en/terms",
        notes="api.binance.com returns HTTP 451 from restricted locations (incl. this box); data-api.binance.vision is the market-data-only mirror.")

    def hosts(self):
        v = self.env.get("ATLAS_BINANCE_REST_HOSTS")
        return tuple(h.strip() for h in v.split(",")) if v else DEFAULT_HOSTS

    def _history(self, instrument, interval, start, end, now):
        sym, step = self.provider_symbol(instrument), INTERVALS[interval]
        out, t = [], start
        hosts = list(self.hosts())
        while t < end:
            rows = None
            for host in list(hosts):
                try:
                    rows = self.get_json(f"{host}/api/v3/klines", {"symbol": sym, "interval": interval,
                                         "startTime": t * 1000, "endTime": end * 1000 - 1, "limit": 1000})
                    break
                except ProviderError as e:
                    if e.geo_blocked or not e.retryable:
                        hosts.remove(host)  # fail over to next host
                        continue
                    raise
            if rows is None:
                raise ProviderError("binance: all REST hosts failed/geo-blocked", geo_blocked=True)
            if not rows:
                break
            for r in rows:
                out.append(self._bar(instrument, interval, r[0] // 1000, r[1], r[2], r[3], r[4], r[5], now))
            nxt = rows[-1][0] // 1000 + step
            if nxt <= t:
                break
            t = nxt
        return out

    async def stream(self, instruments, interval):  # pragma: no cover - network
        streams = "/".join(f"{self.provider_symbol(i).lower()}@kline_{interval}" for i in instruments)
        rev = {self.provider_symbol(i): i for i in instruments}
        url = f"wss://data-stream.binance.vision/stream?streams={streams}"

        async def on_open(ws):
            return None

        def parse(msg, now):
            yield from parse_kline_ws(msg, now, rev, self)
        async for b in ws_loop(self, url, on_open, parse):
            yield b


def parse_kline_ws(msg, now, rev, adapter):
    d = msg.get("data", msg)
    if d.get("e") != "kline":
        return
    k = d["k"]
    inst = rev.get(k["s"], k["s"])
    yield adapter._bar(inst, k["i"], k["t"] // 1000, k["o"], k["h"], k["l"], k["c"], k["v"], now, final=bool(k["x"]))
