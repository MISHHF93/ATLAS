"""TradingView chart map for the desk.

The picture is TradingView's widget set, loaded from their site. The home desk
keeps one ticker tape and one advanced chart. Listings calls the rest of the
iframe registry published in their embed script: screeners, heatmaps, the
economic calendar, forex cross rates and heat map, hot lists, market overview,
market quotes, a static ticker strip, top stories, and the three single-symbol
embeds (symbol overview, mini chart, single quote). None of those iframes
return bars to ATLAS, and their symbol database is not downloaded. The model
keeps reading the public-candle path for the same symbol and the same
resolution. TradingView's licensed Advanced Charts library is not bundled.
Web Components that are absent from that iframe registry (Seasonal Chart,
World Market Summary, Market Summary, Economic Map, Ticker Tag) are not given
an invented tag.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

WIDGET_HOST = "https://s.tradingview.com/widgetembed/"
EMBED_HOST = "https://s.tradingview.com/embed-widget/"
CHART_PAGE = "https://www.tradingview.com/chart/"
TAPE_SYMBOLS = ("BTC-USD", "ETH-USD", "SOL-USD", "SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA")
EQUITY_PREFIXES = frozenset({"NASDAQ", "NYSE", "AMEX"})
TA_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1D": "1D",
    "1W": "1W",
}

# TradingView resolution strings. Minutes are a bare number. Days are "D".
# The free widget has no 1-second resolution. "1S" belongs to the licensed library.
WIDGET_INTERVALS = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1D": "D",
    "1W": "W",
}
BUCKET_TIMEFRAMES = {
    1: "1s",
    60: "1m",
    300: "5m",
    900: "15m",
    3600: "1h",
    14400: "4h",
    86400: "1D",
    604800: "1W",
}
TIMEFRAME_BUCKETS = {name: seconds for seconds, name in BUCKET_TIMEFRAMES.items()}

# Continuous front-month symbols as TradingView publishes them.
FUTURES = {
    "ES": "CME_MINI:ES1!",
    "NQ": "CME_MINI:NQ1!",
    "YM": "CBOT_MINI:YM1!",
    "RTY": "CME_MINI:RTY1!",
    "CL": "NYMEX:CL1!",
    "GC": "COMEX:GC1!",
    "MES": "CME_MINI:MES1!",
    "MNQ": "CME_MINI:MNQ1!",
    "MYM": "CBOT_MINI:MYM1!",
    "M2K": "CME_MINI:M2K1!",
    "MCL": "NYMEX:MCL1!",
    "MGC": "COMEX:MGC1!",
    "SI": "COMEX:SI1!",
    "NG": "NYMEX:NG1!",
    "ZN": "CBOT:ZN1!",
    "ZB": "CBOT:ZB1!",
    "6E": "CME:6E1!",
    "6J": "CME:6J1!",
}

# TradingView's prefix for NYSE Arca names such as SPY is AMEX.
EXCHANGE_PREFIX = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "NYSE_ARCA": "AMEX",
    "ARCA": "AMEX",
    "AMEX": "AMEX",
}

_EQUITY = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
_CRYPTO = re.compile(r"^([A-Z0-9]{2,15})-USD$")
_FIXTURE_EQUITY = re.compile(r"^EQ\d+$")
_FIXTURE_PERP = re.compile(r"^PERP\d+-USD$")
_QUALIFIED = re.compile(r"^[A-Z0-9._!]{1,20}:[A-Z0-9._!]{1,30}$")
_COINBASE_BASE = re.compile(r"^([A-Z0-9]{2,15})USD$")
_LOCAL_ORIGIN = re.compile(r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?$", re.IGNORECASE)


def _catalog_exchange(symbol: str) -> str | None:
    from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG

    asset = GLOBAL_ASSET_CATALOG.get_asset(symbol)
    if asset is None:
        return None
    return str(asset.exchange)


def tradingview_symbol(symbol: str, exchange: str | None = None) -> str | None:
    """Return a TradingView symbol, or None when this id is not one of their listings."""
    sym = symbol.strip().upper()
    if not sym or _FIXTURE_EQUITY.match(sym) or _FIXTURE_PERP.match(sym):
        return None
    if sym in FUTURES:
        return FUTURES[sym]
    crypto = _CRYPTO.match(sym)
    if crypto:
        return f"COINBASE:{crypto.group(1)}USD"
    if _EQUITY.match(sym):
        prefix = EXCHANGE_PREFIX.get((exchange or _catalog_exchange(sym) or "").upper())
        if prefix is None:
            return None
        return f"{prefix}:{sym}"
    return None


_FUTURES_BY_LISTING = {listing: root for root, listing in FUTURES.items()}


def model_symbol_for(tv_symbol: str) -> str | None:
    """Desk symbol the public-candle path can read for this TradingView listing."""
    if ":" not in tv_symbol:
        return None
    prefix, name = tv_symbol.split(":", 1)
    if _FIXTURE_EQUITY.match(name) or name.startswith("PERP"):
        return None
    if prefix == "COINBASE":
        match = _COINBASE_BASE.match(name)
        if match is None:
            return None
        desk = f"{match.group(1)}-USD"
        if _FIXTURE_PERP.match(desk):
            return None
        return desk
    if prefix in EQUITY_PREFIXES and _EQUITY.match(name):
        return name
    return _FUTURES_BY_LISTING.get(tv_symbol)


def local_chart_url(origin: str | None) -> str | None:
    """Widget click-through. Only this machine's desk is accepted."""
    if not origin:
        return None
    cleaned = origin.strip().rstrip("/")
    if _LOCAL_ORIGIN.fullmatch(cleaned) is None:
        return None
    return cleaned + "/?tvwidgetsymbol={symbolname}"


