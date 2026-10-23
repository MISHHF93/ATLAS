"""Native chart and model snapshots from the same real provider data.

Trade streams retain their one-second resolution. Listings without that
transport use available minute API candles, never interpolated second bars.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import math
import threading
import time
from weakref import WeakValueDictionary
from typing import Any

from atlas.marketdata import public_quotes
from atlas.marketdata.live_artifacts import artifact_store
from atlas.marketdata.second_tape import snapshot
from atlas.models.live_observer import observe_public_bars

REFRESH_SECONDS = 10
_CACHE: OrderedDict[str, tuple[float, dict[str, Any] | None, bool]] = OrderedDict()
_FETCH_LOCK = threading.Lock()
_SYMBOL_FETCH_LOCKS: WeakValueDictionary[str, Any] = WeakValueDictionary()
INTEREST_TTL_SECONDS = 300
INTEREST_CAPACITY = 12
_INTEREST_LOCK = threading.Lock()
_INTERESTS: OrderedDict[str, float] = OrderedDict()
_INTEREST_EXPIRED = 0
_INTEREST_EVICTED = 0


def _expire_interests(moment: float) -> None:
    global _INTEREST_EXPIRED
    expired = [symbol for symbol, seen in _INTERESTS.items() if moment - seen >= INTEREST_TTL_SECONDS]
    for symbol in expired:
        del _INTERESTS[symbol]
    _INTEREST_EXPIRED += len(expired)


def note_live_interest(symbol: str) -> None:
    """Keep recently viewed listings under autonomous observation for five minutes."""
    global _INTEREST_EVICTED
    sym = symbol.strip().upper()
    if not sym or len(sym) > 64:
        return
    moment = time.monotonic()
    with _INTEREST_LOCK:
        _expire_interests(moment)
        _INTERESTS[sym] = moment
        _INTERESTS.move_to_end(sym)
        while len(_INTERESTS) > INTEREST_CAPACITY:
            _INTERESTS.popitem(last=False)
            _INTEREST_EVICTED += 1


def viewer_interest_status() -> dict[str, Any]:
    moment = time.monotonic()
    now = datetime.now(timezone.utc)
    with _INTEREST_LOCK:
        _expire_interests(moment)
        return {"ttl_seconds": INTEREST_TTL_SECONDS, "capacity": INTEREST_CAPACITY,
                "expired_total": _INTEREST_EXPIRED, "evicted_total": _INTEREST_EVICTED,
                "active": [{"symbol": symbol,
                            "expires_in_seconds": round(INTEREST_TTL_SECONDS - (moment - seen), 3),
                            "expires_at": (now + timedelta(seconds=INTEREST_TTL_SECONDS - (moment - seen))).isoformat()}
                           for symbol, seen in reversed(_INTERESTS.items())]}


def _minute_payload(symbol: str) -> tuple[dict[str, Any] | None, bool]:
    # Single flight and negative caching keep multiple browser tabs from
    # hammering a public endpoint when a symbol is missing or rate limited.
    # Slow requests for one listing must not hold the cache lock for all names.
    with _FETCH_LOCK:
        symbol_lock = _SYMBOL_FETCH_LOCKS.get(symbol)
        if symbol_lock is None:
            symbol_lock = threading.Lock()
            _SYMBOL_FETCH_LOCKS[symbol] = symbol_lock
    with symbol_lock:
        with _FETCH_LOCK:
            cached = _CACHE.get(symbol)
            if cached and time.monotonic() - cached[0] < REFRESH_SECONDS:
                _CACHE.move_to_end(symbol)
                return cached[1], cached[2]
        fetched = public_quotes.fetch_public_candles(symbol, 60, limit=180)
        payload = fetched or (cached[1] if cached else None)
        failed = fetched is None
        with _FETCH_LOCK:
            _CACHE[symbol] = (time.monotonic(), payload, failed)
            _CACHE.move_to_end(symbol)
            while len(_CACHE) > 128:
                _CACHE.popitem(last=False)
        if fetched:
            store = artifact_store()
            from atlas.marketdata.data_rights import check_data_use
            rights = check_data_use(str(fetched.get("feed_source") or "unknown"), symbol, 60, "retention")
            if store and rights["allowed"]:
                stamp = str(fetched["as_of"])
                store.record([("candle_snapshot", symbol, stamp, fetched)])
        return payload, failed


def _valid_candles(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    valid: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            volume = float(row.get("volume") or 0)
            if stamp.tzinfo is None or stamp > now or not all(math.isfinite(value) and value > 0 for value in values.values()):
                continue
            if not math.isfinite(volume) or volume < 0 or values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]):
                continue
            key = stamp.astimezone(timezone.utc).isoformat()
            valid[key] = {**row, **values, "timestamp": key, "volume": volume}
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return [valid[key] for key in sorted(valid)][-180:]


def live_view_snapshot(symbol: str, *, sampling: bool, now: datetime | None = None,
                       register_interest: bool = True) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    sym = symbol.strip().upper()
    if sampling and register_interest:
        note_live_interest(sym)
    tape = snapshot(sym, sampling=sampling) if register_interest else snapshot(sym, sampling=sampling, register_interest=False)
    bucket = 1
    refresh = .4
    if not sampling:
        tape = {**tape, "candles": [], "notice": "Public market feeds are disabled in this process.",
                "feed_health": {"connection": "disabled"}}
        if not sym.endswith("-USD"):
            bucket, refresh = 60, REFRESH_SECONDS
    if sampling and not sym.endswith("-USD"):
        bucket, refresh = 60, REFRESH_SECONDS
        payload, failed = _minute_payload(sym)
        rows = _valid_candles(list((payload or {}).get("candles") or []), moment)
        received = (payload or {}).get("as_of")
        receive_age = None
        if received:
            receive_age = max(0, (moment - datetime.fromisoformat(str(received).replace("Z", "+00:00"))).total_seconds())
        age = max(0, (moment - datetime.fromisoformat(rows[-1]["timestamp"])).total_seconds()) if rows else None
        metadata = (payload or {}).get("provider_metadata") or {}
        delay = metadata.get("exchangeDataDelayedBy")
        delay = delay if isinstance(delay, (int, float)) and math.isfinite(delay) and delay >= 0 else None
        notice = (
            "Native API chart: one-minute candles, refreshed every 10 seconds. "
            "This is not a one-second trade feed. Provider delay is unknown unless reported. "
            "The observer uses completed candles from this same response."
        )
        if not rows:
            notice = "No API candles returned for this listing. The provider may not cover it or may be unavailable. No prices are generated."
        elif failed:
            notice += " Latest refresh failed; retained candles keep their original timestamps."
        if age is not None and age > 180:
            notice += " The latest candle is old; the market may be closed or the feed delayed. Learning is paused."
        tape = {"candles": rows, "chart_source": "public_market_candles" if rows else "withheld",
                "feed_origin": (payload or {}).get("feed_source", "none"), "notice": notice,
                "feed_health": {"connection": "unavailable" if not rows else "stale" if failed or (age is not None and age > 180) else "connected",
                                "transport": "https_poll", "receive_age_seconds": receive_age,
                                "trade_age_seconds": age, "last_received_at": received,
                                "delay_status": "provider_reported_delay" if delay else "unknown",
                                # Preserve the provider field without guessing its units.
                                "delay_reported": delay, "delay_seconds": None, "candle_resolution_seconds": bucket,
                                "coverage": "provider_minute_candles", "provider_metadata": metadata}}
    rows = _valid_candles(list(tape.get("candles") or []), moment)
    origin = str(tape.get("feed_origin") or "none")
    model_origin = origin if origin != "none" else ("coinbase_exchange_public" if sym.endswith("-USD") else "yahoo_chart_public")
    health = tape.get("feed_health") or {}
    healthy = health.get("connection") == "connected"
    from atlas.marketdata.data_rights import check_data_use
    training_rights = check_data_use(model_origin, sym, bucket, "training")
    retention_rights = check_data_use(model_origin, sym, bucket, "retention")
    admitted = training_rights["allowed"] and retention_rights["allowed"]
    admission_reason = next((item["reason"] for item in (training_rights, retention_rights) if not item["allowed"]), None)
    # A cached forming candle must not become a target merely as wall time
    # passes its close. Require a successful source observation after close.
    watermark_text = health.get("last_received_at") if bucket >= 60 else health.get("last_exchange_at")
    watermark = datetime.fromisoformat(str(watermark_text).replace("Z", "+00:00")) if watermark_text else moment
    observation = observe_public_bars(
        sym, rows, now=moment, bucket_seconds=bucket, feed_origin=model_origin,
        learning_allowed=healthy and admitted,
        pause_reason=admission_reason or f"Feed is {health.get('connection', 'unavailable')}. Saved learning is retained; new updates are paused.",
        completed_through=watermark,
        state_scope=training_rights.get("policy_sha256") if admitted else None,
    )
    completed = observation.pop("candles")
    model_notice = observation.get("notice", "")
    if tape.get("chart_source") == "withheld":
        observation["notice"] = tape.get("notice", model_notice)
    data_mode = "observed" if completed and tape["chart_source"] in {"public_last_trade", "public_market_candles"} else "withheld"
    active = {"symbol": sym, "bucket_seconds": bucket, "chart_source": tape["chart_source"],
              "data_mode": data_mode,
              "feed_origin": origin, "bars_read": len(completed), "candles": completed,
              "last_close": completed[-1]["close"] if completed else None,
              "last_bar_close": (datetime.fromisoformat(completed[-1]["timestamp"]) + timedelta(seconds=bucket)).isoformat() if completed else None,
              "model_id": "online_logistic_observer:experimental", "online_observer": observation,
              "direction": observation["direction"], "feed_health": tape.get("feed_health", {}),
              "notice": observation.get("notice"), "execution_permission": "none"}
    return {"status": "ok", "as_of": moment.isoformat(), "symbol": sym,
            "bucket_seconds": bucket, "refresh_seconds": refresh, "candles": rows,
            "data_mode": data_mode, "chart_source": tape["chart_source"], "feed_origin": origin,
            "notice": tape.get("notice"), "feed_health": tape.get("feed_health", {}),
            "active": active, "data_use": {"training": training_rights, "retention": retention_rights},
            "orders_submitted": 0, "execution_permission": "none"}
