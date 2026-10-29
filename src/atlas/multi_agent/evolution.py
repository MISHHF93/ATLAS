"""Offline evolution report over reflected runs.

The report compares the research view only with transparent baselines.  It does
not retrain, promote or authorize any model, and it does not treat an LLM
confidence label as a calibrated probability.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import BaselineMetric, EvolutionReport
from .store import ResearchStore



def build_evolution(store: ResearchStore, *, now: datetime | None = None) -> EvolutionReport:
    reflections = store.list_reflections(limit=1000)
    completed = store.stats().get("completed_runs", 0)
    directional = [r for r in reflections if r.directional_correct is not None]
    accuracy = (
        sum(1 for r in directional if r.directional_correct) / len(directional)
        if directional else None
    )
    abstentions = [r for r in reflections if r.predicted_direction == "none"]
    abstention_rate = len(abstentions) / len(reflections) if reflections else None

    # Baselines ignore the research view.  They use the long-side return, so a
    # reflected short candidate is not mistaken for a bullish observation.
    def long_return(r):
        return -r.realized_return if r.proposal_action == "SELL_CANDIDATE" and r.realized_return is not None else r.realized_return

    up_correct = [r for r in reflections if long_return(r) is not None and long_return(r) > 0]
    down_correct = [r for r in reflections if long_return(r) is not None and long_return(r) < 0]
    n = len(up_correct) + len(down_correct)
    baselines = [
        BaselineMetric(
            name="always_bullish",
            status="available" if n else "unavailable",
            observations=n,
            directional_accuracy=(len(up_correct) / n) if n else None,
            note="Long every reflected observation; ignores research view.",
        ),
        BaselineMetric(
            name="always_bearish",
            status="available" if n else "unavailable",
            observations=n,
            directional_accuracy=(len(down_correct) / n) if n else None,
            note="Short every reflected observation; ignores research view.",
        ),
        BaselineMetric(
            name="always_abstain",
            status="available" if reflections else "unavailable",
            observations=len(reflections),
            abstention_rate=1.0 if reflections else None,
            note="Abstain on every run; directional accuracy is undefined.",
        ),
        BaselineMetric(
            name="research_view",
            status="available" if directional else "unavailable",
            observations=len(directional),
            directional_accuracy=accuracy,
            abstention_rate=abstention_rate,
            note="Directional accuracy over completed reflections only; one observation is not calibration.",
        ),
    ]
    return EvolutionReport(
        generated_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc),
        completed_runs=int(completed),
        reflected_runs=len(reflections),
        research_directional_accuracy=accuracy,
        research_abstention_rate=abstention_rate,
        baselines=baselines,
        cost_notes=[
            "Reflections use caller-supplied outcome prices; no transaction costs are applied automatically.",
            "No promotion, weighting or live execution is derived from these observations.",
            "LLM confidence labels are not calibrated probabilities.",
        ],
    )


__all__ = ["build_evolution"]
