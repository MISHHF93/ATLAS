from __future__ import annotations

import datetime as dt
import json

from ..core import Capabilities, FeedQuote, FeedTrade, ProviderAdapter, RateLimiter
from ._ws import ws_loop

# Alpaca Basic (free) plan, works with paper accounts: 200 historical calls/min, 30 websocket symbols, IEX real time.
ALPACA_RATE_PER_MIN = 180          # stay under the 200/min cap
ALPACA_WS_SYMBOL_CAP = 30
TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class AlpacaAdapter(ProviderAdapter):
    caps = Capabilities(
        name="alpaca", title="Alpaca Market Data API v2 (stocks)", status="interface_fixture_tested",
        asset_classes=("equity", "etf"), schemas=("bars", "trades", "quotes"), intervals=tuple(TF),
        history_depth="Since 2016 (SIP needs paid plan for recent 15 min; IEX free)",
        live_stream="websocket: wss://stream.data.alpaca.markets/v2/iex (free) | /v2/sip (paid)",
        rate_limits="Free (Basic) 200 req/min; X-RateLimit-Limit/Remaining/Reset headers; HTTP 429 when exceeded",
        auth_env=("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"),
        official_docs=("https://docs.alpaca.markets/reference/stockbars",
                       "https://docs.alpaca.markets/docs/real-time-stock-pricing-data",
                       "https://docs.alpaca.markets/docs/about-market-data-api"),
        terms_url="https://alpaca.markets/disclosures",
        notes="Optional ALPACA_DATA_FEED=iex|sip (default iex). Streamed bars are 1-minute; ATLAS aggregates to 15m/1h. "
              "'u' updatedBars messages are stored as revisions.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(ALPACA_RATE_PER_MIN / 60.0, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def _headers(self):
        return {"APCA-API-KEY-ID": self.env["ALPACA_API_KEY_ID"], "APCA-API-SECRET-KEY": self.env["ALPACA_API_SECRET_KEY"]}

    def _history(self, instrument, interval, start, end, now):
        out, token = [], None
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        while True:
            js = self.get_json("https://data.alpaca.markets/v2/stocks/bars",
                               {"symbols": self.provider_symbol(instrument), "timeframe": TF[interval], "start": iso(start),
                                "end": iso(end), "limit": 10000, "feed": self.env.get("ALPACA_DATA_FEED", "iex"),
                                "adjustment": "raw", "sort": "asc", "page_token": token}, headers=self._headers())
            for b in (js.get("bars") or {}).get(self.provider_symbol(instrument), []):
                out.append(self._bar(instrument, interval, _ts(b["t"]), b["o"], b["h"], b["l"], b["c"], b["v"], now))
            token = js.get("next_page_token")
            if not token:
                return out

    def parse_stream(self, msgs, now, rev=None):
        rev = rev or {}
        for m in msgs:
            T = m.get("T")
            if T in ("b", "u"):  # minute bar / updated (revised) minute bar
                yield self._bar(rev.get(m["S"], m["S"]), "1m", _ts(m["t"]), m["o"], m["h"], m["l"], m["c"], m["v"], now)
            elif T == "t":
                yield FeedTrade(rev.get(m["S"], m["S"]), _ts(m["t"]), m["p"], m["s"], self.name, now)
            elif T == "q":
                yield FeedQuote(rev.get(m["S"], m["S"]), _ts(m["t"]), m["bp"], m["ap"], m["bs"], m["as"], self.name, now)
            elif T == "error":
                self._health.last_error, self._health.last_error_at = f"alpaca ws {m.get('code')}: {m.get('msg')}", now

    async def stream(self, instruments, interval="1m"):  # pragma: no cover - network
        rev = {self.provider_symbol(i): i for i in list(instruments)[:ALPACA_WS_SYMBOL_CAP]}  # free plan: 30 symbols
        url = f"wss://stream.data.alpaca.markets/v2/{self.env.get('ALPACA_DATA_FEED', 'iex')}"

        async def on_open(ws):
            await ws.recv()  # [{"T":"success","msg":"connected"}]
            await ws.send(json.dumps({"action": "auth", "key": self.env["ALPACA_API_KEY_ID"], "secret": self.env["ALPACA_API_SECRET_KEY"]}))
            await ws.recv()
            await ws.send(json.dumps({"action": "subscribe", "bars": list(rev), "updatedBars": list(rev)}))
        async for x in ws_loop(self, url, on_open, lambda m, now: self.parse_stream(m, now, rev)):
            yield x


def _crypto_pair(instrument: str) -> str:
    """ATLAS id BTCUSDT / BTC-USD / BTC/USD -> Alpaca pair BTC/USD (Alpaca US crypto quotes in USD)."""
    s = instrument.upper().replace("-", "/")
    if "/" in s:
        return s
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q):
            return s[: -len(q)] + "/USD"
    return s + "/USD"


class AlpacaCryptoAdapter(ProviderAdapter):
    """Alpaca crypto bars. Historical crypto needs NO auth; keys (if set) are sent for the higher limit."""
    caps = Capabilities(
        name="alpaca_crypto", title="Alpaca Market Data v1beta3 (crypto, keyless history)", status="interface_fixture_tested",
        asset_classes=("crypto",), schemas=("bars",), intervals=tuple(TF),
        history_depth="Since 2021 (US crypto venue, USD pairs)", live_stream="wss://stream.data.alpaca.markets/v1beta3/crypto/us",
        rate_limits="200 req/min (ATLAS caps at 180/min)", auth_env=(),
        official_docs=("https://docs.alpaca.markets/reference/cryptobars-1",
                       "https://docs.alpaca.markets/docs/about-market-data-api"),
        terms_url="https://alpaca.markets/disclosures",
        notes="BTCUSDT maps to BTC/USD; bars are tagged provider=alpaca_crypto.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(ALPACA_RATE_PER_MIN / 60.0, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def provider_symbol(self, instrument: str) -> str:
        return self.symbol_map.get(instrument) or _crypto_pair(instrument)

    def _history(self, instrument, interval, start, end, now):
        out, token = [], None
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        k, s = self.env.get("ALPACA_API_KEY_ID"), self.env.get("ALPACA_API_SECRET_KEY")
        hdr = {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else {}
        pair = self.provider_symbol(instrument)
        while True:
            js = self.get_json("https://data.alpaca.markets/v1beta3/crypto/us/bars",
                               {"symbols": pair, "timeframe": TF[interval], "start": iso(start), "end": iso(end),
                                "limit": 10000, "sort": "asc", "page_token": token}, headers=hdr)
            for b in (js.get("bars") or {}).get(pair, []):
                out.append(self._bar(instrument, interval, _ts(b["t"]), b["o"], b["h"], b["l"], b["c"], b["v"], now))
            token = js.get("next_page_token")
            if not token:
                return out