def _iframe(widget_id: str, config: dict[str, object]) -> str:
    payload = quote(json.dumps(config, separators=(",", ":")), safe="")
    return f"{EMBED_HOST}{widget_id}/?locale=en#{payload}"


def _symbol_page(tv_symbol: str) -> str:
    return "https://www.tradingview.com/symbols/" + quote(tv_symbol.replace(":", "-"), safe="") + "/"


def _is_equity(tv_symbol: str) -> bool:
    return tv_symbol.split(":", 1)[0] in EQUITY_PREFIXES


def _pane(
    widget_id: str,
    title: str,
    config: dict[str, object],
    page: str,
    note: str,
) -> dict[str, object]:
    return {
        "id": widget_id,
        "title": title,
        "embed_url": _iframe(widget_id, config),
        "page_url": page,
        "note": note,
        "feeds_model": False,
        "execution_permission": "none",
    }


def _companion_widgets(tv_symbol: str, timeframe: str) -> list[dict[str, object]]:
    page = _symbol_page(tv_symbol)
    dark = {"colorTheme": "dark", "isTransparent": True, "locale": "en", "width": "100%"}
    panes = [
        _pane(
            "symbol-info",
            f"{tv_symbol} quote",
            {**dark, "symbol": tv_symbol},
            page,
            "TradingView quote for this symbol. It is not a training input.",
        )
    ]
    ta_interval = TA_INTERVALS.get(timeframe)
    if ta_interval is not None:
        panes.append(
            _pane(
                "technical-analysis",
                f"{tv_symbol} technical rating",
                {
                    **dark,
                    "symbol": tv_symbol,
                    "interval": ta_interval,
                    "height": 400,
                    "showIntervalTabs": True,
                    "displayMode": "single",
                },
                page,
                "TradingView's own technical rating. Interval tabs are theirs. This is not the ATLAS model and it cannot submit an order.",
            )
        )
    panes.extend(
        [
            _pane(
                "symbol-profile",
                f"{tv_symbol} profile",
                {**dark, "height": "100%", "symbol": tv_symbol},
                page,
                "TradingView company or asset profile. Not a training input.",
            ),
            _pane(
                "financials",
                f"{tv_symbol} fundamental data",
                {**dark, "height": "100%", "symbol": tv_symbol, "displayMode": "adaptive", "largeChartUrl": ""},
                page,
                "TradingView Fundamental Data in the adaptive layout from their stock page. Statements stay inside this widget. It does not feed the model. FRED stays out of the model.",
            ),
            _pane(
                "timeline",
                f"{tv_symbol} news",
                {**dark, "height": "100%", "symbol": tv_symbol, "feedMode": "symbol", "displayMode": "regular"},
                page,
                "TradingView news for this symbol. Not a training input.",
            ),
        ]
    )
    return panes


