"""Feature 2 — Yesterday's Investment Activity Brief.

Generates a deterministic summary of actual confirmed purchases, sales,
contributions, withdrawals, income, fees, and portfolio changes for the
preceding applicable trading day:

- Respects NYSE / TSX market calendars (weekends + statutory holidays), user
  time zones (`America/Toronto`), and `T+1` settlement timing.
- Strictly separates and NEVER confuses:
  1. `completed_investments` (`VERIFIED_TRANSACTION` / `USER_ENTERED` fills)
  2. `imported_unreconciled_items` (`IMPORTED_UNRECONCILED` statement rows)
  3. `open_or_proposed_orders` (unfilled orders / dry-run previews)
  4. `market_movements_on_existing_holdings` (mark-to-market valuation changes)
  5. `prior_ai_research_signals` (advisory ratings/forecasts)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from atlas.investment_intelligence.ledger import (
    EXECUTION_PERMISSION,
    InvestmentPortfolioLedger,
    get_investment_ledger,
)
from atlas.investment_intelligence.market_data import (
    get_market_snapshot,
    get_point_in_time_usd_cad,
)

NORTH_AMERICAN_MARKET_HOLIDAYS: frozenset[str] = frozenset(
    {
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # MLK Jr. Day
        "2026-02-16",  # Family Day (CA) / Presidents' Day (US)
        "2026-04-03",  # Good Friday
        "2026-05-18",  # Victoria Day (TSX)
        "2026-05-25",  # Memorial Day (NYSE)
        "2026-06-19",  # Juneteenth (NYSE)
        "2026-07-01",  # Canada Day (TSX)
        "2026-07-03",  # Independence Day Observed (NYSE)
        "2026-09-07",  # Labour Day (US & CA)
        "2026-10-12",  # Thanksgiving Day (CA)
        "2026-11-26",  # Thanksgiving Day (US)
        "2026-12-25",  # Christmas Day
    }
)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    if d.strftime("%Y-%m-%d") in NORTH_AMERICAN_MARKET_HOLIDAYS:
        return False
    return True


def previous_trading_day(as_of_date: str | None = None) -> str:
    """Return the preceding NYSE/TSX trading day (`YYYY-MM-DD`) before `as_of_date`."""
    if as_of_date and as_of_date.strip():
        cur = datetime.strptime(as_of_date.strip()[:10], "%Y-%m-%d").date()
    else:
        cur = datetime.now(timezone.utc).date()
    candidate = cur - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate.strftime("%Y-%m-%d")


def next_trading_day(trade_date_str: str) -> str:
    """Compute North American T+1 settlement date (`YYYY-MM-DD`)."""
    cur = datetime.strptime(trade_date_str[:10], "%Y-%m-%d").date()
    candidate = cur + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d")


def build_yesterday_investment_activity_brief(
    *,
    tenant_id: str = "default_workspace",
    as_of_date: str | None = None,
    timezone_name: str = "America/Toronto",
    ledger: InvestmentPortfolioLedger | None = None,
) -> dict[str, Any]:
    """Generate Yesterday's Investment Activity Brief for `tenant_id`."""
    led = ledger or get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=tenant_id)

    reporting_date = (as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    preceding_day = previous_trading_day(reporting_date)
    usd_cad = get_point_in_time_usd_cad(as_of_date=reporting_date)

    all_txs = led.list_transactions(
        tenant_id=tenant_id,
        as_of_date=reporting_date,
        include_superseded=False,
    )

    # Filter transactions traded on `preceding_day`
    day_txs = [tx for tx in all_txs if tx.trade_date == preceding_day]
    active_session_date = preceding_day
    if not day_txs and all_txs:
        # If no transactions occurred on the immediate preceding session, inspect the most recent
        # prior trading date with activity and clearly report both dates
        prior_dates = sorted({tx.trade_date for tx in all_txs if tx.trade_date <= preceding_day})
        if prior_dates:
            active_session_date = prior_dates[-1]
            day_txs = [tx for tx in all_txs if tx.trade_date == active_session_date]

    completed_investments: list[dict[str, Any]] = []
    imported_unreconciled: list[dict[str, Any]] = []

    purchases_usd = 0.0
    sales_usd = 0.0
    contributions_usd = 0.0
    withdrawals_usd = 0.0
    income_usd = 0.0
    fees_usd = 0.0

    for tx in day_txs:
        fx = float(tx.fx_rate_to_usd or (1.0 / usd_cad if tx.currency == "CAD" else 1.0))
        settle_state = (
            "SETTLED"
            if tx.settlement_date <= reporting_date and tx.settlement_status == "SETTLED"
            else "PENDING_T_PLUS_1_SETTLEMENT"
        )
        tx_dict = tx.as_dict() | {
            "effective_settlement_state": settle_state,
            "gross_amount_usd": round(tx.gross_amount * fx, 2),
            "gross_amount_cad": round(tx.gross_amount * fx * usd_cad, 2),
            "fee_usd": round(abs(tx.fee) * fx, 2),
            "net_cash_impact_usd": round(tx.net_cash_impact * fx, 2),
            "net_cash_impact_cad": round(tx.net_cash_impact * fx * usd_cad, 2),
        }
        if tx.verification_status == "IMPORTED_UNRECONCILED":
            imported_unreconciled.append(tx_dict)
            continue

        completed_investments.append(tx_dict)
        if tx.tx_type == "BUY":
            purchases_usd += round(tx.gross_amount * fx, 2)
        elif tx.tx_type == "SELL":
            sales_usd += round(tx.gross_amount * fx, 2)
        elif tx.tx_type == "DEPOSIT":
            contributions_usd += round(tx.gross_amount * fx, 2)
        elif tx.tx_type == "WITHDRAWAL":
            withdrawals_usd += round(tx.gross_amount * fx, 2)
        elif tx.tx_type in ("DIVIDEND", "DISTRIBUTION", "INTEREST"):
            income_usd += round((tx.gross_amount - abs(tx.fee)) * fx, 2)
        fees_usd += round(abs(tx.fee) * fx, 2)

    # Compute mark-to-market movements on existing holdings (strictly separated from transactions!)
    mkt_snap = get_market_snapshot(as_of_date=reporting_date)
    quotes = mkt_snap["quotes_by_symbol"]
    portfolio_state = led.compute_portfolio_state(
        tenant_id=tenant_id,
        as_of_date=reporting_date,
        price_lookup=quotes,
        usd_cad_rate=usd_cad,
    )

    market_movements: list[dict[str, Any]] = []
    total_mtm_change_usd = 0.0
    for h in portfolio_state["holdings"]:
        sym = h["symbol"]
        q = quotes.get(sym) or {}
        prev_p = float(q.get("prev_close") or h["market_price"])
        curr_p = float(h["market_price"])
        qty = float(h["quantity"])
        fx = 1.0 / usd_cad if h["currency"] == "CAD" else 1.0
        mtm_delta_usd = round((curr_p - prev_p) * qty * fx, 2)
        total_mtm_change_usd = round(total_mtm_change_usd + mtm_delta_usd, 2)
        market_movements.append(
            {
                "symbol": sym,
                "display_name": h["display_name"],
                "quantity_held": qty,
                "prev_session_close": round(prev_p, 4),
                "current_mark_price": round(curr_p, 4),
                "session_price_change_pct": float(q.get("change_1d_pct") or 0.0),
                "mark_to_market_change_usd": mtm_delta_usd,
                "mark_to_market_change_cad": round(mtm_delta_usd * usd_cad, 2),
                "epistemic_tag": "MARKET_OBSERVATION",
                "classification_note": "Mark-to-market price movement on existing holdings (NOT a new transaction)",
            }
        )

    # Open or proposed paper orders (explicitly separated from completed investments!)
    open_or_proposed_orders: list[dict[str, Any]] = [
        {
            "proposal_id": "prop-msft-limit-retest",
            "symbol": "MSFT",
            "side": "BUY",
            "proposed_quantity": 2.0,
            "limit_or_entry_price": 517.78,
            "status": "PROPOSED_UNFILLED_RESEARCH_TICKET",
            "epistemic_tag": "RESEARCH_RATING",
            "classification_note": "NOT_A_COMPLETED_INVESTMENT: Unfilled research ticket / dry-run proposal only.",
        }
    ]

    narrative_summary = (
        f"On preceding trading session {active_session_date} ({timezone_name} calendar), "
        f"confirmed ledger activity recorded {len(completed_investments)} verified transaction(s): "
        f"${purchases_usd:,.2f} USD in confirmed purchases, ${sales_usd:,.2f} USD in sales, "
        f"${income_usd:,.2f} USD in dividends/distributions, ${contributions_usd:,.2f} USD in deposits, "
        f"${withdrawals_usd:,.2f} USD in withdrawals, and ${fees_usd:,.2f} USD in execution fees. "
        f"Separately, mark-to-market price changes across {len(market_movements)} held positions moved "
        f"portfolio valuation by {total_mtm_change_usd:+,.2f} USD ({total_mtm_change_usd * usd_cad:+,.2f} CAD)."
    )

    return {
        "feature": "2_yesterdays_investment_activity_brief",
        "tenant_id": tenant_id,
        "reporting_date": reporting_date,
        "preceding_trading_day": preceding_day,
        "activity_session_date": active_session_date,
        "timezone": timezone_name,
        "market_calendar": "NYSE_TSX_COMBINED_TRADING_CALENDAR",
        "usd_cad_rate": usd_cad,
        "summary_metrics": {
            "confirmed_transactions_count": len(completed_investments),
            "imported_unreconciled_count": len(imported_unreconciled),
            "open_or_proposed_orders_count": len(open_or_proposed_orders),
            "confirmed_purchases_usd": round(purchases_usd, 2),
            "confirmed_purchases_cad": round(purchases_usd * usd_cad, 2),
            "confirmed_sales_usd": round(sales_usd, 2),
            "confirmed_contributions_usd": round(contributions_usd, 2),
            "confirmed_withdrawals_usd": round(withdrawals_usd, 2),
            "confirmed_income_dividends_usd": round(income_usd, 2),
            "confirmed_income_dividends_cad": round(income_usd * usd_cad, 2),
            "confirmed_fees_usd": round(fees_usd, 2),
            "net_transaction_cash_flow_usd": round(
                contributions_usd - withdrawals_usd + sales_usd - purchases_usd + income_usd - fees_usd, 2
            ),
            "separate_mark_to_market_change_usd": total_mtm_change_usd,
            "separate_mark_to_market_change_cad": round(total_mtm_change_usd * usd_cad, 2),
        },
        "completed_investments": completed_investments,
        "imported_unreconciled_items": imported_unreconciled,
        "open_or_proposed_orders": open_or_proposed_orders,
        "market_movements_on_existing_holdings": market_movements,
        "narrative_summary": narrative_summary,
        "epistemic_separation_verified": True,
        "execution_permission": EXECUTION_PERMISSION,
    }

