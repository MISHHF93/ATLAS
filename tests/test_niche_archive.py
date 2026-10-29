"""MAP-Elites niches: one specialist per venue, session and volatility. No borrowed fitness."""
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml import niche_archive as N
from atlas.ai.ml.selector import session_bucket

ET = ZoneInfo("America/New_York")


def _frame(instrument, hour, vol, n=40, seed=0):
    rng = np.random.default_rng(seed)
    # 2026-10-28 is a Wednesday. Hour is America/New_York.
    start = datetime(2026, 10, 28, hour, 0, tzinfo=ET)
    t = int(start.timestamp()) + np.arange(n) * 60
    return pd.DataFrame({
        "instrument": instrument,
        "t": t,
        "rv_pctile_480": vol,
        "r": rng.normal(size=n),
    })


def _eval(frame, cell):
    fitness = 0.4 if "CRYPTO" in cell and cell.endswith("|high") else -0.2
    return {"genome_id": f"g-{cell}", "metrics": {"fitness": fitness, "beats_baseline": fitness > 0}}


def test_one_elite_per_cell_and_qd_score_keeps_losers():
    data = pd.concat([
        _frame("BTCUSDT", 15, 0.9, seed=1),   # ny_pm, high
        _frame("BTCUSDT", 6, 0.1, seed=2),    # london, low
        _frame("SPY", 15, 0.9, seed=3),
        _frame("SPY", 15, 0.9, n=5, seed=4),  # too few to form their own extra cell; same cell as SPY ny_pm
    ], ignore_index=True)
    # The 5-row block shares SPY's cell, so it is not skipped. Add a tiny other cell.
    tiny = _frame("ETHUSDT", 10, 0.5, n=5, seed=5)  # ny_am, mid
    data = pd.concat([data, tiny], ignore_index=True)
    archive = N.illuminate(data, _eval, min_rows=30)
    assert archive["promoted_to_execution"] is False
    assert any(s["reason"] == "too_few_rows" and s["cell"].startswith("CRYPTO_24_7|ny_am|") for s in archive["skipped"])
    crypto_high = [k for k in archive["cells"] if k.startswith("CRYPTO_24_7|") and k.endswith("|high")]
    assert crypto_high and archive["cells"][crypto_high[0]]["beats_baseline"] is True
    replaced = N.offer_elite(archive, crypto_high[0], {"genome_id": "worse", "metrics": {"fitness": -1, "beats_baseline": False}}, 40)
    assert replaced is False and archive["cells"][crypto_high[0]]["genome_id"] != "worse"
    better = N.offer_elite(archive, crypto_high[0], {"genome_id": "better", "metrics": {"fitness": 0.8, "beats_baseline": True,
                                                                                        "strict_gate": {"passed": True}}}, 40)
    assert better is True and archive["cells"][crypto_high[0]]["strict"] is True
    stats = N.summary(archive)
    assert stats["cells_filled"] >= 2 and stats["qd_score"] != 0
    assert stats["n_evaluated"] == archive["n_evaluated"]


def test_selection_uses_the_open_session_cell_only():
    archive = N.empty_archive()
    now = datetime(2026, 10, 28, 15, 0, tzinfo=ET)
    session = session_bucket(int(now.timestamp()))
    assert session == "ny_pm"
    N.offer_elite(archive, f"CRYPTO_24_7|{session}|high",
                  {"genome_id": "crypto-now", "metrics": {"fitness": 0.2, "beats_baseline": True}}, 50)
    N.offer_elite(archive, "CRYPTO_24_7|london|high",
                  {"genome_id": "crypto-london", "metrics": {"fitness": 0.9, "beats_baseline": True}}, 50)
    N.offer_elite(archive, f"US_EQUITIES_ETFS|{session}|high",
                  {"genome_id": "equity-now", "metrics": {"fitness": 5.0, "beats_baseline": True, "strict_gate": {"passed": True}}}, 50)
    pick = N.select_elite(archive, now, 0.95)
    assert pick["genome_id"] == "equity-now" and pick["cell"].endswith(f"{session}|high")
    assert pick["execution_permission"] == "none" and pick["closes_other_positions"] is False
    # Saturday afternoon uses the same clock bucket, but the equity elite is invisible.
    saturday = datetime(2026, 10, 24, 15, 0, tzinfo=ET)
    sat_session = session_bucket(int(saturday.timestamp()))
    N.offer_elite(archive, f"US_EQUITIES_ETFS|{sat_session}|high",
                  {"genome_id": "equity-sat", "metrics": {"fitness": 9.0, "beats_baseline": True, "strict_gate": {"passed": True}}}, 50)
    weekend = N.select_elite(archive, saturday, 0.95)
    assert weekend["island"] == "CRYPTO_24_7" and weekend["genome_id"] == "crypto-now"
    assert N.select_elite(archive, now, None)["reason"] == "volatility regime is unknown"


def test_alt_bar_types_can_be_limited_to_time():
    from atlas.ai.ml.evolution import alt_bar_types
    assert alt_bar_types(("time",)) == ()
    assert "renko_atr" in alt_bar_types(None)
    assert alt_bar_types(("time", "renko_atr", "not_a_bar")) == ("renko_atr",)


