"""Competition vs open-market rule configuration, side by side, plus live enforcement probes.

The two rulebooks live on ActionableControlPlaneEngine (comp_rulebook / open_rulebook) and every order is checked
against ``_rulebook_for(track)`` only, so competition rules never leak into open_market or vice versa. The probes
below run the SAME synthetic paper signal through a fresh engine on each track and report the real decisions; they
demonstrate enforcement, they are not trades (fresh engines, nothing persisted, execution_permission none)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

FIELDS = ("rulebook_id", "revision", "max_per_trade_risk_fraction", "required_stop_kind", "min_stop_distance_bps",
          "max_daily_loss_fraction", "drawdown_mode", "max_drawdown_fraction", "max_position_notional_usd", "max_gross_leverage",
          "max_correlated_exposure_fraction", "max_sector_exposure_fraction", "max_data_age_seconds", "max_holding_seconds",
          "forbid_funding_window_entry", "min_trading_days", "max_single_day_profit_share", "evidence_ref")

PROBES = [
    {"id": "stop_28bps", "why": "stop distance between competition (25 bps) and open-market (30 bps) minimums",
     "signal": {"symbol": "SPY", "direction": "BUY", "target_entry_price": 600.0, "suggested_stop_loss": 598.32,
                "suggested_take_profit": 604.8}},
    {"id": "stop_100bps", "why": "comfortably wide stop; both tracks size it under their own caps",
     "signal": {"symbol": "SPY", "direction": "BUY", "target_entry_price": 600.0, "suggested_stop_loss": 594.0,
                "suggested_take_profit": 612.0}},
]


def _v(x: Any) -> Any:
    return float(x) if isinstance(x, Decimal) else sorted(x) if isinstance(x, frozenset) else x


def rulebooks(engine) -> dict[str, Any]:
    comp, opn = engine.comp_rulebook, engine.open_rulebook
    rows = [{"field": f, "competition": _v(getattr(comp, f, None)), "open_market": _v(getattr(opn, f, None))} for f in FIELDS]
    for r in rows:
        r["differs"] = r["competition"] != r["open_market"]
    return {"rows": rows, "active_track": engine.active_track}


def probe(engine_factory=None) -> list[dict[str, Any]]:
    from atlas.control.engine import ActionableControlPlaneEngine
    mk = engine_factory or (lambda: ActionableControlPlaneEngine())
    out = []
    for p in PROBES:
        row = {"id": p["id"], "why": p["why"]}
        for track in ("competition", "open_market"):
            eng = mk()
            eng.flatten_all_positions(reason="track_probe_clean_slate")
            sig = {**p["signal"], "execution_permission": "none", "telemetry": {"vpin": 0.2}}
            d = eng.ingest_whale_policy_signal(sig, track=track, data_age_ms=5.0).decision
            row[track] = {"decision": d.control_plane_decision, "quantity": float(d.quantity), "notional_usd": float(d.notional_usd),
                          "violations": list(d.violations)}
        out.append(row)
    return out
