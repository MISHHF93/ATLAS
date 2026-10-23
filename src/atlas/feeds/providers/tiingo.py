from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class TiingoAdapter(ProviderAdapter):
    caps = Capabilities(
        name='tiingo', title='Tiingo (EOD + IEX intraday)', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'crypto', 'fx'), schemas=('bars', 'quotes', 'trades'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='EOD 30+ years; IEX intraday history (resampleFreq)',
        live_stream='websocket: wss://api.tiingo.com/iex',
        rate_limits='Free: 50 req/hour, 1000 req/day, 500 unique symbols/month',
        auth_env=('TIINGO_API_KEY',),
        official_docs=('https://www.tiingo.com/documentation/iex', 'https://www.tiingo.com/documentation/end-of-day', 'https://www.tiingo.com/documentation/websockets/iex'),
        terms_url='https://www.tiingo.com/about/terms',
        notes='')

    def _history(self, instrument, interval, start, end, now):
        iv = {"1d": None, "1m": "1min", "5m": "5min", "15m": "15min", "1h": "1hour"}[interval]
        sym = self.provider_symbol(instrument).lower()
        d = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d")
        tok = {"token": self.env["TIINGO_API_KEY"], "startDate": d(start), "endDate": d(end)}
        if iv:
            rows = self.get_json(f"https://api.tiingo.com/iex/{sym}/prices", {**tok, "resampleFreq": iv, "columns": "open,high,low,close,volume"})
        else:
            rows = self.get_json(f"https://api.tiingo.com/tiingo/daily/{sym}/prices", tok)
        return [self._bar(instrument, interval, _ts(r["date"]), r["open"], r["high"], r["low"], r["close"], r.get("volume", 0), now) for r in rows]
