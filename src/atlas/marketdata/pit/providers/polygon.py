"""Massive (formerly Polygon.io) aggregates adapter. Disabled/offline by default."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.marketdata.pit.models import Bar
from atlas.marketdata.pit.providers.base import OfflineTransport, ProviderDisabled, Transport, require_real_key


class MassivePolygonAdapter:
    def __init__(self, api_key: str | None = None, enabled: bool = False, transport: Transport | None = None,
                 base_url: str = "https://api.massive.com"):
        self.enabled = enabled
        self.api_key = api_key
        self.transport = transport or OfflineTransport()
        self.base_url = base_url.rstrip("/")

    def get_daily_bars(self, symbol: str, start: str, end: str) -> list[Bar]:
        if not self.enabled:
            raise ProviderDisabled("Massive/Polygon adapter disabled")
        key = require_real_key(self.api_key, "POLYGON_API_KEY")
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        data = self.transport.get_json(url, {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key})
        if data.get("status") not in ("OK", "DELAYED"):
            raise RuntimeError(f"polygon error status {data.get('status')}")
        out = []
        for r in data.get("results", []) or []:
            start_ts = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
            close_ts = start_ts + timedelta(days=1)  # conservative: usable only after the day ends
            out.append(Bar(symbol=symbol, ts=close_ts, open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                           volume=r.get("v", 0), available_at=close_ts))
        return out
