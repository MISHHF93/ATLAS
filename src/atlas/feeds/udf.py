"""Pure-Python helpers the UDF/chart worker calls (no web framework here; routes live in the UDF worker's files)."""
from __future__ import annotations

from .core import INTERVALS
from .feed import AtlasFeed, get_feed

RES = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "240": "4h", "1D": "1d", "D": "1d"}


def history(symbol: str, resolution: str, frm: int, to: int, feed: AtlasFeed | None = None, include_unconfirmed: bool = False) -> dict:
    """TradingView UDF /history payload from the authoritative ATLAS feed."""
    feed = feed or get_feed()
    iv = RES.get(resolution, resolution)
    bars = feed.bars(symbol, iv, frm, to + 1, confirmed_only=not include_unconfirmed)
    if not bars:
        older = feed.bars(symbol, iv, None, frm)
        return {"s": "no_data", **({"nextTime": older[-1].event_time} if older else {})}
    return {"s": "ok", "t": [b.event_time for b in bars], "o": [b.open for b in bars], "h": [b.high for b in bars],
            "l": [b.low for b in bars], "c": [b.close for b in bars], "v": [b.volume for b in bars]}


def symbol_info(symbol: str, feed: AtlasFeed | None = None) -> dict:
    feed = feed or get_feed()
    i = feed.instruments.get(symbol)
    session = {"24x7": "24x7", "us_equity_rth": "0930-1600", "fx_24x5": "24x7", "cme_globex": "1700-1600"}.get(i.session, "24x7")
    return {"name": i.id, "ticker": i.id, "description": i.description, "type": i.asset_class, "exchange": i.venue,
            "timezone": "Etc/UTC" if i.timezone == "UTC" else i.timezone, "session": session, "minmov": 1,
            "pricescale": int(round(1 / i.tick_size)), "currency_code": i.currency, "has_intraday": True,
            "supported_resolutions": ["15", "60", "1D"], "data_status": "streaming" if i.asset_class == "crypto" else "delayed_streaming"}
