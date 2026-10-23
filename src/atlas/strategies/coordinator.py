"""Opportunity Ranking and Strategy Coordination System for ATLAS.

This system coordinates the flow from raw market data to a ranked list of
trading opportunities by integrating:
1. ZoneEngine -> Structural reaction areas
2. SnapbackDetector -> Setup identification
3. StrategyClassifier -> Probabilistic filtering

All candidates are passed to the ActionableControlPlaneEngine for risk authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional, List, TYPE_CHECKING
import pandas as pd

from atlas.features.zones import ZoneEngine, ZoneType, PriceZone
from atlas.strategies.snapback import SnapbackDetector, SnapbackSetup, SnapbackState
from atlas.models.strategy_classifier import StrategyClassifier, StrategyPrediction
from atlas.features.pa_integration import PriceActionFeatureExtractor
from atlas.models.schemas import Record, Text

if TYPE_CHECKING:
    from atlas.research.memory import MarketMemoryEngine


@dataclass
class RankedOpportunity:
    """A structural opportunity ranked by its expected value and probability."""
    symbol: Text
    opportunity_id: Text
    strategy_name: Text
    direction: Literal["long", "short"]
    probability: float
    expected_value: float
    uncertainty: float
    setup_details: dict[str, Any]
    recommended_action: str
    evaluated_at: datetime
    execution_permission: str = "none"


class OpportunityCoordinator:
    """
    The 'Brain' of the strategy layer. It monitors assets and ranks 
    detected setups based on structural and probabilistic evidence.
    """

    def __init__(
        self, 
        classifier: StrategyClassifier, 
        feature_extractor: PriceActionFeatureExtractor,
        memory_engine: MarketMemoryEngine
    ):
        self.classifier = classifier
        self.extractor = feature_extractor
        self.memory = memory_engine
        # Symbol-specific state tracking
        self.zone_engines: dict[str, ZoneEngine] = {}
        self.detectors: dict[str, SnapbackDetector] = {}

    def _get_or_create_engines(self, symbol: str) -> tuple[ZoneEngine, SnapbackDetector]:
        sym = symbol.upper()
        if sym not in self.zone_engines:
            self.zone_engines[sym] = ZoneEngine(sym)
            self.detectors[sym] = SnapbackDetector(sym)
        return self.zone_engines[sym], self.detectors[sym]

    def evaluate_asset(
        self,
        symbol: str,
        df: pd.DataFrame,
        session_start: Optional[datetime] = None,
        event_time: Optional[datetime] = None,
        microstructure: Optional[Any] = None
    ) -> Optional[RankedOpportunity]:
        """
        Full pipeline execution for a single asset:
        Zones -> Setup Detection -> ML Scoring -> Ranking.
        """
        zone_engine, detector = self._get_or_create_engines(symbol)

        # 1. Update structural zones
        active_zones = zone_engine.update_zones(
            df,
            session_start=session_start,
            event_time=event_time
        )

        # 2. Detect Snapback Setup
        opening_box = active_zones.get(ZoneType.OPENING)
        setup = detector.process_bars(df, opening_box)

        if setup is None or setup.state != SnapbackState.QUALIFIED:
            return None

        # 3. Extract features for the ML model
        timestamp = df['timestamp'].iloc[-1]
        zone_features = self.extractor.extract_zone_features(
            symbol, df, active_zones, timestamp, microstructure=microstructure
        )
        snapback_features = self.extractor.extract_snapback_features(
            symbol, setup, timestamp
        )

        # Combine features into a single vector
        full_features = pd.concat([zone_features, snapback_features], axis=1)
        # Remove duplicate timestamp/symbol columns
        full_features = full_features.loc[:, ~full_features.columns.duplicated()]

        # 4. Get probabilistic forecast from the ML Classifier
        prediction = self.classifier.predict(setup, full_features)

        # 5. Retrieve Historical Analogues (Market Memory)
        analogues = self.memory.find_analogues(full_features)
        consensus_prob = self.memory.get_analogue_consensus(analogues)

        # Blend Model Probability with Historical Consensus
        # Weight: 70% Model, 30% Historical Analogue
        blended_prob = (prediction.probability_of_success * 0.7) + (consensus_prob * 0.3)

        # Update prediction with blended probability for EV calculation
        blended_ev = (blended_prob * 1.5) - ((1 - blended_prob) * 1.0)

        # 6. Construct the ranked opportunity
        return RankedOpportunity(
            symbol=symbol,
            opportunity_id=setup.setup_id,
            strategy_name="SnapbackEntry",
            direction="long" if setup.direction == "long" else "short",
            probability=blended_prob,
            expected_value=blended_ev,
            uncertainty=prediction.uncertainty_score,
            setup_details={
                "state": setup.state.name,
                "box_height": opening_box.boundary.height if opening_box else 0,
                "breakout_time": setup.breakout_time.isoformat() if setup.breakout_time else None,
                "analogue_count": len(analogues),
                "consensus_prob": consensus_prob
            },
            recommended_action=prediction.recommended_action,
            evaluated_at=datetime.now(timezone.utc)
        )
    def rank_opportunities(self, opportunities: list[RankedOpportunity]) -> list[RankedOpportunity]:
        """
        Ranks opportunities by Expected Value (EV) and filters by 
        minimum probability thresholds.
        """
        # Filter out "ignore" recommendations
        filtered = [o for o in opportunities if o.recommended_action != "ignore"]
        
        # Sort by EV descending
        return sorted(filtered, key=lambda x: x.expected_value, reverse=True)
