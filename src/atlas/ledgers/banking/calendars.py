"""Business-day calendars (offline, rule-based, cross-checked against published schedules).

* "CA" (default): Payments Canada system closures (ACSS, Lynx): weekends + federal statutory holidays, moved to the
  next weekday when they fall on a weekend (e.g. Boxing Day 2026 Sat -> Mon Dec 28; Sep 30 National Day for Truth
  and Reconciliation is a closure). Source: https://www.payments.ca/system-closure-schedule (2026 table checked in tests).
  Not closures: Easter Monday, Civic Holiday, Family Day (provincial).
* "CA-ON", "CA-QC", "CA-BC", "CA-AB", "CA-MB", "CA-SK", "CA-NS", "CA-NB", "CA-PE", "CA-NL": the CA calendar plus that
  province's general holidays (for branch/value-date and investor-facing cut-off messaging; interbank settlement
  still follows "CA").
* "US": Federal Reserve (Fedwire/FedACH) holidays for USD value dates (Sunday holidays move to Monday; Saturday holidays
  are not observed by the Fed).
These are rule-based so they extend to any year; PUBLISHED holds officially published years for verification. Always
confirm next year's schedule when Payments Canada publishes it."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

D = dt.date

PUBLISHED = {  # Payments Canada system closure schedule (published), used to verify the rules
    ("CA", 2026): {D(2026, 1, 1), D(2026, 4, 3), D(2026, 5, 18), D(2026, 7, 1), D(2026, 9, 7), D(2026, 9, 30),
                   D(2026, 10, 12), D(2026, 11, 11), D(2026, 12, 25), D(2026, 12, 28)},
}
REGIONS = ("CA", "CA-ON", "CA-QC", "CA-BC", "CA-AB", "CA-MB", "CA-SK", "CA-NS", "CA-NB", "CA-PE", "CA-NL", "US")


def easter(y: int) -> D:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return D(y, month, (h + l_ - 7 * m + 114) % 31 + 1)


def nth_weekday(y: int, month: int, weekday: int, n: int) -> D:
    """n-th weekday (0=Mon) of a month; n=-1 for the last."""
    if n > 0:
        d = D(y, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    d = (D(y + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1))
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def victoria_day(y: int) -> D:
    d = D(y, 5, 24)
    return d - dt.timedelta(days=d.weekday())  # Monday on or before May 24


def _observe_next_weekday(days: list[tuple[str, D]]) -> dict[D, str]:
    """Weekend holidays move to the next weekday not already taken (Christmas Sat -> Mon, Boxing Sun -> Tue)."""
    out: dict[D, str] = {}
    for name, d in sorted(days, key=lambda x: x[1]):
        o = d
        while o.weekday() >= 5 or o in out:
            o += dt.timedelta(days=1)
        out[o] = name if o == d else f"{name} (observed)"
    return out


def _federal(y: int) -> list[tuple[str, D]]:
    return [("New Year's Day", D(y, 1, 1)), ("Good Friday", easter(y) - dt.timedelta(days=2)),
            ("Victoria Day", victoria_day(y)), ("Canada Day", D(y, 7, 1)), ("Labour Day", nth_weekday(y, 9, 0, 1)),
            ("National Day for Truth and Reconciliation", D(y, 9, 30)), ("Thanksgiving", nth_weekday(y, 10, 0, 2)),
            ("Remembrance Day", D(y, 11, 11)), ("Christmas Day", D(y, 12, 25)), ("Boxing Day", D(y, 12, 26))]


def _provincial(region: str, y: int) -> list[tuple[str, D]]:
    feb3 = nth_weekday(y, 2, 0, 3)
    aug1 = nth_weekday(y, 8, 0, 1)
    return {
        "CA-ON": [("Family Day", feb3)],
        "CA-QC": [("Fête nationale du Québec", D(y, 6, 24))],   # Journée nationale des patriotes = Victoria Day
        "CA-BC": [("Family Day", feb3), ("British Columbia Day", aug1)],
        "CA-AB": [("Family Day", feb3), ("Heritage Day", aug1)],
        "CA-MB": [("Louis Riel Day", feb3), ("Terry Fox Day", aug1)],
        "CA-SK": [("Family Day", feb3), ("Saskatchewan Day", aug1)],
        "CA-NS": [("Heritage Day", feb3), ("Natal Day", aug1)],
        "CA-NB": [("Family Day", feb3), ("New Brunswick Day", aug1)],
        "CA-PE": [("Islander Day", feb3), ("Gold Cup Parade Day", nth_weekday(y, 8, 4, 3))],
        "CA-NL": [("St. Patrick's Day (observed)", _nearest_monday(D(y, 3, 17)))],
    }.get(region, [])


def _nearest_monday(d: D) -> D:
    back = d.weekday()
    return d - dt.timedelta(days=back) if back <= 3 else d + dt.timedelta(days=7 - back)


def _us(y: int) -> dict[D, str]:
    days = [("New Year's Day", D(y, 1, 1)), ("Martin Luther King Jr. Day", nth_weekday(y, 1, 0, 3)),
            ("Presidents Day", nth_weekday(y, 2, 0, 3)), ("Memorial Day", nth_weekday(y, 5, 0, -1)),
            ("Juneteenth", D(y, 6, 19)), ("Independence Day", D(y, 7, 4)), ("Labor Day", nth_weekday(y, 9, 0, 1)),
            ("Columbus Day", nth_weekday(y, 10, 0, 2)), ("Veterans Day", D(y, 11, 11)),
            ("Thanksgiving Day", nth_weekday(y, 11, 3, 4)), ("Christmas Day", D(y, 12, 25))]
    out = {}
    for name, d in days:
        if d.weekday() == 6:
            out[d + dt.timedelta(days=1)] = f"{name} (observed)"
        elif d.weekday() < 5:
            out[d] = name               # Saturday holidays: the Fed is open the preceding Friday
    return out


@lru_cache(maxsize=256)
def holidays(year: int, region: str = "CA") -> dict[D, str]:
    if region not in REGIONS:
        raise ValueError(f"unknown calendar region {region!r}; one of {REGIONS}")
    if region == "US":
        return _us(year)
    days = _federal(year) + (_provincial(region, year) if region != "CA" else [])
    return _observe_next_weekday(days)


def _d(x) -> D:
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, D):
        return x
    return D.fromisoformat(str(x)[:10])


def is_business_day(d, region: str = "CA") -> bool:
    d = _d(d)
    return d.weekday() < 5 and d not in holidays(d.year, region)


def holiday_name(d, region: str = "CA") -> str | None:
    d = _d(d)
    return holidays(d.year, region).get(d) or ("weekend" if d.weekday() >= 5 else None)


def next_business_day(d, region: str = "CA", include_self: bool = False) -> D:
    d = _d(d)
    if not include_self:
        d += dt.timedelta(days=1)
    while not is_business_day(d, region):
        d += dt.timedelta(days=1)
    return d


def previous_business_day(d, region: str = "CA", include_self: bool = False) -> D:
    d = _d(d)
    if not include_self:
        d -= dt.timedelta(days=1)
    while not is_business_day(d, region):
        d -= dt.timedelta(days=1)
    return d


def add_business_days(d, n: int, region: str = "CA") -> D:
    d = _d(d)
    step = 1 if n >= 0 else -1
    for _ in range(abs(n)):
        d = next_business_day(d, region) if step > 0 else previous_business_day(d, region)
    return d


def business_days_between(a, b, region: str = "CA") -> int:
    """Business days in (a, b]."""
    a, b = _d(a), _d(b)
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        n += is_business_day(d, region)
    return n


def last_business_day_of_month(d, region: str = "CA") -> D:
    d = _d(d)
    end = D(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(days=1)
    return previous_business_day(end, region, include_self=True)


def value_date(d, region: str = "CA") -> D:
    """Roll a requested value/settlement date forward to a business day (modified-following not applied)."""
    return next_business_day(d, region, include_self=True)


def calendar_view(year: int, region: str = "CA") -> list[dict]:
    return [{"date": d.isoformat(), "weekday": d.strftime("%a"), "name": n} for d, n in sorted(holidays(year, region).items())]
