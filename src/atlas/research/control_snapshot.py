"""Read-only view of the deterministic control-plane state for research modules (no orders, no mutation)."""
from __future__ import annotations

from typing import Any


def control_snapshot() -> dict[str, Any]:
    from atlas.api.app import control_engine

    st = control_engine.get_state()
    a = st.account
    return {
        "kill_switch_engaged": bool(st.kill_switch_engaged),
        "account": {
            "current_equity_usd": float(a.current_equity_usd),
            "starting_equity_usd": float(a.initial_equity_usd),
            "start_of_day_equity_usd": float(a.start_of_day_equity_usd),
            "total_cumulative_profit_usd": float(a.total_cumulative_profit_usd),
            # The control plane does not split realized vs unrealized P&L; leave unavailable.
            "realized_pnl_today_usd": None,
            "unrealized_pnl_usd": None,
        },
        "open_positions": [
            {"position_id": p.position_id, "instrument_id": p.instrument_id, "side": p.side,
             "notional_usd": float(p.notional_usd), "track": p.track, "status": p.status}
            for p in st.open_positions
        ],
        "source": str(a.source),
    }
