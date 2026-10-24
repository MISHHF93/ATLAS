"""Governed re-entry: limits on how often the same level / family / instrument may produce an actionable candidate.

Rules (all deterministic, per instrument): at most ``per_level`` candidates per level id per trading day,
at most ``per_day`` candidates per family per trading day, and at least ``cooldown_s`` seconds between two candidates
of the same family. A refused candidate becomes NO_TRADE(REENTRY_LIMIT); nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReentryConfig:
    per_level: int = 1
    per_day: int = 3
    cooldown_s: int = 3600


class ReentryGovernor:
    def __init__(self, cfg: ReentryConfig | None = None):
        self.cfg = cfg or ReentryConfig()
        self._lvl: dict[tuple[str, str, str], int] = {}
        self._day: dict[tuple[str, str], int] = {}
        self._last: dict[str, int] = {}

    def allow(self, family: str, level_id: str, day: str, ts: int) -> tuple[bool, str]:
        if self._lvl.get((family, level_id, day), 0) >= self.cfg.per_level:
            return False, "per-level limit"
        if self._day.get((family, day), 0) >= self.cfg.per_day:
            return False, "per-day limit"
        if family in self._last and ts - self._last[family] < self.cfg.cooldown_s:
            return False, "cooldown"
        return True, ""

    def record(self, family: str, level_id: str, day: str, ts: int) -> None:
        self._lvl[(level_id, day)] = self._lvl.get((family, level_id, day), 0) + 1
        self._day[(family, day)] = self._day.get((family, day), 0) + 1
        self._last[family] = ts
