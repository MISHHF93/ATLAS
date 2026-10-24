"""Control-plane futures sizing: quantity is whole contracts and notional = qty x entry x multiplier."""
from decimal import Decimal

import pytest

from atlas.control.engine import ActionableControlPlaneEngine
from atlas.feeds.contracts import contract_for


def _sig(sym, entry, stop, tp, direction="BUY"):
    return {"symbol": sym, "direction": direction, "target_entry_price": entry, "suggested_stop_loss": stop,
            "suggested_take_profit": tp, "execution_permission": "none", "telemetry": {"vpin": 0.2}}


def _intake(sym, entry, stop, tp, direction="BUY"):
    eng = ActionableControlPlaneEngine()
    eng.flatten_all_positions(reason="test_clean_slate")
    return eng.ingest_whale_policy_signal(_sig(sym, entry, stop, tp, direction), track="open_market", data_age_ms=5.0)


@pytest.mark.parametrize("sym", ["GC", "MGC", "SI", "ES"])
def test_futures_quantity_is_whole_contracts(sym):
    spec = contract_for(sym)
    entry = {"GC": 4000.0, "MGC": 4000.0, "SI": 48.0, "ES": 6500.0}[sym]
    r = _intake(sym, entry, entry * 0.99, entry * 1.02)
    d = r.decision
    assert "instrument_lot_metadata_unavailable" not in d.violations
    qty = d.quantity
    assert qty == qty.to_integral_value(), f"{sym}: fractional contracts {qty}"
    if qty > 0:
        assert d.notional_usd == qty * Decimal(str(entry)) * Decimal(str(spec.multiplier))
    else:
        assert "insufficient_remaining_room_for_one_lot" in d.violations
        assert d.control_plane_decision == "rejected_by_control_plane"


def test_one_gc_contract_exceeds_open_track_cap_and_is_rejected():
    # 1 GC at 4000 = $400,000 notional, far above the open-track position cap -> zero contracts, rejected.
    d = _intake("GC", 4000.0, 3960.0, 4080.0).decision
    assert d.quantity == 0
    assert d.control_plane_decision == "rejected_by_control_plane"
    assert "insufficient_remaining_room_for_one_lot" in d.violations


def test_mgc_is_one_tenth_of_gc_per_contract():
    gc, mgc = contract_for("GC"), contract_for("MGC")
    assert gc.notional(4000.0) == 10 * mgc.notional(4000.0)


def test_unknown_instrument_has_no_lot_metadata():
    d = _intake("ZZZ", 100.0, 99.0, 102.0).decision
    assert "instrument_lot_metadata_unavailable" in d.violations
    assert d.control_plane_decision == "rejected_by_control_plane"
