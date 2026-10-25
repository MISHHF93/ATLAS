"""Daily trend ledger: causal forecasts, abstentions, and a proof bar that does not send an order."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.models.live_training import COMPETITION_SYMBOLS, OPEN_MARKET_SYMBOLS
from atlas.models.outcome_ledger import (
    COMPETITION_SYMBOLS as LEDGER_COMPETITION,
    OPEN_MARKET_SYMBOLS as LEDGER_OPEN,
    build_outcome_ledger,
    combine_stance,
)


def _candles(closes: list[float]) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {"timestamp": (start + timedelta(days=index)).isoformat(), "close": price}
        for index, price in enumerate(closes)
    ]


def _frame(symbol: str, closes: list[float], *, data_mode: str = "public_market_candles") -> dict[str, object]:
    track = "competition" if symbol.endswith("-USD") else "open_market"
    return {
        "symbol": symbol,
        "track": track,
        "data_mode": data_mode,
        "feed_origin": "test_public" if data_mode == "public_market_candles" else "labeled_synthetic_fixture",
        "candles": _candles(closes),
    }


def test_stance_abstains_when_the_filter_is_unsure_or_disagrees() -> None:
    assert combine_stance("BUY", 0.70) == ("research_long", None)
    assert combine_stance("SELL", 0.20) == ("research_short", None)
    assert combine_stance("BUY", 0.20) == ("abstain", "disagreed")
    assert combine_stance("SELL", 0.80) == ("abstain", "disagreed")
    assert combine_stance("BUY", 0.50) == ("abstain", "uncertain")
    assert combine_stance("FLAT", 0.90) == ("abstain", "no_trend")
    assert combine_stance("BUY", None) == ("abstain", "filter_not_fit")


def test_flat_tape_abstains_and_a_later_close_does_not_change_the_prior_stance() -> None:
    flat = build_outcome_ledger([_frame("BTC-USD", [100.0] * 40)])
    assert flat["orders_submitted"] == 0
    assert flat["execution_permission"] == "none"
    assert flat["may_propose_order"] is False
    assert all(row["stance"] == "abstain" and row["abstain_reason"] == "no_trend" for row in flat["decisions"])
    assert all(row["net_return"] is None for row in flat["decisions"])
    assert sum(1 for row in flat["decisions"] if row["status"] == "open") == 1

    rising = [100.0 + index for index in range(40)]
    first = build_outcome_ledger([_frame("BTC-USD", rising)])
    spiked = list(rising)
    spiked[31] = 1000.0
    second = build_outcome_ledger([_frame("BTC-USD", spiked)])
    prior = next(row for row in first["decisions"] if row["decision_timestamp"].startswith("2024-01-31"))
    again = next(row for row in second["decisions"] if row["decision_timestamp"].startswith("2024-01-31"))
    assert prior["primary_side"] == "BUY"
    assert again["primary_side"] == prior["primary_side"]
    assert again["filter_probability"] == prior["filter_probability"]
    assert again["stance"] == prior["stance"]
    if prior["net_return"] is not None:
        gross = rising[31] / rising[30] - 1.0
        signed = gross if prior["primary_side"] == "BUY" else -gross
        assert prior["net_return"] == round(signed - 0.0016, 8)
        assert again["net_return"] != prior["net_return"]


def test_cost_is_charged_only_on_a_taken_stance_and_fixtures_do_not_count() -> None:
    report = build_outcome_ledger([_frame("NVDA", [100.0 + index * 0.5 for index in range(50)])])
    taken = [row for row in report["decisions"] if row["status"] == "resolved" and row["stance"] != "abstain"]
    abstained = [row for row in report["decisions"] if row["status"] == "resolved" and row["stance"] == "abstain"]
    assert taken
    assert all(row["net_return"] is None for row in abstained)
    if taken:
        row = taken[0]
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        index = (datetime.fromisoformat(row["decision_timestamp"]) - start).days
        entry = 100.0 + index * 0.5
        exit_price = 100.0 + (index + 1) * 0.5
        signed = (exit_price / entry - 1.0) if row["primary_side"] == "BUY" else -(exit_price / entry - 1.0)
        assert row["net_return"] == round(signed - 0.0004, 8)
        assert row["counts_toward_proof"] is True

    fixture = build_outcome_ledger(
        [_frame("NVDA", [100.0 + index for index in range(90)], data_mode="synthetic_fixture_training")]
    )
    assert fixture["tracks"]["open_market"]["judgment"] == "too_few_to_judge"
    assert fixture["tracks"]["open_market"]["public_resolved_stances"] == 0
    assert fixture["tracks"]["competition"]["judgment"] == "too_few_to_judge"


def test_one_open_forecast_per_symbol_and_tracks_stay_separate() -> None:
    report = build_outcome_ledger(
        [
            _frame("BTC-USD", [100.0 + index for index in range(30)]),
            _frame("ETH-USD", [50.0 + index for index in range(30)]),
            _frame("SPY", [400.0 + index for index in range(30)]),
        ]
    )
    opens = report["open_forecasts"]
    assert len(opens) == 3
    assert len({row["symbol"] for row in opens}) == 3
    assert all(row["horizon_id"] == "next_daily_close" for row in opens)
    assert report["tracks"]["competition"]["public_resolved_stances"] < 60
    assert report["tracks"]["competition"]["judgment"] == "too_few_to_judge"
    assert "decisions" in report
    assert LEDGER_COMPETITION == COMPETITION_SYMBOLS
    assert LEDGER_OPEN == OPEN_MARKET_SYMBOLS


def test_outcome_ledger_route_submits_nothing() -> None:
    source = Path("src/atlas/ai/models/outcome_ledger.py").read_text(encoding="utf-8")
    assert "submit_order" not in source
    assert "process_strategy_signal" not in source
    assert "ActionableControlPlane" not in source
    assert "import lightgbm" not in source
    assert "import xgboost" not in source
    assert "import sklearn" not in source

    client = TestClient(app)
    response = client.get("/api/research/outcome-ledger")
    assert response.status_code == 200
    body = response.json()
    assert body["execution_permission"] == "none"
    assert body["orders_submitted"] == 0
    assert body["may_propose_order"] is False
    assert set(body["tracks"]) == {"competition", "open_market"}
    assert body["tracks"]["competition"]["judgment"] == "too_few_to_judge"
    assert body["tracks"]["competition"]["reliability"]["execution"] == "not_attempted"
    assert body["tracks"]["open_market"]["reliability"]["execution_permission"] == "none"
    assert "submit_order" not in response.text


def test_reliability_keeps_direction_confidence_and_execution_apart() -> None:
    from atlas.models.outcome_ledger import _reliability

    closes = [100.0 + index * 0.01 for index in range(80)]
    report = build_outcome_ledger([_frame("NVDA", closes)])
    reliability = report["tracks"]["open_market"]["reliability"]
    taken = [row for row in report["decisions"] if row["counts_toward_proof"]]
    assert reliability["execution"] == "not_attempted"
    assert reliability["direction_attempts"] == len(taken)
    assert taken
    assert reliability["direction_hit_rate"] == 1.0
    assert all(row["net_return"] < 0 for row in taken)
    assert report["tracks"]["open_market"]["judgment"] == "too_few_to_judge"

    rows = []
    pattern = ((0.9, True), (0.1, False), (0.8, True))
    for index, (probability, up) in enumerate(pattern * 12):
        rows.append(
            {
                "status": "resolved",
                "data_mode": "public_market_candles",
                "counts_toward_proof": False,
                "stance": "abstain",
                "primary_side": "BUY",
                "entry_close": 100.0,
                "exit_close": 101.0 if up else 99.0,
                "filter_probability": probability,
                "symbol": "NVDA",
                "decision_timestamp": f"2024-01-{index + 1:02d}",
            }
        )
    rows.append(
        {
            "status": "resolved",
            "data_mode": "synthetic_fixture_training",
            "counts_toward_proof": False,
            "stance": "abstain",
            "primary_side": "BUY",
            "entry_close": 100.0,
            "exit_close": 50.0,
            "filter_probability": 0.99,
            "symbol": "NVDA",
        }
    )
    scored = _reliability(rows)
    assert scored["confidence"] == "scored"
    assert scored["calibration_rows"] == 36
    assert scored["brier_score"] == round((0.01 + 0.01 + 0.04) / 3, 6)
    assert scored["direction_attempts"] == 0
    assert scored["execution"] == "not_attempted"
    assert scored["bins"][4]["count"] == 24
    assert scored["bins"][0]["observed_up_rate"] == 0.0
