"""Shared, causal price-action engine (zones, opening range, breakout-retest, dual Bollinger, wick reversal).

All outputs are research/proposal artefacts with execution_permission="none"; only the
deterministic control plane can authorize anything. See docs/spec/price-action.md.
"""
from atlas.features.price_action.bars import Bar, bar_confirmed, bars_from_rows, candle_geometry
from atlas.features.price_action.detectors import (STATES, Candidate, DualBandConfig, DualBollingerDetector,
                                                   ORBRetestConfig, ORBRetestDetector, Transition, WickConfig,
                                                   WickReversalDetector)
from atlas.features.price_action.prior_day import PDR_STATES, PriorDayRangeConfig, PriorDayRangeReversalDetector
from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.events import EconomicEvent, event_zone
from atlas.features.price_action.sessions import PRESETS, SessionSpec
from atlas.features.price_action.zones import Zone

__all__ = ["Bar", "bar_confirmed", "bars_from_rows", "candle_geometry", "STATES", "Candidate", "DualBandConfig",
           "DualBollingerDetector", "ORBRetestConfig", "ORBRetestDetector", "Transition", "WickConfig",
           "WickReversalDetector", "EngineConfig", "PriceActionEngine", "EconomicEvent", "event_zone", "PRESETS",
           "SessionSpec", "Zone", "PDR_STATES", "PriorDayRangeConfig", "PriorDayRangeReversalDetector"]
