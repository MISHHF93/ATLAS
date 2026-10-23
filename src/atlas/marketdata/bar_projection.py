"""Labeled bar history for every catalog symbol.

The desk chart asks for a full candle series, not the handful of ticks collected
since the page connected. History is a deterministic fixture anchored to the
catalog price. When the ring buffer already has ticks for that symbol, those
ticks replace the right edge. Nothing here is written back into the buffer, and
nothing here is a venue print. ``execution_permission`` stays ``none``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG
from atlas.marketdata.live_stream import LiveMarketDataGateway, LiveTickFrame

_COMPETITION_ROOTS = {"ES", "NQ", "YM", "RTY", "CL", "GC", "MES", "MNQ", "MYM", "M2K", "MCL", "MGC", "SI", "NG", "ZN", "ZB", "6E", "6J"}


def _no_quote_report(sym: str, asset: Any, bucket: int) -> dict[str, Any]:
    """A directory name with no stored price. No series is invented."""
    return {
        "symbol": sym,
        "track": _track_for(sym, asset.track if asset is not None else None),
        "bucket_seconds": bucket,
        "bar_count": 0,
        "candles": [],
        "last_close": 0.0,
        "chart_source": "no_quote",
        "data_mode": "withheld",
        "feed_origin": "labeled_synthetic_fixture",
        "catalog_found": asset is not None,
        "venue_sessions": "unconfigured",
        "notice": "This directory name has no quote. No price series is invented.",
        "execution_permission": "none",
    }


def _track_for(symbol: str, catalog_track: str | None) -> str:
    if catalog_track in ("competition", "open_market"):
        return catalog_track
    sym = symbol.upper()
    if sym.endswith("-USD") or sym in _COMPETITION_ROOTS:
        return "competition"
    return "open_market"


def _round_px(price: float, anchor: float) -> float:
    scale = max(abs(anchor), abs(price), 1e-8)
    if scale >= 100:
        return round(price, 2)
    if scale >= 1:
        return round(price, 4)
    if scale >= 0.01:
        return round(price, 6)
    return round(price, 8)


def _repair_bar(bar: dict[str, Any], anchor: float) -> None:
    floor = max(anchor * 1e-6, 1e-8)
    for key in ("open", "high", "low", "close"):
        bar[key] = max(_round_px(float(bar[key]), anchor), floor)
    low = min(float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
    high = max(float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
    bar["low"] = _round_px(low, anchor)
    bar["high"] = _round_px(max(high, float(bar["low"])), anchor)


def _align(moment: datetime, bucket_seconds: int) -> datetime:
    bucket = max(1, int(bucket_seconds))
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp((epoch // bucket) * bucket, tz=timezone.utc)


def _fixture_history(
    symbol: str,
    anchor: float,
    *,
    bucket_seconds: int,
    limit: int,
    end: datetime,
) -> list[dict[str, Any]]:
    count = max(0, int(limit))
    if count == 0 or anchor <= 0:
        return []
    bucket = max(1, int(bucket_seconds))
    seed = sum((index + 1) * ord(char) for index, char in enumerate(symbol))
    amp = max(anchor * 0.0035, 1e-8)
    end_aligned = _align(end, bucket)
    raw: list[dict[str, Any]] = []
    price = anchor
    for idx in range(count):
        wave = math.sin(seed * 0.017 + idx * 0.41) * amp + math.sin(idx * 0.13 + seed * 0.01) * amp * 0.35
        open_px = price
        close_px = open_px + wave
        high_px = max(open_px, close_px) + abs(wave) * 0.45 + amp * 0.08
        low_px = min(open_px, close_px) - abs(wave) * 0.40 - amp * 0.08
        stamp = end_aligned - timedelta(seconds=bucket * (count - 1 - idx))
        raw.append(
            {
                "timestamp": stamp.isoformat(),
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "volume": round(900.0 + (idx % 17) * 70.0 + abs(wave) / max(amp, 1e-8) * 180.0, 2),
            }
        )
        price = close_px
    shift = anchor - float(raw[-1]["close"])
    for bar in raw:
        for key in ("open", "high", "low", "close"):
            bar[key] = float(bar[key]) + shift
        _repair_bar(bar, anchor)
    raw[-1]["close"] = _round_px(anchor, anchor)
    _repair_bar(raw[-1], anchor)
    return raw


def _bucket_frames(frames: list[LiveTickFrame], bucket_seconds: int) -> list[dict[str, Any]]:
    bucket = max(1, int(bucket_seconds))
    bars: list[dict[str, Any]] = []
    current_key: int | None = None
    for frame in frames:
        key = int(frame.exchange_timestamp.timestamp()) // bucket
        price = float(frame.price)
        size = float(frame.size)
        if current_key != key or not bars:
            current_key = key
            start = datetime.fromtimestamp(key * bucket, tz=timezone.utc)
            bars.append(
                {
                    "timestamp": start.isoformat(),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": size,
                }
            )
        else:
            bar = bars[-1]
            bar["high"] = max(float(bar["high"]), price)
            bar["low"] = min(float(bar["low"]), price)
            bar["close"] = price
            bar["volume"] = float(bar["volume"]) + size
    for bar in bars:
        anchor = float(bar["close"])
        _repair_bar(bar, anchor if anchor > 0 else 1.0)
        bar["volume"] = round(float(bar["volume"]), 4)
    return bars


def project_symbol_bars(
    gateway: LiveMarketDataGateway,
    symbol: str,
    *,
    bucket_seconds: int = 60,
    limit: int = 160,
) -> dict[str, Any]:
    sym = symbol.strip().upper() or "BTC-USD"
    bucket = min(86_400, max(1, int(bucket_seconds)))
    bar_limit = min(240, max(8, int(limit)))
    now = datetime.now(timezone.utc)
    asset = GLOBAL_ASSET_CATALOG.get_asset(sym)
    if asset is not None and str(asset.exchange).upper() == "UNLISTED":
        return _no_quote_report(sym, asset, bucket)
    public = gateway.public_bars(sym, bucket) if hasattr(gateway, "public_bars") else None
    if public and len(public.get("candles") or []) >= 8:
        candles = list(public["candles"])[-bar_limit:]
        gateway.note_chart_symbol(sym)
        return {
            "symbol": sym,
            "track": _track_for(sym, asset.track if asset is not None else None),
            "bucket_seconds": int(public["bucket_seconds"]),
            "bar_count": len(candles),
            "candles": candles,
            "last_close": float(candles[-1]["close"]),
            "chart_source": "public_market_candles",
            "data_mode": "observed",
            "feed_origin": str(public["feed_source"]),
            "catalog_found": asset is not None,
            "venue_sessions": "public_market_data",
            "notice": "Public candles from the named feed. This is not a Polygon, Databento, or broker session. The model still cannot send an order.",
            "execution_permission": "none",
        }

    if bucket == 1:
        from atlas.marketdata.second_tape import snapshot

        tape = snapshot(sym, sampling=bool(getattr(gateway, "public_fetch_enabled", False)), register_interest=False)
        tape_rows = [bar for bar in (tape.get("candles") or []) if bar.get("timestamp")]
        if len(tape_rows) >= 8:
            gateway.note_chart_symbol(sym)
            return {
                "symbol": sym,
                "track": _track_for(sym, asset.track if asset is not None else None),
                "bucket_seconds": 1,
                "bar_count": len(tape_rows),
                "candles": tape_rows[-bar_limit:],
                "last_close": float(tape_rows[-1]["close"]),
                "chart_source": tape.get("chart_source", "public_last_trade"),
                "data_mode": "observed",
                "feed_origin": tape.get("feed_origin", "coinbase_exchange_public"),
                "catalog_found": asset is not None,
                "venue_sessions": "public_trade_tape",
                "notice": "One-second bars from the same public trade tape used by the live viewer. Equities stay withheld without that transport.",
                "execution_permission": "none",
            }

    latest = gateway.ring_buffer.latest(sym)
    if latest is not None and latest.price > 0:
        anchor = float(latest.price)
    elif asset is not None and asset.last_price > 0:
        anchor = float(asset.last_price)
    elif asset is not None and asset.last_price <= 0:
        return _no_quote_report(sym, asset, bucket)
    else:
        anchor = 100.0

    frames = gateway.ring_buffer.query_pit_records(as_of=now, symbol=sym)
    frames = sorted(frames, key=lambda frame: frame.exchange_timestamp)
    stream_bars = _bucket_frames(frames, bucket) if len(frames) >= 2 else []
    if stream_bars:
        first_stamp = datetime.fromisoformat(str(stream_bars[0]["timestamp"]))
        history_end = first_stamp - timedelta(seconds=bucket)
        fixture = _fixture_history(
            sym,
            float(stream_bars[0]["open"]),
            bucket_seconds=bucket,
            limit=max(0, bar_limit - len(stream_bars)),
            end=history_end,
        )
        first_key = stream_bars[0]["timestamp"]
        candles = [bar for bar in fixture if str(bar["timestamp"]) < str(first_key)] + stream_bars
        candles = candles[-bar_limit:]
        chart_source = "stream_ring_buffer" if len(fixture) == 0 else "fixture_history_plus_stream_tail"
    else:
        candles = _fixture_history(sym, anchor, bucket_seconds=bucket, limit=bar_limit, end=now)
        chart_source = "labeled_fixture_bars"

    gateway.note_chart_symbol(sym)
    feed_origin = "labeled_synthetic_fixture" if gateway.demo_mode or (latest is not None and latest.data_mode == "demo") else "stream_ring_buffer"
    if gateway.demo_mode:
        feed_origin = "labeled_synthetic_fixture"
    return {
        "symbol": sym,
        "track": _track_for(sym, asset.track if asset is not None else None),
        "bucket_seconds": bucket,
        "bar_count": len(candles),
        "candles": candles,
        "last_close": float(candles[-1]["close"]) if candles else anchor,
        "chart_source": chart_source,
        "data_mode": "synthetic" if chart_source in {"labeled_fixture_bars", "fixture_history_plus_stream_tail"} else "observed",
        "feed_origin": feed_origin,
        "catalog_found": asset is not None,
        "venue_sessions": "unconfigured",
        "notice": "Labeled fixture history for this symbol. The right edge follows the desk stream once that symbol is ticking. This is not an exchange or SIP print.",
        "execution_permission": "none",
    }
