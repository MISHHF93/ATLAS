"""Subsystem I: Integrations & MCP Isolation (`src/atlas/integrations/`).

Re-exports allowlisted read-only MCP data source adapters, quarantined `irohan0/quant-mcp`
rejection, FRED model-training prohibition, and SEC EDGAR point-in-time XBRL ingestion.
"""
from atlas.marketdata.mcp_adapters import (
    ALLOWLISTED_MCP_SERVERS,
    QUARANTINED_MCP_SERVERS,
    MCPDataSourceAdapter,
    MCPServerPolicy,
    MCPToolCallRequest,
)
from atlas.marketdata.sec_edgar import SecEdgarFact, select_point_in_time_sec_facts

__all__ = [
    "ALLOWLISTED_MCP_SERVERS",
    "MCPDataSourceAdapter",
    "MCPServerPolicy",
    "MCPToolCallRequest",
    "QUARANTINED_MCP_SERVERS",
    "SecEdgarFact",
    "select_point_in_time_sec_facts",
]

