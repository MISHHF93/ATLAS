"""Economic-event range interface (no event-data source is wired in ATLAS yet).

Every value carries the time it became knowable; `as_of(t)` hides values not yet available,
so consensus/actual/revision can never leak into features before release.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.zones import Zone


@dataclass(frozen=True)
class EconomicEvent:
    event_id: str
    event_type: str
    scheduled_release_time: int
    instrument_relevance: tuple[str, ...] = ()
    actual_release_time: int | None = None
    reported_value: float | None = None
    consensus_value: float | None = None
    consensus_available_at: int | None = None
    previous_value: float | None = None
    previous_available_at: int | None = None
    revision: float | None = None
    revision_available_at: int | None = None

    def as_of(self, t: int) -> "EconomicEvent":
        def ok(at):
            return at is not None and at <= t
        released = ok(self.actual_release_time)
        return replace(self,
                       actual_release_time=self.actual_release_time if released else None,
                       reported_value=self.reported_value if released else None,
                       consensus_value=self.consensus_value if ok(self.consensus_available_at) else None,
                       previous_value=self.previous_value if ok(self.previous_available_at) else None,
                       revision=self.revision if ok(self.revision_available_at) else None)

    def raw_surprise(self, t: int) -> float | None:
        e = self.as_of(t)
        if e.reported_value is None or e.consensus_value is None:
            return None
        return e.reported_value - e.consensus_value


def event_zone(event: EconomicEvent, bars_1h: list[Bar], instrument: str, now: int) -> Zone | None:
    """Zone from the completed 1h candle containing the release time; None until it is complete."""
    t = event.actual_release_time or event.scheduled_release_time
    for b in bars_1h:
        if b.duration == 3600 and b.start <= t < b.end and now >= b.end:
            return Zone(instrument, 3600, "economic_event", "neutral", b.low, b.high, b.start, confirmed_at=b.end,
                        source_event=event.event_id, feature_snapshot={"event_type": event.event_type})
    return None
