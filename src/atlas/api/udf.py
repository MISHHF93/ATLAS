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


def _projected_rows(gateway: Any, symbol: str, bucket_seconds: int) -> tuple[list[tuple[int, float, float, float, float, float]], dict[str, Any]]:
    report = project_symbol_bars(gateway, symbol, bucket_seconds=bucket_seconds, limit=240)
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
) -> dict[str, Any]:
    bucket = resolution_seconds(resolution)
    if bucket is None:
        return {"s": "error", "errmsg": "unsupported_resolution"}
    clock = as_of or _now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    as_of_unix = int(clock.timestamp())
    rows, report = _projected_rows(gateway, _desk_symbol(symbol), bucket)
    closed_by = min(end, as_of_unix)
    visible = causal_bars(rows, bucket_seconds=bucket, start=start, end=end, as_of=closed_by)
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


def symbol_info(symbol: str) -> dict[str, Any]:
    desk = _desk_symbol(symbol)
    asset = GLOBAL_ASSET_CATALOG.get_asset(desk)
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
        "supports_timescale_marks": False,
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
) -> dict[str, Any]:
    if to <= from_ts:
        raise HTTPException(status_code=400, detail="to must be after from")
    from atlas.api.app import live_market_gateway

    return history_payload(live_market_gateway, symbol, resolution, from_ts, to)


@udf_router.get("/marks")
def udf_marks(
    symbol: str = Query(min_length=1),
    resolution: str = "D",
    from_ts: int = Query(alias="from"),
    to: int = Query(...),
) -> list[dict[str, Any]]:
    from atlas.api.app import live_market_gateway

    return marks_payload(live_market_gateway, symbol, resolution, from_ts, to)
