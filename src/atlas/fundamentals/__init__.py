"""Subsystem S: SEC EDGAR & Point-in-Time Fundamental Ingestion (`src/atlas/fundamentals/`).

Re-exports the as-filed SEC EDGAR XBRL fact selector enforcing `acceptance_time <= as_of`
with zero restatement lookahead bias (`execution_permission = "none"`).
"""
from atlas.marketdata.sec_edgar import SecEdgarFact, select_point_in_time_sec_facts

__all__ = ["SecEdgarFact", "select_point_in_time_sec_facts"]

