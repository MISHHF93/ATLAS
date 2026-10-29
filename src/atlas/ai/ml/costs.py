"""Venue cost table (round trip). Assumptions, not measured fills; see docs/ml/pipeline.md#costs.

binance spot: 10 bp taker fee per side (no BNB discount) + 2 bp slippage per side = 24 bp round trip.
us equity ETFs (SPY/QQQ/IWM): ~1 bp half-spread + 1 bp slippage per side = 4 bp, plus $0.01/share commission
round trip (conservative retail-broker assumption). Identical to research.setup_evidence.COSTS_BPS so results are
comparable with the published evidence.
"""
from __future__ import annotations

VENUE_COSTS = {
    "binance": {"cost_bps": 24.0, "cost_per_unit": 0.0, "note": "10bp taker + 2bp slip per side"},
    "cme_gold": {"cost_bps": 4.0, "cost_per_unit": 0.0, "note": "assumption: 2bp spread+slip per side (GC/MGC/GLD), not a measured fill"},
    "us_equity": {"cost_bps": 4.0, "cost_per_unit": 0.01, "note": "1bp spread + 1bp slip per side + $0.01/sh"},
}


def venue_for(asset_class: str) -> str:
    return "binance" if asset_class == "crypto" else "cme_gold" if asset_class == "gold" else "us_equity"
