"""Price-action engine: one entry point for replay (batch) and live (bar-by-bar streaming).

Streaming uses incremental indicators; batch precomputes indicators with independent numpy
implementations. Both feed the same detector state machines, and parity is tested.
Unconfirmed bars (now < bar_end or provider completion not verified), duplicates and
out-of-order bars are refused, never consumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from atlas.features.price_action.bars import Bar, bar_confirmed
from atlas.features.price_action.detectors import (Candidate, DualBandConfig, DualBollingerDetector, ORBRetestConfig,
                                                   ORBRetestDetector, Transition, WickConfig, WickReversalDetector)
from atlas.features.price_action.prior_day import PriorDayRangeConfig, PriorDayRangeReversalDetector
from atlas.features.price_action.features import StreamingFeatures, batch_features
from atlas.features.price_action.sessions import SessionSpec
from atlas.features.price_action.zones import Zone


@dataclass
class EngineConfig:
    session: SessionSpec | None = None
    orb: ORBRetestConfig = field(default_factory=ORBRetestConfig)
    dual: DualBandConfig = field(default_factory=DualBandConfig)
    wick: WickConfig = field(default_factory=WickConfig)
    atr_n: int = 14
    pdr: PriorDayRangeConfig | None = None      # prior-day range reversal; off unless configured (needs a session)
    suite: Any = None                           # levels.SuiteConfig: SFP / gold Snapback / gold ORB (all off by default)


class PriceActionEngine:
    def __init__(self, instrument: str, timeframe: int, cfg: EngineConfig | None = None):
        self.instrument, self.timeframe, self.cfg = instrument, timeframe, cfg or EngineConfig()
        self.detectors: list[Any] = [DualBollingerDetector(instrument, timeframe, self.cfg.dual),
                                     WickReversalDetector(instrument, timeframe, self.cfg.wick)]
        if self.cfg.session is not None:
            self.detectors.insert(0, ORBRetestDetector(instrument, timeframe, self.cfg.session, self.cfg.orb))
            if self.cfg.pdr is not None:
                self.detectors.append(PriorDayRangeReversalDetector(instrument, timeframe, self.cfg.session, self.cfg.pdr))
        if self.cfg.suite is not None:
            from atlas.features.price_action.suite import LevelSuiteDetector
            self.detectors.append(LevelSuiteDetector(instrument, timeframe, self.cfg.suite))
        self._features = StreamingFeatures(self.cfg.atr_n)
        self.last_start: int | None = None
        self.refused: list[tuple[int, str]] = []
        self.events: list[Any] = []

    def _admit(self, bar: Bar, now: int) -> bool:
        if bar.duration != self.timeframe:
            self.refused.append((bar.start, "timeframe_mismatch"))
        elif not bar_confirmed(bar, now):
            self.refused.append((bar.start, "bar_not_confirmed"))
        elif self.last_start is not None and bar.start <= self.last_start:
            self.refused.append((bar.start, "duplicate_or_out_of_order"))
        else:
            return True
        return False

    def _step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        self.last_start = bar.start
        out: list[Any] = []
        for d in self.detectors:
            out += d.step(bar, ctx)
        self.events += out
        return out

    def update(self, bar: Bar, now: int | None = None) -> list[Any]:
        """Live path. `now` defaults to bar_end (replay clock)."""
        if not self._admit(bar, bar.end if now is None else now):
            return []
        return self._step(bar, self._features.update(bar))

    def run_batch(self, bars: Sequence[Bar], now: int | None = None) -> list[Any]:
        """Replay path: admit bars, precompute indicators in batch, then step."""
        admitted: list[Bar] = []
        last = self.last_start
        for b in bars:
            n = b.end if now is None else now
            if b.duration != self.timeframe or not bar_confirmed(b, n) or (last is not None and b.start <= last):
                self.refused.append((b.start, "refused"))
                continue
            admitted.append(b)
            last = b.start
        ctxs = batch_features(admitted, self.cfg.atr_n)
        out: list[Any] = []
        for b, c in zip(admitted, ctxs):
            out += self._step(b, c)
        return out

    # ---- read views ----
    @property
    def zones(self) -> list[Zone]:
        return [z for d in self.detectors for z in d.zones]

    @property
    def candidates(self) -> list[Candidate]:
        return [c for d in self.detectors for c in getattr(d, "candidates", [])]

    @property
    def transitions(self) -> list[Transition]:
        return [t for d in self.detectors for t in getattr(d, "transitions", [])]

    def summary(self) -> dict[str, Any]:
        return {"instrument": self.instrument, "timeframe": self.timeframe,
                "zones": [z.to_dict() for z in self.zones],
                "candidates": [c.to_dict() for c in self.candidates],
                "transitions": [t.__dict__ for t in self.transitions],
                "refused": len(self.refused), "execution_permission": "none"}
