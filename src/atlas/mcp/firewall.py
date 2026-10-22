"""External MCP firewall — allowlist-only egress gateway for third-party MCP servers.

Invariants enforced *before* any transport invocation:
- Server ID must be on the explicit read-only allowlist (`ALLOWED_MCP_TOOLS`).
- Quarantined mutating packages (`irohan0/quant-mcp`, `quantgpt-mcp`, ...) are
  permanently rejected regardless of caller configuration (hard quarantine).
- Tool names must not contain order/execution/mutation keywords.
- Tool must be explicitly allowlisted for the requesting server.
- Serialized parameters are secret-screened (no credentials embedded).

This module delegates the canonical allowlist/quarantine constants to
`atlas.marketdata.mcp_adapters` so there is a single source of truth.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from atlas.ai.policy import screen_context
from atlas.marketdata.mcp_adapters import (
    ALLOWED_MCP_TOOLS,
    FORBIDDEN_MCP_SERVERS,
    FORBIDDEN_TOOL_KEYWORDS,
)


class QuarantineDecision:
    """-result of a firewall verdict (never raises alone; `MCPFirewall` enforces)."""

    __slots__ = ("allowed", "server_id", "tool_name", "reason", "verdict_kind")

    def __init__(self, *, allowed: bool, server_id: str, tool_name: str, reason: str, verdict_kind: Literal["allow", "quarantined_server", "unknown_server", "forbidden_keyword", "tool_not_allowlisted", "input_screened"]):
        self.allowed = allowed
        self.server_id = server_id
        self.tool_name = tool_name
        self.reason = reason
        self.verdict_kind = verdict_kind

    def model_dump_result(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "verdict_kind": self.verdict_kind,
            "reason": self.reason,
        }


class MCPFirewall:
    """Deterministic egress firewall for external MCP server/tool invocation."""

    def __init__(self, *, strict_allowlist: bool = True) -> None:
        self.strict_allowlist = strict_allowlist

    def evaluate(self, server_id: str, tool_name: str, params: dict[str, Any] | None = None) -> QuarantineDecision:
        """Produce the firewall verdict for an (external server, tool, params) triple."""
        if server_id in FORBIDDEN_MCP_SERVERS:
            return QuarantineDecision(
                allowed=False,
                server_id=server_id,
                tool_name=tool_name,
                reason=(
                    f"MCP server '{server_id}' is PERMANENTLY QUARANTINED: its tool surface "
                    "contains mutating (trade/execution/write) operations"
                ),
                verdict_kind="quarantined_server",
            )
        if self.strict_allowlist and server_id not in ALLOWED_MCP_TOOLS:
            return QuarantineDecision(
                allowed=False,
                server_id=server_id,
                tool_name=tool_name,
                reason=f"MCP server '{server_id}' is not on the read-only allowlist",
                verdict_kind="unknown_server",
            )
        tool_lower = tool_name.lower()
        if any(keyword in tool_lower for keyword in FORBIDDEN_TOOL_KEYWORDS):
            return QuarantineDecision(
                allowed=False,
                server_id=server_id,
                tool_name=tool_name,
                reason=f"Tool '{tool_name}' contains a forbidden order/execution/mutation keyword",
                verdict_kind="forbidden_keyword",
            )
        if self.strict_allowlist and tool_name not in ALLOWED_MCP_TOOLS.get(server_id, frozenset()):
            return QuarantineDecision(
                allowed=False,
                server_id=server_id,
                tool_name=tool_name,
                reason=f"Tool '{tool_name}' is not allowlisted for read-only server '{server_id}'",
                verdict_kind="tool_not_allowlisted",
            )
        # Screen serialized parameters for embedded secret material (raises on leak)
        try:
            screen_context(json.dumps(params or {}, sort_keys=True, default=str))
        except Exception as exc:
            return QuarantineDecision(
                allowed=False,
                server_id=server_id,
                tool_name=tool_name,
                reason=f"Input secret screening failed: {exc}",
                verdict_kind="input_screened",
            )
        return QuarantineDecision(
            allowed=True,
            server_id=server_id,
            tool_name=tool_name,
            reason="Read-only allowlisted tool call; execution_permission remains 'none'",
            verdict_kind="allow",
        )

    def assert_allowed(self, server_id: str, tool_name: str, params: dict[str, Any] | None = None) -> QuarantineDecision:
        """Raise `PermissionError` unless the invocation passes the firewall."""
        verdict = self.evaluate(server_id, tool_name, params)
        if not verdict.allowed:
            raise PermissionError(verdict.reason)
        return verdict

    def allowlist_snapshot(self) -> dict[str, list[str]]:
        """Deterministic copy of the read-only allowlist surface (for audit reporting)."""
        return {server: sorted(tools) for server, tools in sorted(ALLOWED_MCP_TOOLS.items())}
