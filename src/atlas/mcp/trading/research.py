"""Read-only research tools for the MCP server (BRD US-06; TRD §4 market.get_bars / market.get_quote / indicators.compute).

Offline only: bars come from the local point-in-time bar store (Parquet or SQLite, written by the data layer);
quotes come from the paper book or the last stored bar. No network calls here. Every response is labelled with its
source and the as-of time, and nothing in here can place, approve or change anything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_BARS = 10_000
INDICATORS = ("SMA", "EMA", "RSI", "ATR", "BBANDS")


def _ts(x: datetime | None) -> str | None:
    return x.astimezone(timezone.utc).isoformat() if x else None


def get_bars(store, symbol: str, limit: int = 200, as_of: datetime | None = None) -> dict[str, Any]:
    if store is None:
        return {"symbol": symbol, "bars": [], "source": "none", "note": "no local bar store configured (ATLAS_DATA_DIR)"}
    limit = max(1, min(int(limit), MAX_BARS))
    bars = store.read(symbol, as_of=as_of)[-limit:]                       # point-in-time: never bars not yet available
    return {"symbol": symbol, "source": "local_store", "as_of": _ts(as_of),
            "bars": [{"ts": _ts(b.ts), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume} for b in bars]}


def get_quote(broker, store, symbol: str, as_of: datetime | None = None) -> dict[str, Any]:
    pos = broker.positions.get(symbol) if broker is not None else None
    if pos is not None and pos.last_price:
        return {"symbol": symbol, "last": pos.last_price, "source": "paper_book", "ts": None}
    if store is not None:
        bars = store.read(symbol, as_of=as_of)
        if bars:
            return {"symbol": symbol, "last": bars[-1].close, "source": "last_stored_bar", "ts": _ts(bars[-1].ts)}
    return {"symbol": symbol, "last": None, "source": "none", "note": "no paper position or stored bars for this symbol"}


def _sma(xs: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def _ema(xs: list[float], n: int) -> list[float | None]:
    from atlas.features.price_action.indicators import ema_batch  # canonical implementation
    return ema_batch(xs, n)


def _rsi(xs: list[float], n: int) -> list[float | None]:
    from atlas.features.price_action.indicators import rsi_batch  # canonical; legacy flat value 100
    return rsi_batch(xs, n, flat_value=100.0)


def _atr(bars, n: int) -> list[float | None]:
    from atlas.features.price_action.indicators import atr_batch  # canonical Wilder ATR
    return atr_batch([b.high for b in bars], [b.low for b in bars], [b.close for b in bars], n)


def compute_indicators(store, symbol: str, indicators: list[dict], lookback: int = 200, as_of: datetime | None = None) -> dict[str, Any]:
    if store is None:
        return {"symbol": symbol, "series": {}, "source": "none", "note": "no local bar store configured (ATLAS_DATA_DIR)"}
    bars = store.read(symbol, as_of=as_of)[-max(1, min(int(lookback), MAX_BARS)):]
    closes, ts = [b.close for b in bars], [_ts(b.ts) for b in bars]
    series: dict[str, list[dict]] = {}
    for spec in indicators:
        name = str(spec.get("name", "")).upper()
        n = int((spec.get("params") or {}).get("period", 14 if name in ("RSI", "ATR") else 20))
        if name not in INDICATORS:
            raise ValueError(f"unsupported indicator {name!r}; supported: {', '.join(INDICATORS)}")
        if not 1 <= n <= 1000:
            raise ValueError("period must be 1..1000")
        if name == "SMA":
            vals = {f"SMA_{n}": _sma(closes, n)}
        elif name == "EMA":
            vals = {f"EMA_{n}": _ema(closes, n)}
        elif name == "RSI":
            vals = {f"RSI_{n}": _rsi(closes, n)}
        elif name == "ATR":
            vals = {f"ATR_{n}": _atr(bars, n)}
        else:
            k = float((spec.get("params") or {}).get("k", 2.0))
            mid = _sma(closes, n)
            sd = [None if m is None else (sum((c - m) ** 2 for c in closes[i - n + 1:i + 1]) / n) ** 0.5 for i, m in enumerate(mid)]
            vals = {f"BB_MID_{n}": mid, f"BB_UP_{n}": [None if m is None else m + k * s for m, s in zip(mid, sd)],
                    f"BB_LO_{n}": [None if m is None else m - k * s for m, s in zip(mid, sd)]}
        for key, v in vals.items():
            series[key] = [{"ts": t, "value": x} for t, x in zip(ts, v) if x is not None]
    return {"symbol": symbol, "source": "local_store", "bars_used": len(bars), "series": series}
