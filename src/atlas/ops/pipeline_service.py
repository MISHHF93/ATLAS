"""Glue between the decision pipeline and the paper TradingService (ctx adapter + one cycle)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from typing import TYPE_CHECKING

from atlas.ops.pipeline_models import ModelSet

if TYPE_CHECKING:
    from atlas.ops.pipeline_full import FullPipeline

class ServiceContext:
    """Adapts TradingService + point-in-time bar frames to the pipeline's ctx interface."""

    def __init__(self, svc, frames: dict[str, pd.DataFrame], instruments: dict, now: datetime):
        from atlas.research.backtest.engine import Context  # noqa: F401  (interface reference)
        self.svc, self.frames, self.instruments, self.now = svc, frames, instruments, now
        self.portfolio = svc.broker.snapshot()
        self.bot_capital = svc.engine.bot_capital(self.portfolio)
        self.pending_symbols = {p.intent.symbol for p in svc.approvals.pending()} | {o.intent.symbol for o in svc.broker.open_orders.values()}

    def has_pending(self, s):
        return s in self.pending_symbols

    def history(self, s):
        from types import SimpleNamespace
        df = self.frames.get(s)
        if df is None:
            return []
        t = pd.Timestamp(self.now)
        t = t.tz_convert(None) if t.tzinfo else t
        df = df[df.index <= t]
        return [SimpleNamespace(ts=t, close=float(c), volume=float(v)) for t, c, v in zip(df.index, df["close"], df["volume"])]

    def instrument(self, s):
        return self.instruments[s]

    def fx(self, ccy):
        return self.svc.engine.fx.rate(ccy, self.svc.cfg.risk.base_currency) if getattr(self.svc.engine, "fx", None) else 1.0

    def intent(self, symbol, side, qty, strategy):
        from atlas.risk.models import OrderIntent
        h = self.history(symbol)
        if not h or qty <= 0:
            return None
        ins = self.instrument(symbol)
        return OrderIntent(symbol=symbol, side=side, qty=qty, order_type="market", reference_price=h[-1].close, quote_age_s=0.0,
                           fx_rate_to_base=self.fx(ins.currency), currency=ins.currency, sleeve=ins.sleeve, asset_class=ins.asset_class,
                           broker=ins.broker, sector=ins.sector, issuer=ins.issuer, source="strategy")


def paper_pipeline_step(svc, frames: dict[str, pd.DataFrame], instruments: dict, now: datetime, headlines: dict | None = None,
                        pipeline: "FullPipeline | None" = None, size_overlay=None, should_continue=None) -> dict:
    """One decision cycle in the PAPER service: every child goes through the risk engine again; at autonomy
    level < approval_required_below_level it is queued for owner approval (never auto-executed); otherwise
    it is routed to the paper broker. The trail is appended to the state store for the dashboard.

    `size_overlay(intent) -> factor` (autopilot risk budget) can only SHRINK a child (factor clamped to [0, 1]);
    `should_continue()` is checked before each child so an autopilot stop takes effect mid-cycle."""
    from atlas.ops.pipeline_full import FullPipeline
    from atlas.research.screener.news import NewsScreener
    p = pipeline or FullPipeline(svc.cfg, ModelSet(svc.models_root, audit=svc.audit),
                                 NewsScreener(svc.cfg.risk.ai_controls.llm_screener, audit=svc.audit), audit=svc.audit)
    ctx = ServiceContext(svc, frames, instruments, now)
    n0 = getattr(p, "n_decisions", 0)
    children = p.decide(now, ctx, list(frames), headlines or {}, svc.engine)
    queued, routed, rejected, shrunk = [], [], [], []
    for ch in children:
        if should_continue is not None and not should_continue():
            rejected.append(["autopilot stopped mid-cycle"])
            break
        if size_overlay is not None:
            f = max(0.0, min(1.0, float(size_overlay(ch))))
            if f < 1.0:
                q = ch.qty * f if ch.asset_class == "crypto_spot" else float(int(ch.qty * f))
                shrunk.append({"symbol": ch.symbol, "side": ch.side, "from_qty": ch.qty, "to_qty": q, "factor": round(f, 4),
                               "why": "autopilot risk budget (vol target / fractional Kelly / allocation cap)"})
                if q <= 0:
                    rejected.append(["autopilot risk budget: no headroom"])
                    continue
                ch = ch.model_copy(update={"qty": q})
        if svc.approval_required:
            d = svc.engine.evaluate(ch, svc.broker.snapshot(), record_rate=False)
            if d.approved:
                queued.append(svc.approvals.enqueue(ch).approval_id)
            else:
                rejected.append(d.reasons)
        else:
            r = svc.router.execute(ch, svc.broker.snapshot())
            (routed if r.get("executes") else rejected).append(r.get("order_id") or r.get("reasons"))
    k = getattr(p, "n_decisions", 0) - n0
    new = p.trail[-k:] if k else []  # robust to trail trimming
    for t in new:
        t["routing"] = "owner_approval_queue" if svc.approval_required else "paper_broker"
    from atlas.risk.trail import merge_trail
    svc.store.set("decision_trail", merge_trail(svc.store.get("decision_trail") or [], new))
    svc.audit.append("pipeline.cycle", {"decisions": len(new), "children": len(children), "queued": len(queued),
                                        "routed": len(routed), "rejected": len(rejected)}, actor="strategy")
    return {"decisions": len(new), "children": len(children), "queued_for_approval": queued, "routed": routed, "rejected": rejected,
            "shrunk": shrunk, "trail": new}
