"""Deterministic multi-agent research pipeline (TradingAgents-style roles, no LLM):

analysts -> bull/bear debate -> trader proposal -> risk manager (the ATLAS control plane, dry run) -> portfolio manager.

The analysts restate rule outputs from the dossier and persona scorers; the debate orders the evidence; the trader turns
the verdict into an order request; the risk manager is ``ActionableControlPlaneEngine.preview_order`` (the same rules
as a real paper order, no booking). Nothing here submits an order: execution_permission is "none" and the final
output is a research decision record."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import ADVISORY
from .personas import PERSONAS, score_persona

DEFAULT_NOTIONAL = Decimal("1000")


def analysts(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    conv = dossier["conviction"]
    tech_pts = [c for c in conv.get("components", []) if c["rule"] not in ("fundamental_quality", "sentiment")]
    out = [{"analyst": "technical", "stance": sum(c["points"] for c in tech_pts), "evidence": tech_pts}]
    m, t = dossier["fundamentals"].get("metrics") or {}, dossier["technicals"]
    if m:
        res = [score_persona(p, m, t) for p in PERSONAS]
        out.append({"analyst": "fundamental", "stance": sum({"bullish": 1, "bearish": -1}.get(r["signal"], 0) * r["confidence"] / 10 for r in res),
                    "evidence": [{"rule": r["persona"], "points": {"bullish": 1, "bearish": -1}.get(r["signal"], 0) * r["confidence"] / 10,
                                  "why": f"{r['signal']} ({r['confidence']}%), {r['evaluated']}/{r['of']} checks evaluable"} for r in res]})
    else:
        out.append({"analyst": "fundamental", "stance": 0, "evidence": [], "status": "unavailable", "why": dossier["fundamentals"].get("status")})
    out.append({"analyst": "sentiment", "stance": 0, "evidence": [], "status": "unavailable", "why": "no sentiment source configured"})
    out.append({"analyst": "news", "stance": 0, "evidence": [], "status": "unavailable", "why": "no licensed news source configured"})
    return out


def debate(reports: list[dict[str, Any]], rounds: int = 3) -> dict[str, Any]:
    pts = [{"analyst": r["analyst"], **e} for r in reports for e in r["evidence"] if e.get("points")]
    bull = sorted([p for p in pts if p["points"] > 0], key=lambda p: -p["points"])
    bear = sorted([p for p in pts if p["points"] < 0], key=lambda p: p["points"])
    log = []
    for i in range(rounds):
        b, s = (bull[i] if i < len(bull) else None), (bear[i] if i < len(bear) else None)
        if not b and not s:
            break
        log.append({"round": i + 1, "bull": b and f"{b['analyst']}/{b['rule']}: {b['why']} (+{b['points']:.1f})",
                    "bear": s and f"{s['analyst']}/{s['rule']}: {s['why']} ({s['points']:.1f})",
                    "round_edge": round((b["points"] if b else 0) + (s["points"] if s else 0), 2)})
    bs, ss = sum(p["points"] for p in bull), sum(p["points"] for p in bear)
    net = bs + ss
    verdict = "bull" if net >= 10 else "bear" if net <= -10 else "no_edge"
    return {"rounds": log, "bull_total": bs, "bear_total": ss, "net": net, "verdict": verdict,
            "rule": "verdict bull if net evidence >= +10, bear if <= -10, else no_edge"}


def trader_proposal(symbol: str, verdict: dict, levels: dict, track: str = "open_market",
                    notional_usd: Decimal = DEFAULT_NOTIONAL) -> dict[str, Any] | None:
    if verdict["verdict"] == "no_edge" or not levels.get("side"):
        return None
    side = "buy" if levels["side"] == "long" else "sell"
    if (verdict["verdict"] == "bull") != (side == "buy"):
        return None                      # debate and level engine disagree -> no proposal
    bps = Decimal(str(round(levels.get("stop_distance_bps") or 0, 2)))
    return {"track": track, "instrument_id": symbol.upper(), "side": side, "notional_usd": str(notional_usd), "stop_kind": "structure",
            "stop_distance_bps": str(bps), "entry": levels["entry"], "stop": levels["stop"], "target": levels["target"],
            "reward_risk": levels.get("reward_risk")}


def risk_manager(proposal: dict[str, Any] | None, engine, data_age_ms: float) -> dict[str, Any]:
    if proposal is None:
        return {"status": "skipped", "reason": "no proposal"}
    from atlas.control.engine import ActionableOrderRequest
    req = ActionableOrderRequest(track=proposal["track"], instrument_id=proposal["instrument_id"], side=proposal["side"],
                                 notional_usd=Decimal(proposal["notional_usd"]), stop_kind="structure",
                                 stop_distance_bps=Decimal(proposal["stop_distance_bps"]), data_age_ms=data_age_ms)
    rep = engine.preview_order(req)
    return {"status": "approved" if rep.compliance_passed else "rejected", "violations": list(rep.violations),
            "authority": "ActionableControlPlaneEngine.preview_order (deterministic; no booking)"}


def run_pipeline(dossier: dict[str, Any], engine, *, data_age_ms: float, track: str = "open_market",
                 notional_usd: Decimal = DEFAULT_NOTIONAL) -> dict[str, Any]:
    reps = analysts(dossier)
    deb = debate(reps)
    prop = trader_proposal(dossier["symbol"], deb, dossier["trade_levels"], track, notional_usd)
    risk = risk_manager(prop, engine, data_age_ms)
    final = "approve_for_paper_review" if risk["status"] == "approved" else "reject" if risk["status"] == "rejected" else "no_trade"
    return {"symbol": dossier["symbol"], "analysts": reps, "debate": deb, "trader_proposal": prop, "risk_manager": risk,
            "portfolio_manager": {"decision": final, "submitted": False,
                                  "why": "research pipeline; a paper order still needs an explicit owner action through the control plane"},
            "llm_used": False, "advisory": ADVISORY, "execution_permission": "none"}
