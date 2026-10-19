"""Read-only MCP market-data adapters behind explicit tool allowlists and ProviderRuntime.

Security & governance controls:
- Only explicitly allowlisted read-only server/tool pairs may be invoked.
- Mutating tools (e.g. `irohan0/quant-mcp` portfolio/watchlist writes, `quantgpt-mcp`
  writes) and any order/execution tools are rejected before transport execution.
- Secrets are screened before transport invocation and never logged.
- Responses are normalized into `MarketDataBatch` with `execution_permission: none`.
"""
from collections.abc import Awaitable, Callable
import hashlib
import json
from typing import Any

from atlas.ai.policy import screen_context
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import (
    Capability,
    DataProvenance,
    MarketDataBatch,
    MarketDataRequest,
    Observation,
    ProviderInfo,
    Usage,
)

# Explicit per-provider read-only tool allowlists (Decision #28, #30, #31)
ALLOWED_MCP_TOOLS: dict[str, frozenset[str]] = {
    "alpha_vantage_mcp": frozenset({
        "TIME_SERIES_DAILY_ADJUSTED",
        "TIME_SERIES_INTRADAY",
        "FX_DAILY",
        "DIGITAL_CURRENCY_DAILY",
        "EARNINGS_CALL_TRANSCRIPT",
        "NEWS_SENTIMENT",
    }),
    "financial_datasets_mcp": frozenset({
        "get_historical_stock_prices",
        "get_current_stock_price",
        "get_income_statements",
        "get_balance_sheets",
        "get_cash_flow_statements",
        "get_company_news",
        "get_crypto_prices",
    }),
    "fin_data_mcp": frozenset({
        "sec_company_facts",
        "sec_submissions",
        "ecb_fx_rates",
        "cboe_delayed_quotes",
        "okx_public_candles",
    }),
}

FORBIDDEN_MCP_SERVERS: frozenset[str] = frozenset({
    "quant_mcp",
    "irohan0/quant-mcp",
    "quantgpt-mcp",
})

FORBIDDEN_TOOL_KEYWORDS: tuple[str, ...] = (
    "order",
    "trade",
    "execute",
    "submit",
    "cancel",
    "withdraw",
    "deposit",
    "transfer",
    "watchlist",
    "portfolio",
    "create",
    "update",
    "delete",
    "mutate",
    "write",
)

MCPTransport = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MCPDataSourceAdapter:
    """Bounded read-only MCP data adapter implementing `ReadOnlyDataProvider`."""

    def __init__(
        self,
        provider_id: str,
        *,
        runtime: ProviderRuntime,
        transport: MCPTransport,
        venue: str,
        calendar_ref: str,
        license_ref: str,
        allow_retention: bool = False,
        allow_training: bool = False,
        allow_competition: bool = False,
    ) -> None:
        if provider_id in FORBIDDEN_MCP_SERVERS:
            raise ValueError(f"MCP server '{provider_id}' is disallowed due to mutating tools or license terms")
        if provider_id not in ALLOWED_MCP_TOOLS:
            raise ValueError(f"MCP server '{provider_id}' is not in the read-only allowlist")
        self.provider_id = provider_id
        self.runtime = runtime
        self._transport = transport
        self.venue = venue
        self.calendar_ref = calendar_ref
        self.license_ref = license_ref
        self.allow_retention = allow_retention
        self.allow_training = allow_training
        self.allow_competition = allow_competition

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self.provider_id,
            capabilities=frozenset({Capability.DATA_SOURCE}),
            location="cloud",
            models=tuple(sorted(ALLOWED_MCP_TOOLS[self.provider_id])),
        )

    def _validate_tool_call(self, request: MarketDataRequest) -> None:
        if request.provider_id != self.provider_id:
            raise ValueError("MarketDataRequest provider_id does not match adapter")
        tool_lower = request.tool_name.lower()
        if any(keyword in tool_lower for keyword in FORBIDDEN_TOOL_KEYWORDS):
            raise PermissionError(f"Tool '{request.tool_name}' contains forbidden write/execution keyword")
        if request.tool_name not in ALLOWED_MCP_TOOLS[self.provider_id]:
            raise PermissionError(f"Tool '{request.tool_name}' is not allowlisted for {self.provider_id}")
        # Screen serialized parameters to ensure no secret material is embedded
        screen_context(
            json.dumps(
                {
                    "instrument_id": request.instrument_id,
                    "tool_name": request.tool_name,
                    "request_id": request.request_id,
                }
            )
        )

    async def fetch_market_data(self, request: MarketDataRequest) -> MarketDataBatch:
        self._validate_tool_call(request)

        params = {
            "instrument_id": request.instrument_id,
            "start_time": request.start_time.isoformat(),
            "end_time": request.end_time.isoformat(),
            "max_rows": request.max_rows,
        }

        async def _invoke() -> dict[str, Any]:
            return await self._transport(self.provider_id, request.tool_name, params)

        payload = await self.runtime.call("fetch_market_data", _invoke, retry_safe=True)
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest()

        raw_rows = payload.get("observations", [])
        if not isinstance(raw_rows, list) or len(raw_rows) > request.max_rows:
            raise ValueError("MCP response observations missing or exceeded bounded max_rows")

        observations = tuple(
            Observation(
                event_time=row["event_time"],
                available_at=row["available_at"],
                value=row["value"],
            )
            for row in raw_rows
        )
        if any(obs.available_at > request.as_of for obs in observations):
            raise ValueError("MCP response contains future observations beyond request.as_of")

        provenance = DataProvenance(
            provider_id=self.provider_id,
            source_ref=f"{self.provider_id}:{request.tool_name}",
            upstream_id=str(payload.get("upstream_id", request.request_id)),
            instrument_id=request.instrument_id,
            venue=self.venue,
            timezone=str(payload.get("timezone", "UTC")),
            adjustment_basis=payload.get("adjustment_basis", "unknown"),
            calendar_ref=self.calendar_ref,
            license_ref=self.license_ref,
            allow_retention=self.allow_retention,
            allow_training=self.allow_training,
            allow_competition=self.allow_competition,
            retrieved_at=request.as_of,
            content_sha256=digest,
        )

        return MarketDataBatch(
            request_id=request.request_id,
            provenance=provenance,
            observations=observations,
            quality="unknown",
            usage=Usage(),
        )

