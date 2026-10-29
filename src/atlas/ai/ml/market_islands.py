"""Island evolution across venues that do not share a clock.

Each venue is its own population. A genome is fit only against that island's
own after-cost outcomes and its own take-all baseline. Opening another
exchange does not move a position, reset the risk day, or make a failed
genome eligible.

At decision time the coordinator ranks islands whose session is actually
scheduled. A higher score on a closed venue cannot win. If no open island
beats its own baseline, the decision is abstain. Cash stays a valid result.
``execution_permission`` is always ``none``.

This does not retrain the saved registry and does not make a model eligible.
The five fitted meta-models on disk still fail the gates in ``train.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

# Representative symbol used only to read that venue's schedule.
ISLAND_PROBE = {
    "CRYPTO_24_7": "BTCUSDT",
    "US_EQUITIES_ETFS": "SPY",
    "CME_COMEX_FUTURES": "ES",
    "GLOBAL_FX": "EUR_USD",
    "CANADA_TSX": "XIU.TO",
}
# Sessions in which a new research candidate may be ranked. Pause, holiday,
# weekend and the CME pre-open are not in this set.
ADMITTED_STATUS = frozenset({
    "OPEN", "REGULAR_SESSION", "EARLY_CLOSE", "PREMARKET", "AFTER_HOURS", "OVERNIGHT_SESSION",
})
CASH_SESSIONS = frozenset({"REGULAR_SESSION", "EARLY_CLOSE", "GLOBEX_ELECTRONIC", "CONTINUOUS_24_7"})


def island_of(instrument: str) -> str:
    from atlas.market.sessions import classify_symbol_venue
    return classify_symbol_venue(instrument)


def split_islands(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Group rows by venue. Unknown symbols and Pump tokens are left out."""
    if data is None or len(data) == 0 or "instrument" not in data.columns:
        return {}
    keys = data["instrument"].map(lambda s: island_of(str(s)))
    out: dict[str, pd.DataFrame] = {}
    for name in ISLAND_PROBE:
        part = data.loc[keys == name]
        if len(part):
            out[name] = part.reset_index(drop=True)
    return out


def session_snapshot(now: datetime) -> dict[str, dict[str, Any]]:
    """Scheduled status of each island at ``now``. Does not check feeds or brokers."""
    from atlas.market.sessions import evaluate_instrument_market_status
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    snap = {}
    for island, symbol in ISLAND_PROBE.items():
        st = evaluate_instrument_market_status(symbol, now=now)
        status = st["scheduled_market_status"]
        snap[island] = {
            "symbol": symbol,
            "scheduled_market_status": status,
            "trading_session": st.get("trading_session"),
            "admitted": status in ADMITTED_STATUS,
            "cash_session_open": bool(st.get("is_open")) and (
                st.get("trading_session") in CASH_SESSIONS or status in {"OPEN", "REGULAR_SESSION", "EARLY_CLOSE"}
            ),
            "is_open": bool(st.get("is_open")),
        }
    return snap


def open_islands(now: datetime) -> set[str]:
    return {name for name, st in session_snapshot(now).items() if st["admitted"]}


def desk_attention(now: datetime | None = None) -> dict[str, Any]:
    """Venues the research hand may look at.

    The scored book stays the official crypto 4h set. Other venues are on
    the session clock. A closed island is not ranked. Looking at an open
    market does not close a position and does not grant an order.
    """
    from atlas.market.sessions import open_market_venues
    if now is None:
        now = datetime.now(timezone.utc)
    venues = open_market_venues(now)
    return {
        "execution_permission": "none",
        "promoted_to_execution": False,
        "may_propose_order": False,
        "closes_other_positions": False,
        "cash_valid": True,
        "scored_book": "CRYPTO_24_7",
        "scored_book_note": (
            "The scored research book is the official crypto 4h set. "
            "Every other venue follows its own session clock. "
            "The hand ranks an island only while that session is admitted. "
            "Cash stays a valid result. Existing positions stay open."
        ),
        "open_islands": [v["market_id"] for v in venues if v["market_admitted"]],
        "open_markets": [v for v in venues if v["market_open"]],
        "venues": venues,
    }


def coordinate(reports: Sequence[Mapping[str, Any]], open_now: set[str]) -> dict[str, Any]:
    """Pick one open island that beats its own baseline, or abstain.

    Strict-gate passes sort ahead of baseline-only passes. Fitness breaks ties.
    A closed island is reported and then ignored, even if its fitness is higher.
    """
    considered = []
    for row in reports:
        metrics = dict(row.get("metrics") or {})
        island = str(row.get("island") or "")
        gate = metrics.get("strict_gate") or {}
        considered.append({
            "island": island,
            "genome_id": row.get("genome_id"),
            "open": island in open_now,
            "beats_baseline": bool(metrics.get("beats_baseline")),
            "strict": bool(gate.get("passed")),
            "fitness": float(metrics.get("fitness") or 0.0),
            "n_rows": row.get("n_rows"),
        })
    eligible = [c for c in considered if c["open"] and c["beats_baseline"]]
    eligible.sort(key=lambda c: (c["strict"], c["fitness"]), reverse=True)
    base = {
        "execution_permission": "none",
        "promoted_to_execution": False,
        "closes_other_positions": False,
        "considered": considered,
    }
    if not eligible:
        return {**base, "decision": "abstain", "island": None, "genome_id": None,
                "reason": "no admitted island beats its own baseline"}
    best = eligible[0]
    return {**base, "decision": "research_candidate", "island": best["island"],
            "genome_id": best["genome_id"], "fitness": best["fitness"], "strict": best["strict"],
            "reason": "best admitted island that beats its own baseline"}


def evolve_islands(data: pd.DataFrame, meta: dict | None = None, **evolve_kwargs: Any) -> dict[str, Any]:
    """Run the existing governed loop once per island. Does not promote anything."""
    from atlas.ai.ml.evolution import evolve
    meta = dict(meta or {})
    islands = split_islands(data)
    reports = []
    strict_passes = []
    for name, frame in islands.items():
        result = evolve(frame, {**meta, "island": name, "n_rows": len(frame)}, **evolve_kwargs)
        chosen = result.get("best_passing_strict_gate") or result.get("best_beating_baseline") or result.get("best") or {}
        passed = (((result.get("best_passing_strict_gate") or {}).get("metrics") or {}).get("strict_gate") or {}).get("passed")
        if passed:
            strict_passes.append(result)
        reports.append({
            "island": name,
            "n_rows": len(frame),
            "genome_id": chosen.get("genome_id"),
            "metrics": chosen.get("metrics") or {"status": "insufficient"},
            "no_model_beats_baseline": result.get("no_model_beats_baseline", True),
            "no_model_passes_strict_gate": result.get("no_model_passes_strict_gate", True),
        })
    return {
        "islands": reports,
        "strict_passes": strict_passes,
        "execution_permission": "none",
        "promoted_to_execution": False,
        "note": "Per-island research only. A strict pass is published by the same record path as a pooled run. Eligibility still requires the gates in atlas.ai.ml.train.",
    }
