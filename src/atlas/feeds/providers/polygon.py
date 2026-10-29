from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError, RateLimiter

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
        notes='Supports both POLYGON_API_KEY and MASSIVE_API_KEY; primary host api.massive.com.')

    def __init__(self, transport=None, env=None, **kwargs):
        if env is not None and env.get("MASSIVE_API_KEY") and not env.get("POLYGON_API_KEY"):
            env = {**env, "POLYGON_API_KEY": env["MASSIVE_API_KEY"]}
        if env is not None and env.get("MASSIVE_BASE_URL") and not env.get("POLYGON_BASE_URL"):
            env = {**env, "POLYGON_BASE_URL": env["MASSIVE_BASE_URL"]}
        if "limiter" not in kwargs:   # Basic plan: 5 calls/min. Paid plans (ATLAS_POLYGON_PLAN=paid) are not throttled by ATLAS.
            from ..stock_providers import plan_is_paid
            kwargs["limiter"] = RateLimiter(5, 1.0 if plan_is_paid("polygon", env) else 60.0, sleep=kwargs.get("sleep", __import__("time").sleep))
        super().__init__(transport=transport, env=env, **kwargs)

    def _history(self, instrument, interval, start, end, now):
        mult, span = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"), "1h": (1, "hour"), "1d": (1, "day")}[interval]
        base = self.env.get("POLYGON_BASE_URL") or self.env.get("MASSIVE_BASE_URL") or "https://api.massive.com"
        api_key = self.env.get("POLYGON_API_KEY") or self.env.get("MASSIVE_API_KEY") or ""
        url = f"{base}/v2/aggs/ticker/{self.provider_symbol(instrument)}/range/{mult}/{span}/{start*1000}/{end*1000-1}"
        out, params = [], {"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": api_key}
        while url:
            js = self.get_json(url, params)
            out += [self._bar(instrument, interval, r["t"] // 1000, r["o"], r["h"], r["l"], r["c"], r.get("v", 0), now) for r in js.get("results") or []]
            url = js.get("next_url")
            params = {"apiKey": api_key}
        return out
