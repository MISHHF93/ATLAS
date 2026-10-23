from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class TwelveDataAdapter(ProviderAdapter):
    caps = Capabilities(
        name='twelvedata', title='Twelve Data', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'fx', 'crypto', 'index'), schemas=('bars', 'quotes'), intervals=('1m', '5m', '15m', '1h', '4h', '1d'),
        history_depth='Decades for daily; intraday multi-year; 5000 points/request',
        live_stream='websocket: wss://ws.twelvedata.com/v1/quotes/price (paid tiers)',
        rate_limits='Basic (free): 8 API credits/min, 800/day',
        auth_env=('TWELVEDATA_API_KEY',),
        official_docs=('https://twelvedata.com/docs#time-series', 'https://twelvedata.com/docs#websocket'),
        terms_url='https://twelvedata.com/terms',
        notes='')

    def _history(self, instrument, interval, start, end, now):
        iv = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1day"}[interval]
        d = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        js = self.get_json("https://api.twelvedata.com/time_series", {"symbol": self.provider_symbol(instrument), "interval": iv, "start_date": d(start),
                           "end_date": d(end), "timezone": "UTC", "outputsize": 5000, "order": "asc", "apikey": self.env["TWELVEDATA_API_KEY"]})
        if js.get("status") == "error":
            raise ProviderError(f"twelvedata: {js.get('message')}", retryable=js.get("code") == 429)
        return [self._bar(instrument, interval, _ts(r["datetime"].replace(" ", "T") + ("" if "T" in r["datetime"] or " " in r["datetime"] else "T00:00:00") + "+00:00"),
                          r["open"], r["high"], r["low"], r["close"], r.get("volume", 0), now) for r in js.get("values", [])]
