"""Follow-the-sun session model from schedule.yaml.

Open/closed comes from the exchange calendars (holidays, half days); unknown venue or any
error is CLOSED (fail closed). Phase names and size multipliers come from schedule.yaml in each
venue's local time zone. Weekend mode (fx close Fri 17:00 ET to fx open Sun 17:00 ET): only the
venues in weekend_mode.active_venues accept NEW orders."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from atlas.marketdata.pit.calendars import fx_open, is_open

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
from atlas.ops.timez import TORONTO as TOR  # noqa: E402


def _hm(s: str) -> time:
    return time(23, 59, 59) if s == "24:00" else time.fromisoformat(s)


class SessionModel:
    def __init__(self, schedule: dict):
        self.s = schedule
        self.venues = {k: v for k, v in schedule["venues"].items() if v.get("enabled", True)}

    def weekend_mode(self, now: datetime) -> bool:
        return not fx_open(now)

    def _phase(self, name: str, v: dict, now: datetime) -> tuple[str, float]:
        local = now.astimezone(ZoneInfo(v.get("tz", "UTC")))
        t, day = local.time(), DAYS[local.weekday()]
        mult = 1.0
        phase = "open"
        for ph in v.get("sessions", []):
            if ph.get("days") and day not in ph["days"]:
                continue
            if _hm(ph["start"]) <= t < _hm(ph["end"]) or (ph["end"] == "24:00" and t >= _hm(ph["start"])):
                phase, mult = ph["phase"], float(ph.get("size_mult", 1.0))
                break
        for ll in v.get("low_liquidity", []):
            if "days" in ll and day in ll["days"] and "start" not in ll:
                mult = min(mult, float(ll["mult"]))
            elif "start" in ll and "around" not in ll and (not ll.get("days") or day in ll["days"]) and (not ll.get("day") or ll["day"] == day):
                a, b = _hm(ll["start"]), _hm(ll["end"])
                if (a <= t < b) if a <= b else (t >= a or t < b):
                    mult = min(mult, float(ll["mult"]))
        if phase == "lunch_break":
            mult = 0.0
        return phase, mult

    def status(self, name: str, now: datetime) -> dict:
        v = self.venues[name]
        op = is_open(name, now)
        phase, mult = self._phase(name, v, now) if op else ("closed", 0.0)
        if phase == "lunch_break":
            op = False
        wk = self.weekend_mode(now)
        new_ok = op and (not wk or name in self.s.get("weekend_mode", {}).get("active_venues", []))
        return {"venue": name, "tz": v.get("tz"), "open": op, "phase": phase, "size_mult": mult,
                "new_orders_allowed": new_ok, "brokers": v.get("brokers", []),
                "local_time": now.astimezone(ZoneInfo(v.get("tz", "UTC"))).strftime("%a %H:%M")}

    def next_change(self, name: str, now: datetime, step_min: int = 15, horizon_h: int = 96) -> str | None:
        cur = is_open(name, now)
        t = now.replace(second=0, microsecond=0)
        t += timedelta(minutes=step_min - t.minute % step_min)
        end = now + timedelta(hours=horizon_h)
        while t <= end:
            if is_open(name, t) != cur:
                return t.astimezone(TOR).isoformat(timespec="minutes")
            t += timedelta(minutes=step_min)
        return None

    def strip(self, now: datetime, with_next: bool = True) -> dict:
        rows = []
        for n in self.venues:
            r = self.status(n, now)
            if with_next:
                r["next_change_et"] = self.next_change(n, now)
            rows.append(r)
        # follow-the-sun ordering: open venues first, then by next opening
        rows.sort(key=lambda r: (not r["open"], r.get("next_change_et") or "~"))
        return {"now_et": now.astimezone(TOR).isoformat(timespec="minutes"), "weekend_mode": self.weekend_mode(now),
                "active": [r["venue"] for r in rows if r["new_orders_allowed"]], "venues": rows}

    def can_trade(self, venue: str, now: datetime) -> tuple[bool, float]:
        if venue not in self.venues:
            return False, 0.0
        s = self.status(venue, now)
        return s["new_orders_allowed"], s["size_mult"]
