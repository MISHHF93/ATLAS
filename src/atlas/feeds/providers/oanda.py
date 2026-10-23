from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class OandaAdapter(ProviderAdapter):
    caps = Capabilities(
        name='oanda', title='OANDA v20 REST', status="interface_fixture_tested",
        asset_classes=('fx', 'cfd'), schemas=('bars', 'quotes'), intervals=('1m', '5m', '15m', '1h', '4h', '1d'),
        history_depth='Multi-year candles, 5000 per request',
        live_stream='HTTP stream: https://stream-fxpractice.oanda.com/v3/accounts/<id>/pricing/stream',
        rate_limits='120 requests/s per connection; 2 new connections/s',
        auth_env=('OANDA_API_TOKEN',),
        official_docs=('https://developer.oanda.com/rest-live-v20/pricing-ep/', 'https://developer.oanda.com/rest-live-v20/best-practices/'),
        terms_url='https://www.oanda.com/us-en/legal/',
        notes='Optional OANDA_ENV=practice|live (default practice), OANDA_ACCOUNT_ID for pricing stream. Mid candles, complete flag maps to confirmed.')

    def _history(self, instrument, interval, start, end, now):
        g = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D"}[interval]
        host = "https://api-fxtrade.oanda.com" if self.env.get("OANDA_ENV") == "live" else "https://api-fxpractice.oanda.com"
        js = self.get_json(f"{host}/v3/instruments/{self.provider_symbol(instrument)}/candles", {"granularity": g, "from": start, "to": end, "price": "M"},
                           headers={"Authorization": "Bearer " + self.env["OANDA_API_TOKEN"], "Accept-Datetime-Format": "UNIX"})
        return [self._bar(instrument, interval, float(c["time"]), c["mid"]["o"], c["mid"]["h"], c["mid"]["l"], c["mid"]["c"], c.get("volume", 0), now, final=c.get("complete", True))
                for c in js.get("candles", [])]
