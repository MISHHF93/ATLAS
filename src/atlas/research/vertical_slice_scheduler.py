"""Background scheduler and singleton accessors for the research vertical slice."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from atlas.marketdata.data_rights import DataUseDenied
from atlas.research.vertical_slice_features import (
    SCHEDULER_STATE_KEY,
    _admit_rows,
    _blocked_data_use,
    _public_rows,
    _utc,
    normalize_candles,
)

if TYPE_CHECKING:
    from atlas.research.vertical_slice import VerticalSliceService

def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _scheduler_horizons() -> tuple[int, ...]:
    raw = os.environ.get("ATLAS_VERTICAL_SLICE_HORIZONS", "1")
    horizons: set[int] = set()
    for item in raw.split(","):
        try:
            horizon = int(item.strip())
        except (TypeError, ValueError):
            continue
        if 1 <= horizon <= 24:
            horizons.add(horizon)
    return tuple(sorted(horizons)) or (1,)


def _scheduler_settings() -> tuple[tuple[str, ...], int, int, int]:
    raw = os.environ.get(
        "ATLAS_VERTICAL_SLICE_SYMBOLS",
        "BTC-USD,ETH-USD,SOL-USD,SPY,QQQ,NVDA,AAPL,MSFT,TSLA",
    )
    symbols = tuple(
        symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()
    ) or ("BTC-USD",)
    return (
        symbols,
        _env_int("ATLAS_VERTICAL_SLICE_BUCKET_SECONDS", 86_400),
        _env_int("ATLAS_VERTICAL_SLICE_POLL_SECONDS", 300),
        _env_int("ATLAS_VERTICAL_SLICE_INITIAL_DELAY_SECONDS", 60),
    )


class VerticalSliceScheduler:
    """Check completed public bars and run/resolve the slice at most once per bar."""

    def __init__(
        self,
        service: VerticalSliceService | None = None,
        *,
        symbols: Sequence[str] | None = None,
        bucket_seconds: int | None = None,
        horizons: Sequence[int] | None = None,
        poll_seconds: int | None = None,
        initial_delay_seconds: int | None = None,
    ) -> None:
        defaults = _scheduler_settings()
        self.service = service or get_vertical_slice_service()
        self.symbols = tuple(symbols or defaults[0])
        self.horizons = tuple(
            sorted({max(1, min(int(step), 24)) for step in (horizons or _scheduler_horizons())})
        ) or (1,)
        self.bucket_seconds = int(bucket_seconds or defaults[1])
        self.poll_seconds = int(poll_seconds or defaults[2])
        self.initial_delay_seconds = int(initial_delay_seconds if initial_delay_seconds is not None else defaults[3])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._process_lock_handle: Any | None = None
        saved = self.service.ledger.load_state(SCHEDULER_STATE_KEY) or {}
        self._state: dict[str, Any] = {
            "symbols": list(self.symbols),
            "bucket_seconds": self.bucket_seconds,
            "horizons": list(self.horizons),
            "poll_seconds": self.poll_seconds,
            "last_check_at": saved.get("last_check_at"),
            "last_bar_at": saved.get("last_bar_at"),
            "last_run_at": saved.get("last_run_at"),
            "runs": int(saved.get("runs") or 0),
            "resolutions": int(saved.get("resolutions") or 0),
            "skips": int(saved.get("skips") or 0),
            "errors": int(saved.get("errors") or 0),
            "last_error": saved.get("last_error"),
            "execution_permission": "none",
        }

    def _scheduler_lock_path(self) -> Path | None:
        path = self.service.ledger.path
        if str(path) == ":memory:":
            return None
        return path.with_name(f"{path.name}.scheduler.lock")

    def _acquire_process_lock(self) -> bool:
        if self._process_lock_handle is not None:
            return True
        lock_path = self._scheduler_lock_path()
        if lock_path is None:
            return True
        handle = None
        try:
            handle = open(lock_path, "a+b")
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if handle is not None:
                handle.close()
            return False
        self._process_lock_handle = handle
        return True

    def _release_process_lock(self) -> None:
        handle = self._process_lock_handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
            self._process_lock_handle = None

    def tick(
        self,
        *,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
    ) -> dict[str, Any]:
        leased = self._process_lock_handle is None
        if not self._acquire_process_lock():
            return {
                **self.status(),
                "status": "skipped",
                "reason": "scheduler_lock_held_elsewhere",
                "details": [],
            }
        try:
            return self._tick_unlocked(
                candles_by_symbol=candles_by_symbol,
                now=now,
                fetch=fetch,
            )
        finally:
            if leased and not self.is_running():
                self._release_process_lock()

    def _tick_unlocked(
        self,
        *,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            moment = now or datetime.now(timezone.utc)
            self.service.configure(bucket_seconds=self.bucket_seconds)
            runs = resolutions = skips = errors = 0
            last_bar: datetime | None = None
            last_error: str | None = None
            details: list[dict[str, Any]] = []
            for symbol in self.symbols:
                symbol = symbol.upper()
                rows = (candles_by_symbol or {}).get(symbol)
                if rows is None and fetch:
                    try:
                        from atlas.marketdata.public_quotes import fetch_public_candles

                        payload = fetch_public_candles(symbol, self.bucket_seconds, limit=400, intended_use="training")
                        rows = _public_rows(payload)
                    except DataUseDenied as exc:
                        skips += 1
                        details.append(_blocked_data_use(symbol, exc))
                        continue
                    except Exception as exc:  # noqa: BLE001 - one symbol must not stop the loop
                        errors += 1
                        last_error = f"{symbol}:{type(exc).__name__}"
                        details.append({"symbol": symbol, "status": "fetch_error", "error": type(exc).__name__})
                        continue
                if not rows:
                    skips += 1
                    details.append({"symbol": symbol, "status": "no_candles"})
                    continue
                try:
                    normalized, quality = _admit_rows(rows, symbol=symbol, bucket_seconds=self.bucket_seconds, as_of=moment)
                except DataUseDenied as exc:
                    skips += 1
                    details.append(_blocked_data_use(symbol, exc))
                    continue
                if not normalized:
                    skips += 1
                    details.append({"symbol": symbol, "status": "no_usable_candles", "quality": quality})
                    continue
                available_at = normalized[-1].available_at
                if last_bar is None or available_at > last_bar:
                    last_bar = available_at
                for horizon in self.horizons:
                    latest = self.service.ledger.latest_forecast_decision(symbol, horizon)
                    already_done = latest is not None and _utc(latest) >= available_at
                    if not already_done:
                        try:
                            report = self.service.run(
                                symbols=[symbol],
                                bucket_seconds=self.bucket_seconds,
                                horizon_steps=horizon,
                                candles_by_symbol={symbol: rows},
                                fetch=False,
                                now=moment,
                            )
                            runs += 1
                            symbol_report = (report.get("symbols") or [{}])[0]
                            details.append(
                                {
                                    "symbol": symbol,
                                    "horizon": horizon,
                                    "status": "ran",
                                    "result": symbol_report.get("status"),
                                    "bar_at": available_at.isoformat(),
                                }
                            )
                        except Exception as exc:  # noqa: BLE001
                            errors += 1
                            last_error = f"{symbol}:h{horizon}:{type(exc).__name__}"
                            details.append(
                                {
                                    "symbol": symbol,
                                    "horizon": horizon,
                                    "status": "run_error",
                                    "error": type(exc).__name__,
                                }
                            )
                    else:
                        skips += 1
                        details.append(
                            {
                                "symbol": symbol,
                                "horizon": horizon,
                                "status": "already_processed",
                                "bar_at": available_at.isoformat(),
                            }
                        )
                try:
                    resolution = self.service.resolve(
                        symbols=[symbol],
                        candles_by_symbol={symbol: rows},
                        fetch=False,
                        as_of=moment,
                    )
                    resolutions += int(resolution.get("count") or 0)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    last_error = f"{symbol}:{type(exc).__name__}"
                    details.append({"symbol": symbol, "status": "resolve_error", "error": type(exc).__name__})
            self._state.update(
                {
                    "symbols": list(self.symbols),
                    "bucket_seconds": self.bucket_seconds,
                    "horizons": list(self.horizons),
                    "poll_seconds": self.poll_seconds,
                    "last_check_at": moment.isoformat(),
                    "last_bar_at": last_bar.isoformat() if last_bar else self._state.get("last_bar_at"),
                    "last_run_at": moment.isoformat() if runs else self._state.get("last_run_at"),
                    "runs": int(self._state.get("runs") or 0) + runs,
                    "resolutions": int(self._state.get("resolutions") or 0) + resolutions,
                    "skips": int(self._state.get("skips") or 0) + skips,
                    "errors": int(self._state.get("errors") or 0) + errors,
                    "last_error": last_error or self._state.get("last_error"),
                    "execution_permission": "none",
                }
            )
            self.service.ledger.save_state(SCHEDULER_STATE_KEY, self._state, moment)
            return {**self._state, "details": details, "running": self.is_running()}

    def __tick_safely(self) -> None:
        try:
            self.tick()
        except Exception as exc:  # noqa: BLE001 - the background loop must survive
            with self._lock:
                self._state["errors"] = int(self._state.get("errors") or 0) + 1
                self._state["last_error"] = type(exc).__name__
                self._state["last_check_at"] = datetime.now(timezone.utc).isoformat()
                self.service.ledger.save_state(
                    SCHEDULER_STATE_KEY, self._state, datetime.now(timezone.utc)
                )

    def _loop(self) -> None:
        if self.initial_delay_seconds and self._stop.wait(self.initial_delay_seconds):
            return
        while not self._stop.is_set():
            self.__tick_safely()
            if self._stop.wait(self.poll_seconds):
                break

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                if not self._acquire_process_lock():
                    self._state["errors"] = int(self._state.get("errors") or 0) + 1
                    self._state["last_error"] = "scheduler_lock_held_elsewhere"
                    return self.status()
                if self._state.get("last_error") == "scheduler_lock_held_elsewhere":
                    self._state["last_error"] = None
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._loop,
                    name="vertical-slice-scheduler",
                    daemon=True,
                )
                try:
                    self._thread.start()
                except Exception:
                    self._thread = None
                    self._release_process_lock()
                    raise
        return self.status()

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._release_process_lock()
        return self.status()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            **self._state,
            "running": self.is_running(),
            "initial_delay_seconds": self.initial_delay_seconds,
            "execution_permission": "none",
        }


_SERVICE: VerticalSliceService | None = None
_SERVICE_LOCK = threading.Lock()
_SCHEDULER: VerticalSliceScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def get_vertical_slice_service() -> VerticalSliceService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            from atlas.research.vertical_slice import VerticalSliceService
            _SERVICE = VerticalSliceService()
        return _SERVICE


def get_vertical_slice_scheduler() -> VerticalSliceScheduler:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = VerticalSliceScheduler(get_vertical_slice_service())
        return _SCHEDULER
