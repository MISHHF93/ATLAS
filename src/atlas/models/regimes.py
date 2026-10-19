"""Deterministic, causal, point-in-time regime classification.

Regime labels organize research evaluations and diagnostics. They never authorize
automatic live model switching or order execution (`execution_permission: none`).
"""
from datetime import datetime
import math
from statistics import pstdev
from typing import Literal, Self

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from atlas.models.calendars import MarketCalendar, calendar_session_state
from atlas.models.schemas import FeatureValue, Observation, Probability, Record, Text

VolatilityRegime = Literal["low_vol", "normal_vol", "high_vol", "shock_vol", "unknown"]
TrendRegime = Literal["uptrend", "downtrend", "ranging", "unknown"]
LiquidityRegime = Literal["liquid", "normal_liquidity", "thin_liquidity", "stressed_liquidity", "unknown"]
SessionRegime = Literal[
    "regular_open",
    "opening_auction",
    "closing_auction",
    "early_close_session",
    "off_hours",
    "continuous_24_7",
    "funding_window",
    "maintenance",
    "holiday_closed",
    "unknown",
]
MacroEventRegime = Literal["pre_event", "event_release", "post_event_digestion", "clear", "unknown"]


class ScheduledMacroEvent(Record):
    event_id: Text
    name: Text
    scheduled_for: AwareDatetime
    known_at: AwareDatetime
    impact: Literal["high", "medium", "low"] = "high"

    @model_validator(mode="after")
    def schedule_known_before_release(self) -> Self:
        if self.known_at > self.scheduled_for:
            raise ValueError("Scheduled event announcement must precede or match release time")
        return self


class RegimeConfig(Record):
    taxonomy_revision: Text = "regime-taxonomy:v1"
    min_observations: int = Field(default=5, ge=3)
    low_vol_threshold: float = Field(default=0.005, gt=0, allow_inf_nan=False)
    high_vol_threshold: float = Field(default=0.015, gt=0, allow_inf_nan=False)
    shock_vol_threshold: float = Field(default=0.030, gt=0, allow_inf_nan=False)
    trend_threshold: float = Field(default=0.010, gt=0, allow_inf_nan=False)
    liquid_threshold: Probability = 0.75
    thin_liquidity_threshold: Probability = 0.45
    stressed_spread_bps: float = Field(default=25.0, gt=0, allow_inf_nan=False)
    pre_event_window_seconds: int = Field(default=1800, gt=0)
    release_window_seconds: int = Field(default=600, gt=0)
    post_event_window_seconds: int = Field(default=3600, gt=0)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> Self:
        if not (self.low_vol_threshold < self.high_vol_threshold < self.shock_vol_threshold):
            raise ValueError("Volatility thresholds must satisfy low < high < shock")
        if not (self.thin_liquidity_threshold < self.liquid_threshold):
            raise ValueError("Liquidity thresholds must satisfy thin < liquid")
        return self


class RegimeState(Record):
    as_of: AwareDatetime
    instrument_id: Text
    taxonomy_revision: Text
    volatility: VolatilityRegime
    trend: TrendRegime
    liquidity: LiquidityRegime
    session: SessionRegime
    macro_event: MacroEventRegime
    realized_volatility: FiniteFloat | None = None
    cumulative_return: FiniteFloat | None = None
    liquidity_score: Probability | None = None
    spread_bps: FiniteFloat | None = None
    composite_label: Text
    execution_permission: Literal["none"] = "none"

    def to_feature_value(self, *, source: str = "atlas.regimes", license_ref: str = "internal:deterministic") -> FeatureValue:
        """Encode regime state as a point-in-time FeatureValue for ForecastRequest."""
        severity_map: dict[VolatilityRegime, float] = {
            "unknown": 0.0,
            "low_vol": 1.0,
            "normal_vol": 2.0,
            "high_vol": 3.0,
            "shock_vol": 4.0,
        }
        quality: Literal["verified", "unknown"] = (
            "unknown" if "unknown" in (self.volatility, self.session) else "verified"
        )
        return FeatureValue(
            name=f"regime:{self.composite_label}",
            source=source,
            lineage_ref=self.taxonomy_revision,
            license_ref=license_ref,
            quality=quality,
            event_time=self.as_of,
            available_at=self.as_of,
            value=severity_map[self.volatility],
        )


