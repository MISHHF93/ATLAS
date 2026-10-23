"""Finnhub adapter (earnings calendar, news sentiment). Disabled/offline by default."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from atlas.marketdata.pit.models import EarningsEvent
from atlas.marketdata.pit.providers.base import OfflineTransport, ProviderDisabled, Transport, require_real_key

_HOUR = {"bmo": time(13, 0), "amc": time(21, 30), "dmh": time(17, 0)}  # UTC approximations of ET


class FinnhubAdapter:
    def __init__(self, api_key: str | None = None, enabled: bool = False, transport: Transport | None = None,
                 base_url: str = "https://finnhub.io/api/v1"):
        self.enabled = enabled
        self.api_key = api_key
        self.transport = transport or OfflineTransport()
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.enabled:
            raise ProviderDisabled("Finnhub adapter disabled")
        key = require_real_key(self.api_key, "FINNHUB_API_KEY")
        return self.transport.get_json(f"{self.base_url}{path}", {**params, "token": key})

    def earnings_calendar(self, start: str, end: str) -> list[EarningsEvent]:
        data = self._get("/calendar/earnings", {"from": start, "to": end})
        out = []
        for e in data.get("earningsCalendar", []) or []:
            d = datetime.fromisoformat(e["date"]).date()
            t = _HOUR.get((e.get("hour") or "").lower(), time(23, 59))
            avail = datetime.combine(d, t, tzinfo=timezone.utc)
            if (e.get("hour") or "").lower() not in _HOUR:
                avail += timedelta(hours=1)  # unknown timing: assume available after day end
            out.append(EarningsEvent(symbol=e["symbol"], date=e["date"], hour=e.get("hour"),
                                     eps_estimate=e.get("epsEstimate"), eps_actual=e.get("epsActual"), available_at=avail))
        return out

    def news_sentiment(self, symbol: str) -> dict[str, float]:
        d = self._get("/news-sentiment", {"symbol": symbol})
        s = d.get("sentiment", {}) or {}
        return {"bullish": float(s.get("bullishPercent", 0)), "bearish": float(s.get("bearishPercent", 0)),
                "company_news_score": float(d.get("companyNewsScore", 0))}
