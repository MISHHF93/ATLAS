"""Follow-the-sun session model from schedule.yaml.

Open/closed comes from the exchange calendars (holidays, half days); unknown venue or any
error is CLOSED (fail closed). Phase names and size multipliers come from schedule.yaml in each
venue's local time zone. Weekend mode (fx close Fri 17:00 ET to fx open Sun 17:00 ET): only the
venues in weekend_mode.active_venues accept NEW orders."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from atlas.marketdata.pit.calendars import (
    CalendarUnavailable, _utc, calendar_metadata, fx_open, trading_windows,
)

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
        now = _utc(now)
        v = self.venues[name]
        error = None
        try:
            active = next(iter(trading_windows(name, now, now + timedelta(microseconds=1))), None)
        except CalendarUnavailable as exc:
            active, error = None, str(exc)
        op = active is not None
        phase, mult = self._phase(name, v, now) if op else ("closed", 0.0)
        if phase == "lunch_break":
            op = False
        wk = self.weekend_mode(now)
        weekend_ok = not wk or name in self.s.get("weekend_mode", {}).get("active_venues", [])
        buffer_min = max(0, float(self.s.get("defaults", {}).get("no_new_entries_before_close_min", 0)))
        cutoff = active.session_close - timedelta(minutes=buffer_min) if active and name != "crypto" else None
        near_close = cutoff is not None and now >= cutoff
        new_ok = op and weekend_ok and not near_close
        return {"venue": name, "tz": v.get("tz"), "open": op, "phase": phase, "size_mult": mult,
                "new_orders_allowed": new_ok, "brokers": v.get("brokers", []),
                "entry_block_reason": "calendar_unavailable" if error else "calendar_closed" if not op else
                                      "weekend_mode" if not weekend_ok else "close_buffer" if near_close else None,
                "session_close_utc": active.session_close.isoformat() if active else None,
                "entry_cutoff_utc": cutoff.isoformat() if cutoff else None,
                "calendar": calendar_metadata(name), "schedule_error": error,
                "local_time": now.astimezone(ZoneInfo(v.get("tz", "UTC"))).strftime("%a %H:%M")}

    def next_change(self, name: str, now: datetime, step_min: int = 15, horizon_h: int = 96) -> str | None:
        """Exact next scheduled open/break/close; ``step_min`` is retained for compatibility."""
        now = _utc(now)
        if name not in self.venues:
            return None
        try:
            windows = trading_windows(name, now, now + timedelta(hours=horizon_h))
        except CalendarUnavailable:
            return None
        # Crypto's midnight accounting boundary does not close its continuous market.
        if name == "crypto":
            return None
        window = next(iter(windows), None)
        if window is None:
            return None
        change = window.close if window.open <= now < window.close else window.open
        if change > now + timedelta(hours=horizon_h):
            return None
        return change.astimezone(TOR).isoformat(timespec="minutes")

    def plan(self, now: datetime, horizon_h: float = 24) -> dict:
        """Read-only global session plan. An open schedule conveys no order permission."""
        now = _utc(now)
        if not 0 < horizon_h <= 168:
            raise ValueError("horizon_h must be greater than zero and at most 168 hours")
        end = now + timedelta(hours=horizon_h)
        rows, windows, transitions = [], [], []
        for name in self.venues:
            row = self.status(name, now)
            row["next_change_et"] = self.next_change(name, now, horizon_h=horizon_h)
            rows.append(row)
            try:
                upcoming = trading_windows(name, now, end)
            except CalendarUnavailable:
                continue
            for window in upcoming:
                buffer_min = max(0, float(self.s.get("defaults", {}).get("no_new_entries_before_close_min", 0)))
                cutoff = window.session_close - timedelta(minutes=buffer_min) if name != "crypto" else None
                windows.append({"venue": name, "session_date": window.session_date.isoformat(),
                                "open_utc": window.open.isoformat(), "close_utc": window.close.isoformat(),
                                "entry_cutoff_utc": cutoff.isoformat() if cutoff else None,
                                "in_progress": window.open <= now < window.close,
                                "source": calendar_metadata(name)})
                if name != "crypto":
                    for kind, at in (("open", window.open), ("close", window.close)):
                        if now < at <= end:
                            transitions.append({"venue": name, "kind": kind, "at_utc": at.isoformat(),
                                                "at_et": at.astimezone(TOR).isoformat(timespec="minutes")})
        rows.sort(key=lambda row: (not row["open"], row["next_change_et"] or "~", row["venue"]))
        windows.sort(key=lambda window: (window["open_utc"], window["venue"]))
        transitions.sort(key=lambda transition: (transition["at_utc"], transition["venue"], transition["kind"]))
        return {"now_utc": now.isoformat(), "now_et": now.astimezone(TOR).isoformat(),
                "horizon_end_utc": end.isoformat(), "purpose": "scheduled_sessions_only",
                "execution_permission": "none", "weekend_mode": self.weekend_mode(now),
                "eligibility_note": "Broker permissions, feed quality, model validation, and portfolio risk are not evaluated.",
                "active": [row["venue"] for row in rows if row["new_orders_allowed"]],
                "venues": rows, "windows": windows, "transitions": transitions}

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
