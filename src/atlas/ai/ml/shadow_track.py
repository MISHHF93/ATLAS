"""Forward shadow log for the meta-label. Weeks accrue from resolved outcomes only.

A week counts when at least one observed setup has a resolved target, stop, or timeout.
Observations alone do not increment the gate. The count is an input to the existing
``shadow_weeks`` gate. It does not skip the other gates and it does not set execution permission.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from atlas.ai.models.shadow import ShadowCollector, iso_week

DEFAULT_PATH = "var/shadow/ml_meta_shadow.jsonl"
_RESOLVED = {"target", "stop", "timeout"}


def _skip_pytest_default(path) -> bool:
    return path is None and "PYTEST_CURRENT_TEST" in os.environ


def shadow_weeks_count(collector_or_path) -> int:
    if collector_or_path is None:
        return 0
    collector = collector_or_path if hasattr(collector_or_path, "records") else ShadowCollector(collector_or_path)
    weeks: set[str] = set()
    for row in collector.records():
        res = row.get("resolution") or {}
        if res.get("outcome") in _RESOLVED:
            weeks.add(str(row.get("week") or iso_week(int(row["detected_at"]))))
    return len(weeks)


def shadow_report(path=None) -> dict[str, Any]:
    if _skip_pytest_default(path):
        collector = None
        records: list[dict[str, Any]] = []
        weekly: list[dict[str, Any]] = []
    else:
        collector = ShadowCollector(path or DEFAULT_PATH)
        records = collector.records()
        weekly = collector.weekly()
    return {
        "path": str(path or DEFAULT_PATH),
        "n_observed": len(records),
        "n_resolved": sum(1 for r in records if r.get("resolution")),
        "shadow_weeks": shadow_weeks_count(collector) if collector is not None else 0,
        "min_shadow_weeks": 4,
        "weekly": weekly,
        "execution_permission": "none",
        "note": "Weeks count only after a target, stop, or timeout. Eligibility still needs every other gate.",
    }


def observe_open_setup(row: dict[str, Any], *, model_version: str | None, probability: float | None,
                       expected_value_r: float | None, take: bool, path=None) -> bool:
    """Append one open setup if its candidate id is new. No-op under pytest unless ``path`` is set."""
    if _skip_pytest_default(path):
        return False
    collector = ShadowCollector(path or DEFAULT_PATH)
    cid = str(row.get("candidate_id") or "")
    if not cid or any(r.get("candidate_id") == cid for r in collector.records()):
        return False
    detected = int(row["t"])
    candidate = SimpleNamespace(
        candidate_id=cid, instrument=str(row.get("instrument") or ""), detector=str(row.get("detector") or ""),
        direction=str(row.get("direction") or "long"), detected_at=detected,
        entry_reference=float(row.get("entry") or 0.0), proposed_stop=float(row.get("stop") or 0.0),
        proposed_target=float(row.get("target") or 0.0),
    )
    decision = "proposal_rejected" if take else "abstain"
    reasons = ["shadow_only_not_an_order"] if take else ["conformal_or_ev_abstain"]
    collector.observe(candidate=candidate, decision=decision, reasons=reasons, probability=probability,
                      expected_value_r=expected_value_r, model_version=model_version, data_label="ml-meta-live")
    return True


def resolve_known(rows: list[dict[str, Any]], path=None) -> int:
    """Resolve shadow ids that now have a training-style outcome. Does not invent outcomes."""
    if _skip_pytest_default(path):
        return 0
    collector = ShadowCollector(path or DEFAULT_PATH)
    open_ids = {r["candidate_id"] for r in collector.records() if not r.get("resolution")}
    n = 0
    for row in rows:
        cid = str(row.get("candidate_id") or "")
        outcome = str(row.get("outcome") or "")
        if cid not in open_ids or outcome not in _RESOLVED:
            continue
        r = row.get("r")
        collector.resolve(cid, outcome=outcome, r_multiple=None if r is None else float(r), exit_at=int(row.get("exit_at") or 0))
        open_ids.discard(cid)
        n += 1
    return n
