"""Earned-autonomy ladder evaluator (TRD §11.7). Computes promotion-readiness evidence from paper
results against the policy gates. It is READ-ONLY with respect to autonomy: it cannot change the
policy or the level (no method does). Promotion = owner edits + re-signs the policy with step-up,
and in this build autonomy.level is locked at 1 anyway (live impossible)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class Check:
    name: str
    value: object
    threshold: object
    passed: bool


def _metrics(equity: list[list], trade_pnls: list[float]) -> dict:
    if len(equity) < 2:
        return {"days": len(equity), "sharpe": 0.0, "mdd_pct": 0.0, "profit_factor": 0.0, "total_return_pct": 0.0}
    by_day: dict = {}
    for ts, v in equity:
        by_day[datetime.fromisoformat(ts).date()] = float(v)
    vals = np.array([by_day[d] for d in sorted(by_day)])
    r = np.diff(np.log(vals)) if len(vals) > 1 else np.array([])
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0
    peak = np.maximum.accumulate(vals)
    gains = sum(p for p in trade_pnls if p > 0); losses = -sum(p for p in trade_pnls if p < 0)
    pf = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
    return {"days": len(by_day), "sharpe": sharpe, "mdd_pct": float(((peak - vals) / peak).max() * 100),
            "profit_factor": pf, "total_return_pct": float((vals[-1] / vals[0] - 1) * 100)}


def _dsr(equity: list[list], trial_srs: list[float]) -> dict:
    """DSR of the paper equity curve, deflated by every logged model/strategy trial."""
    from atlas.models.quant.validation import validation_report
    by_day = {datetime.fromisoformat(ts).date(): float(v) for ts, v in equity}
    vals = np.array([by_day[d] for d in sorted(by_day)])
    r = np.diff(np.log(vals)) if len(vals) > 2 else np.zeros(3)
    v = validation_report(r, list(trial_srs) + [float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0])
    return {"dsr": v["dsr"], "psr": v["psr"], "n_trials": v["n_trials"]}


class LadderEvaluator:
    def __init__(self, policy):
        self.policy = policy

    def evaluate(self, equity: list[list], trade_pnls: list[float], backtest_return_pct: float | None = None,
                 breaches: int = 0, trial_srs: list[float] | None = None) -> dict:
        lvl = self.policy.autonomy.level
        gates = (self.policy.autonomy.model_extra or {}).get("gates") or {}
        target = min(lvl + 1, 4)
        g = gates.get(f"level_{target}", {})
        m = _metrics(equity, trade_pnls)
        m.update(_dsr(equity, trial_srs or []))
        checks: list[Check] = []
        if target == 2:
            div = (abs(m["total_return_pct"] - backtest_return_pct) / max(abs(backtest_return_pct), 1e-9) * 100
                   if backtest_return_pct is not None else None)
            checks = [Check("paper_trading_days", m["days"], g.get("min_paper_trading_days", 60), m["days"] >= g.get("min_paper_trading_days", 60)),
                      Check("sharpe", round(m["sharpe"], 3), g.get("min_sharpe", 1.0), m["sharpe"] >= g.get("min_sharpe", 1.0)),
                      Check("max_drawdown_pct", round(m["mdd_pct"], 3), g.get("max_drawdown_pct", 10), m["mdd_pct"] <= g.get("max_drawdown_pct", 10)),
                      Check("profit_factor", round(m["profit_factor"], 3), g.get("min_profit_factor", 1.3), m["profit_factor"] >= g.get("min_profit_factor", 1.3)),
                      Check("backtest_divergence_pct", None if div is None else round(div, 2), g.get("max_backtest_divergence_pct", 30),
                            div is not None and div <= g.get("max_backtest_divergence_pct", 30)),
                      Check("unhandled_breaches", breaches, 0, breaches == 0),
                      Check("deflated_sharpe", round(m["dsr"], 4), f"> 0.95 (n_trials={m['n_trials']})", m["dsr"] > 0.95)]
        else:
            checks = [Check("requires_live_evidence", None, f"level_{target} gates", False)]
        evidence_ready = all(c.passed for c in checks)
        return {"current_level": lvl, "target_level": target, "metrics": m, "checks": [c.__dict__ for c in checks],
                "evidence_ready": evidence_ready, "can_self_promote": False,
                "live_locked": True,
                "next_step": ("Evidence passes; owner may review and sign a policy change (blocked in this build: level locked at 1)"
                              if evidence_ready else "Keep paper trading; gates not met"),
                "demotion_recommended": breaches > 0}


def evaluate_service(svc, backtest_return_pct: float | None = None) -> dict:
    from atlas.ops.equity import equity_series
    pnls = [float(d.gain) for d in svc.tax.report().dispositions] if getattr(svc, "tax", None) else []
    breaches = len(svc.audit.entries("risk.breach")) if hasattr(svc.audit, "entries") else 0
    trials: list[float] = []
    root = getattr(svc, "models_root", None)
    if root:
        from pathlib import Path
        from atlas.models.quant.validation import TrialLog
        for f in Path(root).glob("*/trials.jsonl"):
            trials += TrialLog(f).srs()
    res = LadderEvaluator(svc.cfg.risk).evaluate(equity_series(svc), pnls, backtest_return_pct, breaches, trials)
    svc.store.set("autonomy_readiness", res)
    svc.audit.append("autonomy.evaluated", {"target": res["target_level"], "ready": res["evidence_ready"]}, actor="autonomy_evaluator")
    return res
