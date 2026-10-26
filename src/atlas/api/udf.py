"""TradingView Universal Data Feed for the ATLAS bar store.

The Charting Library is not bundled. These endpoints follow the UDF shapes
documented at https://www.tradingview.com/charting-library-docs/latest/connecting_data/UDF
so a licensed library can point at `/api/udf`. Bars come from the same public
or labeled-fixture projection the desk already uses, queried through DuckDB
with the bar close time at or before `as_of`. Nothing here submits an order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import duckdb
from fastapi import APIRouter, HTTPException, Query

from atlas.marketdata.bar_projection import project_symbol_bars
from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG

udf_router = APIRouter(prefix="/api/udf", tags=["udf"], include_in_schema=False)

RESOLUTIONS: dict[str, int] = {"1": 60, "5": 300, "15": 900, "60": 3600, "D": 86_400, "1D": 86_400}
RESOLUTION_NAMES = ["1", "5", "15", "60", "D"]
_BONDS = {"MUB", "VTEB", "TFI", "HYMB", "CMF", "NYF", "SGOV", "BIL", "SHY", "IEF", "TLT"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _desk_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if ":" in raw:
        prefix, name = raw.split(":", 1)
        if prefix == "COINBASE" and name.endswith("USD") and len(name) > 3:
            return f"{name[:-3]}-USD"
        return name
    return raw


def _kind(symbol: str, asset_class: str | None) -> str:
    if symbol in _BONDS:
        return "bond"
    if asset_class == "crypto_perps" or symbol.endswith("-USD"):
        return "crypto"
    if asset_class == "futures":
        return "futures"
    return "stock"


def _session(kind: str) -> str:
    if kind in {"crypto", "futures"}:
        return "24x7"
    return "0930-1600"


def resolution_seconds(resolution: str) -> int | None:
    return RESOLUTIONS.get(resolution.strip().upper())


def causal_bars(
    rows: list[tuple[int, float, float, float, float, float]],
    *,
    bucket_seconds: int,
    start: int,
    end: int,
    as_of: int,
) -> list[tuple[int, float, float, float, float, float]]:
    """Keep bars whose close has printed: open >= start, close <= as_of, open < end.

    `end` is the UDF `to` bound and is exclusive. A bar is available only after
    its bucket has closed, so a request cannot see a bar that finishes later.
    """
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE udf_bars (t BIGINT, o DOUBLE, h DOUBLE, l DOUBLE, c DOUBLE, v DOUBLE)")
        if rows:
            connection.executemany("INSERT INTO udf_bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        found = connection.execute(
            """
            SELECT t, o, h, l, c, v
            FROM udf_bars
            WHERE t >= ? AND t < ? AND t + ? <= ?
            ORDER BY t
            """,
            [int(start), int(end), int(bucket_seconds), int(as_of)],
        ).fetchall()
    finally:
        connection.close()
    return [(int(t), float(o), float(h), float(l), float(c), float(v)) for t, o, h, l, c, v in found]


FEED_INTERVALS = {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 14400: "4h", 86400: "1d"}
# Desk symbols -> ATLAS feed instrument ids. BTC-USD/ETH-USD map to the USDT spot series the feed carries (labelled).
FEED_ALIASES = {
    "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT",
    "EURUSD": "EUR_USD", "EUR/USD": "EUR_USD", "EUR-USD": "EUR_USD",
    "USDCAD": "USD_CAD", "USD/CAD": "USD_CAD", "USD-CAD": "USD_CAD",
}
UDF_LIMIT = 240


def _feed() -> Any | None:
    """The process-wide ATLAS feed, or None when no store exists yet (never creates var/ files on read)."""
    import os
    from atlas.feeds import feed as feed_mod
    if feed_mod._DEFAULT is not None:
        return feed_mod._DEFAULT
    if not os.path.exists(feed_mod.DEFAULT_STORE):
        return None
    return feed_mod.get_feed()


def udf_feed_bars(gateway: Any, symbol: str, bucket_seconds: int) -> dict[str, Any]:
    """Single seam between the UDF router / detectors and ATLAS's bar source.

    Reads the authoritative ATLAS feed (``atlas.feeds``): confirmed bars only, known at ``now``. When the feed has no
    series for this symbol/interval (store not backfilled yet, or an instrument the feed does not carry) it falls back
    to the legacy projection and says so in ``feed_origin``. Returns {"candles": [{timestamp, open, high, low, close,
    volume}], "feed_origin", "quality_flags"}. /api/udf/history and /api/quant/setups both call this, so they always
    see the same bars.
    """
    interval = FEED_INTERVALS.get(int(bucket_seconds))
    from atlas.feeds.universe import resolve
    instrument = FEED_ALIASES.get(symbol.upper()) or resolve(symbol) or symbol.upper()
    feed = _feed() if interval else None
    if feed is not None and instrument in feed.instruments:
        now = int(datetime.now(timezone.utc).timestamp())
        bars = feed.bars(instrument, interval, now - UDF_LIMIT * int(bucket_seconds) * 2, now + 1, as_of=now)[-UDF_LIMIT:]
        if bars:
            providers = sorted({b.provider for b in bars})
            return {
                "candles": [
                    {"timestamp": datetime.fromtimestamp(b.event_time, timezone.utc).isoformat(), "open": b.open, "high": b.high,
                     "low": b.low, "close": b.close, "volume": b.volume}
                    for b in bars
                ],
                "feed_origin": "atlas_feed:" + "+".join(providers) + ("" if instrument == symbol.upper() else f" ({instrument})"),
                "quality_flags": list(feed.quality_flags(instrument, interval, now)),
                "instrument": instrument,
            }
    report = dict(project_symbol_bars(gateway, symbol, bucket_seconds=bucket_seconds, limit=UDF_LIMIT))
    report["feed_origin"] = f"legacy_projection (ATLAS feed has no {instrument} {interval or bucket_seconds} series): " + str(report.get("feed_origin", "unknown"))
    return report


def _projected_rows(gateway: Any, symbol: str, bucket_seconds: int) -> tuple[list[tuple[int, float, float, float, float, float]], dict[str, Any]]:
    report = udf_feed_bars(gateway, symbol, bucket_seconds)
    rows: list[tuple[int, float, float, float, float, float]] = []
    for candle in report.get("candles") or []:
        stamp = datetime.fromisoformat(str(candle["timestamp"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        rows.append(
            (
                int(stamp.timestamp()),
                float(candle["open"]),
                float(candle["high"]),
                float(candle["low"]),
                float(candle["close"]),
                float(candle.get("volume") or 0.0),
            )
        )
    return rows, report


def history_payload(
    gateway: Any,
    symbol: str,
    resolution: str,
    start: int,
    end: int,
    *,
    as_of: datetime | None = None,
    countback: int | None = None,
) -> dict[str, Any]:
    """UDF ``/history``. ``countback`` wins over ``from`` per the UDF spec."""
    bucket = resolution_seconds(resolution)
    if bucket is None:
        return {"s": "error", "errmsg": "unsupported_resolution"}
    clock = as_of or _now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    as_of_unix = int(clock.timestamp())
    rows, report = _projected_rows(gateway, _desk_symbol(symbol), bucket)
    closed_by = min(end, as_of_unix)
    if countback is not None and countback > 0:
        start = 0
    visible = causal_bars(rows, bucket_seconds=bucket, start=start, end=end, as_of=closed_by)
    if countback is not None and countback > 0:
        visible = visible[-int(countback):]
    if not visible:
        earlier = [row[0] for row in rows if row[0] < start and row[0] + bucket <= closed_by]
        payload: dict[str, Any] = {"s": "no_data", "execution_permission": "none"}
        if earlier:
            payload["nextTime"] = max(earlier)
        return payload
    return {
        "s": "ok",
        "t": [row[0] for row in visible],
        "o": [row[1] for row in visible],
        "h": [row[2] for row in visible],
        "l": [row[3] for row in visible],
        "c": [row[4] for row in visible],
        "v": [row[5] for row in visible],
        "feed_origin": report.get("feed_origin"),
        "execution_permission": "none",
    }


def _atr(rows: list[tuple[int, float, float, float, float, float]], index: int) -> float:
    """Mean of up to 14 true ranges ending at ``index`` (rolling simple mean; canonical TR)."""
    from atlas.features.price_action.indicators import true_range_batch
    start = max(1, index - 13)
    if index < start:
        return 0.0
    seg = rows[start - 1:index + 1]
    tr = true_range_batch([r[2] for r in seg], [r[3] for r in seg], [r[4] for r in seg])[1:]
    return float(sum(float(v) for v in tr) / len(tr))


def marks_payload(gateway: Any, symbol: str, resolution: str, start: int, end: int) -> list[dict[str, Any]]:
    """Chart marks from closed bars only. There is no news feed on this path."""
    bucket = resolution_seconds(resolution) or 60
    rows, _report = _projected_rows(gateway, _desk_symbol(symbol), bucket)
    visible = causal_bars(rows, bucket_seconds=bucket, start=start, end=end, as_of=min(end, int(_now().timestamp())))
    marks: list[dict[str, Any]] = []
    volumes = [row[5] for row in visible]
    for index, row in enumerate(visible):
        if index < 15:
            continue
        prior = volumes[max(0, index - 20) : index]
        median = sorted(prior)[len(prior) // 2] if prior else 0.0
        atr = _atr(visible, index - 1)
        previous_close = visible[index - 1][4]
        if atr > 0 and row[4] >= previous_close + 1.5 * atr:
            marks.append(
                {
                    "id": f"fan-{row[0]}",
                    "time": row[0],
                    "color": "#00C8FF",
                    "text": "Closed bar crossed the prior +1.5 ATR band",
                    "label": "F",
                    "labelFontColor": "#070A0F",
                    "minSize": 14,
                }
            )
        if median > 0 and row[5] >= median * 3:
            marks.append(
                {
                    "id": f"cluster-{row[0]}",
                    "time": row[0],
                    "color": "#F4C460",
                    "text": "Volume at least 3x the prior median. Not an identified iceberg.",
                    "label": "V",
                    "labelFontColor": "#070A0F",
                    "minSize": 14,
                }
            )
    return marks[-40:]


def to_table(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, list[Any]]:
    """UDF "response-as-a-table": one array per column."""
    return {key: [row.get(key) for row in rows] for key in keys}


MARK_KEYS = ("id", "time", "color", "text", "label", "labelFontColor", "minSize")


def timescale_marks_payload(gateway: Any, symbol: str, resolution: str, start: int, end: int) -> list[dict[str, Any]]:
    """Session-open marks on the time scale for intraday stock bars (09:30 New York).

    Derived only from the bar timestamps ATLAS already holds. No news or events feed.
    """
    from zoneinfo import ZoneInfo

    bucket = resolution_seconds(resolution) or 60
    if bucket >= 86_400:
        return []
    desk = _desk_symbol(symbol)
    asset = GLOBAL_ASSET_CATALOG.get_asset(desk)
    if _kind(desk, asset.asset_class if asset is not None else None) not in {"stock", "bond"}:
        return []
    rows, _report = _projected_rows(gateway, desk, bucket)
    visible = causal_bars(rows, bucket_seconds=bucket, start=start, end=end, as_of=min(end, int(_now().timestamp())))
    zone = ZoneInfo("America/New_York")
    seen: set[str] = set()
    marks: list[dict[str, Any]] = []
    for row in visible:
        local = datetime.fromtimestamp(row[0], zone)
        day = local.date().isoformat()
        if day in seen or (local.hour, local.minute) < (9, 30):
            continue
        seen.add(day)
        marks.append(
            {
                "id": f"open-{day}",
                "time": row[0],
                "color": "#56B4E9",
                "label": "O",
                "tooltip": [f"First regular-session bar {day} (09:30 New York)"],
            }
        )
    return marks[-40:]


def symbol_info(symbol: str) -> dict[str, Any]:
    desk = _desk_symbol(symbol)
    asset = GLOBAL_ASSET_CATALOG.get_asset(desk)
    if asset is None and not desk.endswith("-USD") and desk not in _BONDS:
        return {"s": "error", "errmsg": "unknown_symbol"}
    kind = _kind(desk, asset.asset_class if asset is not None else None)
    price = float(asset.last_price) if asset is not None else 100.0
    pricescale = 100 if price >= 1 else 10000
    return {
        "name": desk,
        "ticker": desk,
        "description": asset.name if asset is not None else desk,
        "type": kind,
        "session": _session(kind),
        "timezone": "America/New_York",
        "exchange": asset.exchange if asset is not None else "ATLAS",
        "listed_exchange": asset.exchange if asset is not None else "ATLAS",
        "minmov": 1,
        "pricescale": pricescale,
        "has_intraday": True,
        "has_daily": True,
        "has_weekly_and_monthly": False,
        "supported_resolutions": RESOLUTION_NAMES,
        "volume_precision": 2,
        "visible_plots_set": "ohlcv",
        "data_status": "pulsed",
        "format": "price",
        "execution_permission": "none",
    }


@udf_router.get("/config")
def udf_config() -> dict[str, Any]:
    return {
        "supported_resolutions": RESOLUTION_NAMES,
        "supports_group_request": False,
        "supports_marks": True,
        "supports_search": True,
        "supports_timescale_marks": True,
        "supports_time": True,
        "symbols_types": [
            {"name": "Stock", "value": "stock"},
            {"name": "Crypto", "value": "crypto"},
            {"name": "Futures", "value": "futures"},
            {"name": "Bond", "value": "bond"},
        ],
        "exchanges": [
            {"value": "", "name": "All", "desc": "All"},
            {"value": "NASDAQ", "name": "NASDAQ", "desc": "NASDAQ"},
            {"value": "NYSE", "name": "NYSE", "desc": "NYSE"},
            {"value": "NYSE_ARCA", "name": "NYSE Arca", "desc": "NYSE Arca"},
            {"value": "COINBASE", "name": "Coinbase", "desc": "Coinbase"},
            {"value": "CME", "name": "CME", "desc": "CME"},
        ],
        "execution_permission": "none",
    }


@udf_router.get("/time")
def udf_time() -> int:
    return int(_now().timestamp())


@udf_router.get("/symbols")
def udf_symbols(symbol: str = Query(min_length=1)) -> dict[str, Any]:
    return symbol_info(symbol)


@udf_router.get("/search")
def udf_search(
    query: str = "",
    type: str = "",
    exchange: str = "",
    limit: int = 30,
) -> list[dict[str, Any]]:
    kind_map = {"stock": "equities", "crypto": "crypto_perps", "futures": "futures", "bond": "equities"}
    asset_class = kind_map.get(type.strip().lower())
    found = GLOBAL_ASSET_CATALOG.search(
        query,
        asset_class=asset_class,
        limit=max(1, min(limit, 50)),
    )
    rows = []
    for item in found.get("results") or []:
        desk = str(item["symbol"])
        if exchange and exchange.upper() not in str(item.get("exchange", "")).upper():
            continue
        kind = _kind(desk, str(item.get("asset_class")))
        if type and kind != type.strip().lower():
            continue
        rows.append(
            {
                "symbol": desk,
                "full_name": desk,
                "description": item.get("name") or desk,
                "exchange": item.get("exchange") or "",
                "type": kind,
                "execution_permission": "none",
            }
        )
    return rows


@udf_router.get("/history")
def udf_history(
    symbol: str = Query(min_length=1),
    resolution: str = "D",
    from_ts: int = Query(alias="from"),
    to: int = Query(...),
    countback: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    if to <= from_ts and not countback:
        raise HTTPException(status_code=400, detail="to must be after from")
    from atlas.api.app import live_market_gateway

    return history_payload(live_market_gateway, symbol, resolution, from_ts, to, countback=countback)


@udf_router.get("/marks")
def udf_marks(
    symbol: str = Query(min_length=1),
    resolution: str = "D",
    from_ts: int = Query(alias="from"),
    to: int = Query(...),
    layout: str = "table",
) -> Any:
    """Bar marks. Default is the UDF table form; ``layout=rows`` keeps the array form."""
    from atlas.api.app import live_market_gateway

    rows = marks_payload(live_market_gateway, symbol, resolution, from_ts, to)
    return rows if layout == "rows" else to_table(rows, MARK_KEYS)


@udf_router.get("/timescale_marks")
def udf_timescale_marks(
    symbol: str = Query(min_length=1),
    resolution: str = "D",
    from_ts: int = Query(alias="from"),
    to: int = Query(...),
) -> list[dict[str, Any]]:
    from atlas.api.app import live_market_gateway

    return timescale_marks_payload(live_market_gateway, symbol, resolution, from_ts, to)
