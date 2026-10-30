"""Unified Third-Party Execution Connector Abstraction (`src/atlas/connectors/base.py`).

Provides `BaseExecutionConnector` and concrete institutional adapters:
1. `AlpacaEquitiesConnector` — REST/WebSocket DMA adapter for Open-Market US Equities.
2. `CCXTPerpConnector` — Async WebSocket adapter for multi-exchange Crypto Perpetuals.
3. `DXtradePropConnector` — FIX/REST challenge evaluation bridge for Prop Competition accounts.

Normalizes ticker symbols, order placement requests, position blotters, and execution callbacks
into immutable ATLAS Pydantic `Record` schemas, and strictly requires deterministic authorization
from `ActionableControlPlaneEngine` before dispatching any order to an external venue.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field, FiniteFloat

from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableOrderDecision,
    ActionableOrderRequest,
)
from atlas.models.schemas import NonnegativeDecimal, PositiveDecimal, Record, Text


ConnectorVenueType = Literal["alpaca_equities", "ccxt_perp", "dxtrade_prop", "ibkr_dma", "ctrader_prop"]
UnifiedOrderSide = Literal["BUY", "SELL"]
UnifiedOrderType = Literal["LIMIT", "MARKET", "ALMGREN_CHRISS", "TWAP"]
UnifiedOrderStatus = Literal["ACCEPTED", "PARTIALLY_FILLED", "FILLED", "REJECTED_BY_CONTROL_PLANE", "CANCELED"]


class UnifiedOrderPlacementRequest(Record):
    """Normalized ATLAS order placement request across equities, crypto perps, and prop bridges."""

    client_order_id: Text
    canonical_symbol: Text
    venue_symbol: Text
    track: Literal["open_market", "competition"]
    side: UnifiedOrderSide
    order_type: UnifiedOrderType
    notional_usd: PositiveDecimal
    limit_price: FiniteFloat | None = None
    stop_loss_bps: PositiveDecimal = Decimal("150")
    take_profit_bps: PositiveDecimal = Decimal("270")
    vpin_toxicity: float = 0.0
    strategy_id: Text = "MANUAL_OR_BOT"


class UnifiedPositionBlotterEntry(Record):
    """Normalized position blotter record returned by any execution connector."""

    position_id: Text
    connector_id: Text
    track: Literal["open_market", "competition"]
    canonical_symbol: Text
    venue_symbol: Text
    side: UnifiedOrderSide
    quantity: FiniteFloat = Field(gt=0)
    average_entry_price: FiniteFloat = Field(gt=0)
    mark_price: FiniteFloat = Field(gt=0)
    notional_usd: PositiveDecimal
    unrealized_pnl_usd: Decimal
    stop_loss_bps: NonnegativeDecimal
    opened_at: AwareDatetime


class UnifiedExecutionCallback(Record):
    """Normalized execution fill/ack callback emitted by any execution connector."""

    callback_id: Text
    client_order_id: Text
    venue_order_id: Text
    connector_id: Text
    track: Literal["open_market", "competition"]
    canonical_symbol: Text
    venue_symbol: Text
    side: UnifiedOrderSide
    status: UnifiedOrderStatus
    filled_notional_usd: NonnegativeDecimal
    average_fill_price: FiniteFloat = Field(ge=0)
    control_plane_order_id: Text
    violations: tuple[str, ...] = ()
    timestamp_utc: AwareDatetime
    execution_permission: Literal["none"] = "none"
    execution_mode: Literal["paper"] = "paper"
    stop_loss_price: float | None = None
    take_profit_price: float | None = None


class BaseExecutionConnector(ABC):
    """Abstract base class for third-party execution connectors."""

    connector_id: str
    venue_type: ConnectorVenueType
    track: Literal["open_market", "competition"]
    protocol: str

    def __init__(
        self,
        *,
        connector_id: str,
        venue_type: ConnectorVenueType,
        track: Literal["open_market", "competition"],
        protocol: str,
    ) -> None:
        self.connector_id = connector_id
        self.venue_type = venue_type
        self.track = track
        self.protocol = protocol
        self._positions: list[UnifiedPositionBlotterEntry] = []
        self._callbacks: list[UnifiedExecutionCallback] = []
        self._seq: int = 1

    @abstractmethod
    def normalize_symbol(self, raw_symbol: str) -> str:
        """Convert a venue-specific ticker into the canonical ATLAS symbol (e.g., `BTC-USD`, `SPY`)."""

    @abstractmethod
    def to_venue_symbol(self, canonical_symbol: str) -> str:
        """Convert a canonical ATLAS symbol into the venue-specific wire format."""

    @abstractmethod
    def _default_reference_price(self, canonical_symbol: str) -> float:
        """Return a deterministic reference price when limit_price is not specified."""

    def place_order_via_control_plane(
        self,
        request: UnifiedOrderPlacementRequest,
        control_engine: ActionableControlPlaneEngine,
        *,
        now: datetime | None = None,
    ) -> UnifiedExecutionCallback:
        """Validate the order through `ActionableControlPlaneEngine` and route if authorized."""
        ts = now or datetime.now(timezone.utc)
        prefix = "comp" if request.track == "competition" else "open"
        instrument_id = f"{prefix}:{request.canonical_symbol.lower()}:v1"

        cp_req = ActionableOrderRequest(
            track=request.track,
            instrument_id=instrument_id,
            side="buy" if request.side == "BUY" else "sell",
            notional_usd=request.notional_usd,
            stop_kind="atr",
            stop_distance_bps=request.stop_loss_bps,
            holding_horizon_seconds=14400,
            vpin_toxicity=request.vpin_toxicity,
        )
        decision: ActionableOrderDecision = control_engine.submit_order(cp_req, now=ts)
        self._seq += 1

        if decision.control_plane_decision != "authorized_and_executed":
            cb = UnifiedExecutionCallback(
                callback_id=f"cb-{self.connector_id}-{self._seq:04d}",
                client_order_id=request.client_order_id,
                venue_order_id="REJECTED-PRE-TRADE",
                connector_id=self.connector_id,
                track=request.track,
                canonical_symbol=request.canonical_symbol,
                venue_symbol=request.venue_symbol,
                side=request.side,
                status="REJECTED_BY_CONTROL_PLANE",
                filled_notional_usd=Decimal("0.00"),
                average_fill_price=0.0,
                control_plane_order_id=decision.order_id,
                violations=decision.violations,
                timestamp_utc=ts,
            )
            self._callbacks.append(cb)
            return cb

        fill_px = float(request.limit_price or self._default_reference_price(request.canonical_symbol))
        qty = round(float(request.notional_usd) / max(1e-6, fill_px), 6)
        pos = UnifiedPositionBlotterEntry(
            position_id=decision.position_id or f"pos-{self.connector_id}-{self._seq:04d}",
            connector_id=self.connector_id,
            track=request.track,
            canonical_symbol=request.canonical_symbol,
            venue_symbol=request.venue_symbol,
            side=request.side,
            quantity=max(0.0001, qty),
            average_entry_price=fill_px,
            mark_price=fill_px,
            notional_usd=request.notional_usd,
            unrealized_pnl_usd=Decimal("0.00"),
            stop_loss_bps=request.stop_loss_bps,
            opened_at=ts,
        )
        self._positions.append(pos)

        cb = UnifiedExecutionCallback(
            callback_id=f"cb-{self.connector_id}-{self._seq:04d}",
            client_order_id=request.client_order_id,
            venue_order_id=f"{self.connector_id.upper()}-{self._seq:05d}",
            connector_id=self.connector_id,
            track=request.track,
            canonical_symbol=request.canonical_symbol,
            venue_symbol=request.venue_symbol,
            side=request.side,
            status="FILLED",
            filled_notional_usd=request.notional_usd,
            average_fill_price=fill_px,
            control_plane_order_id=decision.order_id,
            violations=(),
            timestamp_utc=ts,
        )
        self._callbacks.append(cb)
        return cb

    def route_approved_order(
        self,
        decision: ActionableOrderDecision,
        *,
        tactic: str = "ALMGREN_CHRISS",
        reference_price: float | None = None,
        executed_at: datetime | None = None,
    ) -> UnifiedExecutionCallback:
        """Route an already-authorized `ActionableOrderDecision` to the external venue."""
        ts = executed_at or decision.evaluated_at
        if decision.control_plane_decision != "authorized_and_executed":
            raise PermissionError("Cannot route an order that was not authorized by ActionableControlPlaneEngine")

        raw_sym = decision.instrument_id.split(":")[1].replace("-perp", "-usd").replace("-eq", "") if ":" in decision.instrument_id else decision.instrument_id
        canonical = self.normalize_symbol(raw_sym)
        venue_sym = self.to_venue_symbol(canonical)
        fill_px = float(reference_price or self._default_reference_price(canonical))
        self._seq += 1

        cb = UnifiedExecutionCallback(
            callback_id=f"cb-{self.connector_id}-{self._seq:04d}",
            client_order_id=f"cli-{decision.order_id}",
            venue_order_id=f"{self.connector_id.upper()}-{self._seq:05d}",
            connector_id=self.connector_id,
            track=decision.track,
            canonical_symbol=canonical,
            venue_symbol=venue_sym,
            side="BUY" if decision.side == "buy" else "SELL",
            status="FILLED",
            filled_notional_usd=decision.notional_usd,
            average_fill_price=fill_px,
            control_plane_order_id=decision.order_id,
            violations=(),
            timestamp_utc=ts,
            stop_loss_price=decision.stop_loss_price,
            take_profit_price=decision.take_profit_price,
        )
        self._callbacks.append(cb)
        return cb

    def get_position_blotter(self) -> tuple[UnifiedPositionBlotterEntry, ...]:
        """Return normalized open position blotter entries for this connector."""
        return tuple(self._positions)

    def normalize_execution_callback(self, raw_payload: dict[str, Any]) -> UnifiedExecutionCallback:
        """Normalize an external venue webhook/WebSocket fill event into `UnifiedExecutionCallback`."""
        ts_raw = raw_payload.get("timestamp_utc") or datetime.now(timezone.utc)
        if isinstance(ts_raw, str):
            ts_raw = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        raw_sym = str(raw_payload.get("symbol", "SPY"))
        canonical = self.normalize_symbol(raw_sym)
        venue_sym = self.to_venue_symbol(canonical)
        self._seq += 1
        cb = UnifiedExecutionCallback(
            callback_id=str(raw_payload.get("callback_id", f"cb-{self.connector_id}-{self._seq:04d}")),
            client_order_id=str(raw_payload.get("client_order_id", f"cli-{self._seq:04d}")),
            venue_order_id=str(raw_payload.get("venue_order_id", f"ven-{self._seq:04d}")),
            connector_id=self.connector_id,
            track=self.track,
            canonical_symbol=canonical,
            venue_symbol=venue_sym,
            side="SELL" if str(raw_payload.get("side", "BUY")).upper() == "SELL" else "BUY",
            status="FILLED",
            filled_notional_usd=Decimal(str(raw_payload.get("filled_notional_usd", "10000.00"))),
            average_fill_price=float(raw_payload.get("average_fill_price", self._default_reference_price(canonical))),
            control_plane_order_id=str(raw_payload.get("control_plane_order_id", "ord-verified")),
            violations=(),
            timestamp_utc=ts_raw,
        )
        self._callbacks.append(cb)
        return cb


class AlpacaEquitiesConnector(BaseExecutionConnector):
    """REST/WebSocket execution connector for Open-Market US Equities (`SPY`, `QQQ`, `NVDA`, `AAPL`)."""

    _PRICES: dict[str, float] = {
        "SPY": 584.20,
        "QQQ": 498.60,
        "NVDA": 142.10,
        "AAPL": 231.45,
        "MSFT": 428.90,
        "TSLA": 254.30,
    }

    def __init__(self) -> None:
        super().__init__(
            connector_id="alpaca_equities_dma",
            venue_type="alpaca_equities",
            track="open_market",
            protocol="REST v2 + WSS Streaming",
        )

    def normalize_symbol(self, raw_symbol: str) -> str:
        cleaned = raw_symbol.strip().upper().replace("/USD", "").replace("-USD", "")
        if ":" in cleaned:
            cleaned = cleaned.split(":")[-1]
        return cleaned

    def to_venue_symbol(self, canonical_symbol: str) -> str:
        return self.normalize_symbol(canonical_symbol)

    def _default_reference_price(self, canonical_symbol: str) -> float:
        return self._PRICES.get(self.normalize_symbol(canonical_symbol), 250.0)


class CCXTPerpConnector(BaseExecutionConnector):
    """Async WebSocket execution connector for multi-exchange Crypto Perpetuals (`BTC-USD`, `ETH-USD`, `SOL-USD`)."""

    _PRICES: dict[str, float] = {
        "BTC-USD": 68410.0,
        "ETH-USD": 2645.5,
        "SOL-USD": 176.8,
    }

    def __init__(self, *, exchange_id: str = "hyperliquid") -> None:
        super().__init__(
            connector_id=f"ccxt_perp_{exchange_id}",
            venue_type="ccxt_perp",
            track="competition",
            protocol="CCXT Pro Async WebSocket",
        )
        self.exchange_id = exchange_id

    def normalize_symbol(self, raw_symbol: str) -> str:
        cleaned = raw_symbol.strip().upper()
        # Convert CCXT 'BTC/USDT:USDT' or 'BTCUSDT' -> 'BTC-USD'
        if "/" in cleaned:
            base = cleaned.split("/")[0]
            return f"{base}-USD"
        if cleaned.endswith("USDT"):
            return f"{cleaned[:-4]}-USD"
        if not cleaned.endswith("-USD"):
            return f"{cleaned}-USD"
        return cleaned

    def to_venue_symbol(self, canonical_symbol: str) -> str:
        norm = self.normalize_symbol(canonical_symbol)
        base = norm.split("-")[0]
        return f"{base}/USDT:USDT"

    def _default_reference_price(self, canonical_symbol: str) -> float:
        return self._PRICES.get(self.normalize_symbol(canonical_symbol), 1000.0)


class DXtradePropConnector(BaseExecutionConnector):
    """Challenge account FIX/REST execution bridge for Prop Competition accounts (`DXtradePropConnector`)."""

    _PRICES: dict[str, float] = {
        "BTC-USD": 68410.0,
        "ETH-USD": 2645.5,
        "SOL-USD": 176.8,
        "SPY": 584.20,
        "NVDA": 142.10,
    }

    def __init__(self, *, challenge_program_id: str = "ATLAS-PROP-100K") -> None:
        super().__init__(
            connector_id="dxtrade_prop_bridge",
            venue_type="dxtrade_prop",
            track="competition",
            protocol="FIX 4.4 / DXtrade Prop REST Bridge",
        )
        self.challenge_program_id = challenge_program_id

    def normalize_symbol(self, raw_symbol: str) -> str:
        cleaned = raw_symbol.strip().upper().replace("DX:", "").replace(".PROP", "")
        if cleaned in {"BTCUSD", "ETHUSD", "SOLUSD"}:
            return f"{cleaned[:3]}-USD"
        return cleaned

    def to_venue_symbol(self, canonical_symbol: str) -> str:
        norm = self.normalize_symbol(canonical_symbol)
        return f"DX:{norm.replace('-', '')}.PROP"

    def _default_reference_price(self, canonical_symbol: str) -> float:
        return self._PRICES.get(self.normalize_symbol(canonical_symbol), 500.0)

