"""Decision pipeline (TRD §13): rules propose -> ML filters/ranks -> LLM screener may only
veto/downsize -> deterministic risk engine decides. Produces a plain-language "why this trade"."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Decision:
    intent: object
    approved: bool
    why: str
    p_hit: float | None = None
    shap_top: list = field(default_factory=list)
    screener: str = "n/a"
    risk_reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class DecisionPipeline:
    def __init__(self, ml_stage, screener, engine):
        self.ml, self.screener, self.engine = ml_stage, screener, engine

    def run(self, candidates, headlines: dict, state) -> list[Decision]:
        out = []
        for rec in self.ml.apply(candidates):
            i0 = rec["intent"]
            sr = self.screener.screen(i0, headlines.get(i0.symbol, []))
            scr = "veto" if sr.intent is None else (f"x{sr.applied_mult:g}" if sr.applied_mult < 1 else "pass")
            if sr.failure:
                scr += f" ({sr.failure})"
            if sr.intent is None:
                out.append(Decision(i0, False, f"{i0.side} {i0.symbol}: vetoed by news screener [{scr}]", rec["p_hit"],
                                    rec["shap_top"], scr))
                continue
            d = self.engine.evaluate(sr.intent, state, record_rate=False)
            drivers = ", ".join(f"{k} {v:+.3f}" for k, v in rec["shap_top"][:3]) or "n/a"
            ph = f"{rec['p_hit']:.2f}" if rec["p_hit"] is not None else f"n/a ({rec['fallback']})"
            why = (f"{sr.intent.side} {sr.intent.qty:g} {sr.intent.symbol} ({sr.intent.sleeve}, {sr.intent.source}): "
                   f"ML P(hit)={ph}; top drivers: {drivers}; screener: {scr}; "
                   f"risk: {'APPROVED' if d.approved else 'REJECTED: ' + '; '.join(d.reasons)}")
            out.append(Decision(sr.intent, d.approved, why, rec["p_hit"], rec["shap_top"], scr, d.reasons, d.warnings))
        return out
