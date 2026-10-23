from __future__ import annotations

from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_s: float = 60.0):
        self.max_events = max_events
        self.window_s = window_s
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_s:
            self._events.popleft()

    def would_allow(self, now: float) -> bool:
        self._prune(now)
        return len(self._events) < self.max_events

    def record(self, now: float) -> None:
        self._prune(now)
        self._events.append(now)


class SharedWindowLimiter:
    """Order-rate budget shared by every process using the same StateStore (core loop, owner CLI,
    dashboard heartbeat). Uses wall-clock time (monotonic clocks differ per process). `record` is an
    atomic read-modify-write; `would_allow` is a read (the risk gate re-checks on every intent)."""

    def __init__(self, store, max_events: int, window_s: float = 60.0, key: str = "rate:orders", clock=None):
        import time
        self.store, self.max_events, self.window_s, self.key = store, max_events, window_s, key
        self.clock = clock or time.time

    def _live(self, evs, now: float) -> list[float]:
        return [t for t in (evs or []) if now - t < self.window_s]

    def would_allow(self, now: float | None = None) -> bool:
        return len(self._live(self.store.get(self.key, []), self.clock())) < self.max_events

    def record(self, now: float | None = None) -> None:
        t = self.clock()
        self.store.update(self.key, lambda evs: self._live(evs, t) + [t], [])
