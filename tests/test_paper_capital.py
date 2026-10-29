"""Paper deposit, operator trade, and withdrawal. The ledger is the book."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app, control_engine
from atlas.capital.paper import (
    bind_paper_journal,
    capital_status,
    deposit_paper,
    replay_paper_capital,
    withdraw_paper,
)
from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.investment_intelligence.ledger import InvestmentPortfolioLedger
from atlas.strategies.base import StrategySignal
from atlas.strategies.range_garden import RangeGardenBook


def _book(tmp_path: Path):
    ledger = InvestmentPortfolioLedger(tmp_path / "paper.sqlite")
    engine = ActionableControlPlaneEngine()
    engine.unload_deposits()
    engine.link_research_hand({
        "genome_id": "model=ridge|features=full|regime=none|bar_type=time|context=htf",
        "can_buy": True,
        "can_sell": True,
    })
    bind_paper_journal(engine, ledger)
    return engine, ledger


def _cash_order(notional: str, *, price: float | None = 100.0, stop_bps: str = "180") -> ActionableOrderRequest:
    return ActionableOrderRequest(
        side="buy",
        notional_usd=Decimal(notional),
        stop_distance_bps=Decimal(stop_bps),
        reference_price=price,
    )


def test_same_day_deposits_of_the_same_amount_both_post(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    first = deposit_paper(engine, ledger, Decimal("100"))
    second = deposit_paper(engine, ledger, Decimal("100"))
    assert first["status"] == "deposited"
    assert second["status"] == "deposited"
    assert engine.cash_usd == Decimal("200.00")
    assert engine.current_equity_usd == Decimal("200.00")
    assert capital_status(engine, ledger)["ledger_cash_usd"] == "200.00"
    assert capital_status(engine, ledger)["transactions"] == 2


def test_deposit_trade_close_and_withdraw_round_trip(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposited = deposit_paper(engine, ledger, Decimal("1000"))
    assert deposited["deposits_loaded"] is True
    assert deposited["customer_custody"] is False
    assert deposited["live_withdrawal"] is False
    assert deposited["deposit_address"] is None
    assert deposited["execution_permission"] == "none"
    assert deposited["may_propose_order"] is False
    assert engine.research_hand["can_buy"] is False
    assert engine.research_hand["can_sell"] is False
    assert engine.active_champion_model == "none"

    too_large = engine.submit_order(_cash_order("1200", stop_bps="25"))
    assert too_large.control_plane_decision == "rejected_by_control_plane"
    assert "insufficient_paper_cash" in too_large.violations
    assert engine.cash_usd == Decimal("1000.00")
    assert engine.open_positions == []

    filled = engine.submit_order(_cash_order("400"))
    assert filled.control_plane_decision == "authorized_and_executed"
    assert engine.cash_usd == Decimal("600.00")
    assert engine.current_equity_usd == Decimal("1000.00")
    assert len([pos for pos in engine.open_positions if pos.status == "open"]) == 1

    blocked = withdraw_paper(engine, ledger, Decimal("700"))
    assert blocked["status"] == "refused"
    assert blocked["reason"] == "insufficient_paper_cash"
    assert engine.cash_usd == Decimal("600.00")

    pulled = withdraw_paper(engine, ledger, Decimal("100"))
    assert pulled["status"] == "withdrawn"
    assert engine.cash_usd == Decimal("500.00")
    assert engine.current_equity_usd == Decimal("900.00")
    assert engine.high_water_mark_usd >= engine.initial_equity_usd

    position_id = filled.position_id
    assert position_id is not None
    closed = engine.close_position(position_id, exit_price=110.0)
    assert closed["status"] == "closed"
    assert closed["execution_permission"] == "none"
    assert engine.cash_usd == Decimal("940.00")
    assert engine.current_equity_usd == Decimal("940.00")
    assert capital_status(engine, ledger)["ledger_cash_usd"] == "940.00"
    assert [pos for pos in engine.open_positions if pos.status == "open"] == []

    emptied = withdraw_paper(engine, ledger, Decimal("940"))
    assert emptied["status"] == "withdrawn"
    assert engine.deposits_loaded is False
    assert engine.cash_tracked is False
    assert engine.research_hand["genome_id"].startswith("model=ridge")
    assert engine.research_hand["can_buy"] is False
    refused = engine.submit_order(_cash_order("100"))
    assert "no_deposited_capital" in refused.violations


def test_replay_rebuilds_cash_and_the_open_position(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposit_paper(engine, ledger, Decimal("1000"))
    filled = engine.submit_order(_cash_order("400"))
    assert filled.position_id is not None

    restarted = ActionableControlPlaneEngine()
    restarted.unload_deposits()
    restarted.link_research_hand(dict(engine.research_hand))
    bind_paper_journal(restarted, ledger)
    replayed = replay_paper_capital(restarted, ledger)
    assert replayed["status"] == "replayed"
    assert restarted.cash_usd == Decimal("600.00")
    assert restarted.current_equity_usd == Decimal("1000.00")
    assert restarted.research_hand["can_buy"] is False
    open_positions = [pos for pos in restarted.open_positions if pos.status == "open"]
    assert len(open_positions) == 1
    assert open_positions[0].entry_price == 100.0
    closed = restarted.close_position(open_positions[0].position_id, exit_price=110.0)
    assert closed["status"] == "closed"
    assert restarted.cash_usd == Decimal("1040.00")
    assert capital_status(restarted, ledger)["ledger_cash_usd"] == "1040.00"


def test_flatten_returns_cash_and_the_garden_does_not_spend_it(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposit_paper(engine, ledger, Decimal("1000"))
    filled = engine.submit_order(_cash_order("200", stop_bps="25"))
    assert filled.control_plane_decision == "authorized_and_executed"
    assert engine.cash_usd == Decimal("800.00")
    engine.flatten_all_positions(reason="operator_test")
    assert engine.cash_usd == Decimal("1000.00")
    assert engine.current_equity_usd == Decimal("1000.00")
    assert [pos for pos in engine.open_positions if pos.status == "open"] == []

    decision = RangeGardenBook()._apply(
        engine,
        {"action": "harvest_buy", "symbol": "BTC-USD", "direction": "BUY"},
        now=datetime.now(timezone.utc),
    )
    assert decision["reason"] == "paper_capital_is_operator_only"
    assert [pos for pos in engine.open_positions if pos.status == "open"] == []


def test_strategy_signal_cannot_replace_paper_equity(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposit_paper(engine, ledger, Decimal("1000"))
    report = engine.process_strategy_signal(
        StrategySignal(
            symbol="BTC-USD",
            direction="BUY",
            suggested_stop_loss=90,
            suggested_take_profit=120,
            reference_price=100,
            target_entry_price=100,
        ),
        999999.0,
    )
    assert report.execution_permission == "none"
    assert report.decision.control_plane_decision == "authorized_and_executed"
    assert engine.current_equity_usd == Decimal("1000.00")
    assert engine.cash_usd < Decimal("1000.00")
    assert engine.research_hand["can_buy"] is False
    assert engine.research_hand["may_propose_order"] is False


def test_cash_book_books_the_ticket_notional_and_refuses_the_rest(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposit_paper(engine, ledger, Decimal("1000"))
    booked = engine.process_strategy_signal(
        StrategySignal(
            symbol="BTC-USD",
            direction="BUY",
            suggested_stop_loss=98.2,
            suggested_take_profit=103.6,
            reference_price=100,
            target_entry_price=100,
            telemetry={"desired_notional_usd": "400.00"},
        ),
        1000.0,
    )
    assert booked.decision.control_plane_decision == "authorized_and_executed"
    assert booked.decision.notional_usd == Decimal("400.00")
    assert booked.decision.position_id == "pos-002"
    assert engine.cash_usd == Decimal("600.00")
    assert engine.research_hand["can_buy"] is False

    refused = engine.process_strategy_signal(
        StrategySignal(
            symbol="ETH-USD",
            direction="BUY",
            suggested_stop_loss=98.2,
            suggested_take_profit=103.6,
            reference_price=100,
            target_entry_price=100,
            telemetry={"desired_notional_usd": "1200.00"},
        ),
        1000.0,
    )
    assert refused.decision.control_plane_decision == "rejected_by_control_plane"
    assert "insufficient_paper_cash" in refused.decision.violations
    assert engine.cash_usd == Decimal("600.00")
    assert len([pos for pos in engine.open_positions if pos.status == "open"]) == 1


def test_a_model_signal_cannot_spend_paper_cash(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    deposit_paper(engine, ledger, Decimal("1000"))
    report = engine.ingest_whale_policy_signal(
        StrategySignal(
            symbol="BTC-USD",
            direction="BUY",
            suggested_stop_loss=98.2,
            suggested_take_profit=103.6,
            reference_price=100,
            target_entry_price=100,
        )
    )
    assert report.execution_permission == "none"
    assert report.decision.control_plane_decision == "rejected_by_control_plane"
    assert "research_model_cannot_order" in report.decision.violations
    assert engine.cash_usd == Decimal("1000.00")
    assert [pos for pos in engine.open_positions if pos.status == "open"] == []
    assert engine.research_hand["can_buy"] is False


def test_an_empty_book_tick_does_not_trip_the_kill_switch() -> None:
    engine = ActionableControlPlaneEngine()
    engine.unload_deposits()
    report = engine.evaluate_market_tick(symbol="BTC-USD", price=100.0, latency_ms=1.0)
    assert report["kill_switch_engaged"] is False
    assert report["auto_flattened"] is False
    assert engine.kill_switch_engaged is False


def test_funded_demo_book_refuses_a_paper_deposit(tmp_path: Path) -> None:
    engine = ActionableControlPlaneEngine()
    ledger = InvestmentPortfolioLedger(tmp_path / "paper.sqlite")
    refused = deposit_paper(engine, ledger, Decimal("1000"))
    assert refused["status"] == "refused"
    assert refused["reason"] == "paper_capital_requires_unfunded_or_tracked_book"
    assert engine.current_equity_usd == Decimal("101850")
    assert engine.cash_tracked is False


def test_another_account_does_not_fund_the_desk(tmp_path: Path) -> None:
    engine, ledger = _book(tmp_path)
    ledger.record_transaction(
        tenant_id="default_workspace",
        account_id="default_workspace_core_multi_asset",
        tx_type="DEPOSIT",
        trade_date="2026-10-28",
        gross_amount=100000.0,
        source_provenance="manual_user_entry",
    )
    replay_paper_capital(engine, ledger)
    assert engine.deposits_loaded is False
    assert engine.cash_usd == Decimal("0")


def test_http_deposit_does_not_change_the_funded_test_engine(tmp_path: Path) -> None:
    equity = control_engine.current_equity_usd
    positions = len(control_engine.open_positions)
    client = TestClient(app)
    response = client.post("/api/capital/deposit", json={"amount_usd": "1000.00"})
    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "paper_capital_requires_unfunded_or_tracked_book"
    assert control_engine.current_equity_usd == equity
    assert len(control_engine.open_positions) == positions
    assert tmp_path is not None
