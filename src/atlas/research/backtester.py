"""Scientific Backtesting and Strategy Validation Suite for ATLAS.

Implements a walk-forward, event-aware backtester to evaluate the 
Price Action Framework and Snapback Entry strategy.

Strictly prevents lookahead bias by using a sliding window for 
zone detection and setup confirmation.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

from atlas.features.zones import ZoneEngine, ZoneType
from atlas.strategies.snapback import SnapbackDetector, SnapbackState
from atlas.strategies.coordinator import OpportunityCoordinator
from atlas.models.strategy_classifier import StrategyClassifier
from atlas.features.pa_integration import PriceActionFeatureExtractor


@dataclass
class TradeOutcome:
    """The result of a specific strategy setup."""
    setup_id: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    exit_time: datetime
    outcome: Literal["win", "loss", "expired"]
    pnl_bps: float
    duration_sec: float


class StrategyBacktester:
    """
    Event-driven backtester for validating Price Action strategies.
    
    Processes historical bars chronologically and simulates the 
    exact state transitions of the Snapback detector.
    """

    def __init__(self, classifier: StrategyClassifier, extractor: PriceActionFeatureExtractor):
        self.classifier = classifier
        self.extractor = extractor

    def run_backtest(
        self, 
        symbol: str, 
        df: pd.DataFrame, 
        session_starts: List[datetime],
        reward_risk_ratio: float = 1.5
    ) -> List[TradeOutcome]:
        """
        Simulates the strategy over a historical dataset.
        """
        zone_engine = ZoneEngine(symbol)
        detector = SnapbackDetector(symbol)
        outcomes = []
        
        # We iterate through the data in windows to simulate real-time arrival
        # and prevent lookahead bias.
        for i in range(20, len(df)):
            window = df.iloc[:i+1]
            current_ts = window['timestamp'].iloc[-1]
            
            # Determine if we are at a session start
            current_session_start = next(
                (s for s in session_starts if s <= current_ts < s + pd.Timedelta(hours=24)), 
                None
            )
            
            # 1. Update Zones
            active_zones = zone_engine.update_zones(window, session_start=current_session_start)
            
            # 2. Update Snapback State
            opening_box = active_zones.get(ZoneType.OPENING)
            setup = detector.process_bars(window, opening_box)
            
            if setup and setup.state == SnapbackState.QUALIFIED:
                # We have a qualified setup! Now simulate the trade.
                # For backtesting, we use the close of the confirmation candle as entry.
                entry_price = window['close'].iloc[-1]
                
                # Calculate Stop and Target based on specifications
                box_height = opening_box.boundary.height
                if setup.direction == "long":
                    stop_loss = entry_price - (2 * box_height)
                    take_profit = entry_price + (reward_risk_ratio * (entry_price - stop_loss))
                else:
                    stop_loss = entry_price + (2 * box_height)
                    take_profit = entry_price - (reward_risk_ratio * (stop_loss - entry_price))
                
                # Simulate the trade until hit SL, TP, or end of data
                outcome = self._simulate_trade(df.iloc[i+1:], entry_price, stop_loss, take_profit, current_ts)
                if outcome:
                    outcomes.append(outcome)
                
                # Reset detector for the next possible setup in this session
                detector.reset()

        return outcomes

    def _simulate_trade(
        self, 
        remaining_df: pd.DataFrame, 
        entry: float, 
        stop: float, 
        target: float, 
        start_time: datetime
    ) -> TradeOutcome | None:
        """Simulates a trade until a boundary is hit."""
        if remaining_df.empty:
            return None
            
        for idx, row in remaining_df.iterrows():
            high = row['high']
            low = row['low']
            ts = row['timestamp']
            
            # Check for exit conditions
            # We assume the more conservative order: if both hit in one candle, it's a loss.
            is_long = target > entry
            
            if is_long:
                if low <= stop:
                    return self._create_outcome(stop, ts, "loss", entry, stop, target, start_time)
                if high >= target:
                    return self._create_outcome(target, ts, "win", entry, stop, target, start_time)
            else:
                if high >= stop:
                    return self._create_outcome(stop, ts, "loss", entry, stop, target, start_time)
                if low <= target:
                    return self._create_outcome(target, ts, "win", entry, stop, target, start_time)
        
        return None # Expired

    def _create_outcome(self, price, ts, status, entry, stop, target, start) -> TradeOutcome:
        pnl = (price - entry) / entry if target > entry else (entry - price) / entry
        return TradeOutcome(
            setup_id="backtest_setup",
            symbol="BACKTEST",
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            exit_price=price,
            exit_time=ts,
            outcome=status,
            pnl_bps=pnl * 10_000,
            duration_sec=(ts - start).total_seconds()
        )

    def evaluate_performance(self, outcomes: List[TradeOutcome]) -> Dict[str, Any]:
        """Computes scientific metrics for the strategy."""
        if not outcomes:
            return {"error": "No trades executed"}
            
        wins = [o for o in outcomes if o.outcome == "win"]
        losses = [o for o in outcomes if o.outcome == "loss"]
        
        win_rate = len(wins) / len(outcomes)
        avg_win = np.mean([o.pnl_bps for o in wins]) if wins else 0
        avg_loss = abs(np.mean([o.pnl_bps for o in losses])) if losses else 0
        profit_factor = (len(wins) * avg_win) / (len(losses) * avg_loss) if losses else float('inf')
        
        return {
            "total_trades": len(outcomes),
            "win_rate": win_rate,
            "avg_win_bps": avg_win,
            "avg_loss_bps": avg_loss,
            "profit_factor": profit_factor,
            "expectancy_bps": (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        }