def classify_regime(
    *,
    as_of: datetime,
    instrument_id: str,
    observations: tuple[Observation, ...],
    config: RegimeConfig | None = None,
    calendar: MarketCalendar | None = None,
    liquidity_score: float | None = None,
    spread_bps: float | None = None,
    macro_events: tuple[ScheduledMacroEvent, ...] = (),
) -> RegimeState:
    """Classify market regime strictly from information available at or before `as_of`."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    cfg = config or RegimeConfig()

    # Enforce strict point-in-time causality on observations and events
    if any(obs.available_at > as_of for obs in observations):
        raise ValueError("Future observation availability is not permitted in causal regime classification")
    if any(evt.known_at > as_of for evt in macro_events):
        raise ValueError("Macro event schedule not yet known at as_of")

    times = [obs.event_time for obs in observations]
    if times != sorted(set(times)):
        raise ValueError("Regime observations must be unique and ordered")

    # 1. Volatility & Trend Regimes
    vol_regime: VolatilityRegime = "unknown"
    trend_regime: TrendRegime = "unknown"
    realized_vol: float | None = None
    cum_return: float | None = None

    if len(observations) >= cfg.min_observations and all(obs.value > 0 for obs in observations):
        returns = [
            (observations[i].value - observations[i - 1].value) / observations[i - 1].value
            for i in range(1, len(observations))
        ]
        realized_vol = pstdev(returns) if len(returns) >= 2 else abs(returns[0])
        cum_return = (observations[-1].value - observations[0].value) / observations[0].value

        if realized_vol >= cfg.shock_vol_threshold:
            vol_regime = "shock_vol"
        elif realized_vol >= cfg.high_vol_threshold:
            vol_regime = "high_vol"
        elif realized_vol <= cfg.low_vol_threshold:
            vol_regime = "low_vol"
        else:
            vol_regime = "normal_vol"

        if cum_return >= cfg.trend_threshold:
            trend_regime = "uptrend"
        elif cum_return <= -cfg.trend_threshold:
            trend_regime = "downtrend"
        else:
            trend_regime = "ranging"

    # 2. Liquidity Regime
    liq_regime: LiquidityRegime = "unknown"
    if liquidity_score is not None:
        if not math.isfinite(liquidity_score) or not 0 <= liquidity_score <= 1:
            raise ValueError("liquidity_score must be in [0, 1]")
        if spread_bps is not None and (not math.isfinite(spread_bps) or spread_bps < 0):
            raise ValueError("spread_bps must be finite and nonnegative")
        if (spread_bps is not None and spread_bps >= cfg.stressed_spread_bps) or liquidity_score < 0.25:
            liq_regime = "stressed_liquidity"
        elif liquidity_score < cfg.thin_liquidity_threshold:
            liq_regime = "thin_liquidity"
        elif liquidity_score >= cfg.liquid_threshold:
            liq_regime = "liquid"
        else:
            liq_regime = "normal_liquidity"

    # 3. Session Regime
    sess_regime: SessionRegime = "unknown"
    if calendar is not None:
        sess_regime = calendar_session_state(calendar, as_of=as_of)

    # 4. Macro Event Regime
    macro_regime: MacroEventRegime = "clear" if calendar is not None or observations else "unknown"
    for evt in macro_events:
        if evt.impact == "low":
            continue
        delta_sec = (as_of - evt.scheduled_for).total_seconds()
        if -cfg.pre_event_window_seconds <= delta_sec < 0:
            macro_regime = "pre_event"
            break
        if 0 <= delta_sec <= cfg.release_window_seconds:
            macro_regime = "event_release"
            break
        if cfg.release_window_seconds < delta_sec <= cfg.post_event_window_seconds:
            macro_regime = "post_event_digestion"

    composite = f"{vol_regime}|{trend_regime}|{liq_regime}|{sess_regime}|{macro_regime}"
    return RegimeState(
        as_of=as_of,
        instrument_id=instrument_id,
        taxonomy_revision=cfg.taxonomy_revision,
        volatility=vol_regime,
        trend=trend_regime,
        liquidity=liq_regime,
        session=sess_regime,
        macro_event=macro_regime,
        realized_volatility=realized_vol,
        cumulative_return=cum_return,
        liquidity_score=liquidity_score,
        spread_bps=spread_bps,
        composite_label=composite,
    )

