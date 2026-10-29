"""Island coordinator: a closed venue cannot outrank an open one, and abstain is allowed."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from atlas.ai.ml import market_islands as I

ET = ZoneInfo("America/New_York")


def test_split_assigns_venues_and_drops_unknown():
    df = pd.DataFrame({"instrument": ["BTCUSDT", "PEPEUSDT", "SPY", "ES", "EUR_USD", "NOPE??", "PUMP:abc"]})
    parts = I.split_islands(df)
    assert list(parts["CRYPTO_24_7"]["instrument"]) == ["BTCUSDT", "PEPEUSDT"]
    assert list(parts["US_EQUITIES_ETFS"]["instrument"]) == ["SPY"]
    assert list(parts["CME_COMEX_FUTURES"]["instrument"]) == ["ES"]
    assert "GLOBAL_FX" in parts
    assert all("NOPE" not in parts[k]["instrument"].tolist() for k in parts)


def test_closed_island_cannot_win_and_abstain_is_cash():
    reports = [
        {"island": "US_EQUITIES_ETFS", "genome_id": "eq", "n_rows": 100,
         "metrics": {"beats_baseline": True, "fitness": 0.9, "strict_gate": {"passed": True}}},
        {"island": "CRYPTO_24_7", "genome_id": "cr", "n_rows": 100,
         "metrics": {"beats_baseline": True, "fitness": 0.1, "strict_gate": {"passed": False}}},
    ]
    pick = I.coordinate(reports, {"CRYPTO_24_7"})
    assert pick["decision"] == "research_candidate" and pick["island"] == "CRYPTO_24_7"
    assert pick["execution_permission"] == "none" and pick["closes_other_positions"] is False
    none = I.coordinate([
        {"island": "CRYPTO_24_7", "metrics": {"beats_baseline": False, "fitness": 1.0}},
    ], {"CRYPTO_24_7"})
    assert none["decision"] == "abstain" and none["island"] is None


def test_strict_pass_outranks_a_higher_fitness_baseline():
    reports = [
        {"island": "CRYPTO_24_7", "genome_id": "loose", "metrics": {"beats_baseline": True, "fitness": 5.0, "strict_gate": {"passed": False}}},
        {"island": "GLOBAL_FX", "genome_id": "strict", "metrics": {"beats_baseline": True, "fitness": 0.2, "strict_gate": {"passed": True}}},
    ]
    pick = I.coordinate(reports, {"CRYPTO_24_7", "GLOBAL_FX"})
    assert pick["genome_id"] == "strict" and pick["strict"] is True


def test_open_islands_follow_the_clock():
    wednesday = datetime(2026, 10, 28, 15, 0, tzinfo=ET)
    open_wd = I.open_islands(wednesday)
    assert {"CRYPTO_24_7", "US_EQUITIES_ETFS", "CME_COMEX_FUTURES", "GLOBAL_FX", "CANADA_TSX"} <= open_wd
    saturday = datetime(2026, 10, 24, 12, 0, tzinfo=ET)
    assert I.open_islands(saturday) == {"CRYPTO_24_7"}
    # Before the published launch, 22:30 ET is not an equity session.
    early = datetime(2026, 12, 2, 22, 30, tzinfo=ET)
    assert "US_EQUITIES_ETFS" not in I.open_islands(early)
    # Launch Sunday 21:30 ET admits the night session. The 20:30 pause does not.
    assert "US_EQUITIES_ETFS" in I.open_islands(datetime(2026, 12, 6, 21, 30, tzinfo=ET))
    pause = I.session_snapshot(datetime(2026, 12, 7, 20, 30, tzinfo=ET))
    assert pause["US_EQUITIES_ETFS"]["admitted"] is False
    assert pause["CRYPTO_24_7"]["admitted"] is True
    assert pause["CME_COMEX_FUTURES"]["admitted"] is True


def test_evolve_islands_keeps_permission_none(monkeypatch):
    def fake_evolve(frame, meta, **kwargs):
        return {"best": {"genome_id": meta["island"], "metrics": {"status": "ok", "beats_baseline": False, "fitness": -0.1}},
                "best_beating_baseline": None, "best_passing_strict_gate": None,
                "no_model_beats_baseline": True, "no_model_passes_strict_gate": True}

    monkeypatch.setattr("atlas.ai.ml.evolution.evolve", fake_evolve)
    out = I.evolve_islands(pd.DataFrame({"instrument": ["BTCUSDT", "SPY"]}), {})
    assert out["promoted_to_execution"] is False and out["execution_permission"] == "none"
    assert out["strict_passes"] == []
    assert {r["island"] for r in out["islands"]} == {"CRYPTO_24_7", "US_EQUITIES_ETFS"}


def test_evolve_islands_returns_only_a_strict_pass(monkeypatch):
    def fake_evolve(frame, meta, **kwargs):
        passed = meta["island"] == "CRYPTO_24_7"
        genome = {"genome_id": meta["island"], "metrics": {"status": "ok", "beats_baseline": True, "fitness": 0.2,
                                                           "strict_gate": {"passed": passed}}}
        return {"best": genome, "best_beating_baseline": genome,
                "best_passing_strict_gate": genome if passed else None,
                "no_model_beats_baseline": False, "no_model_passes_strict_gate": not passed,
                "leaderboard": [genome], "data": {"data_hash": "h"}, "seed": 1, "generations": 1, "by_bar_type": {}}

    monkeypatch.setattr("atlas.ai.ml.evolution.evolve", fake_evolve)
    out = I.evolve_islands(pd.DataFrame({"instrument": ["BTCUSDT", "SPY"]}), {})
    assert [r["best_passing_strict_gate"]["genome_id"] for r in out["strict_passes"]] == ["CRYPTO_24_7"]
    assert out["promoted_to_execution"] is False
