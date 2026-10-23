"""Integration layer for Price Action features into the ATLAS Feature Store.

Translates structural zones and Snapback states into quantitative features
suitable for ML training and inference.

All features maintain execution_permission = 'none'.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Any
import pandas as pd
import numpy as np

from atlas.features.feature_store import FeatureStore, FeatureMetadata, FeatureLineage
from atlas.features.zones import ZoneType, PriceZone, ZoneDirection
from atlas.strategies.snapback import SnapbackSetup, SnapbackState
from atlas.models.schemas import Record, Text
from atlas.marketdata.live_stream import LiveMarketDataGateway, LiveTickFrame


class PriceActionFeatureExtractor:
    """
    Extracts ML-ready features from Price Action Zones and Snapback setups.
    
    This class bridges the gap between the ZoneEngine/SnapbackDetector and the 
    centralized FeatureStore.
    """

    def __init__(self, store: FeatureStore):
        self.store = store

    def extract_zone_features(
        self,
        symbol: str,
        df: pd.DataFrame,
        active_zones: dict[ZoneType, PriceZone | None],
        timestamp: datetime,
        microstructure: Optional[LiveTickFrame | dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Computes quantitative features based on current active zones and order-flow.

        Returns a DataFrame with a single row containing the features for the given timestamp.
        """
        # 1. Distance from Zones (Normalized by volatility or price)
        current_price = df['close'].iloc[-1]
        features = {
            "timestamp": timestamp,
            "symbol": symbol,
            "price": current_price,
        }

        for z_type, zone in active_zones.items():
            if zone is None:
                features[f"{z_type.name.lower()}_dist_pct"] = np.nan
                features[f"{z_type.name.lower()}_active"] = 0
                continue

            # Distance to nearest boundary
            dist = min(abs(current_price - zone.boundary.high),
                       abs(current_price - zone.boundary.low))
            features[f"{z_type.name.lower()}_dist_pct"] = dist / current_price * 10_000
            features[f"{z_type.name.lower()}_active"] = 1

            # Relative position (Inside vs Outside)
            is_inside = zone.boundary.low <= current_price <= zone.boundary.high
            features[f"{z_type.name.lower()}_inside"] = 1 if is_inside else 0

        # 2. Zone Overlap (Structural Coincidence)
        active_count = sum(1 for z in active_zones.values() if z is not None)
        features["zone_overlap_count"] = active_count

        # 3. Microstructure Integration (Whale/Order Flow)
        if microstructure:
            # Handle both dataclass and dict formats
            m_data = microstructure if isinstance(microstructure, dict) else microstructure.__dict__
            features["vpin"] = m_data.get("vpin", 0.0)
            features["ofi"] = m_data.get("ofi", 0.0)
            features["kyles_lambda"] = m_data.get("kyles_lambda", 0.0)
            features["regime"] = 1 if m_data.get("regime") == "Expansion" else 0
        else:
            features["vpin"] = 0.0
            features["ofi"] = 0.0
            features["kyles_lambda"] = 0.0
            features["regime"] = 0

        return pd.DataFrame([features])
    def extract_snapback_features(
        self, 
        symbol: str, 
        setup: SnapbackSetup | None, 
        timestamp: datetime
    ) -> pd.DataFrame:
        """
        Computes features specifically for the Snapback entry.
        """
        features = {
            "timestamp": timestamp,
            "symbol": symbol,
            "snapback_state": -1, # Default: No setup
            "snapback_direction": 0, # 0: None, 1: Long, -1: Short
            "retest_count": 0,
            "setup_duration_sec": 0,
        }

        if setup:
            state_map = {
                SnapbackState.AWAITING_BREAKOUT: 0,
                SnapbackState.AWAITING_RETEST: 1,
                SnapbackState.AWAITING_CONFIRMATION: 2,
                SnapbackState.QUALIFIED: 3,
                SnapbackState.INVALIDATED: -1,
                SnapbackState.EXPIRED: -2,
            }
            features["snapback_state"] = state_map.get(setup.state, -1)
            features["snapback_direction"] = 1 if setup.direction == "long" else -1 if setup.direction == "short" else 0
            
            if setup.breakout_time:
                features["setup_duration_sec"] = (timestamp - setup.breakout_time).total_seconds()
            
            # In a real implementation, we would track actual touches in the setup object
            # for 'retest_count'. For now, we use the state transition as a proxy.
            features["retest_count"] = 1 if setup.state == SnapbackState.QUALIFIED else 0

        return pd.DataFrame([features])

    def store_structural_features(
        self, 
        symbol: str, 
        feature_df: pd.DataFrame, 
        feature_name: str,
        metadata: FeatureMetadata
    ):
        """Writes the extracted features to the FeatureStore."""
        lineage = FeatureLineage(
            lineage_id=f"lineage_{feature_name}_{datetime.now(timezone.utc).timestamp()}",
            feature_name=feature_name,
            transformation_steps=({"step1": "Extract structural zones", "step2": "Normalize distance"}),
            source_features=("ohlcv",),
            created_at=datetime.now(timezone.utc)
        )
        self.store.store_feature(feature_name, feature_df, metadata, lineage)
