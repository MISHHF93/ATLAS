"""Paper reserve sleeve. A target plan for swept profit. It cannot submit an order."""

from __future__ import annotations

import math
from decimal import Decimal

PATH_ID = "reserve-yield:v1"
DEFAULT_MARGINAL_RATE = 0.37

# Primary listings checked against iShares materials and the 2026 NYSE listing for SGOV.
_NAMES: dict[str, tuple[str, str]] = {
    "MUB": ("iShares National Muni Bond ETF", "munis"),
    "VTEB": ("Vanguard Tax-Exempt Bond ETF", "munis"),
    "TFI": ("SPDR Nuveen Bloomberg Municipal Bond ETF", "munis"),
    "HYMB": ("SPDR Nuveen Bloomberg High Yield Municipal Bond ETF", "munis"),
    "CMF": ("iShares California Muni Bond ETF", "munis"),
    "NYF": ("iShares New York Muni Bond ETF", "munis"),
    "SGOV": ("iShares 0-3 Month Treasury Bond ETF", "tbills"),
    "BIL": ("SPDR Bloomberg 1-3 Month T-Bill ETF", "tbills"),
    "SHY": ("iShares 1-3 Year Treasury Bond ETF", "treasury_ladder"),
    "IEF": ("iShares 7-10 Year Treasury Bond ETF", "treasury_ladder"),
    "TLT": ("iShares 20+ Year Treasury Bond ETF", "treasury_ladder"),
    "VOO": ("Vanguard S&P 500 ETF", "broad_equity"),
    "QQQ": ("Invesco QQQ Trust", "broad_equity"),
    "VNQ": ("Vanguard Real Estate ETF", "reits"),
    "CPT": ("Camden Property Trust", "reits"),
    "SPG": ("Simon Property Group", "real_assets"),
    "HST": ("Host Hotels & Resorts", "real_assets"),
    "VICI": ("VICI Properties", "real_assets"),
}

_SWEEP: tuple[tuple[str, str, str], ...] = (
    ("munis", "0.40", "MUB,VTEB,TFI,HYMB,CMF,NYF"),
    ("tbills", "0.30", "SGOV,BIL"),
    ("broad_equity", "0.20", "VOO,QQQ"),
    ("reits", "0.10", "VNQ,CPT"),
)


def tax_equivalent_yield(distribution_yield: float, marginal_rate: float) -> float | None:
    """TEY = yield / (1 - t). Municipal income only. t is the federal marginal rate."""
    if not math.isfinite(distribution_yield) or distribution_yield < 0:
        return None
    if not math.isfinite(marginal_rate) or marginal_rate < 0 or marginal_rate >= 1:
        return None
    return distribution_yield / (1.0 - marginal_rate)


def _sweep_rows() -> list[tuple[str, str, Decimal]]:
    """Even split inside each sleeve. The last name absorbs the rounding remainder."""
    rows: list[tuple[str, str, Decimal]] = []
    quantum = Decimal("0.00000001")
    for sleeve, weight, names in _SWEEP:
        symbols = names.split(",")
        total = Decimal(weight)
        share = (total / Decimal(len(symbols))).quantize(quantum)
        spent = Decimal("0")
        for index, symbol in enumerate(symbols):
            if index == len(symbols) - 1:
                part = total - spent
            else:
                part = share
                spent += part
            rows.append((symbol, sleeve, part))
    return rows


def build_reserve_plan(
    *,
    distributable_usd: float,
    marginal_rate: float = DEFAULT_MARGINAL_RATE,
    distribution_yields: dict[str, float] | None = None,
) -> dict[str, object]:
    """Target notionals for one paper sweep. This function does not submit anything."""
    profit = Decimal("0.00")
    if math.isfinite(distributable_usd) and distributable_usd > 0:
        profit = Decimal(str(distributable_usd)).quantize(Decimal("0.01"))
    rate_ok = math.isfinite(marginal_rate) and 0 <= marginal_rate < 1
    rate = marginal_rate if rate_ok else DEFAULT_MARGINAL_RATE
    observed = distribution_yields or {}
    weighted = _sweep_rows()
    if sum((weight for _, _, weight in weighted), Decimal("0")) != Decimal("1"):
        raise RuntimeError("reserve sweep weights must sum to 1")

    from atlas.marketdata.tradingview import tradingview_symbol

    spent = Decimal("0")
    holdings: list[dict[str, object]] = []
    positive = [(symbol, sleeve, weight) for symbol, sleeve, weight in weighted if weight > 0]
    for index, (symbol, sleeve, weight) in enumerate(positive):
        if index == len(positive) - 1:
            target = (profit - spent).quantize(Decimal("0.01"))
        else:
            target = (profit * weight).quantize(Decimal("0.01"))
            spent += target
        raw_yield = observed.get(symbol)
        tey = tax_equivalent_yield(float(raw_yield), rate) if sleeve == "munis" and raw_yield is not None else None
        name, _bucket = _NAMES[symbol]
        holdings.append(
            {
                "symbol": symbol,
                "name": name,
                "sleeve": sleeve,
                "in_sweep": True,
                "sweep_weight": format(weight, "f"),
                "target_usd": format(target, "f"),
                "tradingview_symbol": tradingview_symbol(symbol),
                "distribution_yield": None if raw_yield is None else raw_yield,
                "tax_equivalent_yield": tey,
                "execution_permission": "none",
            }
        )
    for symbol, (name, sleeve) in _NAMES.items():
        if any(row["symbol"] == symbol for row in holdings):
            continue
        holdings.append(
            {
                "symbol": symbol,
                "name": name,
                "sleeve": sleeve,
                "in_sweep": False,
                "sweep_weight": "0",
                "target_usd": "0.00",
                "tradingview_symbol": tradingview_symbol(symbol),
                "distribution_yield": None,
                "tax_equivalent_yield": None,
                "execution_permission": "none",
            }
        )
    sleeves = []
    for sleeve, weight, _names in _SWEEP:
        sleeve_target = sum(
            (Decimal(str(row["target_usd"])) for row in holdings if row["sleeve"] == sleeve),
            Decimal("0"),
        )
        sleeves.append(
            {
                "id": sleeve,
                "weight": weight,
                "target_usd": format(sleeve_target, "f"),
                "execution_permission": "none",
            }
        )
    return {
        "path_id": PATH_ID,
        "track": "reserve_yield",
        "distributable_usd": format(profit, "f"),
        "distributable_source": "control_plane_cumulative_paper_profit",
        "marginal_tax_rate": rate,
        "marginal_tax_rate_basis": "assumed_top_statutory_federal_ordinary_rate",
        "tax_equivalent_yield_formula": "yield / (1 - marginal_rate)",
        "yield_observation": "unobserved" if not observed else "caller_supplied_distribution_yield",
        "sleeves": sleeves,
        "holdings": holdings,
        "orders_submitted": 0,
        "withheld_reason": "public_equity_prints_are_older_than_the_open_market_freshness_rule",
        "venues_unconfigured": ["msrb_emma", "finra_trace", "ibkr_bond_scanner"],
        "settlement": "T+1 when a venue session exists",
        "execution_mode": "paper",
        "execution_permission": "none",
    }
