"""Public candle reads for the desk.

Coinbase's public product API supplies crypto candles. Yahoo's public chart
API supplies equity and ETF candles. Neither call is a Polygon, Databento, or
broker session. A miss returns no candles. Callers keep the labeled fixture
and say so.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

_COINBASE_GRANULARITY = (60, 300, 900, 3600, 21600, 86400)
_YAHOO_INTERVAL = {
    60: ("1m", "1d"),
    300: ("5m", "5d"),
    900: ("15m", "5d"),
    3600: ("1h", "1mo"),
    21600: ("1h", "3mo"),
    86400: ("1d", "6mo"),
}


def public_bucket(bucket_seconds: int) -> int | None:
    """Snap a chart bucket to a granularity a public endpoint actually serves."""
    bucket = int(bucket_seconds)
    if bucket < 60:
        return None
    for choice in _COINBASE_GRANULARITY:
        if bucket <= choice:
            return choice
    return 86400


def _get_json(url: str, timeout: float = 3.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "ATLASQuantEngine/2.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _coinbase_candles(symbol: str, granularity: int, limit: int) -> list[dict[str, Any]]:
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles?granularity={granularity}"
    raw = _get_json(url)
    if not isinstance(raw, list) or len(raw) < 8:
        return []
    candles: list[dict[str, Any]] = []
    for row in reversed(raw[: max(8, min(limit, len(raw)))]):
        if not isinstance(row, list) or len(row) < 6:
            continue
        stamp = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
        low, high, open_px, close_px = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        if min(open_px, high, low, close_px) <= 0 or low > high:
            continue
        candles.append(
            {
                "timestamp": stamp.isoformat(),
                "open": open_px,
                "high": high,
                "low": low,
                "close": close_px,
                "volume": float(row[5]),
            }
        )
    return candles


def _yahoo_candles(symbol: str, granularity: int, limit: int) -> list[dict[str, Any]]:
    interval, range_ = _YAHOO_INTERVAL.get(granularity, ("1h", "1mo"))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
    raw = _get_json(url)
    result = (raw.get("chart") or {}).get("result") or []
    if not result:
        return []
    block = result[0]
    timestamps = block.get("timestamp") or []
    quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    candles: list[dict[str, Any]] = []
    for stamp, open_px, high, low, close_px, volume in zip(
        timestamps,
        quote.get("open") or [],
        quote.get("high") or [],
        quote.get("low") or [],
        quote.get("close") or [],
        quote.get("volume") or [],
    ):
        if None in (open_px, high, low, close_px):
            continue
        values = (float(open_px), float(high), float(low), float(close_px))
        if min(values) <= 0 or values[2] > values[1]:
            continue
        candles.append(
            {
                "timestamp": datetime.fromtimestamp(int(stamp), tz=timezone.utc).isoformat(),
                "open": values[0],
                "high": values[1],
                "low": values[2],
                "close": values[3],
                "volume": float(volume or 0.0),
            }
        )
    return candles[-max(8, min(limit, len(candles))):]


def fetch_public_candles(symbol: str, bucket_seconds: int, *, limit: int = 180) -> dict[str, Any] | None:
    """Return public OHLCV bars, or None when the endpoint misses."""
    sym = symbol.strip().upper()
    granularity = public_bucket(bucket_seconds)
    if granularity is None or not sym:
        return None
    try:
        if sym.endswith("-USD"):
            candles = _coinbase_candles(sym, granularity, limit)
            source = "coinbase_exchange_public"
        else:
            candles = _yahoo_candles(sym, granularity, limit)
            source = "yahoo_chart_public"
    except Exception:
        return None
    if len(candles) < 8:
        return None
    return {
        "symbol": sym,
        "bucket_seconds": granularity,
        "candles": candles,
        "feed_source": source,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "execution_permission": "none",
    }


def fetch_public_ticker(symbol: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """Last public crypto trade from Coinbase. Equities have no second print here."""
    sym = symbol.strip().upper()
    if not sym.endswith("-USD"):
        return None
    try:
        raw = _get_json(f"https://api.exchange.coinbase.com/products/{sym}/ticker", timeout=timeout)
        size = float(raw.get("size") or 0) if isinstance(raw, dict) else 0.0
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        price = float(raw.get("price") or 0)
        bid = float(raw.get("bid") or 0)
        ask = float(raw.get("ask") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    observed = raw.get("time")
    if not isinstance(observed, str) or not observed:
        return None
    return {
        "symbol": sym,
        "price": price,
        "size": size if size > 0 else 0.0,
        "bid": bid if bid > 0 else None,
        "ask": ask if ask > 0 else None,
        "observed_at": observed,
        "feed_origin": "coinbase_exchange_public",
        "data_mode": "public_last_trade",
        "execution_permission": "none",
    }