def test_fill_from_genomes_keeps_the_better_score_and_skips_short_cells(monkeypatch):
    from atlas.ai.ml import evolution as E
    data = pd.concat([
        _frame("BTCUSDT", 15, 0.9, n=40, seed=1),
        _frame("BTCUSDT", 6, 0.1, n=10, seed=2),
    ], ignore_index=True)
    calls = []

    def fake_eval(frame, g, fs):
        calls.append(g["model"])
        fit = 0.2 if g["model"] == "hgb" else -0.4
        return {"status": "ok", "fitness": fit, "beats_baseline": fit > 0, "folds": [{"ev": fit, "n_taken": 30}] * 5, "_taken_r": np.array([0.1, 0.1, 0.1])}

    monkeypatch.setattr(E, "evaluate_genome", fake_eval)
    monkeypatch.setattr(E, "folds", lambda frame, n=5: [(i, np.array([0]), np.array([1])) for i in range(n)])
    archive = N.fill_from_genomes(data, [{"model": "hgb", "features": "full", "regime": "none", "bar_type": "time"},
                                        {"model": "logit", "features": "full", "regime": "none", "bar_type": "time"}], min_rows=30)
    filled = list(archive["cells"])
    assert len(filled) == 1 and archive["cells"][filled[0]]["genome_id"].startswith("model=hgb")
    assert any(s["reason"] == "too_few_rows" for s in archive["skipped"])
    assert archive["n_evaluated"] == 2 and calls == ["hgb", "logit"]


def test_a_short_session_slice_is_scored_and_cannot_pass_five_folds(monkeypatch):
    from atlas.ai.ml import evolution as E
    data = _frame("SPY", 15, 0.9, n=40, seed=3)

    def fake_eval(frame, g, fs):
        return {"status": "ok", "fitness": 0.2, "beats_baseline": True,
                "folds": [{"ev": 0.1, "n_taken": 30} for _ in fs], "_taken_r": np.array([0.1, 0.1, 0.1])}

    monkeypatch.setattr(E, "evaluate_genome", fake_eval)
    monkeypatch.setattr(E, "folds", lambda frame, n=5: [(i, np.array([0]), np.array([1])) for i in range(4)])
    archive = N.fill_from_genomes(data, [{"model": "hgb", "features": "full", "regime": "none", "bar_type": "time"}], min_rows=30)
    assert len(archive["cells"]) == 1
    elite = next(iter(archive["cells"].values()))
    assert elite["beats_baseline"] is True and elite["strict"] is False


def test_a_thin_fine_grid_falls_back_to_the_same_island_pool(monkeypatch):
    from atlas.ai.ml import evolution as E
    # Two sessions, both under the fine floor, together large enough to score.
    data = pd.concat([
        _frame("BTCUSDT", 15, 0.9, n=40, seed=1),
        _frame("BTCUSDT", 6, 0.9, n=40, seed=2),
    ], ignore_index=True)

    def fake_eval(frame, g, fs):
        return {"status": "ok", "fitness": 0.3, "beats_baseline": True,
                "folds": [{"ev": 0.1, "n_taken": 25} for _ in fs], "_taken_r": np.array([0.2, 0.2, 0.2])}

    monkeypatch.setattr(E, "evaluate_genome", fake_eval)
    monkeypatch.setattr(E, "folds", lambda frame, n=5: [(i, np.array([0]), np.array([1])) for i in range(n)])
    archive = N.fill_from_genomes(
        data, [{"model": "logit", "features": "full", "regime": "none", "bar_type": "time"}], min_rows=50,
    )
    assert archive["grid"] == "coarse"
    assert any(cell.endswith("|all") or "|all|" in cell for cell in archive["cells"])
    assert all(cell.startswith("CRYPTO_24_7|") for cell in archive["cells"])
    now = datetime(2026, 10, 28, 15, 0, tzinfo=ET)
    pick = N.select_elite(archive, now, 0.95)
    assert pick["decision"] == "research_candidate"
    assert pick["island"] == "CRYPTO_24_7"
    assert pick["cell"].startswith("CRYPTO_24_7|")
    assert pick["execution_permission"] == "none"


def test_migration_does_not_carry_fitness_across_venues():
    archive = N.empty_archive()
    N.offer_elite(archive, "CRYPTO_24_7|london|low",
                  {"genome_id": "crypto", "genome": {"model": "hgb"}, "metrics": {"fitness": 0.3, "beats_baseline": True}}, 40)
    refused = N.migrant_challenger(archive, "CRYPTO_24_7|london|low", "US_EQUITIES_ETFS|london|low")
    assert refused["status"] == "refused"
    moved = N.migrant_challenger(archive, "CRYPTO_24_7|london|low", "CRYPTO_24_7|ny_pm|low")
    assert moved["status"] == "challenger" and moved["fitness"] is None and moved["beats_baseline"] is False
    assert moved["genome_id"] == "crypto"
