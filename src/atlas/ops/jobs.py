"""Job scheduler for schedule.yaml `jobs` (+ weekend learning loop). Times in America/Toronto
unless noted. Each job runs at most once per scheduled slot; last-run is persisted in the
StateStore so restarts don't double-run. Missed slots older than `grace` are skipped."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from atlas.ops.timez import TORONTO as TOR  # noqa: E402
NY = ZoneInfo("America/New_York")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SPEC = re.compile(r"^(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(\d{2}):(\d{2})")


def parse(spec) -> tuple:
    if isinstance(spec, (int, float)):
        return ("interval", float(spec))
    m = SPEC.match(str(spec).strip())
    if not m:
        raise ValueError(f"bad job spec {spec!r}")
    day, h, mi = m.groups()
    return ("weekly" if day else "daily", DAYS.index(day) if day else None, int(h), int(mi))


def last_slot(spec: tuple, now: datetime, tz=TOR) -> datetime:
    loc = now.astimezone(tz)
    if spec[0] == "interval":
        sec = int(loc.timestamp() // spec[1] * spec[1])
        return datetime.fromtimestamp(sec, tz)
    _, wd, h, mi = spec
    cand = loc.replace(hour=h, minute=mi, second=0, microsecond=0)
    if spec[0] == "daily":
        return cand if cand <= loc else cand - timedelta(days=1)
    cand -= timedelta(days=(loc.weekday() - wd) % 7)
    return cand if cand <= loc else cand - timedelta(days=7)


class JobScheduler:
    def __init__(self, store, audit=None, grace: timedelta = timedelta(hours=6)):
        self.store, self.audit, self.grace = store, audit, grace
        self.jobs: dict[str, tuple[tuple, Callable[[datetime], object], object]] = {}

    def add(self, name: str, spec, fn: Callable[[datetime], object], tz=TOR) -> None:
        self.jobs[name] = (parse(spec), fn, tz)

    @classmethod
    def from_schedule(cls, schedule: dict, handlers: dict[str, Callable], store, audit=None) -> "JobScheduler":
        js = cls(store, audit)
        jobs = dict(schedule.get("jobs", {}))
        ll = schedule.get("weekend_mode", {}).get("learning_loop", {})
        if ll.get("run"):
            jobs["learning_loop"] = f"{ll['day']} {ll['time_et']}"
        for name, spec in jobs.items():
            key = name.removesuffix("_interval_s")
            if key in handlers:
                js.add(key, spec, handlers[key], NY if name == "learning_loop" else TOR)
        return js

    def tick(self, now: datetime) -> list[str]:
        ran = []
        for name, (spec, fn, tz) in self.jobs.items():
            slot = last_slot(spec, now, tz)
            last = self.store.get(f"job:{name}")
            if last and datetime.fromisoformat(last) >= slot:
                continue
            if now - slot > self.grace:
                continue
            self.store.set(f"job:{name}", slot.isoformat())  # mark first: never double-run on crash loops
            try:
                fn(now)
                status = "ok"
            except Exception as e:  # noqa: BLE001
                status = f"error: {e}"
            if self.audit:
                self.audit.append("ops.job", {"job": name, "slot": slot.isoformat(), "status": status})
            ran.append(name)
        return ran
