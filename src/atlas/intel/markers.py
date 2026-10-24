"""Chart opportunity markers (research signal, paper only, not advice).

Sources (both causal; a marker sits on the confirmation bar, i.e. the bar whose END == detected_at, never earlier):
  1. unified candidate engine (the replay of the default engine + every suite toggle) -> each Candidate goes through
     the unified ``proposals.evaluate`` gate (models.predict -> models.opportunity.evaluate_candidate). With no
     validated calibrated model the gate abstains: probability is shown as "uncalibrated/LOW_CONFIDENCE".
  2. the research champion of the model-evolution loop: walk-forward OUT-OF-SAMPLE calibrated p / EV_R per
     candidate (ml.evolution.oos_predictions) for its instruments; never in-sample numbers.
Classes: ml_suggested (OOS EV_R > 0 and conformal take), ml_skip, rule_only (gate abstained only for lack of a
validated model), risk_rejected (gate rejected on geometry/costs/edge). ``risk_status`` is the gate result the
deterministic control plane would receive; ML never authorizes or sizes (execution_permission none).
Outcome = replay result on real prices: target / stop / timeout / open / not_filled.
"""
from __future__ import annotations

import json
from typing import Any

DISCLAIMER = "research signal, paper only, not advice"
MODEL_ABSENT = {"NO_VALIDATED_MODEL", "MODEL_UNAVAILABLE", "UNCALIBRATED", "NO_MODEL", "LOW_CONFIDENCE"}


def _model_absent(reasons) -> bool:
    return bool(reasons) and all(any(k in str(r).upper() for k in ("MODEL", "CALIBRAT", "LOW_CONFIDENCE", "VALIDATED")) for r in reasons)


def from_replay(res, tf: int, cost_per_unit: float = 0.0) -> list[dict[str, Any]]:
    from atlas.features.price_action.proposals import evaluate
    by_c = {t.candidate_id: t for t in res.trades}
    out = []
    for c in res.candidates:
        try:
            pred, ev = evaluate(c, cost_per_unit=cost_per_unit)
            reasons = list(ev.abstention_reason)
            prob = ev.probability
            mv = getattr(pred, "model_version", None)
            evr = ev.expected_value_r
        except Exception as e:  # noqa: BLE001 - gate failure is a rejection, never an approval
            reasons, prob, mv, evr = [f"gate_error:{type(e).__name__}"], None, None, None
        if not reasons:
            cls, risk = ("ml_suggested" if prob is not None else "rule_only"), "authorized_for_control_plane"
        elif _model_absent(reasons):
            cls, risk = "rule_only", "gate abstained, no validated model (not a risk rejection): " + ",".join(map(str, reasons))
        else:
            cls, risk = "risk_rejected", "rejected: " + ",".join(map(str, reasons))
        t = by_c.get(c.candidate_id)
        gain = abs(c.proposed_target - c.entry_reference)
        loss = abs(c.entry_reference - c.proposed_stop)
        out.append({"id": c.candidate_id, "source": "candidate_engine", "strategy": c.detector, "direction": c.direction,
                    "time": int(c.detected_at - tf), "detected_at": int(c.detected_at), "price": c.entry_reference,
                    "stop": c.proposed_stop, "target": c.proposed_target,
                    "probability": prob, "probability_label": f"{prob:.2f}" if prob is not None else "uncalibrated/LOW_CONFIDENCE",
                    "uncertainty": None, "ev_r": evr,
                    "gross_rr": gain / loss if loss > 0 else None, "model_version": mv or "none (no validated model)",
                    "risk_status": risk, "class": cls,
                    "outcome": (t.outcome if t else "not_filled"), "r": (t.r_multiple if t else None)})
    return out


def from_evolution(inst: str, interval: str, path=None) -> tuple[list[dict[str, Any]], dict | None]:
    from atlas.ml.evolution import evo_dir, latest_run
    run = latest_run(path)
    if not run:
        return [], None
    p = evo_dir(path) / f"oos_{run['run_id']}.json"
    if not p.exists():
        return [], {"run_id": run["run_id"]}
    rows = [r for r in json.loads(p.read_text()) if r["instrument"] == inst and r["interval"] == interval]
    best = run.get("best_beating_baseline") or run.get("best") or {}
    tf = {"15m": 900, "1h": 3600}.get(interval, 900)
    mv = f"evolution:{run['run_id']}:{best.get('genome_id')}"
    out = []
    for r in rows:
        take = bool(r["take"])
        out.append({"id": f"ml:{r['candidate_id']}", "source": "evolution_oos", "strategy": r["detector"], "direction": r["direction"],
                    "time": int(r["t"] - tf), "detected_at": int(r["t"]), "price": r["entry"], "stop": r["stop"], "target": r["target"],
                    "probability": r["p"], "probability_label": f"{r['p']:.2f} (OOS, {r.get('calibrator')})",
                    "uncertainty": f"conformal alpha 0.2; take requires set {{1}}", "ev_r": r["ev_r"], "model_version": mv,
                    "risk_status": "not_submitted (research champion only; ML cannot authorize)",
                    "class": "ml_suggested" if take else "ml_skip", "outcome": r["outcome"], "r": r["r"]})
    return out, {"run_id": run["run_id"], "genome": best.get("genome_id"), "no_model_beats_baseline": run.get("no_model_beats_baseline"),
                 "decision": run.get("decision")}


CLASS_ORDER = ("ml_suggested", "ml_skip", "rule_only", "risk_rejected")


def class_summary(markers: list[dict[str, Any]], n_rule_candidates: int, has_oos: bool) -> dict[str, dict[str, Any]]:
    """Per-category legend data. ``applicable`` is False when that category could not occur for this chart, so the UI
    shows "n/a" with the reason instead of a misleading zero."""
    counts = {k: 0 for k in CLASS_ORDER}
    for m in markers:
        counts[m["class"]] = counts.get(m["class"], 0) + 1
    out: dict[str, dict[str, Any]] = {}
    for k in ("ml_suggested", "ml_skip"):
        out[k] = {"count": counts[k], "applicable": has_oos,
                  "note": "out-of-sample predictions from the evolution champion" if has_oos
                  else "no out-of-sample ML predictions for this symbol/timeframe"}
    out["rule_only"] = {"count": counts["rule_only"], "applicable": n_rule_candidates > 0,
                        "note": "rule setups the gate abstained on because no validated model exists" if n_rule_candidates
                        else "no rule candidates in this window"}
    out["risk_rejected"] = {"count": counts["risk_rejected"], "applicable": n_rule_candidates > 0,
                            "note": (f"rejected on geometry or costs, out of {n_rule_candidates} rule candidates checked (the edge check needs a validated model)"
                                     if n_rule_candidates else "no rule candidates in this window")}
    return out
