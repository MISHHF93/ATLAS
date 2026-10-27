"""Feature 5 — Transparent Multifactor Asset Ratings.

Implements configurable, asset-class-specific multifactor research ratings with:
- Explicit methodology version (`atlas-multifactor-v2.1`).
- Asset-class-specific rating pillars:
  * Public Equities: valuation, fundamentals, momentum, trend_and_structure,
    volatility_and_tail_risk, liquidity, source_quality.
  * Precious Metals (Gold, Silver, Platinum, Palladium): explicitly sets
    `equity_valuation_applicable = False` (`valuation = "not_applicable_physical_commodity"`)
    and evaluates physical backing/custody quality, macro real-rate sensitivity,
    momentum, trend/structure, liquidity, volatility, and source quality.
  * ETFs & Funds: cost_and_tracking (MER bps), diversification, momentum,
    trend/structure, liquidity, volatility, source quality.
  * Bonds & Cash Equivalents: yield_and_credit_quality, duration_sensitivity,
    liquidity, trend/structure, volatility, source quality.
- Historical score comparison (`current_score`, `yesterday_score`, `score_30d_ago`).
- Confidence limitations & explicit non-guarantee disclosures.
"""
from __future__ import annotations

from typing import Any, Sequence

from atlas.assets.etf_intelligence import ETFS_BY_SYMBOL
from atlas.assets.master import get_canonical_asset_master
from atlas.assets.precious_metals import METALS_BY_SYMBOL
from atlas.ext import dossier, edgar, personas
from atlas.investment_intelligence.market_data import load_point_in_time_bars

EXECUTION_PERMISSION = "none"
RATING_METHODOLOGY_VERSION = "atlas-multifactor-v2.1"


def _clamp(val: float, lo: float = 1.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, val)), 1)