def _symbol_artifacts(tv_symbol: str) -> list[dict[str, object]]:
    """Single-symbol iframe widgets that are not the five chart companions.

    Official embed ids: symbol-overview, mini-symbol-overview, single-quote.
    Their script defaults live in embed-widget-symbol-overview.js. These panes
    stay off the home desk. Listings mounts them for the selected symbol.
    """
    page = _symbol_page(tv_symbol)
    dark = {"colorTheme": "dark", "isTransparent": True, "locale": "en", "width": "100%"}
    label = tv_symbol.split(":", 1)[-1]
    return [
        _pane(
            "symbol-overview",
            f"{tv_symbol} overview",
            {
                **dark,
                "height": "100%",
                "autosize": True,
                "chartOnly": False,
                "symbols": [[label, f"{tv_symbol}|1D"]],
                "hideDateRanges": False,
                "hideMarketStatus": False,
                "hideSymbolLogo": False,
                "scalePosition": "right",
                "scaleMode": "Normal",
                "noTimeScale": False,
                "chartType": "area",
                "valuesTracking": "0",
                "changeMode": "price-and-percent",
            },
            page,
            "TradingView Symbol Overview for this listing. The chart inside it is theirs. It does not feed the model.",
        ),
        _pane(
            "mini-symbol-overview",
            f"{tv_symbol} mini chart",
            {
                **dark,
                "height": 220,
                "symbol": tv_symbol,
                "dateRange": "12M",
                "autosize": False,
                "largeChartUrl": "",
            },
            page,
            "TradingView Mini Chart for this listing. It does not feed the model.",
        ),
        _pane(
            "single-quote",
            f"{tv_symbol} single ticker",
            {**dark, "symbol": tv_symbol},
            page,
            "TradingView Single Ticker for this listing. It does not feed the model.",
        ),
    ]


def describe_tape(origin: str | None = None) -> dict[str, object]:
    """The nine desk names, in TradingView's ticker tape."""
    rows = []
    for name in TAPE_SYMBOLS:
        tv_symbol = tradingview_symbol(name)
        if tv_symbol is not None:
            rows.append({"proName": tv_symbol, "title": name})
    config: dict[str, object] = {
        "symbols": rows,
        "showSymbolLogo": True,
        "colorTheme": "dark",
        "isTransparent": True,
        "displayMode": "adaptive",
        "locale": "en",
    }
    link = local_chart_url(origin)
    note = "TradingView prices for both books. The tape does not select a symbol for the model."
    if link is not None:
        config["largeChartUrl"] = link
        note = "TradingView prices for both books. A click opens that listing on the desk. The tape does not feed the model."
    return {
        "symbols": [row["title"] for row in rows],
        "embed_url": _iframe("ticker-tape", config),
        "page_url": "https://www.tradingview.com/",
        "note": note,
        "origin_accepted": link is not None,
        "feeds_model": False,
        "execution_permission": "none",
    }


