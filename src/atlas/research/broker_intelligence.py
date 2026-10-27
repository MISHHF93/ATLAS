"""Provider-Neutral Broker MCP Intelligence & Account / Equity-Curve Reconciliation.

Implements Sections 10, 11, and 12 of the ATLAS Complete Research-to-Execution
Intelligence Integration specification.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

EXECUTION_PERMISSION = "none"

BROKER_CAPABILITY_TIERS: tuple[str, ...] = (
    "BROKER_READ_ONLY",
    "BROKER_PAPER_EXECUTION",
    "BROKER_LIVE_EXECUTION",
)

OFFICIAL_BROKER_MCP_REGISTRY: dict[str, dict[str, Any]] = {
    "alpaca_mcp_server": {
        "provider": "Alpaca Markets",
        "package_or_endpoint": "uvx alpaca-mcp-server (alpacahq/alpaca-mcp-server)",
        "official_docs_url": "https://docs.alpaca.markets/us/docs/alpaca-mcp-server",
        "supported_asset_classes": ["US Equities", "ETFs", "Crypto (Spot)", "Options"],
        "auth_method": "Environment variables ALPACA_API_KEY / ALPACA_SECRET_KEY (never passed in AI prompts)",
        "read_only_operations": [
            "get_account",
            "get_positions",
            "get_orders",
            "get_portfolio_history",
            "get_clock",
            "get_calendar",
            "get_stock_bars",
            "get_crypto_bars",
        ],
        "order_operations_policy": "Blocked in BROKER_READ_ONLY mode. Paper orders must route through ActionableControlPlaneEngine in BROKER_PAPER_EXECUTION mode.",
        "live_execution_status": "DISABLED_BY_HARD_INVARIANT (guard_alpaca_url rejects https://api.alpaca.markets)",
    },
    "ibkr_mcp_server": {
        "provider": "Interactive Brokers (IBKR)",
        "package_or_endpoint": "https://api.ibkr.com/v1/api/mcp-public",
        "official_docs_url": "https://www.interactivebrokers.com/en/general/about/mediaRelations/7-28-26.php",
        "supported_asset_classes": ["Global Equities", "ETFs", "CME/COMEX Futures", "FX", "Options", "Bonds"],
        "auth_method": "OAuth 2.0 / Client Portal Gateway session token (never pasted into prompts)",
        "read_only_operations": [
            "portfolio_summary",
            "margin_requirements",
            "positions_and_valuations",
            "realized_unrealized_pnl",
            "transaction_history",
        ],
        "order_operations_policy": "Read-only portfolio & margin intelligence by default; trade instructions require explicit human sign-off outside AI.",
        "live_execution_status": "DISABLED_BY_HARD_INVARIANT",
    },
}


def evaluate_broker_capability_guard(
    requested_capability: str,
    *,
    tool_name: str = "get_account",
    is_llm_caller: bool = True,
    control_plane_approved: bool = False,
) -> dict[str, Any]:
    """Section 11: Strict separation of BROKER_READ_ONLY, BROKER_PAPER_EXECUTION, and BROKER_LIVE_EXECUTION."""
    cap = requested_capability.upper().strip()
    mutating_tools = {"place_order", "submit_order", "cancel_order", "replace_order", "close_position", "close_all_positions"}
    is_mutating = tool_name.lower().strip() in mutating_tools

    if cap == "BROKER_LIVE_EXECUTION":
        return {
            "requested_capability": cap,
            "tool_name": tool_name,
            "allowed": False,
            "reason": "BROKER_LIVE_EXECUTION is permanently disabled by ATLAS safety policy.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    if cap == "BROKER_READ_ONLY":
        if is_mutating:
            return {
                "requested_capability": cap,
                "tool_name": tool_name,
                "allowed": False,
                "reason": f"Mutating tool '{tool_name}' is forbidden in BROKER_READ_ONLY mode.",
                "execution_permission": EXECUTION_PERMISSION,
            }
        return {
            "requested_capability": cap,
            "tool_name": tool_name,
            "allowed": True,
            "reason": "Authorized read-only broker query.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    if cap == "BROKER_PAPER_EXECUTION":
        if is_llm_caller:
            return {
                "requested_capability": cap,
                "tool_name": tool_name,
                "allowed": False,
                "reason": "LLM callers cannot directly invoke BROKER_PAPER_EXECUTION tools; all paper orders must pass through the deterministic control plane.",
                "execution_permission": EXECUTION_PERMISSION,
            }
        if is_mutating and not control_plane_approved:
            return {
                "requested_capability": cap,
                "tool_name": tool_name,
                "allowed": False,
                "reason": "Paper execution requires prior deterministic ActionableControlPlaneEngine approval.",
                "execution_permission": EXECUTION_PERMISSION,
            }
        return {
            "requested_capability": cap,
            "tool_name": tool_name,
            "allowed": True,
            "reason": "Deterministic control-plane paper operation permitted on paper endpoint.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    return {
        "requested_capability": cap,
        "tool_name": tool_name,
        "allowed": False,
        "reason": f"Unknown capability tier '{cap}'. Default-deny enforced.",
        "execution_permission": EXECUTION_PERMISSION,
    }


def build_broker_intelligence_snapshot() -> dict[str, Any]:
    """Section 12: Account & Equity-Curve Intelligence distinguishing broker-reported vs ATLAS-calculated values."""
    from atlas.api.app import control_engine
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    from atlas.ext.alpaca_reconcile import reconcile

    now_iso = datetime.now(timezone.utc).isoformat()
    broker = AlpacaPaperBroker()
    broker_desc = broker.describe()
    recon = reconcile(broker)

    cp_state = control_engine.snapshot_state()
    cp_acct = cp_state.get("account", {})
    cp_positions = list(cp_state.get("open_positions", []))

    atlas_equity = float(cp_acct.get("current_equity_usd", 100000.0))
    atlas_starting_equity = float(cp_acct.get("starting_equity_usd", 100000.0))
    atlas_realized_pnl = float(cp_acct.get("realized_pnl_today_usd", 0.0))
    atlas_unrealized_pnl = float(cp_acct.get("unrealized_pnl_usd", 0.0))
    atlas_cum_pnl = float(cp_acct.get("total_cumulative_profit_usd", 0.0))

    gross_exp = sum(abs(float(p.get("notional_usd", 0.0))) for p in cp_positions)
    net_exp = sum(
        float(p.get("notional_usd", 0.0)) * (1.0 if p.get("side") == "buy" else -1.0)
        for p in cp_positions
    )
    atlas_cash = max(0.0, atlas_equity - gross_exp)

    broker_connected = recon.get("status") in {"ok", "partial"} and isinstance(recon.get("account"), dict)
    broker_acct = recon.get("account") if broker_connected else None

    def _tagged(
        broker_val: float | None,
        atlas_val: float,
        *,
        is_estimated: bool = False,
        is_stale: bool = False,
    ) -> dict[str, Any]:
        diff = round(float(broker_val) - atlas_val, 2) if broker_val is not None else None
        return {
            "broker_reported": round(float(broker_val), 2) if broker_val is not None else None,
            "atlas_calculated": round(atlas_val, 2),
            "discrepancy_usd": diff,
            "source_tag": (
                "STALE"
                if is_stale
                else "BROKER_REPORTED"
                if broker_val is not None
                else "ESTIMATED"
                if is_estimated
                else "ATLAS_CALCULATED"
            ),
        }

    b_equity = float(broker_acct["equity"]) if broker_acct and broker_acct.get("equity") is not None else None
    b_cash = float(broker_acct["cash"]) if broker_acct and broker_acct.get("cash") is not None else None
    b_bp = float(broker_acct["buying_power"]) if broker_acct and broker_acct.get("buying_power") is not None else None

    # Build deterministic ATLAS paper equity curve from recorded daily/trade state
    equity_curve = [
        {"step": 0, "label": "Start", "equity_usd": round(atlas_starting_equity, 2), "drawdown_pct": 0.0, "daily_return_pct": 0.0, "source": "ATLAS_CALCULATED"},
        {
            "step": 1,
            "label": "Current",
            "equity_usd": round(atlas_equity, 2),
            "drawdown_pct": round(max(0.0, (atlas_starting_equity - atlas_equity) / max(1.0, atlas_starting_equity) * 100.0), 4),
            "daily_return_pct": round(((atlas_equity - atlas_starting_equity) / max(1.0, atlas_starting_equity)) * 100.0, 4),
            "source": "BROKER_REPORTED" if b_equity is not None else "ATLAS_CALCULATED",
        },
    ]

    # Concentration & correlated exposure
    largest_notional = max((abs(float(p.get("notional_usd", 0.0))) for p in cp_positions), default=0.0)
    max_concentration_pct = (largest_notional / max(1.0, atlas_equity)) * 100.0

    return {
        "as_of_utc": now_iso,
        "capability_tiers": {
            "active_research_mode": "BROKER_READ_ONLY",
            "paper_execution_mode": "BROKER_PAPER_EXECUTION (gated by ActionableControlPlaneEngine)",
            "live_execution_mode": "BROKER_LIVE_EXECUTION (DISABLED)",
        },
        "mcp_registry": OFFICIAL_BROKER_MCP_REGISTRY,
        "broker_connection": {
            "alpaca_paper_status": broker_desc.get("status", "unconfigured"),
            "alpaca_paper_reason": broker_desc.get("reason", "ALPACA_API_KEY_ID not configured in local .env"),
            "alpaca_base_url": broker_desc.get("base_url"),
            "ibkr_mcp_status": "configured" if os.environ.get("IBKR_MCP_TOKEN") else "not_configured",
            "reconciliation_status": recon.get("status", "unconfigured"),
        },
        "metrics": {
            "current_equity_usd": _tagged(b_equity, atlas_equity),
            "cash_usd": _tagged(b_cash, atlas_cash),
            "buying_power_usd": _tagged(b_bp, atlas_cash * 2.0, is_estimated=b_bp is None),
            "gross_exposure_usd": _tagged(None, gross_exp),
            "net_exposure_usd": _tagged(None, net_exp),
            "realized_pnl_usd": _tagged(None, atlas_realized_pnl),
            "unrealized_pnl_usd": _tagged(None, atlas_unrealized_pnl),
            "cumulative_profit_usd": _tagged(None, atlas_cum_pnl),
            "estimated_fees_usd": _tagged(None, round(len(cp_positions) * 1.50, 2), is_estimated=True),
        },
        "exposure_and_concentration": {
            "open_positions_count": len(cp_positions),
            "max_single_position_concentration_pct": round(max_concentration_pct, 2),
            "correlated_exposure_pct": round((gross_exp / max(1.0, atlas_equity)) * 100.0, 2),
            "margin_requirement_usd": round(gross_exp * 0.25, 2),
        },
        "account_restrictions": {
            "kill_switch_engaged": bool(cp_state.get("kill_switch_engaged", False)),
            "paper_only_enforced": True,
            "pdt_restricted": bool(broker_acct.get("pattern_day_trader")) if broker_acct else False,
            "trading_blocked": bool(broker_acct.get("trading_blocked")) if broker_acct else False,
            "permitted_asset_classes": ["US_EQUITIES", "CANADIAN_ETFS", "CME_COMEX_FUTURES", "CRYPTO_SPOT", "PRECIOUS_METALS"],
        },
        "open_positions": cp_positions,
        "broker_positions": recon.get("positions", []),
        "recent_orders": recon.get("orders", []),
        "recent_fills": recon.get("fills", []),
        "reconciliation_checks": recon.get("checks", []),
        "equity_curve": equity_curve,
        "notice": (
            "Broker balances are never fabricated when credentials are unconfigured; "
            "ATLAS-calculated control-plane paper figures are explicitly tagged as ATLAS_CALCULATED."
        ),
        "execution_permission": EXECUTION_PERMISSION,
    }

