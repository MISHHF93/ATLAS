#!/usr/bin/env python
r"""Inspect global session schedules and saved ML evidence without running a bot.

    .venv\Scripts\python.exe -B scripts/global_market_check.py --horizon 24
    .venv\Scripts\python.exe -B scripts/global_market_check.py --at 2026-10-28T04:00:00Z

Reads schedule.yaml and model manifests only. Never loads model binaries, fetches
prices, retrains, starts workers, changes account settings, or submits orders.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def registry_snapshot(registry: Path) -> dict:
    from atlas.ai.ml.registry import list_models

    models = []
    for manifest in list_models(registry):
        metrics = (manifest.get("metrics") or {}).get("primary") or {}
        gates = manifest.get("gates") or []
        models.append({
            "version": manifest["version"],
            "group": manifest["group"],
            "status": manifest.get("status"),
            "created_at": manifest.get("created_at"),
            "passes_recorded_gates": bool(gates) and all(g.get("passed") is True for g in gates),
            "failed_gates": [g.get("gate") for g in gates if g.get("passed") is not True],
            "n_oos": metrics.get("n_oos"),
            "brier_skill": metrics.get("brier_skill"),
            "n_taken": metrics.get("n_taken"),
            "mean_r_taken": metrics.get("mean_r_taken"),
            "deflated_sharpe_probability": (metrics.get("dsr") or {}).get("dsr"),
            "training_scope": [
                {key: series.get(key) for key in ("instrument", "asset_class", "interval")}
                for series in manifest.get("series", [])
            ],
        })
    return {
        "n_registered": len(models),
        "n_gate_eligible": sum(m["status"] == "eligible" and m["passes_recorded_gates"] for m in models),
        "eligibility_note": "Gate eligibility still requires exact instrument, asset class, and interval checks at inference.",
        "models": models,
    }


def main(argv: list[str] | None = None) -> int:
    import yaml
    from atlas.ops.sessions import SessionModel

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", help="Timezone-aware ISO timestamp; defaults to current UTC time")
    parser.add_argument("--horizon", type=int, default=24, help="Schedule horizon in hours (1 to 168)")
    parser.add_argument("--schedule", type=Path, default=ROOT / "config/founder/schedule.yaml")
    parser.add_argument("--registry", type=Path, default=Path(os.environ.get("ATLAS_ML_REGISTRY", ROOT / "var/ml/registry")))
    parser.add_argument("--output", type=Path, help="Optional JSON snapshot path")
    args = parser.parse_args(argv)
    if not 1 <= args.horizon <= 168:
        parser.error("--horizon must be between 1 and 168 hours")
    try:
        now = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset or Z")
    except ValueError as exc:
        parser.error(str(exc))

    schedule = yaml.safe_load(args.schedule.read_text(encoding="utf-8"))
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_at_utc": now.astimezone(timezone.utc).isoformat(),
        "execution_permission": "none",
        "mode": "read_only_assessment",
        "model_evidence": registry_snapshot(args.registry),
        "session_plan": SessionModel(schedule).plan(now, horizon_h=args.horizon),
        "unattended_execution": {
            "status": "not_validated",
            "note": "An open schedule and a saved model do not establish a tradable opportunity.",
            "checks_not_performed": [
                "real-time feed freshness, licensing, and instrument coverage",
                "broker connection, account permissions, balances, and reconciliation",
                "point-in-time FX valuation and executable currency conversion",
                "portfolio risk, existing positions, and correlated exposure",
                "always-on hosting, watchdog recovery, and alerts",
            ],
        },
    }
    rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
