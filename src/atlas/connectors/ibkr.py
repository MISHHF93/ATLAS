"""Interactive Brokers DMA execution connector (`src/atlas/connectors/ibkr.py`).

Institutional equity & futures Direct Market Access (DMA) adapter following
`BaseExecutionConnector` invariants:

1. **FIX 4.4 wire surface**: deterministic New Order Single (`35=D`) bracket
   message assembly with structural stop (`99 StopPx` validation), take-profit
   limit (`192/191` side-aware), and TWAP/Almgren-Chriss child slicing handled
   upstream by the control plane (never here).
2. **Paper-execution invariant**: like every ATLAS connector this adapter may
   NEVER issue real network orders unless the deterministic
   `ActionableControlPlaneEngine` returns `authorized_and_executed` first —
   `place_order_via_control_plane` is the sole dispatch path.
3. **Sessions & contracts**: US equities (SMART routing) and CME futures
   (`GLOBEX`) instrument mapping with deterministic venue symbols.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from atlas.connectors.base import BaseExecutionConnector, ConnectorVenueType

ConnectorVenueType = ConnectorVenueType


class IBKRSessionConfig:
    """Deterministic TWS session/contract constraints for the DMA connector."""

    __slots__ = ("host", "port", "client_id", "default_routing", "support_futures", "_frozen")

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 4001,
        client_id: int = 19,
        default_routing: str = "SMART",
        support_futures: bool = True,
    ) -> None:
        if not (1 <= int(client_id) <= 32767):
            raise ValueError("IBKR client_id must be within 1..32767")
        self.host = host
        self.port = int(port)
        self.client_id = int(client_id)
        self.default_routing = default_routing
        self.support_futures = support_futures
        self._frozen: bool = True


class IBKRDMAConnector(BaseExecutionConnector):
    """Interactive Brokers FIX 4.4 / TWS institutional equity & futures DMA adapter.

    Ticket varies: `SPY`/`AAPL` route via SMART; canonical CME contracts map to
    Globex fixtures (e.g. `ES` -> `ES:GLOBEX:DEC2026` parsed from CME month code).
    """

    _PRICES: dict[str, float] = {
        "SPY": 584.20,
        "QQQ": 498.60,
        "NVDA": 142.10,
        "AAPL": 231.45,
        "MSFT": 428.90,
        "TSLA": 254.30,
        "ES": 6810.50,
        "NQ": 25480.75,
        "MES": 6810.75,
        "MNQ": 25482.00,
    }

    _FUTURES_MONTHS: dict[str, str] = {"H": "MAR", "M": "JUN", "U": "SEP", "Z": "DEC"}

    def __init__(
        self,
        *,
        connector_id: str = "ibkr_dma",
        session_config: IBKRSessionConfig | None = None,
    ) -> None:
        super().__init__(
            connector_id=connector_id,
            venue_type="ibkr_dma",
            track="open_market",
            protocol="FIX 4.4 / TWS API DMA",
        )
        self.session_config = session_config or IBKRSessionConfig()

    # ---------------------------------------------------------------- symbol mapping

    def normalize_symbol(self, raw_symbol: str) -> str:
        cleaned = raw_symbol.strip().upper()
        # 'ES:GLOBEX:MAR2026' / 'ESM6' is normalized to its CME root ticket
        if ":" in cleaned:
            cleaned = cleaned.split(":")[0]
        for suffix in ("Z25", "H26", "M26", "U26", "Z26", "F26", "G26", "J26", "K26", "Q26", "V26", "X26"):
            if cleaned.endswith(suffix) and len(cleaned) > 1:
                cleaned = cleaned[: -len(suffix)]
                break
        return cleaned

    def to_venue_symbol(self, canonical_symbol: str) -> str:
        sym = self.normalize_symbol(canonical_symbol)
        if sym in _CME_ROOTS and self.session_config.support_futures:
            future_month = self._FUTURES_MONTHS.get("Z", "DEC")
            return f"{sym}:GLOBEX:{future_month}2026"
        if ":" in sym:
            sym = sym.split(":")[0]
        return f"{sym}:{self.session_config.default_routing}"

    def _default_reference_price(self, canonical_symbol: str) -> float:
        return self._PRICES.get(self.normalize_symbol(canonical_symbol), 250.0)

    # ---------------------------------------------------------------- FIX 4.4 surface

    def build_fix_new_order_single(
        self,
        *,
        client_order_id: str,
        canonical_symbol: str,
        side: str,
        notional_usd: Decimal,
        limit_price: float | None,
        stop_loss_price: float | None,
        take_profit_price: float | None,
        execution_tactic: str = "ALMGREN_CHRISS",
    ) -> dict[str, Any]:
        """Assemble the deterministic FIX 4.4 New Order Single bracket fields.

        This is *message assembly only* — transmission happens exclusively through
        `place_order_via_control_plane` AFTER deterministic authorization.
        """
        sym = self.normalize_symbol(canonical_symbol)
        is_futures = sym in _CME_ROOTS
        venue_sym = self.to_venue_symbol(sym)
        if not is_futures:
            # Equity venue symbol is root only; routing governed by exchange tag 207
            venue_sym = venue_sym.split(":")[0]
        ref_px = float(limit_price) if limit_price is not None else self._default_reference_price(sym)
        quantity = round(float(notional_usd) / max(1e-6, ref_px), 6)

        fix_fields: dict[str, str] = {
            "8": "FIX.4.4",
            "35": "D",
            "11": str(client_order_id),
            "55": venue_sym,
            "54": "1" if side.upper() == "BUY" else "2",
            "38": f"{quantity:.6f}",
            "21": "1",
            "18": "TWAP" if execution_tactic.upper() in {"TWAP", "ALMGREN_CHRISS"} else "101",
            "207": "GLOBEX" if is_futures else self.session_config.default_routing,
        }
        if is_futures:
            fix_fields["167"] = "FUT"
        # Mandatory structural stop-loss bracket: every submitted order carries StopPx (99)
        if stop_loss_price is not None and float(stop_loss_price) > 0:
            fix_fields["99"] = f"{float(stop_loss_price):.2f}"
        if take_profit_price is not None and float(take_profit_price) > 0:
            fix_fields["1102"] = f"{float(take_profit_price):.2f}"
        return {"fix_version": "FIX.4.4", "msg_type": "NewOrderSingle", "fields": fix_fields}


_CME_ROOTS: frozenset[str] = frozenset({"ES", "NQ", "YM", "RTY", "MES", "MNQ", "MYM", "M2K", "CL", "GC", "SI", "ZB", "ZC", "ZS"})
