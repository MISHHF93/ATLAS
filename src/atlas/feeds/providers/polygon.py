from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError, RateLimiter

NY = ZoneInfo("America/New_York")
RTH_OPEN, RTH_CLOSE = 9 * 60 + 30, 16 * 60          # regular session, minutes after midnight ET
NON_EQUITY_PREFIX = ("X:", "C:", "I:", "O:")        # Massive crypto / forex / index / option tickers have no equity session


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def et_midnight(ts: float) -> int:
    """Epoch seconds of the start of the New York calendar day containing ``ts``."""
    d = dt.datetime.fromtimestamp(ts, NY)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def in_rth(ts: int) -> bool:
    d = dt.datetime.fromtimestamp(ts, NY)
    return d.weekday() < 5 and RTH_OPEN <= d.hour * 60 + d.minute < RTH_CLOSE


class PolygonAdapter(ProviderAdapter):
    """Massive (ex-Polygon) aggregates. The key goes in an Authorization header, never in a URL, a log line or ``next_url``.

    Stocks Basic never serves the current New York day (HTTP 403 until midnight ET), so requests end at the last completed
    ET day. Intraday bars on the free plan include pre/post market; stocks and ETFs are cut to the regular session (09:30-16:00 ET)
    to match the ``us_equity_rth`` session. Fully past windows are cached on disk, so a re-run spends no quota.
    """
    caps = Capabilities(
        name='polygon', title='Massive (formerly Polygon.io) aggregates', status="interface_fixture_tested",
        asset_classes=('equity', 'etf', 'option', 'fx', 'crypto', 'index'), schemas=('bars', 'trades', 'quotes'), intervals=('1m', '5m', '15m', '1h', '1d'),
        history_depth='Stocks: free = 2 years of 15m and daily bars and 1m bars (previous completed day, not live; ATLAS stores a recent 1m window for a ticker list); paid = 20+ years, real time',
        live_stream='websocket: wss://socket.massive.com/stocks (paid; delayed.massive.com for delayed)',
        rate_limits='Free (Basic): 5 API calls/min; paid: unlimited (soft)',
        auth_env=('POLYGON_API_KEY',),
        official_docs=('https://massive.com/docs/rest/stocks/aggregates/custom-bars', 'https://massive.com/docs/websocket/stocks/aggregates-per-minute'),
        terms_url='https://massive.com/legal/terms',
        notes='Supports both POLYGON_API_KEY and MASSIVE_API_KEY; primary host api.massive.com. Bearer auth. Individual plan: personal, non-commercial use.')

    def __init__(self, transport=None, env=None, cache_dir=None, **kwargs):
        production = env is None
        if env is not None and env.get("MASSIVE_API_KEY") and not env.get("POLYGON_API_KEY"):
            env = {**env, "POLYGON_API_KEY": env["MASSIVE_API_KEY"]}
        if env is not None and env.get("MASSIVE_BASE_URL") and not env.get("POLYGON_BASE_URL"):
            env = {**env, "POLYGON_BASE_URL": env["MASSIVE_BASE_URL"]}
        if "limiter" not in kwargs:   # Basic plan: 5 calls/min. Paid plans (ATLAS_POLYGON_PLAN=paid) are not throttled by ATLAS.
            from ..stock_providers import plan_is_paid
            paid = plan_is_paid("polygon", env)
            sleep = kwargs.get("sleep", __import__("time").sleep)
            if production and not paid:
                from ..throttle import SharedWindowLimiter     # 4 of the 5 allowed calls per minute, shared by the server and scripts
                kwargs["limiter"] = SharedWindowLimiter(os.environ.get("ATLAS_MASSIVE_THROTTLE", "var/feeds/massive_throttle.json"), 4, 60.0, sleep=sleep)
            else:
                kwargs["limiter"] = RateLimiter(5, 1.0 if paid else 60.0, sleep=sleep)
        super().__init__(transport=transport, env=env, **kwargs)
        self.cache_dir = Path(cache_dir) if cache_dir else (Path(os.environ.get("ATLAS_MASSIVE_CACHE", "var/feeds/massive_cache")) if production else None)

    # ---- cache of fully-past responses ----
    def _cache_path(self, sym, interval, start, end):
        if self.cache_dir is None:
            return None
        h = hashlib.sha256(f"{sym}|{interval}|{start}|{end}|adj".encode()).hexdigest()[:24]
        return self.cache_dir / f"{sym.replace(':', '_')}_{interval}_{h}.json.gz"

    def _history(self, instrument, interval, start, end, now):
        mult, span = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"), "1h": (1, "hour"), "1d": (1, "day")}[interval]
        base = self.env.get("POLYGON_BASE_URL") or self.env.get("MASSIVE_BASE_URL") or "https://api.massive.com"
        api_key = self.env.get("POLYGON_API_KEY") or self.env.get("MASSIVE_API_KEY") or ""
        sym = self.provider_symbol(instrument)
        today0 = et_midnight(now)
        end = min(end, today0)                      # the current ET day is not served on Basic (403)
        if end <= start:
            return []
        cache = self._cache_path(sym, interval, start, end)
        rows = None
        if cache is not None and cache.exists():
            try:
                rows = json.loads(gzip.decompress(cache.read_bytes()))
            except Exception:  # noqa: BLE001
                rows = None
        if rows is None:
            url = f"{base}/v2/aggs/ticker/{sym}/range/{mult}/{span}/{start*1000}/{end*1000-1}"
            rows, params = [], {"adjusted": "true", "sort": "asc", "limit": 50000}
            headers = {"Authorization": f"Bearer {api_key}"}
            while url:
                js = self.get_json(url, params, headers=headers)
                rows += [[r["t"], r["o"], r["h"], r["l"], r["c"], r.get("v", 0)] for r in js.get("results") or []]
                url = js.get("next_url")
                params = None
            if cache is not None:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(gzip.compress(json.dumps(rows).encode()))
                except OSError:
                    pass
        out = []
        equity = not sym.startswith(NON_EQUITY_PREFIX)
        for t, o, h, l_, c, v in rows:
            ts = t // 1000
            if equity and interval != "1d" and not in_rth(ts):
                continue
            out.append(self._bar(instrument, interval, ts, o, h, l_, c, v, now))
        return out
