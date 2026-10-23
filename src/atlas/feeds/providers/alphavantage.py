from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class AlphaVantageAdapter(ProviderAdapter):
    caps = Capabilities(
        name='alphavantage', title='Alpha Vantage', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'fx', 'crypto', 'macro'), schemas=('bars', 'series'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='TIME_SERIES_INTRADAY: 20+ years via month=YYYY-MM; daily 20+ years',
        live_stream='none (polling)',
        rate_limits='Free: 25 requests/day',
        auth_env=('ALPHAVANTAGE_API_KEY',),
        official_docs=('https://www.alphavantage.co/documentation/#intraday', 'https://www.alphavantage.co/support/#api-key'),
        terms_url='https://www.alphavantage.co/terms_of_service/',
        notes='')

    def _history(self, instrument, interval, start, end, now):
        iv = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "60min"}.get(interval)
        p = {"symbol": self.provider_symbol(instrument), "apikey": self.env["ALPHAVANTAGE_API_KEY"], "outputsize": "full"}
        js = self.get_json("https://www.alphavantage.co/query", {**p, "function": "TIME_SERIES_INTRADAY", "interval": iv, "extended_hours": "false"} if iv else {**p, "function": "TIME_SERIES_DAILY"})
        if "Note" in js or "Information" in js:
            raise ProviderError(f"alphavantage: {js.get('Note') or js.get('Information')}", retryable=False)
        key = next((k for k in js if k.startswith("Time Series")), None)
        tz = js.get("Meta Data", {}).get("6. Time Zone", "US/Eastern")
        from zoneinfo import ZoneInfo
        z = ZoneInfo("America/New_York" if "Eastern" in tz else "UTC")
        out = []
        for k, r in (js.get(key) or {}).items():
            t = dt.datetime.fromisoformat(k if " " in k else k + " 00:00:00").replace(tzinfo=z).timestamp()
            if iv:  # AV intraday timestamps are bar END times
                t -= INTERVALS[interval]
            out.append(self._bar(instrument, interval, t, r["1. open"], r["2. high"], r["3. low"], r["4. close"], r["5. volume"], now))
        return out
