"""Opportunity Ledger for ATLAS.

Records every qualifying strategy setup, including those not traded, 
to provide a gold-standard dataset for ML training and strategy auditing.

Distinguishes between:
- Prediction Performance: How well the model forecast the outcome.
- Execution Performance: How well the actual trade performed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional
import pandas as pd
import sqlite3
import json

from atlas.models.schemas import Record, Text
from atlas.strategies.coordinator import RankedOpportunity
from atlas.models.strategy_classifier import StrategyPrediction


@dataclass
class SetupRecord(Record):
    """A complete record of a detected setup and its eventual outcome."""
    setup_id: Text
    symbol: Text
    strategy_name: Text
    detected_at: datetime
    
    # Prediction state
    predicted_prob: float
    expected_value: float
    recommended_action: str
    
    # Execution state
    was_traded: bool
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    # Outcome state
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    outcome: Optional[Literal["win", "loss", "expired", "not_traded"]] = "not_traded"
    pnl_bps: float = 0.0
    
    execution_permission: Literal["none"] = "none"


class OpportunityLedger:
    """
    Persistent store for all strategy opportunities.
    
    Used for 'Challenger' model training by providing a history of 
    what happened after every structural signal.
    """

    def __init__(self, db_path: str = "var/opportunity_ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS setups (
                    setup_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    strategy_name TEXT,
                    detected_at TIMESTAMP,
                    predicted_prob REAL,
                    expected_value REAL,
                    recommended_action TEXT,
                    was_traded INTEGER,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    exit_price REAL,
                    exit_time TIMESTAMP,
                    outcome TEXT,
                    pnl_bps REAL,
                    metadata TEXT
                )
            """)

    def record_setup(
        self, 
        opportunity: RankedOpportunity, 
        prediction: StrategyPrediction, 
        trade_params: dict[str, any] | None = None
    ) -> None:
        """Logs a newly detected opportunity."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO setups 
                (setup_id, symbol, strategy_name, detected_at, predicted_prob, 
                 expected_value, recommended_action, was_traded, entry_price, 
                 stop_loss, take_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opportunity.opportunity_id,
                opportunity.symbol,
                opportunity.strategy_name,
                opportunity.evaluated_at,
                prediction.probability_of_success,
                prediction.expected_value,
                prediction.recommended_action,
                1 if trade_params else 0,
                trade_params.get("entry") if trade_params else None,
                trade_params.get("stop") if trade_params else None,
                trade_params.get("target") if trade_params else None,
            ))

    def update_outcome(
        self, 
        setup_id: str, 
        exit_price: float, 
        exit_time: datetime, 
        outcome: Literal["win", "loss", "expired"]
    ) -> None:
        """Updates a record with the final trade outcome."""
        with sqlite3.connect(self.db_path) as conn:
            # Calculate PnL relative to the stored entry
            row = conn.execute("SELECT entry_price, stop_loss FROM setups WHERE setup_id = ?", (setup_id,)).fetchone()
            if not row:
                return
            
            entry = row[0]
            stop = row[1]
            # Simplified PnL for ledger
            pnl = ((exit_price - entry) / entry) * 10_000 if exit_price > entry else ((entry - exit_price) / entry) * 10_000
            
            conn.execute("""
                UPDATE setups 
                SET exit_price = ?, exit_time = ?, outcome = ?, pnl_bps = ?
                WHERE setup_id = ?
            """, (exit_price, exit_time, outcome, pnl, setup_id))

    def get_training_set(self) -> pd.DataFrame:
        """Retrieves all closed setups for ML retraining."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("SELECT * FROM setups WHERE outcome IS NOT NULL", conn)
