"""Shadow-week collector: every live price-action decision (abstain or proposal) plus its realized outcome.

Each live candidate is recorded once (``observe``) with what the stack decided and why, then resolved later
(``resolve``) with the outcome of the same conservative OHLC rule used by replay (``conservative_ohlc_v1``),
whether or not a paper order was placed. Abstentions are resolved too (counterfactual), so a future model can be
evaluated against exactly the candidates it would have seen.

``weekly()`` aggregates by ISO week; ``registry_record()`` maps one week onto the fields of
``ModelRegistry.record_shadow_week`` (lift_bps, brier, champion_brier, drawdown_pct, n). A field that cannot be
computed from the records is ``None``: nothing is estimated or filled in. Storage is append-only JSONL under
``var/`` (never committed).
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = "var/shadow/price_action_shadow.jsonl"


def iso_week(ts: int) -> str:
    y, w, _ = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


class ShadowCollector:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path or os.environ.get("ATLAS_SHADOW_PATH", DEFAULT_PATH))
        self._lock = threading.Lock()

    def _append(self, rec: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")

    def observe(self, *, candidate: Any, decision: str, reasons: list[str], probability: float | None = None,
                expected_value_r: float | None = None, model_version: str | None = None,
                data_label: str = "live", order_id: str | None = None) -> None:
        """decision: abstain | proposal_rejected | proposal_authorized."""
        entry, stop = float(candidate.entry_reference), float(candidate.proposed_stop)
        self._append({"kind": "observed", "candidate_id": candidate.candidate_id, "instrument": candidate.instrument,
                      "detector": candidate.detector, "direction": candidate.direction,
                      "detected_at": int(candidate.detected_at), "week": iso_week(int(candidate.detected_at)),
                      "entry": entry, "stop": stop, "target": float(candidate.proposed_target),
                      "risk_bps": abs(entry - stop) / entry * 1e4 if entry else None,
                      "decision": decision, "reasons": list(reasons), "probability": probability,
                      "expected_value_r": expected_value_r, "model_version": model_version,
                      "order_id": order_id, "data_label": data_label})

    def resolve(self, candidate_id: str, *, outcome: str, r_multiple: float | None, exit_at: int | None,
                ambiguous: bool = False, rule: str = "conservative_ohlc_v1") -> None:
        """outcome: target | stop | timeout | unfilled."""
        self._append({"kind": "resolved", "candidate_id": candidate_id, "outcome": outcome, "r_multiple": r_multiple,
                      "exit_at": exit_at, "ambiguous": ambiguous, "rule": rule})

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        obs: dict[str, dict[str, Any]] = {}
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r["kind"] == "observed":
                    obs.setdefault(r["candidate_id"], {**r, "resolution": None})
                elif r["kind"] == "resolved" and r["candidate_id"] in obs:
                    obs[r["candidate_id"]]["resolution"] = r
        return list(obs.values())

    def weekly(self, drawdown_pct: dict[str, float] | None = None) -> list[dict[str, Any]]:
        by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.records():
            by[r["week"]].append(r)
        out, prior_labels = [], []
        for wk in sorted(by):
            rows = by[wk]
            res = [r for r in rows if r["resolution"] is not None]
            lab = [(r, int(r["resolution"]["outcome"] == "target")) for r in res
                   if r["resolution"]["outcome"] in ("target", "stop")]
            prop = [r for r in rows if r["decision"] != "abstain"]
            scored = [(r["probability"], y) for r, y in lab if r["decision"] != "abstain" and r["probability"] is not None]

            def bps(rs):
                v = [r["resolution"]["r_multiple"] * r["risk_bps"] for r in rs
                     if r["resolution"] and r["resolution"]["r_multiple"] is not None and r["risk_bps"]]
                return sum(v) / len(v) if v else None

            all_bps, prop_bps = bps(res), bps([r for r in res if r["decision"] != "abstain"])
            brier = sum((p - y) ** 2 for p, y in scored) / len(scored) if scored else None
            prior = sum(prior_labels) / len(prior_labels) if prior_labels else None
            champ = (sum((prior - y) ** 2 for _, y in scored) / len(scored)) if (scored and prior is not None) else None
            out.append({
                "week": wk, "candidates": len(rows), "abstained": len(rows) - len(prop), "proposed": len(prop),
                "authorized": sum(r["decision"] == "proposal_authorized" for r in rows),
                "abstain_reasons": dict(Counter(x for r in rows if r["decision"] == "abstain" for x in r["reasons"])),
                "resolved": len(res), "labelled": len(lab),
                "base_rate": (sum(y for _, y in lab) / len(lab)) if lab else None,
                "mean_bps_all_candidates": all_bps, "mean_bps_proposed": prop_bps,
                "lift_bps": (prop_bps - all_bps) if (prop_bps is not None and all_bps is not None) else None,
                "brier": brier, "champion_brier": champ, "champion": "prior_weeks_base_rate",
                "drawdown_pct": (drawdown_pct or {}).get(wk),
            })
            prior_labels += [y for _, y in lab]
        return out

    def registry_record(self, week: str, drawdown_pct: dict[str, float] | None = None) -> dict[str, Any] | None:
        """Fields for ModelRegistry.record_shadow_week, or None when the week has no scored proposals."""
        row = next((w for w in self.weekly(drawdown_pct) if w["week"] == week), None)
        if row is None or row["brier"] is None:
            return None
        return {"lift_bps": row["lift_bps"], "brier": row["brier"], "champion_brier": row["champion_brier"],
                "drawdown_pct": row["drawdown_pct"], "n": row["labelled"]}
