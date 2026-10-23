from __future__ import annotations

import time
from typing import Callable

from atlas.risk.killswitch import KillSwitch


class Watchdog:
    """Fail-closed heartbeat monitor.

    Healthy only if a heartbeat arrived within interval * missed_beats. No
    heartbeat yet => unhealthy. Clock errors => unhealthy. Going unhealthy
    engages the kill switch (latched; recovering heartbeats don't un-halt)."""

    def __init__(self, interval_s: float, missed_beats: int, kill_switch: KillSwitch,
                 clock: Callable[[], float] = time.monotonic):
        self.interval_s = interval_s
        self.missed_beats = missed_beats
        self.ks = kill_switch
        self.clock = clock
        self.last_beat: float | None = None

    @property
    def window_s(self) -> float:
        return self.interval_s * self.missed_beats

    def heartbeat(self) -> None:
        self.last_beat = self.clock()

    def healthy(self) -> bool:
        try:
            now = self.clock()
        except Exception:
            return False
        if self.last_beat is None:
            return False
        age = now - self.last_beat
        return 0 <= age <= self.window_s

    def check(self) -> bool:
        ok = self.healthy()
        if not ok and not self.ks.engaged:
            self.ks.engage(f"watchdog: no heartbeat within {self.window_s}s", channel="watchdog")
        return ok
