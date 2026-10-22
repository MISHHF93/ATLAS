"""Public last prints for the names currently on the asset library page.

Coinbase supplies a crypto last trade. Yahoo's spark endpoint supplies the
last equity, ETF, and futures print. Unlisted names, EQ#### fillers, and
PERP### fillers are skipped. Nothing is written back into the directory, and
nothing here can submit an order.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG
from atlas.marketdata.public_quotes import _get_json, fetch_public_ticker

MAX_SYMBOLS = 40
_EQUITY = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_FILLER_EQUITY = re.compile(r"^EQ\d+$")
_FILLER_PERP = re.compile(r"^PERP\d+-USD$")

# Yahoo's continuous front-month root for the futures this desk already maps.
FUTURES_YAHOO = {
    "ES": "ES=F",
    "NQ": "NQ=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
    "CL": "CL=F",
    "GC": "GC=F",
    "MES": "MES=F",
    "MNQ": "MNQ=F",
    "MYM": "MYM=F",
    "M2K": "M2K=F",
    "MCL": "MCL=F",
    "MGC": "MGC=F",
    "SI": "SI=F",
    "NG": "NG=F",
    "ZN": "ZN=F",
    "ZB": "ZB=F",
    "6E": "6E=F",
    "6J": "6J=F",
}


def quotes_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("ATLAS_DISABLE_LIVE_PUBLIC") == "1":
        return False
    return True


def _yahoo_symbol(symbol: str) -> str | None:
    if symbol in FUTURES_YAHOO:
        return FUTURES_YAHOO[symbol]
    if symbol.endswith("-USD") or _FILLER_EQUITY.match(symbol) or _FILLER_PERP.match(symbol):
        return None
    if _EQUITY.match(symbol):
        return symbol.replace(".", "-")
    return None


def select_symbols(raw: list[str]) -> list[str]:
    """Library names that can have a public print. Order is preserved. Cap 40."""
    chosen: list[str] = []
    seen: set[str] = set()
    for item in raw:
        symbol = str(item).strip().upper()
        if not symbol or symbol in seen:
            continue
        if _FILLER_EQUITY.match(symbol) or _FILLER_PERP.match(symbol):
            continue
        asset = GLOBAL_ASSET_CATALOG.get_asset(symbol)
        if asset is None or str(asset.exchange).upper() == "UNLISTED":
            continue
        if not (symbol.endswith("-USD") or symbol in FUTURES_YAHOO or _EQUITY.match(symbol)):
            continue
        seen.add(symbol)
        chosen.append(symbol)
        if len(chosen) >= MAX_SYMBOLS:
            break
    return chosen


def _from_spark(body: Any) -> list[dict[str, Any]]:
    result = ((body or {}).get("spark") or {}).get("result") if isinstance(body, dict) else None
    if not isinstance(result, list):
        return []
    quotes: list[dict[str, Any]] = []
    for row in result:
        if not isinstance(row, dict):
            continue
        response = row.get("response") or []
        meta = response[0].get("meta") if response and isinstance(response[0], dict) else None
        if not isinstance(meta, dict):
            continue
        try:
            price = float(meta.get("regularMarketPrice") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        try:
            change = float(meta.get("regularMarketChangePercent") or 0)
        except (TypeError, ValueError):
            change = 0.0
        stamp = meta.get("regularMarketTime")
        observed = None
        if isinstance(stamp, (int, float)) and stamp > 0:
            observed = datetime.fromtimestamp(int(stamp), tz=timezone.utc).isoformat()
        yahoo_name = str(meta.get("symbol") or row.get("symbol") or "")
        quotes.append(
            {
                "yahoo_symbol": yahoo_name,
                "price": price,
                "change_pct": round(change, 4),
                "observed_at": observed,
                "feed_origin": "yahoo_spark_public",
                "delayed": True,
                "execution_permission": "none",
            }
        )
    return quotes


def _yahoo_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    mapping = {symbol: yahoo for symbol in symbols if (yahoo := _yahoo_symbol(symbol))}
    if not mapping:
        return []
    encoded = ",".join(quote(name, safe="") for name in mapping.values())
    url = f"https://query1.finance.yahoo.com/v7/finance/spark?symbols={encoded}&range=1d&interval=1d"
    try:
        parsed = _from_spark(_get_json(url, timeout=4.0))
    except Exception:
        return []
    by_yahoo = {row["yahoo_symbol"]: row for row in parsed}
    quotes: list[dict[str, Any]] = []
    for symbol, yahoo in mapping.items():
        row = by_yahoo.get(yahoo)
        if row is None:
            continue
        quotes.append(
            {
                "symbol": symbol,
                "price": row["price"],
                "change_pct": row["change_pct"],
                "observed_at": row["observed_at"],
                "feed_origin": "yahoo_spark_public",
                "delayed": True,
                "execution_permission": "none",
            }
        )
    return quotes


def _crypto_quote(symbol: str) -> dict[str, Any] | None:
    tick = fetch_public_ticker(symbol, timeout=1.5)
    if tick is None:
        return None
    return {
        "symbol": symbol,
        "price": tick["price"],
        "change_pct": None,
        "observed_at": tick["observed_at"],
        "feed_origin": "coinbase_exchange_public",
        "delayed": False,
        "execution_permission": "none",
    }


def quote_library(raw: list[str]) -> dict[str, Any]:
    """Public prints for one library page. Sampling off returns an empty list."""
    requested = select_symbols(raw)
    notice = (
        "Public last prints for the names on this library page. "
        "Yahoo stock and futures prints can be delayed. Coinbase crypto prints are last trades. "
        "Unlisted names stay without a quote. Nothing is sent."
    )
    if not quotes_enabled():
        return {
            "quotes": [],
            "requested": len(requested),
            "quoted": 0,
            "execution_permission": "none",
            "notice": "Public quoting is off in this process. The directory is unchanged.",
        }
    crypto = [symbol for symbol in requested if symbol.endswith("-USD")]
    yahoo_names = [symbol for symbol in requested if not symbol.endswith("-USD")]
    quotes: list[dict[str, Any]] = []
    if crypto:
        with ThreadPoolExecutor(max_workers=min(6, len(crypto))) as pool:
            for row in pool.map(_crypto_quote, crypto):
                if row is not None:
                    quotes.append(row)
    quotes.extend(_yahoo_quotes(yahoo_names))
    order = {symbol: index for index, symbol in enumerate(requested)}
    quotes.sort(key=lambda row: order.get(str(row["symbol"]), 999))
    return {
        "quotes": quotes,
        "requested": len(requested),
        "quoted": len(quotes),
        "execution_permission": "none",
        "notice": notice,
    }
