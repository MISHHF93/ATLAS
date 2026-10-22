"""cTrader institutional prop-challenge bridge connector (`src/atlas/connectors/ctrader.py`).

Implements the cTrader Open API-style bridging surface used by institutional prop
challenge desks following `BaseExecutionConnector` invariants:

1. Symbol normalization between the cTrader wire convention (`BTCUSD.PURE`)
   and canonical ATLAS symbols (`BTC-USD`).
2. Bracket order envelope construction (stop-loss / take-profit in ticks) for
   the mandatory structural ATR bracket.
3. Deterministic paper-mode execution exclusively through
   `place_order_via_control_plane` — the deterministic control plane is the
   ONLY authority that can authorize dispatch to this venue.
"""

from __future__ import annotations

from typing import Any

from atlas.connectors.base import BaseExecutionConnector


class CTradePropAPIConnector(BaseExecutionConnector):
    """cTrader Open API prop-challenge execution bridge (`competition` track)."""

    _PRICES: dict[str, float] = {
        "BTC-USD": 68410.0,
        "ETH-USD": 2645.5,
        "SOL-USD": 176.8,
        "XAU-USD": 4030.75,
        "EUR-USD": 1.0865,
    }
    _TICK_SIZES: dict[str, float] = {
        "BTC-USD": 10.0,
        "ETH-USD": 5.0,
        "SOL-USD": 1.0,
        "XAU-USD": 0.1,
        "EUR-USD": 0.0001,
    }

    def __init__(
        self,
        *,
        connector_id: str = "ctrader_prop_bridge",
        challenge_program_id: str = "ATLAS-PROP-100K-CT",
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            venue_type="ctrader_prop",
            track="competition",
            protocol="cTrader Open API / REST",
        )
        self.challenge_program_id = challenge_program_id

    def normalize_symbol(self, raw_symbol: str) -> str:
        cleaned = raw_symbol.strip().upper().replace("CT:", "")
        if cleaned.endswith(".PURE"):
            cleaned = cleaned[: -len(".PURE")]
        # 'BTCUSD' / 'ETHUSD' style wire symbols -> canonical 'BTC-USD'
        if cleaned in {"BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "EURUSD"}:
            base = cleaned[:-3]
            return f"{base}-USD"
        if cleaned.endswith("-USD"):
            return cleaned
        if "-" in cleaned:
            return cleaned
        return f"{cleaned}-USD"

    def to_venue_symbol(self, canonical_symbol: str) -> str:
        norm = self.normalize_symbol(canonical_symbol)
        return f"CT:{norm.replace('-', '')}.PURE"

    def _default_reference_price(self, canonical_symbol: str) -> float:
        return self._PRICES.get(self.normalize_symbol(canonical_symbol), 100.0)

    def tick_size(self, canonical_symbol: str) -> float:
        """Deterministic cTrader tick size used to express bracket distances in ticks."""
        return self._TICK_SIZES.get(self.normalize_symbol(canonical_symbol), 0.01)

    def build_bracket_envelope(
        self,
        *,
        client_order_id: str,
        canonical_symbol: str,
        side: str,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        quantity: float,
    ) -> dict[str, Any]:
        """Deterministic cTrader-style bracket order payload (message assembly only).

        Dispatch remains gated behind `place_order_via_control_plane`; this builder
        never contacts the venue and holds no credentials.
        """
        sym = self.normalize_symbol(canonical_symbol)
        tick = self.tick_size(sym)
        if tick <= 0:
            raise ValueError("tick_size must be positive")
        sl_ticks = abs(entry_price - float(stop_loss_price)) / tick
        tp_ticks = abs(float(take_profit_price) - entry_price) / tick
        if sl_ticks <= 0:
            raise ValueError("Structural stop-loss must be a non-zero distance from entry")
        return {
            "client_order_id": client_order_id,
            "symbol_name": self.to_venue_symbol(sym),
            "trade_side": "BUY" if side.upper() == "BUY" else "SELL",
            "order_type": "MARKET_WITH_SL_AND_TP",
            "quantity": round(float(quantity), 6),
            "stop_loss_ticks": round(sl_ticks, 1),
            "take_profit_ticks": round(tp_ticks, 1),
            "relative_stop_loss": True,
            "challenge_program_id": self.challenge_program_id,
            "execution_permission": "none",
        }
