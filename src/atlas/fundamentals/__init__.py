"""Subsystem S: SEC EDGAR & Point-in-Time Fundamental Ingestion (`src/atlas/fundamentals/`).

Re-exports the as-filed SEC EDGAR XBRL fact selector enforcing `acceptance_time <= as_of`
with zero restatement lookahead bias (`execution_permission = "none"`).
"""
from atlas.marketdata.sec_edgar import (
    SECEdgarFilingFact,
    select_as_filed_sec_facts,
)

__all__ = ["SECEdgarFilingFact", "select_as_filed_sec_facts"]
