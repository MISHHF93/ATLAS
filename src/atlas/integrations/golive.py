"""Go-live readiness: a READ-ONLY list of the gates that must all pass before real-money trading could even be considered.

This panel cannot enable anything. Even with every gate green, ATLAS stays paper-only: the live endpoints are refused, ML ``execution_permission`` stays
``none`` and ``risk_policy.yaml`` is unchanged. Turning any of that on would be a separate, reviewed change by the owner. No profitability claim is made:
each gate reports the measured evidence (or that there is none yet)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

EXECUTION_PERMISSION = "none"
BROKERS = ("oanda", "ibkr", "alpaca")


def _gate(key: str, title: str, state: str, detail: str, evidence: Any = None, rule: str = "") -> dict[str, Any]:
    return {"key": key, "title": title, "state": state, "detail": detail, "evidence": evidence, "rule": rule}


def model_gate(root: str | Path | None = None) -> dict[str, Any]:
    from atlas.ai.ml.directional.live import root_path
    from atlas.ai.ml.directional import pipeline as P
    d = root_path(root)
    groups = []
    for man in sorted(d.glob("*/manifest.json")) if d.exists() else []:
        try:
            m = json.loads(man.read_text())
        except Exception:
            continue
        failed = [g["gate"] for g in (m.get("gates") or []) if not g.get("passed") and g.get("gate") != "shadow_weeks"]
        groups.append({"group": man.parent.name, "label": m.get("label"), "failed_gates": failed, "offline_passed": not failed and bool(m.get("gates"))})
    rule = "Every offline gate of the strict model gate (OOS count, Brier and log-loss vs base rate, deflated Sharpe, PBO, ACI coverage, pinball skill) on at least one pool."
    if not groups:
        return _gate("model_gate", "Strict model gate", "pending", "No trained model yet: run scripts/ml_directional.py --run once the bars are stored.", [], rule)
    ok = [g for g in groups if g["offline_passed"]]
    if ok:
        return _gate("model_gate", "Strict model gate", "pass", f"{len(ok)} of {len(groups)} pools passed every offline gate (shadow weeks still required below).", groups, rule)
    return _gate("model_gate", "Strict model gate", "fail", f"0 of {len(groups)} pools passed every offline gate; all are labelled '{P.LABEL_BELOW}'.", groups, rule)


def shadow_gate(collector: Any = None) -> dict[str, Any]:
    from atlas.ai.ml.train import GATES
    need = int(GATES["min_shadow_weeks"])
    rule = f"At least {need} distinct ISO weeks of shadow (paper, counterfactual) results with resolved outcomes."
    try:
        if collector is None:
            from atlas.ai.models.shadow import ShadowCollector
            collector = ShadowCollector()
        weeks = collector.weekly()
    except Exception as ex:
        return _gate("shadow_weeks", "Shadow weeks of paper evidence", "pending", f"Shadow log unreadable: {type(ex).__name__}", [], rule)
    have = [w for w in weeks if w.get("labelled", 0) > 0]
    ev = {"weeks_with_resolved_outcomes": len(have), "weeks_required": need, "weeks_recorded": len(weeks), "candidates": sum(w.get("candidates", 0) for w in weeks)}
    if len(have) >= need:
        return _gate("shadow_weeks", "Shadow weeks of paper evidence", "pass", f"{len(have)} weeks with resolved paper outcomes (need {need}).", ev, rule)
    if not weeks:
        return _gate("shadow_weeks", "Shadow weeks of paper evidence", "pending", f"No shadow week recorded yet (need {need}).", ev, rule)
    return _gate("shadow_weeks", "Shadow weeks of paper evidence", "fail", f"{len(have)} of {need} weeks have resolved paper outcomes.", ev, rule)


def reviewer_gate(scope: str | None = None) -> dict[str, Any]:
    rule = "The LLM reviewer's shadow record shows enough measured outcomes and that restricted trades did worse than allowed ones (95% CI below zero)."
    try:
        from atlas.news import reviewer as RV
        from atlas.news import store as S
        e = RV.gate_eligibility(scope or S.current_scope())
    except Exception as ex:
        return _gate("reviewer_evidence", "LLM reviewer evidence", "pending", f"No reviewer record available ({type(ex).__name__}).", None, rule)
    g = e["effect"]["groups"]
    ev = {"restricted_n": g["restricted"]["n"], "allowed_n": g["allow"]["n"], "min_n": e["min_n"], "mode": RV.mode()}
    if e["eligible"]:
        return _gate("reviewer_evidence", "LLM reviewer evidence", "pass", "Reviewer evidence meets the gate-eligibility rule (a human still sets the mode).", ev, rule)
    none_yet = ev["restricted_n"] == 0 and ev["allowed_n"] == 0
    return _gate("reviewer_evidence", "LLM reviewer evidence", "pending" if none_yet else "fail", "; ".join(e["reasons"]), ev, rule)


def broker_gate(states: Mapping[str, dict]) -> dict[str, Any]:
    rule = "At least one broker PAPER/PRACTICE account is verified (OANDA practice or IBKR paper for Canada; Alpaca paper only if you are eligible)."
    ev = {b: (states.get(b) or {}).get("state", "needs_verification") for b in BROKERS}
    ok = [b for b, s in ev.items() if s == "verified"]
    if ok:
        return _gate("broker_paper", "Verified broker paper account", "pass", f"Verified: {', '.join(ok)} (paper/practice only).", ev, rule)
    return _gate("broker_paper", "Verified broker paper account", "pending", "No broker paper/practice account verified yet: add OANDA practice or IBKR paper keys, then Verify.", ev, rule)


def signoff_gate() -> dict[str, Any]:
    return _gate("owner_signoff", "Your explicit sign-off", "pending",
                 "Manual and outside this panel: nothing here records or implies approval. It is requested only after the four gates above pass.",
                 None, "The owner's explicit, written decision. This panel is read-only and cannot grant it.")


def report(states: Mapping[str, dict] | None = None, model_root: str | Path | None = None, collector: Any = None, scope: str | None = None) -> dict[str, Any]:
    if states is None:
        from atlas.accounts.credentials import effective_environ
        from atlas.integrations import verify as v
        from atlas.integrations.registry import load_env
        states = v.all_states(load_env(environ=dict(effective_environ())))
    gates = [model_gate(model_root), shadow_gate(collector), reviewer_gate(scope), broker_gate(states), signoff_gate()]
    passed = sum(g["state"] == "pass" for g in gates)
    return {"gates": gates, "passed": passed, "total": len(gates), "automated_gates_pass": all(g["state"] == "pass" for g in gates[:4]),
            "headline": f"{passed} of {len(gates)} gates pass. ATLAS stays paper-only regardless: this panel cannot enable real-money trading.",
            "live_endpoints": "refused", "execution_permission": EXECUTION_PERMISSION, "risk_policy": "unchanged (config/founder/risk_policy.yaml, read-only here)",
            "read_only": True, "secrets_echoed": False}
