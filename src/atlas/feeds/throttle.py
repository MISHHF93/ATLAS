"""Cross-process request throttle (sliding window), so the server and a backfill script share ONE vendor quota.

Massive Stocks Basic allows 5 calls per minute for the whole account. Two processes each holding their own in-memory
bucket would together break it, so the call times live in a small JSON file guarded by an exclusive lock file.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable


class SharedWindowLimiter:
    """At most ``max_calls`` per ``window`` seconds across every process that uses the same ``path``."""

    def __init__(self, path: str | os.PathLike, max_calls: int = 4, window: float = 60.0,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.path, self.max_calls, self.window, self.clock, self.sleep = Path(path), max_calls, window, clock, sleep
        self.lock = self.path.with_suffix(self.path.suffix + ".lock")

    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(400):
            try:
                return os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > 10:    # a crashed holder never blocks the quota forever
                        self.lock.unlink()
                        continue
                except OSError:
                    pass
                self.sleep(0.05)
        raise TimeoutError("throttle lock busy")

    def _release(self, fd) -> None:
        os.close(fd)
        try:
            self.lock.unlink()
        except OSError:
            pass

    def _read(self) -> list[float]:
        try:
            return [float(x) for x in json.loads(self.path.read_text())]
        except Exception:  # noqa: BLE001 - a missing or corrupt file means no history
            return []

    def acquire(self) -> None:
        while True:
            fd = self._locked()
            try:
                now = self.clock()
                calls = [t for t in self._read() if now - t < self.window]
                if len(calls) < self.max_calls:
                    calls.append(now)
                    self.path.write_text(json.dumps(calls))
                    return
                wait = self.window - (now - min(calls)) + 0.05
            finally:
                self._release(fd)
            self.sleep(max(wait, 0.05))
