from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class QuestradeAdapter(ProviderAdapter):
    caps = Capabilities(
        name='questrade', title='Questrade API (market candles)', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'option'), schemas=('bars', 'quotes'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='Candles via /v1/markets/candles/{symbolId}, max 2000 per request',
        live_stream='streaming port via /v1/markets/quotes?stream=true (websocket)',
        rate_limits='Market data: 20 req/s, 15000 req/hour',
        auth_env=('QUESTRADE_REFRESH_TOKEN',),
        official_docs=('https://www.questrade.com/api/documentation/rest-operations/market-calls/markets-candles-id', 'https://www.questrade.com/api/documentation/getting-started', 'https://www.questrade.com/api/documentation/rate-limiting'),
        terms_url='https://www.questrade.com/api/home',
        notes='OAuth refresh-token flow: refresh token -> access_token + api_server (login.questrade.com/oauth2/token). Refresh tokens are single-use; ATLAS keeps the rotated token in memory only. Symbol ids resolved via /v1/symbols/search.')

    def _history(self, instrument, interval, start, end, now):
        tok = self.get_json("https://login.questrade.com/oauth2/token", {"grant_type": "refresh_token", "refresh_token": self.env["QUESTRADE_REFRESH_TOKEN"]})
        srv, h = tok["api_server"].rstrip("/"), {"Authorization": "Bearer " + tok["access_token"]}
        sid = self.get_json(f"{srv}/v1/symbols/search", {"prefix": self.provider_symbol(instrument)}, headers=h)["symbols"][0]["symbolId"]
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat()
        g = {"1m": "OneMinute", "5m": "FiveMinutes", "15m": "FifteenMinutes", "1h": "OneHour", "1d": "OneDay"}[interval]
        js = self.get_json(f"{srv}/v1/markets/candles/{sid}", {"startTime": iso(start), "endTime": iso(end), "interval": g}, headers=h)
        return [self._bar(instrument, interval, _ts(c["start"]), c["open"], c["high"], c["low"], c["close"], c.get("volume", 0), now) for c in js.get("candles", [])]
