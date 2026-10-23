"""Explicit session calendars (timezone + local open/close + weekdays + holidays)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SessionSpec:
    name: str
    tz: str
    open_local: time
    close_local: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    holidays: frozenset[date] = field(default_factory=frozenset)

    def window_for(self, ts: int) -> tuple[str, int, int] | None:
        """(session_id, open_utc, close_utc) of the session containing ts, else None."""
        z = ZoneInfo(self.tz)
        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(z)
        for d in (local.date(), local.date() - timedelta(days=1)):
            if d.weekday() not in self.weekdays or d in self.holidays:
                continue
            o = datetime.combine(d, self.open_local, z)
            c = datetime.combine(d if self.close_local > self.open_local else d + timedelta(days=1), self.close_local, z)
            if o.timestamp() <= ts < c.timestamp():
                return f"{self.name}:{d.isoformat()}", int(o.timestamp()), int(c.timestamp())
        return None


# Engineering presets. Holidays are NOT included; pass them explicitly (or use
# atlas.marketdata.pit.calendars) before using these for real sessions.
US_EQUITY_RTH = SessionSpec("us_equity_rth", "America/New_York", time(9, 30), time(16, 0))
LONDON_CASH = SessionSpec("london_cash", "Europe/London", time(8, 0), time(16, 30))
TOKYO_CASH = SessionSpec("tokyo_cash", "Asia/Tokyo", time(9, 0), time(15, 0))
PRESETS = {s.name: s for s in (US_EQUITY_RTH, LONDON_CASH, TOKYO_CASH)}
