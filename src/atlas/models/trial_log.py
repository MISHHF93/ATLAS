"""Append-only record of ledger verdicts, including the misses.

Bailey, Borwein, López de Prado, and Zhu showed that keeping only the best
backtest overstates it (Journal of Computational Finance, first published
19 September 2016; SSRN 2326253). This log keeps every distinct verdict.
It does not estimate that probability, and it cannot submit an order.

SR 11-7 asks for an inventory of models in use, in development, and retired.
A later row does not delete an earlier one.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATH_ID = "research-trial-log:v1"
_LOCK = threading.Lock()


def default_trial_log_path() -> Path:
    """Live desk log under local app data. Tests get a file of their own."""
    override = os.environ.get("ATLAS_TRIAL_LOG", "").strip()
    if override:
        return Path(override)
    current = os.environ.get("PYTEST_CURRENT_TEST", "").strip()
    if current:
        slug = hashlib.sha256(current.encode()).hexdigest()[:12]
        return Path(tempfile.gettempdir()) / f"atlas-trial-{slug}.jsonl"
    local = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local) if local else Path.home() / "AppData" / "Local"
    return root / "ATLAS" / "research-trial-log.jsonl"


def _number(value: Any, places: int) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), places)
    except (TypeError, ValueError):
        return None


def _count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def verdict_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """One compact row per track. The fingerprint ignores the clock."""
    tracks = ledger.get("tracks") if isinstance(ledger.get("tracks"), dict) else {}
    path_id = str(ledger.get("path_id") or "daily-trend-outcome-ledger:v1")
    rows: list[dict[str, Any]] = []
    for track in ("competition", "open_market"):
        row = tracks.get(track) if isinstance(tracks.get(track), dict) else {}
        reliability = row.get("reliability") if isinstance(row.get("reliability"), dict) else {}
        scored = {
            "path_id": path_id,
            "track": track,
            "judgment": str(row.get("judgment") or "unavailable"),
            "public_resolved_stances": _count(row.get("public_resolved_stances")),
            "mean_net_return": _number(row.get("mean_net_return"), 8),
            "brier_score": _number(reliability.get("brier_score"), 6),
            "confidence": str(reliability.get("confidence") or "unavailable"),
            "calibration_rows": _count(reliability.get("calibration_rows")),
            "direction_hit_rate": _number(reliability.get("direction_hit_rate"), 4),
            "execution": str(reliability.get("execution") or "not_attempted"),
        }
        canonical = json.dumps(scored, sort_keys=True, separators=(",", ":"))
        scored["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
        rows.append(scored)
    return rows


def _summary(rows: list[dict[str, Any]], added: int, *, persisted: bool, notice: str) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        track = str(row.get("track") or "")
        if track:
            latest[track] = row
    return {
        "path_id": PATH_ID,
        "count": len(rows),
        "kept_misses": sum(1 for row in rows if row.get("judgment") == "not_supported"),
        "added": added,
        "latest": [latest[track] for track in ("competition", "open_market") if track in latest],
        "persisted": persisted,
        "orders_submitted": 0,
        "may_propose_order": False,
        "execution_permission": "none",
        "notice": notice,
    }


def remember_ledger(ledger: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Append verdicts whose fingerprint is new. Never rewrite an earlier row."""
    target = path or default_trial_log_path()
    fresh = verdict_rows(ledger)
    notice = (
        "Every distinct verdict stays in this log, including a miss. "
        "A later pass does not delete the earlier row. "
        "This is not a probability of backtest overfitting, and it cannot send an order."
    )
    try:
        with _LOCK:
            existing: list[dict[str, Any]] = []
            seen: set[str] = set()
            if target.exists():
                for line in target.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict) or not item.get("fingerprint"):
                        continue
                    existing.append(item)
                    seen.add(str(item["fingerprint"]))
            added = 0
            stamped = datetime.now(timezone.utc).isoformat()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8", newline="\n") as handle:
                for row in fresh:
                    if row["fingerprint"] in seen:
                        continue
                    stored = {
                        **row,
                        "recorded_at": stamped,
                        "orders_submitted": 0,
                        "may_propose_order": False,
                        "execution_permission": "none",
                    }
                    handle.write(json.dumps(stored, sort_keys=True) + "\n")
                    existing.append(stored)
                    seen.add(str(row["fingerprint"]))
                    added += 1
            return _summary(existing, added, persisted=True, notice=notice)
    except OSError:
        return _summary(
            fresh,
            0,
            persisted=False,
            notice="The trial log could not be written. Nothing was sent.",
        )
