"""ATLAS Model Context Protocol (MCP) Hub (`src/atlas/mcp/`).

Two strictly separated surfaces:

1. **Internal read-only MCP server** (`server.AtlasReadonlyMCPServer`): exposes
   point-in-time candles, microstructure metrics, and prop-firm account health to
   connected AI models. Every response envelope carries
   ``metadata={"execution_permission": "none"}`` — the served surface can NEVER
   authorize, size, mutate, or route orders. Order authority remains exclusively
   with the deterministic `ActionableControlPlaneEngine`.

2. **External MCP firewall** (`firewall.MCPFirewall`): permits only explicitly
   allowlisted read-only external MCP server/tool pairs, permanently quarantines
   mutating packages (e.g. ``irohan0/quant-mcp``), and blocks any tool whose name
   embeds order/execution/write keywords before transport invocation.

No network transports or secret-bearing dependencies are imported here; the
gateway itself is dependency-injected so the air-gap stays verifiable.
"""

from atlas.mcp.firewall import (
    FORBIDDEN_MCP_SERVERS,
    FORBIDDEN_TOOL_KEYWORDS,
    QuarantineDecision,
    MCPFirewall,
)
from atlas.mcp.server import (
    MCPServerStatus,
    ReadonlyMCPTool,
    AtlasReadonlyMCPServer,
    ToolCallRejectedError,
)

__all__ = [
    "FORBIDDEN_MCP_SERVERS",
    "FORBIDDEN_TOOL_KEYWORDS",
    "MCPServerStatus",
    "MCPFirewall",
    "QuarantineDecision",
    "ReadonlyMCPTool",
    "ToolCallRejectedError",
    "AtlasReadonlyMCPServer",
]
