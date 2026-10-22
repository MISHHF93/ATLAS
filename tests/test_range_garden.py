"""Range garden watches every print and papers a bracket only when the rail pays."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from atlas.api.app import app, control_engine
from atlas.control.engine import ActionableControlPlaneEngine
from atlas.strategies.range_garden import (
    PATH_ID,
    RangeGardenBook,
    RangeGardenStrategy,
    evaluate_range_garden,
)


NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


def _bed(n: int = 80, low: float = 100.0, high: float = 110.0) -> list[dict[str, float]]:
    bars: list[dict[str, float]] = []
    for index in range(n):
        close = low + 0.2 if index % 2 == 0 else high - 0.2
        bars.append({"open": close, "high": high, "low": low, "close": close})
    return bars


def _print(
    price: float,
    *,
    age_ms: float,
    now: datetime = NOW,
    mode: str = "public_last_trade",
    origin: str = "coinbase_exchange_public",
) -> dict[str, object]:
    return {
        "price": price,
        "observed_at": (now - timedelta(milliseconds=age_ms)).isoformat(),
        "data_mode": mode,
        "feed_origin": origin,
        "bid": price - 0.01,
        "ask": price + 0.01,
    }


def test_middle_of_the_bed_is_a_watch_and_a_thin_box_stands_down() -> None:
    inside = evaluate_range_garden(
        symbol="BTC-USD",
        candles=_bed(),
        last_price=105.0,
        data_mode="public_last_trade",
        feed_origin="coinbase_exchange_public",
        data_age_ms=40,
    )
    assert inside["action"] == "watch"
    assert inside["reason"] == "inside_bed"
    assert inside["execution_permission"] == "none"
    assert inside["direction"] == "HOLD"

    thin = evaluate_range_garden(
        symbol="BTC-USD",
        candles=_bed(low=100.0, high=100.08),
        last_price=100.01,
        data_mode="public_last_trade",
        feed_origin="coinbase_exchange_public",
        data_age_ms=40,
    )
    assert thin["action"] == "stand_down"
    assert thin["reason"] == "range_does_not_pay"


def test_stale_or_synthetic_rail_does_not_become_an_order() -> None:
    stale = evaluate_range_garden(
        symbol="BTC-USD",
        candles=_bed(),
        last_price=100.4,
        data_mode="public_last_trade",
        feed_origin="coinbase_exchange_public",
        data_age_ms=5_000,
    )
    assert stale["action"] == "stand_down"
    assert stale["blocked_action"] == "harvest_buy"
    assert stale["reason"] == "print_older_than_track_limit"

    synthetic = evaluate_range_garden(
        symbol="ETH-USD",
        candles=_bed(),
        last_price=100.4,
        data_mode="demo",
        feed_origin="labeled_synthetic_fixture",
        data_age_ms=20,
    )
    assert synthetic["blocked_action"] == "harvest_buy"
    assert synthetic["reason"] == "synthetic_or_unlabeled_print"

    equity = evaluate_range_garden(
        symbol="NVDA",
        candles=_bed(),
        last_price=100.4,
        data_mode="public_market_candles",
        feed_origin="yahoo_chart_public",
        data_age_ms=30_000,
    )
    assert equity["track"] == "open_market"
    assert equity["action"] == "stand_down"
    assert equity["blocked_action"] == "harvest_buy"
    assert equity["fresh_limit_ms"] == 2000.0


def test_reader_never_emits_an_order() -> None:
    signal = RangeGardenStrategy().generate_signal(_bed(), {}, {"spot_price": 100.4})
    assert signal.direction == "HOLD"
    assert signal.execution_permission == "none"
    assert signal.strategy_id == "STRAT_RANGE_GARDEN"


def test_fresh_rail_opens_one_paper_bracket_and_the_target_closes_it() -> None:
    engine = ActionableControlPlaneEngine()
    book = RangeGardenBook()
    candles = {"BTC-USD": _bed()}
    opened = book.run_cycle(
        engine,
        gateway=None,
        now=NOW,
        prints={"BTC-USD": _print(100.4, age_ms=80)},
        candles=candles,
        allow_network=False,
    )
    assert opened["path_id"] == PATH_ID
    assert opened["orders_submitted"] == 1
    assert opened["execution_permission"] == "none"
    btc = next(row for row in opened["symbols"] if row["symbol"] == "BTC-USD")
    assert btc["action"] == "harvest_buy"
    assert btc["control_plane_decision"] == "authorized_and_executed"
    assert any(pos.position_id == "pos-001" and pos.status == "open" for pos in engine.open_positions)
    garden_open = [pos for pos in engine.open_positions if pos.status == "open" and pos.position_id != "pos-001"]
    assert len(garden_open) == 1

    held_at = NOW + timedelta(seconds=1)
    again = book.run_cycle(
        engine,
        gateway=None,
        now=held_at,
        prints={"BTC-USD": _print(100.4, age_ms=90, now=held_at)},
        candles=candles,
        allow_network=False,
    )
    assert again["orders_submitted"] == 1
    held = next(row for row in again["symbols"] if row["symbol"] == "BTC-USD")
    assert held["action"] == "watch"
    assert held["reason"] == "tending_open_bracket"

    exit_at = NOW + timedelta(seconds=2)
    closed = book.run_cycle(
        engine,
        gateway=None,
        now=exit_at,
        prints={"BTC-USD": _print(110.4, age_ms=70, now=exit_at)},
        candles=candles,
        allow_network=False,
    )
    done = next(row for row in closed["symbols"] if row["symbol"] == "BTC-USD")
    assert done["action"] == "close_long"
    assert done["reason"] == "target"
    assert closed["harvests_closed"] == 1
    assert closed["realized_pnl_usd"] > 0
    assert all(pos.position_id != garden_open[0].position_id or pos.status == "closed" for pos in engine.open_positions)
    assert any(pos.position_id == "pos-001" and pos.status == "open" for pos in engine.open_positions)


def test_kill_switch_blocks_a_fresh_harvest() -> None:
    engine = ActionableControlPlaneEngine()
    engine.set_kill_switch(True, reason="test", now=NOW)
    book = RangeGardenBook()
    report = book.run_cycle(
        engine,
        gateway=None,
        now=NOW,
        prints={"SOL-USD": _print(100.4, age_ms=50)},
        candles={"SOL-USD": _bed()},
        allow_network=False,
    )
    sol = next(row for row in report["symbols"] if row["symbol"] == "SOL-USD")
    assert sol["action"] == "stand_down"
    assert sol["reason"] == "kill_switch_engaged"
    assert report["orders_submitted"] == 0


def test_close_unknown_position_does_not_touch_equity() -> None:
    engine = ActionableControlPlaneEngine()
    before = engine.current_equity_usd
    rejected = engine.close_position("pos-missing", exit_price=10, fee_usd=Decimal("1"))
    assert rejected["status"] == "rejected"
    assert engine.current_equity_usd == before


def test_http_cycle_on_the_fixture_tape_submits_nothing() -> None:
    client = TestClient(app)
    before_equity = control_engine.current_equity_usd
    before_orders = len(control_engine.order_history)
    status = client.get("/api/strategies/range-garden")
    assert status.status_code == 200
    assert status.json()["path_id"] == PATH_ID
    assert status.json()["execution_permission"] == "none"

    forbidden = client.post("/api/strategies/range-garden/cycle", headers={"X-Atlas-Role": "quant_researcher"})
    assert forbidden.status_code == 403

    cycle = client.post("/api/strategies/range-garden/cycle")
    assert cycle.status_code == 200
    body = cycle.json()
    assert body["orders_submitted"] == 0
    assert body["execution_mode"] == "paper"
    assert control_engine.current_equity_usd == before_equity
    assert len(control_engine.order_history) == before_orders
    assert any(pos.position_id == "pos-001" and pos.status == "open" for pos in control_engine.open_positions)
