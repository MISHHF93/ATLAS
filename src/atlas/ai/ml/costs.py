"""Venue cost table (round trip). Assumptions, not measured fills; see docs/ml/pipeline.md#costs.

crypto spot (Coinbase / Kraken, the only crypto venues ATLAS uses): 60 bp taker fee per side + 2 bp slippage per side
= 124 bp round trip. 60 bp is Kraken Pro's published spot taker rate for the $2.5K+ 30-day-volume tier
(tier 1 is 80 bp; the fee falls with volume; https://www.kraken.com/features/fee-schedule, read 2026-10-30).
Coinbase Advanced's entry tier is at least as high, so this is the conservative-for-retail assumption. It replaces the
earlier 24 bp figure, which was a Binance fee schedule and is not available to Canadian residents. Higher costs only
make the cost-aware gates stricter; no gate threshold was changed. Assumption, not a measured fill.
us equity ETFs (SPY/QQQ/IWM): ~1 bp half-spread + 1 bp slippage per side = 4 bp, plus $0.01/share commission
round trip (conservative retail-broker assumption). Identical to research.setup_evidence.COSTS_BPS so results are
comparable with the published evidence (equity only; crypto evidence published before 2026-10-30 used 24 bp).
"""
from __future__ import annotations

VENUE_COSTS = {
    "crypto_spot": {"cost_bps": 124.0, "cost_per_unit": 0.0, "note": "assumption: 60bp taker (Kraken Pro tier 2) + 2bp slip per side"},
    "cme_gold": {"cost_bps": 4.0, "cost_per_unit": 0.0, "note": "assumption: 2bp spread+slip per side (GC/MGC/GLD), not a measured fill"},
    "us_equity": {"cost_bps": 4.0, "cost_per_unit": 0.01, "note": "1bp spread + 1bp slip per side + $0.01/sh"},
}


def venue_for(asset_class: str) -> str:
    return "crypto_spot" if asset_class == "crypto" else "cme_gold" if asset_class == "gold" else "us_equity"