def describe_chart(
    symbol: str,
    *,
    timeframe: str = "1m",
    bucket_seconds: int | None = None,
    exchange: str | None = None,
) -> dict[str, object]:
    """One description for the widget and for the model read of that same slot."""
    raw = symbol.strip().upper()
    frame = timeframe
    if bucket_seconds is not None:
        frame = BUCKET_TIMEFRAMES.get(int(bucket_seconds), frame)
    if _QUALIFIED.fullmatch(raw) and not _fixture_qualified(raw):
        sym = raw
        tv_symbol = raw
        model = model_symbol_for(raw)
    else:
        sym = raw.split(":", 1)[-1] if _fixture_qualified(raw) else raw
        tv_symbol = None if _fixture_qualified(raw) else tradingview_symbol(sym, exchange)
        model = sym if tv_symbol is not None else None
    interval = WIDGET_INTERVALS.get(frame)
    bucket = TIMEFRAME_BUCKETS.get(frame)
    if tv_symbol is None:
        available = False
        reason = "not_a_tradingview_symbol"
        venue = (exchange or _catalog_exchange(sym) or "").upper()
        if venue == "UNLISTED":
            reason_text = f"{sym} is not an exchange listing. No chart is substituted."
        else:
            reason_text = f"{sym} is a catalog id and is not a TradingView listing. No chart is substituted."
        model_reads = "no_public_candle_series"
    elif interval is None:
        available = False
        reason = "resolution_not_in_widget"
        if model is None:
            reason_text = (
                "TradingView's embeddable chart does not offer 1-second bars. "
                "The model has no public-candle series for this listing."
            )
        else:
            reason_text = (
                "TradingView's embeddable chart does not offer 1-second bars. "
                "Choose 1m or a higher desk timeframe to open their chart. "
                "The model can still read this symbol at 1 second from our own tape."
            )
        model_reads = (
            "same_symbol_and_resolution_on_the_public_candle_path"
            if model is not None
            else "no_public_candle_series"
        )
    elif model is None:
        available = True
        reason = "tradingview_widget"
        reason_text = (
            f"Chart {tv_symbol} {interval} is TradingView's Advanced Chart. "
            "The model has no public-candle series for this listing. "
            "The widget does not supply those bars."
        )
        model_reads = "no_public_candle_series"
    else:
        available = True
        reason = "tradingview_widget"
        reason_text = (
            f"Chart {tv_symbol} {interval} is TradingView's Advanced Chart. "
            "The model reads this symbol at the same resolution from the public-candle path. "
            "The widget does not supply those bars."
        )
        model_reads = "same_symbol_and_resolution_on_the_public_candle_path"
    embed = None
    page = None
    widgets: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    if tv_symbol is not None:
        widgets = _companion_widgets(tv_symbol, frame)
        artifacts = _symbol_artifacts(tv_symbol)
        page = CHART_PAGE + "?symbol=" + quote(tv_symbol, safe="")
    if available and tv_symbol is not None and interval is not None:
        embed = WIDGET_HOST + "?" + urlencode(
            {
                "frameElementId": "atlas_tradingview_chart",
                "symbol": tv_symbol,
                "interval": interval,
                "hidesidetoolbar": "0",
                "hidetoptoolbar": "1",
                "symboledit": "0",
                "saveimage": "0",
                "toolbarbg": "0B0F17",
                "studies": "[]",
                "theme": "dark",
                "style": "1",
                "timezone": "Etc/UTC",
                "locale": "en",
                "withdateranges": "1",
                "hideideas": "1",
                "hidevolume": "0",
                "details": "1",
                "calendar": "1" if _is_equity(tv_symbol) else "0",
                "hotlist": "0",
            }
        )
    return {
        "symbol": sym,
        "timeframe": frame,
        "bucket_seconds": bucket,
        "tradingview_symbol": tv_symbol,
        "model_symbol": model,
        "interval": interval,
        "available": available,
        "reason": reason,
        "reason_text": reason_text,
        "embed_url": embed,
        "chart_page_url": page,
        "widgets": widgets,
        "symbol_artifacts": artifacts,
        "information_page": "stock" if tv_symbol is not None and _is_equity(tv_symbol) else "listing" if tv_symbol is not None else "none",
        "widget": "advanced_chart",
        "widget_host": "https://www.tradingview.com",
        "bars_from_tradingview": False,
        "studies_readable": False,
        "drawings_readable": False,
        "crosshair_readable": False,
        "model_reads": model_reads,
        "execution_permission": "none",
    }


