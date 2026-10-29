"""MAP-Elites archive for venue, session and volatility niches.

Mouret and Clune (2015, arXiv:1504.04909) keep the best solution in each cell
of a behavior grid instead of collapsing onto one global winner. Here a cell
is ``island|session|vol``, using the same New York session buckets and
volatility terciles as the strategy selector.

A genome earns a cell only by its score on that cell's own rows. Copying a
crypto elite onto equities, or a London elite onto the New York afternoon,
is refused. Same-island session migration returns a challenger with no
fitness; it enters the archive only after a fresh evaluation. Bailey and
Lopez de Prado (2014) and Lopez de Prado (2018): every evaluation counts as
a trial. Lookup is not a new backtest and does not promote a model.

``execution_permission`` stays ``none``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from atlas.ai.ml.market_islands import island_of, open_islands
from atlas.ai.ml.selector import session_bucket, vol_regime

MIN_ROWS = 30
# A session slice often cannot form all 5 embargoed folds. Two folds are enough to
# keep an elite. The strict gate still demands the full fold count, so a short
# slice cannot be crowned.
MIN_CELL_FOLDS = 2


def cell_id(island: str, session: str, vol: str) -> str:
    return f"{island}|{session}|{vol}"


def cell_of_row(instrument: str, ts: int, rv_pctile: float) -> str | None:
    island = island_of(instrument)
    if island == "UNKNOWN":
        return None
    if rv_pctile is None or not np.isfinite(rv_pctile):
        return None
    return cell_id(island, session_bucket(int(ts)), vol_regime(float(rv_pctile)))


def empty_archive() -> dict[str, Any]:
    return {
        "method": "map_elites",
        "source": "Mouret & Clune 2015, arXiv:1504.04909",
        "cells": {},
        "n_evaluated": 0,
        "skipped": [],
        "execution_permission": "none",
        "promoted_to_execution": False,
    }


def offer_elite(archive: dict[str, Any], cell: str, result: Mapping[str, Any], n_rows: int) -> bool:
    """Keep the candidate when its cell is empty or its fitness is strictly higher."""
    metrics = dict(result.get("metrics") or {})
    fitness = metrics.get("fitness", result.get("fitness"))
    if fitness is None:
        return False
    entry = {
        "cell": cell,
        "genome_id": result.get("genome_id"),
        "genome": result.get("genome"),
        "fitness": float(fitness),
        "beats_baseline": bool(metrics.get("beats_baseline", result.get("beats_baseline"))),
        "strict": bool((metrics.get("strict_gate") or {}).get("passed")),
        "n_rows": int(n_rows),
    }
    current = archive["cells"].get(cell)
    if current is not None and entry["fitness"] <= current["fitness"]:
        return False
    archive["cells"][cell] = entry
    return True


def illuminate(data: pd.DataFrame, evaluate: Callable[[pd.DataFrame, str], Mapping[str, Any]],
               min_rows: int = MIN_ROWS) -> dict[str, Any]:
    """Evaluate one specialist per occupied cell. ``evaluate`` sees only that cell's rows."""
    archive = empty_archive()
    if data is None or len(data) == 0:
        return archive
    needed = {"instrument", "t", "rv_pctile_480"}
    missing = needed - set(data.columns)
    if missing:
        archive["skipped"].append({"cell": None, "reason": f"missing {sorted(missing)}"})
        return archive
    labels = [cell_of_row(str(i), int(t), p) for i, t, p in zip(data.instrument, data.t, data.rv_pctile_480)]
    frame = data.copy()
    frame["_cell"] = labels
    for cell, part in frame.groupby("_cell", dropna=True):
        part = part.drop(columns="_cell")
        if len(part) < min_rows:
            archive["skipped"].append({"cell": str(cell), "n_rows": int(len(part)), "reason": "too_few_rows"})
            continue
        archive["n_evaluated"] += 1
        offer_elite(archive, str(cell), evaluate(part.reset_index(drop=True), str(cell)), len(part))
    return archive


def coarse_cell(instrument: str, ts: int, rv_pctile: float, kind: str) -> str | None:
    """Pool one axis when the session-by-volatility grid is too thin to score.

    ``session`` keeps the session and pools volatility. ``vol`` keeps volatility
    and pools the session. The island never changes.
    """
    island = island_of(instrument)
    if island == "UNKNOWN" or rv_pctile is None or not np.isfinite(rv_pctile):
        return None
    session = session_bucket(int(ts))
    vol = vol_regime(float(rv_pctile))
    if kind == "session":
        return cell_id(island, session, "all")
    if kind == "vol":
        return cell_id(island, "all", vol)
    return None


def _score_cells(frame: pd.DataFrame, genomes: list, archive: dict[str, Any], min_rows: int,
                 n_folds: int, log: Callable[[str], None]) -> None:
    from atlas.ai.ml.evolution import DEFAULTS, apply_gate, evaluate_genome, folds, gid
    for cell, part in frame.groupby("_cell", dropna=True):
        part = part.drop(columns="_cell").sort_values(["t", "instrument"]).reset_index(drop=True)
        cell = str(cell)
        if len(part) < min_rows:
            archive["skipped"].append({"cell": cell, "n_rows": int(len(part)), "reason": "too_few_rows"})
            continue
        fs = folds(part, n_folds)
        if len(fs) < MIN_CELL_FOLDS:
            archive["skipped"].append({"cell": cell, "n_rows": int(len(part)), "n_folds": len(fs), "reason": "too_few_folds"})
            continue
        board = []
        for g in genomes:
            gg = {**DEFAULTS, **g}
            archive["n_evaluated"] += 1
            metrics = evaluate_genome(part, gg, fs)
            board.append({"genome_id": gid(gg), "genome": gg, "metrics": metrics})
            log(f"{cell} {gid(gg)} -> {metrics.get('status')} fitness={metrics.get('fitness')}")
        apply_gate(board, n_folds)
        ok = [b for b in board if b["metrics"].get("status") == "ok" and b["metrics"].get("fitness") is not None]
        if not ok:
            archive["skipped"].append({"cell": cell, "n_rows": int(len(part)), "reason": "no_ok_genome"})
            continue
        best = max(ok, key=lambda b: b["metrics"]["fitness"])
        offer_elite(archive, cell, best, len(part))


