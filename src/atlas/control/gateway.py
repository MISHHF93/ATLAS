"""Deterministic Control-Plane to Execution Connector Gateway (`src/atlas/control/gateway.py`).

Connects `ActionableControlPlaneEngine` to `BaseExecutionConnector` implementations
(`AlpacaEquitiesConnector`, `CCXTPerpConnector`, `DXtradePropConnector`) with:
1. Strict zero-LLM/zero-AI import isolation (`src/atlas/control/` invariant).
2. Pre-trade deterministic rule verification (4% daily loss, 8% trailing HWM drawdown,
   <=35% consistency, 0.50%-0.75% per-trade risk cap, mandatory ATR stop, 500ms staleness gate).
3. Automatic venue selection by track (`competition` -> `CCXTPerpConnector` / `DXtradePropConnector`,
   `open_market` -> `AlpacaEquitiesConnector`) and normalized callback auditing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from atlas.connectors.base import (
    AlpacaEquitiesConnector,
    BaseExecutionConnector,
    CCXTPerpConnector,
    DXtradePropConnector,
)
from atlas.control.engine import (
    ActionableControlPlaneEngine,
    BracketOrderIntakeReport,
)


class ControlPlaneExecutionGateway:
    """Deterministic bridge routing Control-Plane authorized bracket orders to venue connectors."""

    def __init__(
        self,
        control_engine: ActionableControlPlaneEngine | None = None,
        *,
        alpaca_connector: AlpacaEquitiesConnector | None = None,
        ccxt_connector: CCXTPerpConnector | None = None,
        dxtrade_connector: DXtradePropConnector | None = None,
    ) -> None:
        self.control_engine = control_engine or ActionableControlPlaneEngine()
        self.alpaca_connector = alpaca_connector or AlpacaEquitiesConnector()
        self.ccxt_connector = ccxt_connector or CCXTPerpConnector()
        self.dxtrade_connector = dxtrade_connector or DXtradePropConnector()

    def select_connector(
        self,
        symbol: str,
        track: Literal["competition", "open_market"] | None = None,
        *,
        prefer_dxtrade: bool = False,
    ) -> BaseExecutionConnector:
        """Select the canonical execution connector for a symbol and track."""
        sym = symbol.upper().strip()
        resolved_track = (
            track
            if track in ("competition", "open_market")
            else ("competition" if sym.endswith("-USD") or sym.endswith("USDT") else "open_market")
        )
        if resolved_track == "open_market":
            return self.alpaca_connector
        return self.dxtrade_connector if prefer_dxtrade else self.ccxt_connector

    def evaluate_and_dispatch_signal(
        self,
        signal: Any,
        *,
        track: Literal["competition", "open_market"] | None = None,
        risk_fraction_target: Decimal = Decimal("0.0060"),
        desired_notional_usd: Decimal | None = None,
        data_age_ms: float = 8.4,
        prefer_dxtrade: bool = False,
        now: datetime | None = None,
    ) -> BracketOrderIntakeReport:
        """Evaluate an air-gapped `StrategySignal` through `ActionableControlPlaneEngine`
        and route to the appropriate `BaseExecutionConnector` if and only if authorized.
        """
        sig_dict = signal.model_dump() if hasattr(signal, "model_dump") else dict(signal)
        sym = str(sig_dict.get("symbol", "BTC-USD")).upper().strip()
        connector = self.select_connector(sym, track, prefer_dxtrade=prefer_dxtrade)
        return self.control_engine.ingest_whale_policy_signal(
            signal,
            track=track,
            risk_fraction_target=risk_fraction_target,
            desired_notional_usd=desired_notional_usd,
            data_age_ms=data_age_ms,
            execution_connector=connector,
            now=now or datetime.now(timezone.utc),
        )