def _fixture_qualified(symbol: str) -> bool:
    if not _QUALIFIED.fullmatch(symbol):
        return False
    name = symbol.split(":", 1)[1]
    return bool(_FIXTURE_EQUITY.match(name) or name.startswith("PERP"))


def _with_click(config: dict[str, object], link: str | None, field: str) -> dict[str, object]:
    merged = dict(config)
    if link is None:
        return merged
    if field == "symbolUrl":
        merged["symbolUrl"] = link.replace("{symbolname}", "{tvexchange}:{tvsymbol}")
    else:
        merged[field] = link
    return merged


def _book_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in TAPE_SYMBOLS:
        tv_symbol = tradingview_symbol(name)
        if tv_symbol is not None:
            rows.append({"proName": tv_symbol, "title": name})
    return rows


def _overview_tab(title: str, symbols: tuple[str, ...]) -> dict[str, object]:
    return {"title": title, "symbols": [{"s": symbol} for symbol in symbols]}


def describe_markets(origin: str | None = None) -> dict[str, object]:
    """TradingView's iframe catalog. Nothing here is copied into the local symbol table.

    Widget ids are the 22 names in TradingView's embed-widget-symbol-overview.js
    registry. The advanced chart and the five symbol companions are requested
    by describe_chart. Everything else in that registry is requested here.
    """
    link = local_chart_url(origin)
    dark = {"colorTheme": "dark", "locale": "en", "width": "100%", "height": "100%"}
    book = _book_rows()
    quote_groups = (
        {
            "name": "Competition",
            "symbols": [
                {"name": row["proName"], "displayName": row["title"]}
                for row in book
                if row["title"].endswith("-USD")
            ],
        },
        {
            "name": "Open market",
            "symbols": [
                {"name": row["proName"], "displayName": row["title"]}
                for row in book
                if not row["title"].endswith("-USD")
            ],
        },
    )
    specs: tuple[dict[str, object], ...] = (
        {
            "id": "us-stocks",
            "widget_id": "screener",
            "title": "US stocks",
            "height": 540,
            "page_url": "https://www.tradingview.com/screener/",
            "link_field": "largeChartUrl",
            "note": "TradingView's US stock screener. A click opens that listing on the desk. This catalog does not feed the model and cannot submit an order.",
            "config": {
                **dark,
                "defaultColumn": "overview",
                "defaultScreen": "most_capitalized",
                "showToolbar": True,
                "market": "us",
                "isTransparent": True,
            },
        },
        {
            "id": "crypto",
            "widget_id": "screener",
            "title": "Crypto",
            "height": 540,
            "page_url": "https://www.tradingview.com/crypto-coins-screener/",
            "link_field": "largeChartUrl",
            "note": "TradingView's crypto screener. A click opens that listing on the desk. This catalog does not feed the model and cannot submit an order.",
            "config": {
                **dark,
                "defaultColumn": "overview",
                "defaultScreen": "top_gainers",
                "showToolbar": True,
                "market": "crypto",
                "isTransparent": True,
            },
        },
        {
            "id": "etfs",
            "widget_id": "etf-heatmap",
            "title": "US ETFs",
            "height": 520,
            "page_url": "https://www.tradingview.com/heatmap/etf/",
            "link_field": "symbolUrl",
            "note": "TradingView's US ETF heatmap. A click opens that listing on the desk. This catalog does not feed the model and cannot submit an order.",
            "config": {
                **dark,
                "dataSource": "AllUSEtf",
                "blockSize": "volume",
                "blockColor": "change",
                "grouping": "asset_class",
                "hasTopBar": True,
                "isDataSetEnabled": True,
                "isZoomEnabled": True,
                "hasSymbolTooltip": True,
                "isMonoSize": False,
                "symbolUrl": "",
            },
        },
        {
            "id": "forex",
            "widget_id": "screener",
            "title": "Forex",
            "height": 540,
            "page_url": "https://www.tradingview.com/markets/currencies/",
            "link_field": "largeChartUrl",
            "note": "TradingView's forex screener. A click opens that listing on the desk. This catalog does not feed the model and cannot submit an order.",
            "config": {
                **dark,
                "defaultColumn": "overview",
                "defaultScreen": "top_gainers",
                "showToolbar": True,
                "market": "forex",
                "isTransparent": True,
            },
        },
        {
            "id": "stock-heatmap",
            "widget_id": "stock-heatmap",
            "title": "US stock heatmap",
            "height": 520,
            "page_url": "https://www.tradingview.com/heatmap/stock/",
            "link_field": "symbolUrl",
            "note": (
                "TradingView Stock Heatmap for the S&P 500, sized by market cap and colored by change. "
                "US stock widgets are delayed. This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "dataSource": "SPX500",
                "exchanges": [],
                "grouping": "sector",
                "blockSize": "market_cap_basic",
                "blockColor": "change",
                "hasTopBar": True,
                "isDataSetEnabled": True,
                "isZoomEnabled": True,
                "hasSymbolTooltip": True,
                "isMonoSize": False,
                "symbolUrl": "",
            },
        },
        {
            "id": "crypto-heatmap",
            "widget_id": "crypto-coins-heatmap",
            "title": "Crypto heatmap",
            "height": 520,
            "page_url": "https://www.tradingview.com/heatmap/crypto/",
            "link_field": "symbolUrl",
            "note": (
                "TradingView Crypto Coins Heatmap. Their widget FAQ calls crypto widget data real-time. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "dataSource": "Crypto",
                "blockSize": "market_cap_calc",
                "blockColor": "24h_close_change|5",
                "hasTopBar": True,
                "isDataSetEnabled": True,
                "isZoomEnabled": True,
                "hasSymbolTooltip": True,
                "isMonoSize": False,
                "symbolUrl": "",
            },
        },
        {
            "id": "crypto-market",
            "widget_id": "crypto-mkt-screener",
            "title": "Crypto market",
            "height": 540,
            "page_url": "https://www.tradingview.com/markets/cryptocurrencies/prices-all/",
            "link_field": "",
            "note": (
                "TradingView Cryptocurrency Market widget. Their widget FAQ calls crypto widget data real-time. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "defaultColumn": "overview",
                "market": "crypto",
                "screener_type": "crypto_mkt",
                "displayCurrency": "USD",
                "isTransparent": True,
            },
        },
        {
            "id": "economic-calendar",
            "widget_id": "events",
            "title": "Economic calendar",
            "height": 560,
            "page_url": "https://www.tradingview.com/economic-calendar/",
            "link_field": "",
            "note": (
                "TradingView Economic Calendar. It is their events widget. "
                "It does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "isTransparent": True,
                "hideImportanceIndicator": False,
            },
        },
        {
            "id": "forex-cross-rates",
            "widget_id": "forex-cross-rates",
            "title": "Forex cross rates",
            "height": 420,
            "page_url": "https://www.tradingview.com/markets/currencies/cross-rates/",
            "link_field": "",
            "note": (
                "TradingView Forex Cross Rates. Their widget FAQ calls forex widget data real-time. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "isTransparent": True,
                "currencies": ["EUR", "USD", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD"],
            },
        },
        {
            "id": "forex-heat-map",
            "widget_id": "forex-heat-map",
            "title": "Forex heat map",
            "height": 420,
            "page_url": "https://www.tradingview.com/markets/currencies/cross-rates-overview-heat-map/",
            "link_field": "",
            "note": (
                "TradingView Forex Heat Map. Their widget FAQ calls forex widget data real-time. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "isTransparent": True,
                "currencies": ["EUR", "USD", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD", "CNY"],
            },
        },
        {
            "id": "us-hotlists",
            "widget_id": "hotlists",
            "title": "US hot lists",
            "height": 560,
            "page_url": "https://www.tradingview.com/markets/stocks-usa/",
            "link_field": "largeChartUrl",
            "note": (
                "TradingView Stock Market hot lists for US names. US stock widgets are delayed. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "exchange": "US",
                "dateRange": "1D",
                "showChart": True,
                "showSymbolLogo": True,
                "showFloatingTooltip": True,
                "isTransparent": True,
                "largeChartUrl": "",
            },
        },
        {
            "id": "market-overview",
            "widget_id": "market-overview",
            "title": "Market overview",
            "height": 560,
            "page_url": "https://www.tradingview.com/markets/",
            "link_field": "largeChartUrl",
            "note": (
                "TradingView Market Overview for the two books and the futures the desk already maps. "
                "US stock widgets are delayed. Crypto in the widget is their real-time feed. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "dateRange": "12M",
                "showSymbolLogo": True,
                "isTransparent": True,
                "tabs": [
                    _overview_tab(
                        "Open market",
                        ("AMEX:SPY", "NASDAQ:QQQ", "NASDAQ:NVDA", "NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:TSLA"),
                    ),
                    _overview_tab("Competition", ("COINBASE:BTCUSD", "COINBASE:ETHUSD", "COINBASE:SOLUSD")),
                    _overview_tab(
                        "Futures",
                        ("CME_MINI:ES1!", "CME_MINI:NQ1!", "NYMEX:CL1!", "COMEX:GC1!"),
                    ),
                ],
            },
        },
        {
            "id": "market-quotes",
            "widget_id": "market-quotes",
            "title": "Market quotes",
            "height": 460,
            "page_url": "https://www.tradingview.com/markets/",
            "link_field": "",
            "note": (
                "TradingView Market Data table for the nine desk names. "
                "US stock widgets are delayed. Crypto in the widget is their real-time feed. "
                "This pane does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "title": "Both books",
                "showSymbolLogo": True,
                "isTransparent": True,
                "symbolsGroups": quote_groups,
            },
        },
        {
            "id": "tickers",
            "widget_id": "tickers",
            "title": "Tickers",
            "height": 120,
            "page_url": "https://www.tradingview.com/",
            "link_field": "",
            "note": (
                "TradingView Tickers strip for the nine desk names. It is not the scrolling tape. "
                "It does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "symbols": book,
                "showSymbolLogo": True,
                "isTransparent": True,
            },
        },
        {
            "id": "top-stories",
            "widget_id": "timeline",
            "title": "Top stories",
            "height": 520,
            "page_url": "https://www.tradingview.com/news/",
            "link_field": "",
            "note": (
                "TradingView Top Stories, their timeline widget with feedMode all_symbols. "
                "It does not feed the model and cannot submit an order."
            ),
            "config": {
                **dark,
                "isTransparent": True,
                "displayMode": "regular",
                "feedMode": "all_symbols",
            },
        },
    )
    widgets: list[dict[str, object]] = []
    for spec in specs:
        config = spec["config"]
        assert isinstance(config, dict)
        link_field = str(spec["link_field"])
        merged = _with_click(config, link, link_field) if link_field else dict(config)
        widgets.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "embed_url": _iframe(str(spec["widget_id"]), merged),
                "page_url": spec["page_url"],
                "note": spec["note"],
                "height": spec["height"],
                "feeds_model": False,
                "execution_permission": "none",
            }
        )
    return {
        "markets": [pane["id"] for pane in widgets],
        "widgets": widgets,
        "origin_accepted": link is not None,
        "bars_from_tradingview": False,
        "feeds_model": False,
        "execution_permission": "none",
        "note": (
            "These are the TradingView iframe widgets that are not the home chart. "
            "US stock widgets are delayed. Forex and crypto widgets use TradingView's real-time feed. "
            "Their symbol list is not downloaded. None of these panes feed the model. "
            "Seasonal Chart, World Market Summary, Market Summary, Economic Map, and Ticker Tag "
            "are Web Components and are not in the iframe registry, so they are not embedded."
        ),
    }
