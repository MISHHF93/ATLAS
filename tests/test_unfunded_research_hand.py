"""The live desk names a research hand and cannot buy or sell without a deposit."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from atlas.api.app import _arm_unfunded_research_desk, control_engine
from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.investment_intelligence.ledger import InvestmentPortfolioLedger
from atlas.ml.evolution import research_hand
from atlas.strategies.base import StrategySignal


def test_auto_seed_does_not_invent_a_deposit_and_explicit_seed_still_works(tmp_path: Path) -> None:
    ledger = InvestmentPortfolioLedger(tmp_path / "ledger.sqlite")
    ledger.ensure_pilot_seeded("default_workspace")
    assert ledger.list_transactions(tenant_id="default_workspace") == []

    seeded = ledger.seed_pilot_portfolio(tenant_id="tenant_alpha")
    assert seeded["inserted_count"] == 12
    ledger.seed_pilot_portfolio(tenant_id="default_workspace")
    removed = ledger.drop_seeded_deposit_book("default_workspace")
    assert removed["transactions"] == 12
    assert removed["accounts"] == 1
    assert ledger.list_transactions(tenant_id="default_workspace") == []
    assert len(ledger.list_transactions(tenant_id="tenant_alpha")) == 12

    again = ledger.seed_pilot_portfolio(tenant_id="tenant_alpha")
    assert again["inserted_count"] == 0
    assert again["deduplicated_count"] == 12


def test_funded_constructor_keeps_the_demo_book_for_existing_tests() -> None:
    engine = ActionableControlPlaneEngine()
    assert engine.deposits_loaded is True
    assert engine.current_equity_usd == Decimal("101850")
    assert any(pos.position_id == "pos-001" and pos.status == "open" for pos in engine.open_positions)


def test_pytest_startup_does_not_unload_the_shared_engine() -> None:
    equity = control_engine.current_equity_usd
    positions = [(pos.position_id, pos.status) for pos in control_engine.open_positions]
    _arm_unfunded_research_desk()
    assert control_engine.current_equity_usd == equity
    assert [(pos.position_id, pos.status) for pos in control_engine.open_positions] == positions


def test_unfunded_engine_refuses_buy_and_sell_and_ignores_caller_equity() -> None:
    engine = ActionableControlPlaneEngine()
    engine.unload_deposits()
    engine.link_research_hand({
        "genome_id": "model=ridge|features=full|regime=none|bar_type=time|context=htf",
        "strict_gate_passed": False,
        "can_buy": True,
        "can_sell": True,
    })
    assert engine.deposits_loaded is False
    assert engine.current_equity_usd == Decimal("0")
    assert engine.open_positions == []
    assert engine.active_champion_model == "none"
    assert engine.research_hand["can_buy"] is False
    assert engine.research_hand["can_sell"] is False
    assert engine.research_hand["execution_permission"] == "none"
    assert engine.research_hand["promoted_to_execution"] is False
    state = engine.get_state()
    assert state.deposits_loaded is False
    assert state.account.current_equity_usd == Decimal("0")
    assert "no_deposited_capital" in state.rule_evaluation.violations

    buy = engine.submit_order(ActionableOrderRequest(side="buy", notional_usd=Decimal("1000")))
    sell = engine.submit_order(ActionableOrderRequest(side="sell", notional_usd=Decimal("1000")))
    assert buy.control_plane_decision == "rejected_by_control_plane"
    assert sell.control_plane_decision == "rejected_by_control_plane"
    assert "no_deposited_capital" in buy.violations
    assert "no_deposited_capital" in sell.violations
    assert engine.open_positions == []

    report = engine.process_strategy_signal(
        StrategySignal(
            symbol="BTC-USD",
            direction="BUY",
            suggested_stop_loss=90,
            suggested_take_profit=120,
            reference_price=100,
            target_entry_price=100,
        ),
        101850.0,
    )
    assert report.execution_permission == "none"
    assert report.decision.control_plane_decision == "rejected_by_control_plane"
    assert "no_deposited_capital" in report.decision.violations
    assert engine.current_equity_usd == Decimal("0")
    assert engine.open_positions == []

    engine.apply_lifecycle_action("approve_challenger")
    engine.apply_lifecycle_action("promote_challenger")
    assert engine.challenger_approved is False
    assert engine.active_champion_model == "none"


def test_research_hand_names_the_newest_genome_and_writes_nothing(tmp_path: Path) -> None:
    evo = tmp_path / "evolution"
    evo.mkdir()
    (evo / "run_old.json").write_text(json.dumps({
        "created_at": 10,
        "run_id": "run_old",
        "decision": "no_challenger_passes_strict_gate",
        "no_model_beats_baseline": False,
        "best_beating_baseline": {
            "genome_id": "model=logit|features=full|regime=none|bar_type=time|context=none",
            "metrics": {"beats_baseline": True, "strict_gate": {"passed": False, "failed": ["dsr"]}},
        },
    }))
    (evo / "niches_new.json").write_text(json.dumps({
        "created_at": 20,
        "islands": [{
            "genome_id": "model=ridge|features=full|regime=none|bar_type=time|context=htf",
            "no_model_beats_baseline": False,
            "metrics": {
                "beats_baseline": True,
                "ev_r_per_opportunity": 0.016,
                "strict_gate": {"passed": False, "failed": ["min_trades_per_fold", "dsr", "bonferroni"]},
            },
        }],
        "selection": {"decision": "abstain", "reason": "no open niche has an elite that beats its own baseline"},
    }))
    hand = research_hand(tmp_path)
    assert hand["source"] == "niches_new.json"
    assert hand["genome_id"] == "model=ridge|features=full|regime=none|bar_type=time|context=htf"
    assert hand["stance"] == "abstain"
    assert hand["linked"] is True
    assert hand["can_buy"] is False
    assert hand["can_sell"] is False
    assert hand["strict_gate_passed"] is False
    assert hand["research_champion"] is False
    assert hand["promoted_to_execution"] is False
    assert hand["may_propose_order"] is False
    assert not (evo / "champion.json").exists()
