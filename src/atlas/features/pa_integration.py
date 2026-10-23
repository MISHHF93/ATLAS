"""Advanced ML Feature Engineering and Regime-Conditioned Scaling for ATLAS.

Implements a high-alpha feature pipeline that transforms raw Price Action and 
Order Flow data into regime-aware inputs for the StrategyClassifier.

Focuses on:
- Volatility-normalized distance metrics.
- Relative Volume (RVOL) profiles.
- Structural coincidence (Zone Overlap).
- Institutional flow confirmation.
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
from atlas.features.scaling import RegimeScaler


class PriceActionFeatureExtractor:
    """
    Advanced feature extractor that bridges structural zones, microstructure,
    and volatility regimes into a unified ML vector.
    """

    def __init__(self, store: FeatureStore):
        self.store = store
        self.scaler = RegimeScaler()

    def extract_zone_features(
        self,
        symbol: str,
        df: pd.DataFrame,
        active_zones: dict[ZoneType, PriceZone | None],
        timestamp: datetime,
        microstructure: Optional[LiveTickFrame | dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Computes high-alpha features for structural setups.
        """
        # Ensure we have enough data for volatility calculations
        if len(df) < 20:
            # Return zeroed frame to maintain pipeline stability
            return self._empty_feature_frame(timestamp, symbol)

        current_price = df['close'].iloc[-1]
        features = {
            "timestamp": timestamp,
            "symbol": symbol,
            "price": current_price,
        }

        # 1. Structural Distance (Normalized by current ATR/StdDev)
        # Use 20-period std as a proxy for local volatility (vol-normalization)
        close_series = df['close'].tail(20)
        local_vol = close_series.std() + 1e-9
        
        for z_type, zone in active_zones.items():
            if zone is None:
                features[f"{z_type.name.lower()}_dist_norm"] = np.nan
                features[f"{z_type.name.lower()}_active"] = 0
                continue

            # Distance in terms of local volatility (z-score like)
            dist = min(abs(current_price - zone.boundary.high),
                       abs(current_price - zone.boundary.low))
            
            raw_dist_norm = dist / local_vol
            
            # Apply asset-specific scaling if params are available
            scaled_dist = self.scaler.scale_feature(symbol, f"{z_type.name.lower()}_dist", raw_dist_norm)
            features[f"{z_type.name.lower()}_dist_norm"] = scaled_dist
            features[f"{z_type.name.lower()}_active"] = 1
            
            # Relative position (Inside vs Outside)
            is_inside = zone.boundary.low <= current_price <= zone.boundary.high
            features[f"{z_type.name.lower()}_inside"] = 1 if is_inside else 0
        # 2. Structural Coincidence (Zone Overlap)
        active_count = sum(1 for z in active_zones.values() if z is not None)
        features["zone_overlap_count"] = active_count

        # 3. Volatility & Volume Alpha
        # Relative Volume (RVOL) - current volume vs 20-period average
        avg_vol = df['volume'].tail(20).mean()
        features["rvol"] = df['volume'].iloc[-1] / (avg_vol + 1e-9)
            
        # Volatility Compression (BB Width normalized by price)
        close_series = df['close'].tail(20)
        std20 = close_series.std()
        ma20 = close_series.mean()
        features["vol_compression"] = (std20 * 4) / (ma20 + 1e-9)

        # 4. Microstructure Integration (Institutional Flow)
        if microstructure:
            m_data = microstructure if isinstance(microstructure, dict) else microstructure.__dict__
            features["vpin"] = m_data.get("vpin", 0.0)
            features["ofi"] = m_data.get("ofi", 0.0)
            features["kyles_lambda"] = m_data.get("kyles_lambda", 0.0)
            # regime = 1 (Expansion), 0 (Compression)
            features["regime"] = 1 if m_data.get("regime") == "Expansion" else 0
        else:
            features["vpin"] = 0.0
            features["ofi"] = 0.0
            features["kyles_lambda"] = 0.0
            features["regime"] = 0

        return pd.DataFrame([features])

    def _empty_feature_frame(self, timestamp: datetime, symbol: str) -> pd.DataFrame:
        """Provides a zeroed-out frame to prevent pipeline crashes on insufficient data."""
        return pd.DataFrame([{
            "timestamp": timestamp,
            "symbol": symbol,
            "price": 0.0,
            "zone_overlap_count": 0,
            "rvol": 1.0,
            "vol_compression": 0.0,
            "vpin": 0.0,
            "ofi": 0.0,
            "kyles_lambda": 0.0,
            "regime": 0
        }])

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
            "snapback_state": -1, 
            "snapback_direction": 0, 
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
            transformation_steps=({"step1": "Extract structural zones", "step2": "Vol-normalization"}),
            source_features=("ohlcv",),
            created_at=datetime.now(timezone.utc)
        )
        self.store.store_feature(feature_name, feature_df, metadata, lineage)
