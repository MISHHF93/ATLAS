"""Internal read-only MCP server for ATLAS.

Exposes a bounded, explicitly-declared tool surface to connected AI models:

- ``market.point_in_time_candles``: causal OHLCV batches with `available_at <= as_of`.
- ``market.microstructure_metrics``: VPIN / OFI / Kyle's Lambda / Hawkes / ATR telemetry.
- ``prop.account_health``: prop-firm rulebook health (remaining-room HUD, kill switch).

Every tool result envelope carries ``metadata={"execution_permission": "none"}``:
this server is a *strictly read-only research surface*. It cannot place, cancel,
or size orders; it never holds broker credentials; and it never writes state.
Data providers are injected as callables so the deterministic control plane
(`atlas.control`) remains import-free from AI/ML surfaces and vice versa.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

AIRGAP_PERMISSION: Literal["none"] = "none"

NamedData = dict[str, Any]


class InjectorContractViolation(ValueError):
    """A injected provider returned malformed/non-serializable data."""


class ToolCallRejectedError(PermissionError):
    """Tool invocation rejected by the read-only MCP tool registry."""


class ReadonlyMCPTool:
    """Declaration of one read-only internal MCP tool."""

    __slots__ = ("name", "description", "input_schema")

    def __init__(self, name: str, description: str, input_schema: dict[str, str]) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def to_handle(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "execution_permission": AIRGAP_PERMISSION,
        }


class MCPServerStatus:
    """Frozen operational status snapshot of the internal MCP server."""

    def __init__(
        self,
        *,
        server_id: str,
        healthy: bool,
        tools_registered: int,
        invocations_served: int,
        invocations_rejected: int,
        as_of: str,
    ) -> None:
        self.server_id = server_id
        self.healthy = healthy
        self.tools_registered = tools_registered
        self.invocations_served = invocations_served
        self.invocations_rejected = invocations_rejected
        self.as_of = as_of

    def to_payload(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "healthy": self.healthy,
            "tools_registered": self.tools_registered,
            "invocations_served": self.invocations_served,
            "invocations_rejected": self.invocations_rejected,
            "execution_permission": AIRGAP_PERMISSION,
            "as_of": self.as_of,
        }


class AtlasReadonlyMCPServer:
    """Internal read-only MCP tool server (`execution_permission: none` by construction).

    Data providers are injected at construction time; the server never imports
    broker clients, never references the control plane's execution directory, and
    never mutates balances, risk limits, or orders.
    """

    SERVER_ID = "atlas_internal_readonly_mcp:v1"

    def __init__(
        self,
        *,
        provide_point_in_time_candles: Callable[[str, int], list[dict[str, Any]]],
        provide_microstructure_metrics: Callable[[str], dict[str, Any]],
        provide_prop_account_health: Callable[[str | None], dict[str, Any]],
    ) -> None:
        self._provide_point_in_time_candles = provide_point_in_time_candles
        self._provide_microstructure_metrics = provide_microstructure_metrics
        self._provide_prop_account_health = provide_prop_account_health

        self.tools: dict[str, ReadonlyMCPTool] = {t.name: t for t in (
            ReadonlyMCPTool(
                name="market.point_in_time_candles",
                description=(
                    "Causal point-in-time OHLCV candle batch for one symbol: strictly available_at <= as_of, "
                    "never a live mutable order surface."
                ),
                input_schema={"symbol": "string", "max_bars": "integer (<= 500)"},
            ),
            ReadonlyMCPTool(
                name="market.microstructure_metrics",
                description=(
                    "Latest microstructure telemetry (VPIN, OFI, Kyle's Lambda, Hawkes, canonical ATR, spread) "
                    "for one symbol; research-only."
                ),
                input_schema={"symbol": "string"},
            ),
            ReadonlyMCPTool(
                name="prop.account_health",
                description=(
                    "Prop-firm evaluation account health: remaining-room HUD meters (4% daily loss breaker, "
                    "8% trailing drawdown floor, 35% consistency gate), kill-switch state. Read-only."
                ),
                input_schema={"account_id": "string | null (default active account)"},
            ),
        )}
        self.invocations_served = 0
        self.invocations_rejected = 0

    # ------------------------------------------------------------------ tool surface

    def list_tools(self) -> tuple[dict[str, Any], ...]:
        return tuple(tool.to_handle() for tool in self.tools.values())

    def _result_envelope(self, tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
        self.invocations_served += 1
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return {
            "server_id": self.SERVER_ID,
            "tool_name": tool_name,
            "served_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": hashlib.sha256(canonical).hexdigest(),
            "data": data,
            "metadata": {"execution_permission": AIRGAP_PERMISSION},
            "execution_permission": AIRGAP_PERMISSION,
        }

    def invoke_tool(self, tool_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a read-only tool; ALL outputs carry `execution_permission: "none"`."""
        params = dict(params or {})
        tool = self.tools.get(tool_name)
        if tool is None:
            self.invocations_rejected += 1
            raise ToolCallRejectedError(
                f"Unknown tool '{tool_name}' on {self.SERVER_ID}; only the read-only registry is exposed"
            )

        if tool_name == "market.point_in_time_candles":
            symbol = str(params.get("symbol", "")).upper().strip()
            if not symbol:
                self.invocations_rejected += 1
                raise ToolCallRejectedError("symbol is required")
            max_bars = int(params.get("max_bars", 24))
            if max_bars <= 0 or max_bars > 500:
                self.invocations_rejected += 1
                raise ToolCallRejectedError("max_bars must be within 1..500")
            candles = self._provide_point_in_time_candles(symbol, max_bars)
            if not isinstance(candles, list):
                raise InjectorContractViolation("provide_point_in_time_candles must return a list")
            return self._result_envelope(
                tool_name,
                {"symbol": symbol, "candles": candles, "data_provenance": "pit_candle_batch"},
            )

        if tool_name == "market.microstructure_metrics":
            symbol = str(params.get("symbol", "")).upper().strip()
            if not symbol:
                self.invocations_rejected += 1
                raise ToolCallRejectedError("symbol is required")
            metrics = self._provide_microstructure_metrics(symbol)
            if not isinstance(metrics, dict):
                raise InjectorContractViolation("provide_microstructure_metrics must return a dict")
            return self._result_envelope(
                tool_name,
                {"symbol": symbol, "metrics": metrics, "data_provenance": "live_microstructure_telemetry"},
            )

        if tool_name == "prop.account_health":
            account_raw = params.get("account_id")
            account_id = str(account_raw).strip() if account_raw is not None else None
            health = self._provide_prop_account_health(account_id)
            if not isinstance(health, dict):
                raise InjectorContractViolation("provide_prop_account_health must return a dict")
            return self._result_envelope(
                tool_name,
                {"account_id": account_id, "health": health, "data_provenance": "prop_rulebook_evaluation"},
            )

        self.invocations_rejected += 1
        raise ToolCallRejectedError(f"Tool '{tool_name}' is registered but has no executor bound")

    def health_check(self) -> dict[str, Any]:
        """Report the read-only server status: injectors are required to be bound."""
        injectors_bound = all(
            callable(dep)
            for dep in (
                self._provide_point_in_time_candles,
                self._provide_microstructure_metrics,
                self._provide_prop_account_health,
            )
        )
        return MCPServerStatus(
            server_id=self.SERVER_ID,
            healthy=injectors_bound,
            tools_registered=len(self.tools),
            invocations_served=self.invocations_served,
            invocations_rejected=self.invocations_rejected,
            as_of=datetime.now(timezone.utc).isoformat(),
        ).to_payload()
