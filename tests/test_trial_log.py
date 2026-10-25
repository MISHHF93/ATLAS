"""A later pass keeps the earlier miss, and the log cannot send an order."""

from __future__ import annotations

from pathlib import Path

from atlas.models.trial_log import remember_ledger


def _ledger(judgment: str, mean: float) -> dict:
    def track() -> dict:
        return {
            "judgment": judgment,
            "public_resolved_stances": 80,
            "mean_net_return": mean,
            "reliability": {
                "confidence": "scored",
                "brier_score": 0.22,
                "calibration_rows": 90,
                "direction_hit_rate": 0.51,
                "execution": "not_attempted",
            },
        }

    return {
        "path_id": "daily-trend-outcome-ledger:v1",
        "tracks": {"competition": track(), "open_market": track()},
    }


def test_a_later_pass_keeps_the_earlier_miss(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    first = remember_ledger(_ledger("not_supported", -0.003), path)
    assert first["added"] == 2
    assert first["kept_misses"] == 2
    assert first["execution_permission"] == "none"
    assert first["orders_submitted"] == 0

    second = remember_ledger(_ledger("supported_on_this_sample", 0.004), path)
    assert second["added"] == 2
    assert second["count"] == 4
    assert second["kept_misses"] == 2
    text = path.read_text(encoding="utf-8")
    assert "not_supported" in text
    assert "supported_on_this_sample" in text

    third = remember_ledger(_ledger("supported_on_this_sample", 0.004), path)
    assert third["added"] == 0
    assert third["count"] == 4
    assert path.read_text(encoding="utf-8") == text


def test_a_damaged_line_stays_in_place(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    remembered = remember_ledger(_ledger("not_supported", -0.001), path)
    assert remembered["persisted"] is True
    assert remembered["kept_misses"] == 2
    assert path.read_text(encoding="utf-8").startswith("not-json\n")


def test_trial_log_source_cannot_submit() -> None:
    source = Path("src/atlas/ai/models/trial_log.py").read_text(encoding="utf-8")
    assert "submit_order" not in source
    assert "process_strategy_signal" not in source
    assert "ActionableControlPlane" not in source
