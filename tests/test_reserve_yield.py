"""Reserve sleeve is a paper target. Calling it does not submit an order."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from atlas.api.app import app, control_engine
from atlas.marketdata.tradingview import tradingview_symbol
from atlas.strategies.reserve_yield import build_reserve_plan, tax_equivalent_yield


def test_sweep_weights_sum_to_one_and_tey_uses_one_minus_marginal_rate() -> None:
    plan = build_reserve_plan(distributable_usd=2950, distribution_yields={"MUB": 0.04})
    weights = sum(
        (Decimal(str(row["sweep_weight"])) for row in plan["holdings"] if row["in_sweep"]),
        Decimal("0"),
    )
    targets = sum(
        (Decimal(str(row["target_usd"])) for row in plan["holdings"] if row["in_sweep"]),
        Decimal("0"),
    )
    assert weights == Decimal("1")
    assert targets == Decimal("2950.00")
    mub = next(row for row in plan["holdings"] if row["symbol"] == "MUB")
    assert mub["sleeve"] == "munis"
    assert mub["tax_equivalent_yield"] == 0.04 / (1 - 0.37)
    assert mub["tradingview_symbol"] == "AMEX:MUB"
    sgov = next(row for row in plan["holdings"] if row["symbol"] == "SGOV")
    assert sgov["sleeve"] == "tbills"
    assert sgov["tradingview_symbol"] == "NYSE:SGOV"
    assert sgov["tax_equivalent_yield"] is None
    shy = next(row for row in plan["holdings"] if row["symbol"] == "SHY")
    assert shy["in_sweep"] is False
    assert shy["target_usd"] == "0.00"
    assert shy["tradingview_symbol"] == "NASDAQ:SHY"
    assert plan["orders_submitted"] == 0
    assert plan["execution_permission"] == "none"
    assert plan["yield_observation"] == "caller_supplied_distribution_yield"
    assert plan["track"] == "reserve_yield"


def test_invalid_rate_and_zero_profit_stay_a_plan() -> None:
    assert tax_equivalent_yield(0.04, 1.0) is None
    assert tax_equivalent_yield(0.04, -0.1) is None
    assert tax_equivalent_yield(-0.01, 0.37) is None
    bare = build_reserve_plan(distributable_usd=0, marginal_rate=1.5)
    assert bare["distributable_usd"] == "0.00"
    assert bare["marginal_tax_rate"] == 0.37
    assert bare["orders_submitted"] == 0
    assert bare["yield_observation"] == "unobserved"
    assert all(row["target_usd"] == "0.00" for row in bare["holdings"])
    assert all(row["execution_permission"] == "none" for row in bare["holdings"])


def test_http_plan_leaves_the_seed_position_open() -> None:
    client = TestClient(app)
    before_orders = len(control_engine.order_history)
    before_open = [
        (position.position_id, position.status)
        for position in control_engine.open_positions
    ]
    seed_open_before = any(
        position_id == "pos-001" and status == "open" for position_id, status in before_open
    )
    response = client.get("/api/strategies/reserve-yield")
    assert response.status_code == 200
    body = response.json()
    assert body["path_id"] == "reserve-yield:v1"
    assert body["orders_submitted"] == 0
    assert body["execution_permission"] == "none"
    assert body["seed_position_open"] is seed_open_before
    assert body["distributable_usd"] == "2950.00"
    assert body["yield_observation"] == "unobserved"
    assert body["venues_unconfigured"] == ["msrb_emma", "finra_trace", "ibkr_bond_scanner"]
    assert tradingview_symbol("MUB") == "AMEX:MUB"
    assert tradingview_symbol("SGOV") == "NYSE:SGOV"
    assert tradingview_symbol("SHY") == "NASDAQ:SHY"

    state = client.get("/api/control/state")
    assert state.status_code == 200
    positions = state.json()["open_positions"]
    reported_seed = any(row["position_id"] == "pos-001" and row["status"] == "open" for row in positions)
    assert reported_seed is seed_open_before
    assert [
        (position.position_id, position.status) for position in control_engine.open_positions
    ] == before_open
    assert len(control_engine.order_history) == before_orders
