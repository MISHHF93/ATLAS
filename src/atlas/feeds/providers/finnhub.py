from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class FinnhubAdapter(ProviderAdapter):
    caps = Capabilities(
        name='finnhub', title='Finnhub', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'fx', 'crypto'), schemas=('bars', 'trades'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='Stock candles are a premium endpoint; free tier: quotes + websocket trades',
        live_stream='websocket: wss://ws.finnhub.io?token=<key> (trades)',
        rate_limits='Plan limit per minute (429 on excess) plus a global 30 calls/s cap; websocket: 1 connection per key',
        auth_env=('FINNHUB_API_KEY',),
        official_docs=('https://finnhub.io/docs/api/stock-candles', 'https://finnhub.io/docs/api/websocket-trades', 'https://finnhub.io/docs/api/rate-limit'),
        terms_url='https://finnhub.io/terms-of-service',
        notes='')

    def _history(self, instrument, interval, start, end, now):
        res = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "1d": "D"}[interval]
        js = self.get_json("https://finnhub.io/api/v1/stock/candle", {"symbol": self.provider_symbol(instrument), "resolution": res, "from": start, "to": end},
                           headers={"X-Finnhub-Token": self.env["FINNHUB_API_KEY"]})
        if js.get("s") != "ok":
            return []
        return [self._bar(instrument, interval, t, o, h, l_, c, v, now) for t, o, h, l_, c, v in zip(js["t"], js["o"], js["h"], js["l"], js["c"], js["v"])]
