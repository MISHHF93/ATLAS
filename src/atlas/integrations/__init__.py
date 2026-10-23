"""Subsystem I: Integrations & MCP Isolation (`src/atlas/integrations/`).

Re-exports allowlisted read-only MCP data source adapters, quarantined `irohan0/quant-mcp`
rejection, FRED model-training prohibition, and SEC EDGAR point-in-time XBRL ingestion.
"""
from atlas.marketdata.mcp_adapters import (
    ALLOWED_MCP_TOOLS,
    FORBIDDEN_MCP_SERVERS,
    MCPDataSourceAdapter,
)
from atlas.marketdata.sec_edgar import (
    SECEdgarFilingFact,
    select_as_filed_sec_facts,
)

__all__ = [
    "ALLOWED_MCP_TOOLS",
    "FORBIDDEN_MCP_SERVERS",
    "MCPDataSourceAdapter",
    "SECEdgarFilingFact",
    "select_as_filed_sec_facts",
]
