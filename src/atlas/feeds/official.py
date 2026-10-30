"""Official feeds the paper desk is allowed to trade from.

A provider is official when its terms allow automated personal use and the free-data gate
allows it. Yahoo is stored only as a labeled delayed quote. It is not a bar source for the
authoritative series, the trend book, or model evolution. This module submits no orders.
"""
from __future__ import annotations

import time
from typing import Any

from .free_sources import SOURCES, allowed

# Names that must not count as a public proof even if a caller marked the mode public.
_BLOCKED_ORIGIN_PARTS = ("yahoo", "fixture", "synthetic", "unofficial")

# Daily trend book. Crypto uses keyless official history. FX uses BoC and ECB reference rates.
TRADE_DAILY = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "USD_CAD", "EUR_USD")
DAILY_LOOKBACK_S = 400 * 86400

_SYMBOL_IDS = {
    "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "SOL-USD": "SOLUSDT",
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
}


def is_official_origin(origin: str | None) -> bool:
    """True for a named public source that is not Yahoo and not a fixture."""
    text = str(origin or "").strip().lower()
    if not text:
        return False
    return not any(part in text for part in _BLOCKED_ORIGIN_PARTS)


def counts_for_proof(data_mode: str, feed_origin: str | None) -> bool:
    """Public rows count unless they name an unofficial source.

    An empty origin means the caller already labeled the row public and did not
    name a provider. Yahoo and fixtures are named and do not count.
    """
    if data_mode != "public_market_candles":
        return False
    if feed_origin is None or not str(feed_origin).strip():
        return True
    return is_official_origin(feed_origin)


def _instrument_id(symbol: str) -> str:
    key = symbol.strip().upper()
    if key in _SYMBOL_IDS:
        return _SYMBOL_IDS[key]
    from .universe import resolve
    return resolve(key) or key


def _candles_from_bars(bars) -> list[dict[str, Any]]:
    out = []
    for bar in bars:
        out.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(bar.event_time))),
            "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
            "volume": bar.volume or 0.0,
        })
    return out


def daily_frame(symbol: str, feed=None, *, min_bars: int = 21) -> dict[str, Any] | None:
    """Official daily candles for the trend ledger, or None when that symbol has no official series.

    Only stored 1d bars are read. The live ingest writes those from Alpaca crypto, the Bank of Canada,
    and the ECB. This does not scan 1m history and it does not call Yahoo.
    """
    if feed is None:
        from .feed import get_feed
        try:
            feed = get_feed()
        except Exception:
            return None
    iid = _instrument_id(symbol)
    try:
        inst = feed.instruments.get(iid)
    except Exception:
        return None
    if inst is None:
        return None
    try:
        bars = list(feed.bars(iid, "1d", int(time.time()) - DAILY_LOOKBACK_S))
    except Exception:
        return None
    if len(bars) < min_bars:
        return None
    providers = sorted({b.provider for b in bars})
    if not providers or not all(allowed(p) for p in providers):
        return None
    track = "competition" if inst.asset_class == "crypto" else "open_market"
    return {
        "symbol": symbol.strip().upper(),
        "track": track,
        "candles": _candles_from_bars(bars[-400:]),
        "data_mode": "public_market_candles",
        "feed_origin": "+".join(providers),
        "instrument": iid,
    }


def desk_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    """What the paper desk can use right now. Reads no secret values and submits nothing."""
    from atlas.integrations.registry import load_env, status
    env = load_env() if env is None else env
    try:
        services = status(env=env, probe=False)["services"]
    except Exception:
        services = []
    keyless = sorted(name for name, terms in SOURCES.items() if terms.terms_ok and terms.cost == "free" and allowed(name, env))
    configured = [row["id"] for row in services if row.get("configured") and row.get("category") in ("market_data", "broker_paper", "macro", "filings")]
    missing = [
        {"id": row["id"], "title": row["title"], "needs": [k for k, ok in row.get("required_vars", {}).items() if not ok]}
        for row in services
        if row.get("category") in ("market_data", "broker_paper", "macro") and not row.get("configured") and row.get("cost") != "paid"
    ]
    alpaca_on = any(row.get("id") == "alpaca" and row.get("configured") and row.get("mode") != "live_refused" for row in services)
    fresh = _freshness()
    notice = (
        "Paper simulator is the broker. Live orders stay off. "
        "Official book: keyless crypto (Coinbase, Kraken, Alpaca crypto) and daily Bank of Canada / ECB FX. "
        "US stocks, ETFs and CME futures have no official feed until a free key is in .env. "
        "Yahoo quotes stay on the tape as delayed and unofficial. They are not trade bars."
    )
    return {
        "execution_permission": "none",
        "orders_submitted": 0,
        "may_propose_order": False,
        "live_money": "disabled",
        "paper_broker": "alpaca_paper" if alpaca_on else "internal_simulator",
        "live_endpoint": "refused",
        "keyless_official": keyless,
        "configured": configured,
        "needs_key": missing,
        "freshness": fresh,
        "trend_book": list(TRADE_DAILY),
        "notice": notice,
    }


def _freshness() -> dict[str, Any]:
    """Age of the newest official bar for the trend book. Empty when the store is absent."""
    out: dict[str, Any] = {}
    try:
        from .feed import get_feed
        feed = get_feed()
    except Exception:
        return out
    now = time.time()
    for iid, interval in (("BTCUSDT", "1m"), ("ETHUSDT", "1m"), ("USD_CAD", "1d"), ("EUR_USD", "1d")):
        try:
            if interval == "1d":
                rows = feed.bars(iid, "1d", int(now) - DAILY_LOOKBACK_S)
                last = rows[-1] if rows else None
                count = len(rows)
            else:
                last = feed.store.latest_bar(iid, (interval,))
                if last is not None and not allowed(last.provider):
                    last = None
                count = 0 if last is None else 1
        except Exception:
            continue
        if last is None:
            out[iid] = {"interval": interval, "bars": 0, "official": False}
            continue
        out[iid] = {
            "interval": interval, "bars": count, "provider": last.provider,
            "age_seconds": round(now - last.bar_end, 1), "official": allowed(last.provider),
        }
    return out


def official_checks(env: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Readiness rows. A met official feed does not open live money."""
    desk = desk_status(env)
    crypto_live = any(
        (desk["freshness"].get(sym) or {}).get("official") and (desk["freshness"].get(sym) or {}).get("age_seconds", 1e12) < 180
        for sym in ("BTCUSDT", "ETHUSDT")
    )
    fx = any((desk["freshness"].get(sym) or {}).get("bars", 0) >= 21 for sym in ("USD_CAD", "EUR_USD"))
    equities = desk["paper_broker"] == "alpaca_paper"
    return [
        {
            "id": "official_crypto",
            "status": "met" if crypto_live else "closed",
            "detail": "A keyless official crypto bar is under three minutes old." if crypto_live
            else "No official crypto 1m bar is fresh. The live ingest has to be running.",
        },
        {
            "id": "official_fx_reference",
            "status": "met" if fx else "closed",
            "detail": "Bank of Canada or ECB daily history is in the store." if fx
            else "Official daily FX is not in the store yet. The ingest backfill writes USD_CAD and EUR_USD.",
        },
        {
            "id": "paper_simulator",
            "status": "met",
            "detail": f"Broker is {desk['paper_broker']}. The live endpoint is refused. No order is submitted from this page.",
        },
        {
            "id": "equity_official_feed",
            "status": "met" if equities else "closed",
            "detail": "Alpaca paper keys are set, so IEX equities can be an official feed." if equities
            else "US stocks and ETFs need ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in .env. CME futures have no free official feed.",
        },
    ]