def fill_from_genomes(data: pd.DataFrame, genomes: list, min_rows: int = 180, n_folds: int = 5,
                       log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Score each genome on each occupied cell and keep the best elite.

    Trial count for the strict gate is every genome scored on that cell. A cell
    that cannot form purged folds is skipped rather than filled with a leaky score.
    When every session-by-volatility cell is under ``min_rows``, the same genomes
    are scored on the session pool and the volatility pool. That pool is a new
    trial. It does not copy a fine-cell score, and it does not cross venues.
    """
    archive = empty_archive()
    archive["grid"] = "island|session|vol"
    if data is None or len(data) == 0:
        return archive
    needed = {"instrument", "t", "rv_pctile_480"}
    missing = needed - set(data.columns)
    if missing:
        archive["skipped"].append({"cell": None, "reason": f"missing {sorted(missing)}"})
        return archive
    say = log or (lambda _s: None)
    frame = data.copy()
    frame["_cell"] = [cell_of_row(str(i), int(t), p) for i, t, p in zip(data.instrument, data.t, data.rv_pctile_480)]
    _score_cells(frame, genomes, archive, min_rows, n_folds, say)
    if archive["cells"]:
        return archive
    archive["grid"] = "coarse"
    say("fine grid had no cell with enough rows; scoring the session pool and the volatility pool")
    for kind in ("session", "vol"):
        pooled = data.copy()
        pooled["_cell"] = [coarse_cell(str(i), int(t), p, kind) for i, t, p in zip(data.instrument, data.t, data.rv_pctile_480)]
        _score_cells(pooled, genomes, archive, min_rows, n_folds, say)
    return archive


def summary(archive: Mapping[str, Any]) -> dict[str, Any]:
    elites = list((archive.get("cells") or {}).values())
    return {
        "cells_filled": len(elites),
        "n_evaluated": int(archive.get("n_evaluated") or 0),
        "qd_score": float(sum(e["fitness"] for e in elites)),
        "n_beating_baseline": int(sum(1 for e in elites if e.get("beats_baseline"))),
        "execution_permission": "none",
    }


def migrant_challenger(archive: Mapping[str, Any], src_cell: str, dst_cell: str) -> dict[str, Any]:
    """Same-island elites may be re-scored elsewhere. Their old fitness does not travel."""
    elite = (archive.get("cells") or {}).get(src_cell)
    if elite is None:
        return {"status": "no_source", "execution_permission": "none"}
    src_island, dst_island = src_cell.split("|", 1)[0], dst_cell.split("|", 1)[0]
    if src_island != dst_island:
        return {
            "status": "refused",
            "reason": "cross-venue fitness does not transfer; evaluate a native genome on the destination",
            "execution_permission": "none",
            "promoted_to_execution": False,
        }
    return {
        "status": "challenger",
        "genome_id": elite.get("genome_id"),
        "genome": elite.get("genome"),
        "src_cell": src_cell,
        "dst_cell": dst_cell,
        "fitness": None,
        "beats_baseline": False,
        "reason": "re-evaluate on the destination cell before it can replace that elite",
        "execution_permission": "none",
        "promoted_to_execution": False,
    }


def select_elite(archive: Mapping[str, Any], now: datetime, rv_pctile: float | None) -> dict[str, Any]:
    """Use the elite for the open venues at this session and volatility, or abstain."""
    base = {
        "execution_permission": "none",
        "promoted_to_execution": False,
        "closes_other_positions": False,
        "n_trials_already_counted": int(archive.get("n_evaluated") or 0),
    }
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if rv_pctile is None or not np.isfinite(rv_pctile):
        return {**base, "decision": "abstain", "cell": None, "reason": "volatility regime is unknown"}
    session = session_bucket(int(now.timestamp()))
    vol = vol_regime(float(rv_pctile))
    admitted = sorted(open_islands(now))
    cells = archive.get("cells") or {}
    considered = []
    for island in admitted:
        exact = cell_id(island, session, vol)
        # A pooled elite is used only when this exact cell was never scored.
        chosen = exact if exact in cells else cell_id(island, session, "all")
        if chosen not in cells:
            chosen = cell_id(island, "all", vol)
        elite = cells.get(chosen)
        if elite is None:
            chosen = exact
        considered.append({
            "cell": chosen,
            "island": island,
            "present": elite is not None,
            "beats_baseline": bool(elite and elite.get("beats_baseline")),
            "strict": bool(elite and elite.get("strict")),
            "fitness": None if elite is None else elite.get("fitness"),
            "genome_id": None if elite is None else elite.get("genome_id"),
        })
    eligible = [c for c in considered if c["beats_baseline"]]
    eligible.sort(key=lambda c: (c["strict"], c["fitness"]), reverse=True)
    if not eligible:
        return {**base, "decision": "abstain", "cell": None, "session": session, "vol": vol,
                "reason": "no open niche has an elite that beats its own baseline", "considered": considered}
    best = eligible[0]
    return {**base, "decision": "research_candidate", "cell": best["cell"], "island": best["island"],
            "genome_id": best["genome_id"], "fitness": best["fitness"], "strict": best["strict"],
            "session": session, "vol": vol, "considered": considered,
            "reason": "elite of the open niche for this session and volatility"}