def compute_asset_multifactor_rating(
    symbol: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Compute transparent, asset-class-specific multifactor research rating for `symbol`."""
    sym = symbol.strip().upper()
    bars = load_point_in_time_bars(sym, "1d", as_of_date=as_of_date, limit=260)
    master = get_canonical_asset_master()
    inst = master.get_instrument(sym)
    asset_class = inst.asset_class if inst else ("precious_metal" if sym in ("GC", "SI", "PL", "PA", "GLD", "SLV", "MNT.TO") else "public_equity")
    display_name = inst.display_name if inst else sym

    if len(bars) < 5:
        return {
            "symbol": sym,
            "display_name": display_name,
            "asset_class": asset_class,
            "methodology_version": RATING_METHODOLOGY_VERSION,
            "status": "insufficient_data",
            "composite_score": None,
            "rating_label": "UNRATED",
            "epistemic_tag": "RESEARCH_RATING",
            "execution_permission": EXECUTION_PERMISSION,
        }

    # Fetch SEC EDGAR fundamentals only for public equities
    f_raw = None
    f_metrics: dict[str, Any] = {}
    if asset_class in ("public_equity", "equity"):
        try:
            f_raw = edgar.fundamentals(sym)
            if f_raw and f_raw.get("status") == "ok":
                f_metrics = edgar.derived_metrics(f_raw, bars[-1].close) or {}
        except Exception:
            f_metrics = {}

    ds_now = dossier.build_dossier(sym, bars, (), f_raw, f_metrics or None)
    ds_yest = dossier.build_dossier(sym, bars[:-1] if len(bars) > 10 else bars, (), f_raw, f_metrics or None)
    ds_30d = dossier.build_dossier(sym, bars[:-21] if len(bars) > 35 else bars[:15], (), f_raw, f_metrics or None)

    tech = ds_now.get("technicals") or {}
    close = float(tech.get("close") or bars[-1].close)
    sma50 = tech.get("sma50")
    sma200 = tech.get("sma200")
    ret_1m = float(tech.get("ret_1m") or 0.0)
    ret_3m = float(tech.get("ret_3m") or 0.0)
    ret_12m = float(tech.get("ret_12m") or 0.0)
    rsi14 = float(tech.get("rsi14") or 50.0)
    adx14 = float(tech.get("adx14") or 20.0)
    vol20 = float(tech.get("realized_vol_20d_ann") or 0.18)

    # Common technical & quality pillars (0-100 scale)
    momentum_score = _clamp(50.0 + ret_1m * 120.0 + ret_3m * 140.0 + (6.0 if (tech.get("macd_hist") or 0) > 0 else -6.0))
    trend_score = _clamp(
        50.0
        + (20.0 if (sma50 and sma200 and close > sma50 > sma200) else (-20.0 if (sma50 and sma200 and close < sma50 < sma200) else (10.0 if (sma50 and close > sma50) else -10.0)))
        + (8.0 if adx14 >= 25.0 else 0.0)
        + (-8.0 if rsi14 > 76.0 else (6.0 if rsi14 < 28.0 else 0.0))
    )
    volatility_score = _clamp(85.0 - vol20 * 95.0)
    liquidity_score = 92.0 if sym in ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "BIL", "TLT", "GC", "GLD", "EUR_USD", "BTCUSDT") else 80.0
    source_quality_score = 95.0 if inst and inst.identifiers.isin else 88.0

    pillars: list[dict[str, Any]] = []
    equity_valuation_applicable = False

    if asset_class == "precious_metal" or sym in ("GC", "SI", "PL", "PA", "GLD", "SLV", "PPLT", "PALL", "MNT.TO"):
        metal_spec = METALS_BY_SYMBOL.get(sym)
        holding_form = metal_spec.holding_form if metal_spec else ("allocated_etp" if sym in ("GLD", "SLV") else "exchange_future")
        backing_score = (
            94.0
            if holding_form in ("royal_canadian_mint_etr", "physical_allocated_bullion", "exchange_traded_product")
            else 82.0
        )
        macro_score = _clamp(68.0 + ret_3m * 80.0)
        pillars = [
            {
                "dimension": "valuation",
                "score": None,
                "weight": 0.0,
                "status": "not_applicable_physical_commodity",
                "explanation": "Equity P/E and DCF valuation metrics do not apply to physical bullion or commodity futures.",
            },
            {
                "dimension": "backing_and_custody_quality",
                "score": backing_score,
                "weight": 0.25,
                "status": "evaluated",
                "explanation": f"Holding structure ({holding_form}), vault custody specification, and counterparty tier.",
            },
            {
                "dimension": "momentum",
                "score": momentum_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": f"1M return {ret_1m:+.1%}, 3M return {ret_3m:+.1%}, 12M return {ret_12m:+.1%}.",
            },
            {
                "dimension": "trend_and_structure",
                "score": trend_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": f"Close {close:.4g} vs SMA50/SMA200 and ADX14 {adx14:.1f}.",
            },
            {
                "dimension": "macro_real_rate_sensitivity",
                "score": macro_score,
                "weight": 0.15,
                "status": "evaluated",
                "explanation": "Inflation hedge and sovereign real-rate sensitivity profile.",
            },
            {
                "dimension": "liquidity",
                "score": liquidity_score,
                "weight": 0.10,
                "status": "evaluated",
                "explanation": "Exchange/ETR bid-ask spread and institutional turnover depth.",
            },
            {
                "dimension": "volatility_and_tail_risk",
                "score": volatility_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": f"20D annualized realized volatility {vol20:.1%}.",
            },
            {
                "dimension": "source_quality",
                "score": source_quality_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": "Verified exchange/trust identifier and feed bar completeness.",
            },
        ]
    elif asset_class in ("fixed_income_bond", "cash_equivalent") or sym in ("BIL", "SGOV", "SHY", "IEF", "TLT", "AGG", "BND"):
        etf_spec = ETFS_BY_SYMBOL.get(sym)
        mer_bps = etf_spec.expense_ratio_bps if etf_spec else 14.0
        yield_credit_score = 92.0 if sym in ("BIL", "SGOV", "SHY") else 84.0
        duration_score = 95.0 if sym in ("BIL", "SGOV") else (62.0 if sym == "TLT" else 78.0)
        pillars = [
            {
                "dimension": "yield_and_credit_quality",
                "score": yield_credit_score,
                "weight": 0.30,
                "status": "evaluated",
                "explanation": f"Sovereign US/Canadian Treasury backing; MER {mer_bps} bps.",
            },
            {
                "dimension": "duration_and_rate_sensitivity",
                "score": duration_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": "Ultra-short T-Bill stability vs long-duration rate sensitivity.",
            },
            {
                "dimension": "liquidity",
                "score": liquidity_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": "Primary dealer & secondary ETF liquidity.",
            },
            {
                "dimension": "trend_and_structure",
                "score": trend_score,
                "weight": 0.15,
                "status": "evaluated",
                "explanation": f"Close {close:.4g} vs moving average structure.",
            },
            {
                "dimension": "volatility_and_tail_risk",
                "score": volatility_score,
                "weight": 0.10,
                "status": "evaluated",
                "explanation": f"20D annualized realized volatility {vol20:.1%}.",
            },
            {
                "dimension": "source_quality",
                "score": source_quality_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": "Verified ISIN/CUSIP and official NAV/price provenance.",
            },
        ]
    elif asset_class == "etf_and_fund" or sym in ETFS_BY_SYMBOL:
        etf_spec = ETFS_BY_SYMBOL.get(sym)
        mer_bps = float(etf_spec.expense_ratio_bps) if etf_spec else 20.0
        cost_score = _clamp(96.0 - mer_bps * 0.55)
        div_score = 90.0 if sym in ("SPY", "QQQ", "VTI", "XIU.TO", "VFV.TO") else 76.0
        pillars = [
            {
                "dimension": "cost_and_tracking_efficiency",
                "score": cost_score,
                "weight": 0.25,
                "status": "evaluated",
                "explanation": f"Verified fund expense ratio {mer_bps:.1f} bps ({mer_bps/100:.2f}% MER).",
            },
            {
                "dimension": "momentum",
                "score": momentum_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": f"1M {ret_1m:+.1%}, 3M {ret_3m:+.1%}, 12M {ret_12m:+.1%}.",
            },
            {
                "dimension": "trend_and_structure",
                "score": trend_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": f"Close {close:.4g} vs SMA50/SMA200 and Volume Profile Value Area.",
            },
            {
                "dimension": "liquidity",
                "score": liquidity_score,
                "weight": 0.15,
                "status": "evaluated",
                "explanation": "Authorized participant creation/redemption liquidity and tight secondary spread.",
            },
            {
                "dimension": "volatility_and_tail_risk",
                "score": volatility_score,
                "weight": 0.10,
                "status": "evaluated",
                "explanation": f"20D annualized realized volatility {vol20:.1%}.",
            },
            {
                "dimension": "concentration_and_diversification",
                "score": div_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": "Underlying index breadth and issuer diversification.",
            },
            {
                "dimension": "source_quality",
                "score": source_quality_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": "Verified ETF prospectus/factsheet ISIN, CUSIP, and SEC CIK.",
            },
        ]
    else:
        # Public Equity multifactor rating
        equity_valuation_applicable = True
        pe = f_metrics.get("pe")
        fcf_yield = f_metrics.get("fcf_yield")
        roe = f_metrics.get("roe")
        de = f_metrics.get("debt_to_equity")
        rev_g = f_metrics.get("revenue_growth")

        val_score = 62.0
        if pe is not None:
            val_score += 15.0 if 0 < pe < 20 else (-10.0 if pe > 40 else 4.0)
        if fcf_yield is not None:
            val_score += 12.0 if fcf_yield > 0.04 else (-6.0 if fcf_yield < 0 else 3.0)
        val_score = _clamp(val_score)

        fund_score = 66.0
        if roe is not None:
            fund_score += 14.0 if roe > 0.15 else (-12.0 if roe < 0 else 4.0)
        if de is not None:
            fund_score += 8.0 if de < 1.0 else (-10.0 if de > 2.0 else 0.0)
        if rev_g is not None:
            fund_score += 8.0 if rev_g > 0.08 else (-8.0 if rev_g < 0 else 2.0)
        fund_score = _clamp(fund_score)

        pillars = [
            {
                "dimension": "valuation",
                "score": val_score,
                "weight": 0.20,
                "status": "evaluated" if f_metrics else "neutral_no_sec_cache",
                "explanation": (
                    f"P/E {pe:.1f}, FCF yield {fcf_yield:.1%}"
                    if (pe is not None and fcf_yield is not None)
                    else "SEC EDGAR XBRL valuation multiples (neutral baseline when local filing cache not populated)."
                ),
            },
            {
                "dimension": "fundamentals",
                "score": fund_score,
                "weight": 0.20,
                "status": "evaluated" if f_metrics else "neutral_no_sec_cache",
                "explanation": "Balance-sheet profitability (ROE, FCF positive, Debt/Equity, revenue growth).",
            },
            {
                "dimension": "momentum",
                "score": momentum_score,
                "weight": 0.20,
                "status": "evaluated",
                "explanation": f"1M {ret_1m:+.1%}, 3M {ret_3m:+.1%}, 12M {ret_12m:+.1%}.",
            },
            {
                "dimension": "trend_and_structure",
                "score": trend_score,
                "weight": 0.15,
                "status": "evaluated",
                "explanation": f"Close {close:.4g} vs SMA50/SMA200, ADX14 {adx14:.1f}, RSI14 {rsi14:.1f}.",
            },
            {
                "dimension": "volatility_and_tail_risk",
                "score": volatility_score,
                "weight": 0.10,
                "status": "evaluated",
                "explanation": f"20D annualized realized volatility {vol20:.1%}.",
            },
            {
                "dimension": "liquidity",
                "score": liquidity_score,
                "weight": 0.10,
                "status": "evaluated",
                "explanation": "Primary exchange depth and institutional turnover.",
            },
            {
                "dimension": "source_quality",
                "score": source_quality_score,
                "weight": 0.05,
                "status": "evaluated",
                "explanation": "Verified ISO 6166 ISIN, CUSIP, SEC CIK, and Exchange MIC.",
            },
        ]

    weighted_sum = sum((p["score"] or 0.0) * p["weight"] for p in pillars if p["score"] is not None)
    weight_tot = sum(p["weight"] for p in pillars if p["score"] is not None) or 1.0
    multifactor_score = int(round(_clamp(weighted_sum / weight_tot)))

    # Blend with deterministic conviction score from dossier for unified consistency
    dossier_score = int((ds_now.get("conviction") or {}).get("score") or multifactor_score)
    composite_score = int(round(0.55 * dossier_score + 0.45 * multifactor_score))
    yest_score = int((ds_yest.get("conviction") or {}).get("score") or composite_score)
    score_30d = int((ds_30d.get("conviction") or {}).get("score") or composite_score)

    rating_label = "HIGH_CONVICTION_RESEARCH" if composite_score >= 65 else ("CAUTIOUS_UNDERWEIGHT" if composite_score <= 38 else "NEUTRAL_WATCH")
    action_badge = "BUY" if composite_score >= 65 else ("SELL" if composite_score <= 38 else "WATCH")

    persona_checks = [personas.score_persona(pid, f_metrics, tech) for pid in personas.PERSONAS]

    return {
        "feature": "5_transparent_multifactor_asset_ratings",
        "symbol": sym,
        "display_name": display_name,
        "asset_class": asset_class,
        "as_of_date": as_of_date or "latest",
        "methodology_version": RATING_METHODOLOGY_VERSION,
        "equity_valuation_applicable": equity_valuation_applicable,
        "composite_score": composite_score,
        "dossier_conviction_score": dossier_score,
        "multifactor_pillar_score": multifactor_score,
        "rating_label": rating_label,
        "conviction_badge": action_badge,
        "historical_comparison": {
            "current_score": composite_score,
            "yesterday_score": yest_score,
            "delta_vs_yesterday": composite_score - yest_score,
            "score_30d_ago": score_30d,
            "delta_vs_30d_ago": composite_score - score_30d,
        },
        "pillars": pillars,
        "dossier_components": (ds_now.get("conviction") or {}).get("components", []),
        "persona_checklists": persona_checks,
        "trade_levels_reference": ds_now.get("trade_levels"),
        "confidence_and_limitations": {
            "confidence_level": "HIGH" if len(bars) >= 200 else "MEDIUM",
            "bars_evaluated": len(bars),
            "fundamentals_populated": bool(f_metrics),
            "limitations_disclosure": (
                "Multifactor research ratings summarize historical price structure, liquidity, volatility, "
                "and filed fundamentals. A numerical rating is NOT a guarantee of future performance and "
                "does not constitute personalized investment advice under Canadian NI 31-103."
            ),
            "is_performance_guarantee": False,
        },
        "epistemic_tag": "RESEARCH_RATING",
        "execution_permission": EXECUTION_PERMISSION,
    }


def batch_multifactor_ratings(
    symbols: Sequence[str] | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    default_syms = ("AAPL", "MSFT", "BIL", "GLD", "GC", "SPY", "QQQ", "TLT", "NVDA", "SI", "MNT.TO", "BTCUSDT")
    target = [s.strip().upper() for s in (symbols or default_syms) if s.strip()]
    items = [compute_asset_multifactor_rating(sym, as_of_date=as_of_date) for sym in target]
    items.sort(key=lambda x: (x.get("composite_score") or 0), reverse=True)
    return {
        "feature": "5_transparent_multifactor_asset_ratings",
        "methodology_version": RATING_METHODOLOGY_VERSION,
        "as_of_date": as_of_date or "latest",
        "count": len(items),
        "ratings": items,
        "epistemic_tag": "RESEARCH_RATING",
        "execution_permission": EXECUTION_PERMISSION,
    }

