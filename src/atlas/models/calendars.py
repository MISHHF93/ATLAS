"""Select session and continuous targets from versioned calendar metadata."""
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from atlas.models.schemas import Horizon, Instrument, Record, Text


class SessionSchedule(Record):
    calendar_ref: Text
    session_targets: tuple[AwareDatetime, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_targets(self) -> Self:
        if tuple(sorted(set(self.session_targets))) != self.session_targets:
            raise ValueError("Session targets must be unique and ordered")
        return self


class MaintenanceWindow(Record):
    start_time: AwareDatetime
    end_time: AwareDatetime
    reason: Text

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("Maintenance end_time must follow start_time")
        return self


class MarketCalendar(Record):
    calendar_ref: Text
    market_type: Literal["traditional_session", "continuous_crypto"]
    timezone: Text
    session_targets: tuple[AwareDatetime, ...] = ()
    holidays: tuple[str, ...] = ()
    early_closes: tuple[AwareDatetime, ...] = ()
    maintenance_windows: tuple[MaintenanceWindow, ...] = ()
    funding_timestamps: tuple[AwareDatetime, ...] = ()
    regular_session_duration_minutes: int = Field(default=390, gt=0, le=1440)

    @model_validator(mode="after")
    def ordered_metadata(self) -> Self:
        if tuple(sorted(set(self.session_targets))) != self.session_targets:
            raise ValueError("Calendar session_targets must be unique and ordered")
        if tuple(sorted(set(self.funding_timestamps))) != self.funding_timestamps:
            raise ValueError("Calendar funding_timestamps must be unique and ordered")
        if self.market_type == "traditional_session" and not self.session_targets:
            raise ValueError("Traditional session calendar requires explicit session_targets")
        return self


def resolve_session_targets(
    instrument: Instrument,
    horizon: Horizon,
    schedule: SessionSchedule,
    *,
    as_of: datetime,
) -> tuple[datetime, ...]:
    """Resolve future session targets without inferring calendar rules."""
    if horizon.sampling != "session":
        raise ValueError("Session schedules require a session-sampled horizon")
    if schedule.calendar_ref != instrument.calendar_ref:
        raise ValueError("Session schedule does not match the instrument calendar")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    future_targets = tuple(target for target in schedule.session_targets if target > as_of)
    if len(future_targets) < horizon.steps:
        raise ValueError("Session schedule does not contain enough future targets")
    return future_targets[:horizon.steps]


def calendar_session_state(
    calendar: MarketCalendar,
    *,
    as_of: datetime,
) -> Literal[
    "regular_open",
    "opening_auction",
    "closing_auction",
    "early_close_session",
    "off_hours",
    "continuous_24_7",
    "funding_window",
    "maintenance",
    "holiday_closed",
]:
    """Determine deterministic point-in-time session state from versioned calendar."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    for window in calendar.maintenance_windows:
        if window.start_time <= as_of < window.end_time:
            return "maintenance"

    iso_day = as_of.date().isoformat()
    if iso_day in calendar.holidays:
        return "holiday_closed"

    if calendar.market_type == "continuous_crypto":
        for funding_ts in calendar.funding_timestamps:
            if abs((funding_ts - as_of).total_seconds()) <= 900:
                return "funding_window"
        return "continuous_24_7"

    for early_close in calendar.early_closes:
        open_ts = early_close - timedelta(minutes=210)
        if open_ts <= as_of <= early_close:
            return "early_close_session"

    duration = timedelta(minutes=calendar.regular_session_duration_minutes)
    for close_target in calendar.session_targets:
        open_target = close_target - duration
        if open_target <= as_of <= close_target:
            if (as_of - open_target).total_seconds() <= 900:
                return "opening_auction"
            if (close_target - as_of).total_seconds() <= 900:
                return "closing_auction"
            return "regular_open"
    return "off_hours"


def construct_authoritative_targets(
    instrument: Instrument,
    horizon: Horizon,
    calendar: MarketCalendar,
    *,
    as_of: datetime,
    step_seconds: int | None = None,
) -> tuple[datetime, ...]:
    """Construct verified target timestamps from an authoritative MarketCalendar."""
    if calendar.calendar_ref != instrument.calendar_ref:
        raise ValueError("MarketCalendar does not match instrument.calendar_ref")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    state = calendar_session_state(calendar, as_of=as_of)
    if state == "maintenance":
        raise ValueError("Cannot construct targets while venue is in maintenance")

    def _in_maintenance_or_holiday(ts: datetime) -> bool:
        if ts.date().isoformat() in calendar.holidays:
            return True
        return any(w.start_time <= ts < w.end_time for w in calendar.maintenance_windows)

    if horizon.sampling == "session":
        valid_future = tuple(
            target
            for target in calendar.session_targets
            if target > as_of and not _in_maintenance_or_holiday(target)
        )
        if len(valid_future) < horizon.steps:
            raise ValueError("Calendar does not have enough tradable future session targets")
        return valid_future[: horizon.steps]

    if horizon.sampling == "time":
        if step_seconds is None or step_seconds <= 0:
            raise ValueError("Time-sampled target construction requires positive step_seconds")
        targets: list[datetime] = []
        candidate = as_of
        max_iterations = horizon.steps * 20
        for _ in range(max_iterations):
            if len(targets) == horizon.steps:
                break
            candidate = candidate + timedelta(seconds=step_seconds)
            if not _in_maintenance_or_holiday(candidate):
                targets.append(candidate)
        if len(targets) < horizon.steps:
            raise ValueError("Unable to construct enough tradable time targets outside maintenance/holidays")
        return tuple(targets)

    raise ValueError(f"Unsupported calendar target construction for sampling={horizon.sampling}")
