"""Autonomous, bounded observation of the same provider data shown in the UI.

The fast trade path and slower HTTP candle path have independent workers. This
service never uses the gateway's projected/fixture quotes or submits an order.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from datetime import datetime, timezone
import os
import threading
from typing import Any

from atlas.marketdata.live_stream import LiveMarketDataGateway
from atlas.marketdata.live_view import INTEREST_CAPACITY, REFRESH_SECONDS, live_view_snapshot, viewer_interest_status
from atlas.marketdata.public_stream import CORE_SYMBOLS
from atlas.marketdata.second_tape import note_interest

CRYPTO_INTERVAL_SECONDS = .25
MINUTE_INTERVAL_SECONDS = float(REFRESH_SECONDS)
# Match second_tape.watched_symbols/public_stream's actual subscription budget.
EXTRA_CRYPTO_CAPACITY = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObserverService:
    """Continue fitting real completed candles while no browser is polling."""

    def __init__(self, *, sampling: bool):
        self.sampling = bool(sampling)
        self.defaults = tuple(dict.fromkeys((*CORE_SYMBOLS, *LiveMarketDataGateway.EQUITIES_SYMBOLS)))
        # Configuration extends the core scope; admission limits remain visible.
        raw = os.getenv("ATLAS_OBSERVER_SYMBOLS", "")
        self.configured = tuple(dict.fromkeys(
            name.strip().upper() for name in raw.split(",")[:128]
            if name.strip() and len(name.strip()) <= 64
        ))
        self._lock = threading.Lock()
        self._state = "stopped" if sampling else "disabled"
        self._started_at: str | None = None
        self._last_cycle_at: str | None = None
        self._last_error: str | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self._targets: dict[str, tuple[str, ...]] = {"crypto": (), "minute": ()}
        self._omitted: tuple[str, ...] = ()
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._refresh_targets()

    @staticmethod
    def _initial(symbol: str) -> dict[str, Any]:
        path = "crypto" if symbol.endswith("-USD") else "minute"
        return {"symbol": symbol, "path": path, "status": "not_checked", "model_status": "not_checked",
                "feed_status": "not_checked", "feed_origin": "none", "chart_source": "withheld",
                "bucket_seconds": 1 if path == "crypto" else 60, "bars_read": 0,
                "samples_learned": 0, "skipped_outcomes": 0, "last_checked_at": None,
                "last_success_at": None, "last_bar_close": None, "feed_age_seconds": None,
                "direction": "WITHHELD", "probability_up": None, "prediction_at": None,
                "warmup_remaining": None, "failures": 0, "error": None}

    def _refresh_targets(self) -> dict[str, tuple[str, ...]]:
        interests = viewer_interest_status()
        recent = [entry["symbol"] for entry in interests["active"]]
        extras = list(dict.fromkeys(name for name in (*recent, *self.configured) if name not in self.defaults))
        admitted = extras[:INTEREST_CAPACITY]
        names = [*self.defaults, *admitted]
        crypto = [name for name in names if name.endswith("-USD")]
        extra_crypto = [name for name in crypto if name not in CORE_SYMBOLS]
        limited = set(extra_crypto[EXTRA_CRYPTO_CAPACITY:])
        targets = {"crypto": tuple(name for name in crypto if name not in limited),
                   "minute": tuple(name for name in names if not name.endswith("-USD"))}
        with self._lock:
            self._omitted = tuple(extras[INTEREST_CAPACITY:])
            self._targets = targets
            self._entries = {name: self._entries.get(name, self._initial(name)) for name in names}
            for name, entry in self._entries.items():
                if not self.sampling:
                    entry.update(status="disabled", model_status="disabled", feed_status="disabled")
                elif name in limited:
                    entry.update(status="capacity_limited", model_status="paused", feed_status="not_subscribed",
                                 error=f"The connected trade stream supports {EXTRA_CRYPTO_CAPACITY} additional crypto listings; this listing is outside that scope.")
                elif entry["status"] == "capacity_limited":
                    entry.update(status="not_checked", model_status="not_checked", feed_status="not_checked", error=None)
        return targets

    def status(self) -> dict[str, Any]:
        # Expire temporary scope even when status is read after service shutdown.
        self._refresh_targets()
        with self._lock:
            entries = deepcopy(list(self._entries.values()))
            state = self._state
            observing = sum(entry["status"] == "observing" for entry in entries)
            unavailable = sum(entry["status"] in {"unavailable", "error", "stale", "paused", "capacity_limited"} for entry in entries)
            coverage = (state if state in {"disabled", "stopped"} else
                        "observing" if observing == len(entries) and entries else
                        "partially_available" if observing else "waiting")
            result = {"state": state, "coverage_status": coverage, "sampling_enabled": self.sampling,
                      "autonomous": True, "started_at": self._started_at, "last_cycle_at": self._last_cycle_at,
                      "last_error": self._last_error, "intervals_seconds": {"crypto": CRYPTO_INTERVAL_SECONDS, "minute": MINUTE_INTERVAL_SECONDS},
                      "symbols": entries, "default_symbols": list(self.defaults), "configured_symbols": list(self.configured),
                      "omitted_symbols": list(self._omitted), "additional_symbol_capacity": INTEREST_CAPACITY,
                      "transport_extra_crypto_capacity": EXTRA_CRYPTO_CAPACITY,
                      "summary": {"watched": len(entries), "observing": observing, "unavailable": unavailable},
                      "execution_permission": "none", "orders_submitted": 0}
        result["viewer_interests"] = viewer_interest_status()
        return result

    async def _observe(self, symbol: str) -> None:
        try:
            executor = self._executors.get("crypto" if symbol.endswith("-USD") else "minute")
            if executor is None:
                result = await asyncio.to_thread(live_view_snapshot, symbol, sampling=self.sampling, register_interest=False)
            else:
                context = copy_context()
                result = await asyncio.get_running_loop().run_in_executor(
                    executor, lambda: context.run(live_view_snapshot, symbol, sampling=self.sampling, register_interest=False))
            active = result.get("active") or {}
            model = active.get("online_observer") or {}
            health = result.get("feed_health") or {}
            feed_state = str(health.get("connection") or "unavailable")
            model_state = str(model.get("status") or "waiting")
            status = ("unavailable" if result.get("chart_source") == "withheld" or feed_state in {"unavailable", "disabled"} else
                      "stale" if feed_state == "stale" or model_state == "stale" else
                      "paused" if model_state == "paused" or feed_state != "connected" else
                      "observing" if model_state in {"warming_up", "learning"} else "waiting")
            checked = _now()
            with self._lock:
                if symbol not in self._entries or symbol not in self._targets[self._entries[symbol]["path"]]:
                    return
                entry = self._entries[symbol]
                entry.update(status=status, model_status=model_state, feed_status=feed_state,
                             feed_origin=result.get("feed_origin", "none"), chart_source=result.get("chart_source", "withheld"),
                             bucket_seconds=result.get("bucket_seconds", entry["bucket_seconds"]), bars_read=active.get("bars_read", 0),
                             samples_learned=model.get("samples_learned", entry["samples_learned"]),
                             skipped_outcomes=model.get("skipped_outcomes", entry["skipped_outcomes"]),
                             last_checked_at=checked, last_bar_close=active.get("last_bar_close"),
                             feed_age_seconds=model.get("feed_age_seconds", health.get("trade_age_seconds")),
                             direction=active.get("direction", "WITHHELD"),
                             probability_up=model.get("probability_up", entry.get("probability_up")),
                             prediction_at=model.get("prediction_at", entry.get("prediction_at")),
                             warmup_remaining=model.get("warmup_remaining", entry.get("warmup_remaining")), error=None,
                             notice=model.get("notice") or result.get("notice"))
                if status == "observing":
                    entry["last_success_at"] = checked
                self._last_cycle_at = checked
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:240]
            checked = _now()
            with self._lock:
                if symbol in self._entries:
                    entry = self._entries[symbol]
                    entry.update(status="error", model_status="paused", feed_status="error", last_checked_at=checked,
                                 direction="WITHHELD", failures=entry["failures"] + 1, error=error)
                self._last_error = f"{symbol}: {error}"
                self._last_cycle_at = checked

    async def _loop(self, path: str, stop: asyncio.Event) -> None:
        interval = CRYPTO_INTERVAL_SECONDS if path == "crypto" else MINUTE_INTERVAL_SECONDS
        while not stop.is_set():
            began = asyncio.get_running_loop().time()
            names = self._refresh_targets()[path]
            if path == "crypto":
                # The transport expires interest after 20s; retain the admitted
                # five-minute viewer scope without opening duplicate sockets.
                for symbol in names:
                    if symbol not in CORE_SYMBOLS:
                        note_interest(symbol)
            await asyncio.gather(*(self._observe(symbol) for symbol in names))
            try:
                elapsed = asyncio.get_running_loop().time() - began
                await asyncio.wait_for(stop.wait(), timeout=max(.01, interval - elapsed))
            except asyncio.TimeoutError:
                pass

    async def run(self, stop: asyncio.Event) -> None:
        if not self.sampling:
            with self._lock:
                self._state = "disabled"
            await stop.wait()
            return
        with self._lock:
            if self._state == "running":
                raise RuntimeError("ObserverService is already running")
            self._state = "running"
            self._started_at = _now()
        # Slow HTTP work cannot occupy the fast path's thread budget, even on
        # machines whose default asyncio executor has only a few workers.
        self._executors = {"crypto": ThreadPoolExecutor(max_workers=4, thread_name_prefix="observe-trades"),
                           "minute": ThreadPoolExecutor(max_workers=6, thread_name_prefix="observe-candles")}
        workers = [asyncio.create_task(self._loop(path, stop), name=f"observer-{path}") for path in ("crypto", "minute")]
        try:
            await stop.wait()
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            for executor in self._executors.values():
                executor.shutdown(wait=False, cancel_futures=True)
            self._executors = {}
            with self._lock:
                self._state = "stopped"
