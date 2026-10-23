from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class PolygonAdapter(ProviderAdapter):
    caps = Capabilities(
        name='polygon', title='Massive (formerly Polygon.io) aggregates', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'option', 'fx', 'crypto', 'index'), schemas=('bars', 'trades', 'quotes'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='Stocks: up to 20+ years depending on plan (free: 2 years, EOD/delayed)',
        live_stream='websocket: wss://socket.massive.com/stocks (paid; delayed.massive.com for delayed)',
        rate_limits='Free (Basic): 5 API calls/min; paid: unlimited (soft)',
        auth_env=('POLYGON_API_KEY',),
        official_docs=('https://massive.com/docs/rest/stocks/aggregates/custom-bars', 'https://massive.com/docs/websocket/stocks/aggregates-per-minute'),
        terms_url='https://massive.com/legal/terms',
        notes='')

    def _history(self, instrument, interval, start, end, now):
        mult, span = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"), "1h": (1, "hour"), "1d": (1, "day")}[interval]
        url = f"{self.env.get('POLYGON_BASE_URL', 'https://api.massive.com')}/v2/aggs/ticker/{self.provider_symbol(instrument)}/range/{mult}/{span}/{start*1000}/{end*1000-1}"
        out, params = [], {"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": self.env["POLYGON_API_KEY"]}
        while url:
            js = self.get_json(url, params)
            out += [self._bar(instrument, interval, r["t"] // 1000, r["o"], r["h"], r["l"], r["c"], r.get("v", 0), now) for r in js.get("results") or []]
            url = js.get("next_url")
            params = {"apiKey": self.env["POLYGON_API_KEY"]}
        return out
