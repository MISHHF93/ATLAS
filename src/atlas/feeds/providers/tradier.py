from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class TradierAdapter(ProviderAdapter):
    caps = Capabilities(
        name='tradier', title='Tradier market data', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'option'), schemas=('bars', 'trades', 'quotes'), intervals=('1m', '5m', '15m', '1d'),
        history_depth='timesales: 1m ~20 days, 5m/15m ~40 days; daily history full',
        live_stream='websocket: wss://ws.tradier.com/v1/markets/events (needs session id)',
        rate_limits='Per-endpoint quotas with X-Ratelimit-Allowed/Used/Available/Expiry headers; over-quota returns HTTP 400 "Quota Violation" (not 429) - ATLAS retries with backoff',
        auth_env=('TRADIER_ACCESS_TOKEN',),
        official_docs=('https://docs.tradier.com/reference/brokerage-api-markets-get-timesales', 'https://docs.tradier.com/docs/rate-limiting', 'https://docs.tradier.com/docs/streaming-market-data'),
        terms_url='https://tradier.com/legal',
        notes='Optional TRADIER_ENV=sandbox|production (default sandbox; sandbox data is 15-min delayed).')

    def _history(self, instrument, interval, start, end, now):
        host = "https://api.tradier.com" if self.env.get("TRADIER_ENV") == "production" else "https://sandbox.tradier.com"
        h = {"Authorization": "Bearer " + self.env["TRADIER_ACCESS_TOKEN"], "Accept": "application/json"}
        d = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).astimezone(NY).strftime("%Y-%m-%d %H:%M")
        js = self.get_json(f"{host}/v1/markets/timesales", {"symbol": self.provider_symbol(instrument), "interval": {"1m": "1min", "5m": "5min", "15m": "15min"}[interval],
                           "start": d(start), "end": d(end), "session_filter": "open"}, headers=h)
        rows = ((js.get("series") or {}).get("data")) or []
        rows = [rows] if isinstance(rows, dict) else rows
        return [self._bar(instrument, interval, r["timestamp"], r["open"], r["high"], r["low"], r["close"], r.get("volume", 0), now) for r in rows]
