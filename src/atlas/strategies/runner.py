"""Final integration layer wiring the Price Action Framework into the ATLAS Control Plane.

Coordinates the full flow:
Market Data -> ZoneEngine -> SnapbackDetector -> StrategyClassifier -> ControlPlane.

Ensures that no trade is executed without deterministic risk authorization.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import pandas as pd

from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.strategies.coordinator import OpportunityCoordinator, RankedOpportunity
from atlas.models.strategy_classifier import StrategyClassifier
from atlas.features.pa_integration import PriceActionFeatureExtractor
from atlas.features.zones import ZoneEngine, ZoneType
from atlas.strategies.snapback import SnapbackDetector


class AtlasStrategyRunner:
    """
    The top-level orchestrator that executes the Price Action Framework 
    and submits authorized requests to the ActionableControlPlaneEngine.
    """

    def __init__(
        self, 
        control_plane: ActionableControlPlaneEngine,
        classifier: StrategyClassifier,
        feature_extractor: PriceActionFeatureExtractor
    ):
        self.control_plane = control_plane
        self.coordinator = OpportunityCoordinator(classifier, feature_extractor)
        
    def on_market_update(
        self, 
        symbol: str, 
        df: pd.DataFrame, 
        track: str = "competition",
        session_start: Optional[datetime] = None,
        event_time: Optional[datetime] = None
    ) -> Optional[ActionableOrderRequest]:
        """
        Main entry point invoked on every significant market update (e.g., hour close).
        """
        # 1. Rank opportunities using the coordinator
        opportunity = self.coordinator.evaluate_asset(
            symbol=symbol, 
            df=df, 
            session_start=session_start, 
            event_time=event_time
        )
        
        if not opportunity or opportunity.recommended_action == "ignore":
            return None

        # 2. Translate the RankedOpportunity into an ActionableOrderRequest
        # We derive stop and target levels from the a structural boundaries
        zone_engine = self.coordinator.zone_engines[symbol.upper()]
        opening_box = zone_engine.active_zones.get(ZoneType.OPENING)
        
        if not opening_box:
            return None

        # Trade Params based on Framework Specs: 2x Box Height stop
        box_height = opening_box.boundary.height
        entry_price = df['close'].iloc[-1]
        
        # Calculate stop distance in BPS for the Control Plane
        stop_dist_bps = (2 * box_height / entry_price) * 10_000

        request = ActionableOrderRequest(
            track=track,
            instrument_id=f"{track}:{symbol.lower()}:v1",
            side="buy" if opportunity.direction == "long" else "sell",
            notional_usd=25000, # Default starting notional, can be dynamic
            stop_kind="structure",
            stop_distance_bps=float(stop_dist_bps),
            holding_horizon_seconds=86400, # 1 day max
            data_age_ms=0.0 # To be filled by live stream
        )

        # 3. Submit to the deterministic Control Plane for authorization
        # This is the absolute final gate.
        decision = self.control_plane.submit_order(request)
        
        if decision.control_plane_decision == "authorized_and_executed":
            return request
            
        return None
