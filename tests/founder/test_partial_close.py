"""Reduce-only partial close in the deterministic control plane (pass 10)."""
from decimal import Decimal

from atlas.autopilot.setups import SetupAutopilot  # noqa: F401  (import path sanity)
from tests.autopilot_setups.test_setup_autopilot import BARS, END, _ap, _on
from tests.price_action.test_predict import synthetic_setup_registry


def _open(tmp_path):
    ap = _ap(tmp_path, registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1"); _on(ap)
    ap.tick(BARS[-1].start)      # fill bar has closed; the target bar has not
    return ap


def test_partial_close_reduce_only_and_frees_exposure(tmp_path):
    ap = _open(tmp_path)
    cp = ap.cp
    pos = next((p for p in cp.open_positions if p.status == "open"), None)
    if pos is None:
        import pytest; pytest.skip("fixture produced no open position at this bar")
    n0, g0 = pos.notional_usd, cp.gross_notional_usd
    for bad in (0.0, -0.1, 1.5, float("nan")):
        assert cp.close_position(pos.position_id, exit_price=100.0, fraction=bad)["reason"] == "invalid_fraction_reduce_only"
    r = cp.close_position(pos.position_id, exit_price=100.0, fraction=0.25, reason="test_reduce")
    assert r["status"] == "reduced" and r["remaining_notional_usd"] < float(n0)
    p2 = next(p for p in cp.open_positions if p.position_id == pos.position_id)
    assert p2.status == "open" and p2.notional_usd < n0 and cp.gross_notional_usd < g0
    assert any("position_reduced" in a for a in cp.audit_log)
    r2 = cp.close_position(pos.position_id, exit_price=100.0)
    assert r2["status"] == "closed" and r2["closed_notional_usd"] == float(p2.notional_usd)
