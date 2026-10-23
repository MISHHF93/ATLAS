"""Full paper decision pipeline (TRD §13, research items wired end-to-end):

  rules -> sleeve scorers -> (factor sleeve filter) -> meta-label -> news veto
        -> regime / vol / conformal sizing -> portfolio construction -> cost filter
        -> RISK ENGINE -> execution plan -> paper broker

Invariants (tested):
* Models act only through CHAMPIONS. Challengers run in SHADOW: their outputs are logged in the
  explanation trail and scored weekly (registry.record_shadow_week) but never change an order.
* After the rule proposes a candidate, every stage can only keep, shrink or drop it.
  qty is monotonically non-increasing through the trail; exits are never blocked by models.
* No champion for a stage => that stage's policy fallback (scorer: rules-only half size; others: neutral 1.0;
  portfolio: inverse-vol; execution: default parameters). A model error => same fallback, logged.
* The risk engine decides on the parent; every execution-plan child is re-checked by the engine
  before the paper broker (the backtester / router does that).
* Each decision gets a plain-language, per-stage explanation trail (dashboard /api/decisions).
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime

import numpy as np
import pandas as pd

from atlas.models.quant.features import make_features
from atlas.models.quant.meta import META_FEATURES, momentum_primary
from atlas.models.quant.sleeves import POLICY_TO_SCORER, SLEEVES

from atlas.ops.pipeline_models import SHADOW_KINDS, STAGES, Candidate, ModelSet, _sleeve_pct  # noqa: F401  (re-export)

class FullPipeline:
    def __init__(self, cfg, models: ModelSet, screener, audit=None, horizon: int = 5, cost_margin: float = 0.25,
                 spread_bps: dict | None = None):
        self.cfg, self.models, self.screener, self.audit = cfg, models, screener, audit
        self.horizon, self.cost_margin = horizon, cost_margin
        self.spread_bps = spread_bps or {"crypto_spot": 10.0, "index_etf": 2.0}
        self.pending_outcomes: list[dict] = []      # for shadow scoring
        self.trail: list[dict] = []
        self.trail_max: int | None = 2000          # bounded in long-running processes; sim sets None (full report)

    # ------------------------------------------------------------------ helpers
    def _act(self, kind):
        return self.models.acting.get(kind)

    def _try(self, c: Candidate, stage: str, fn, fallback):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            c.log(stage, f"model error -> fallback ({e.__class__.__name__}: {str(e)[:80]})", "fallback")
            if self.audit:
                self.audit.append("ml.fallback", {"stage": stage, "symbol": c.symbol, "error": str(e)[:200]})
            return fallback

    # ------------------------------------------------------------------ main entry
    def decide(self, now: datetime, ctx, symbols: list[str], headlines: dict, engine) -> list:
        """ctx: backtest Context-like (history, instrument, intent, portfolio, bot_capital, fx).
        Returns child OrderIntents for the backtester/router (each re-checked by the risk engine)."""
        from atlas.marketdata.pit.models import Bar  # noqa: F401
        frames = {}
        for s in symbols:
            h = ctx.history(s)
            if len(h) < 60:
                continue
            frames[s] = pd.DataFrame({"close": [b.close for b in h], "volume": [b.volume for b in h]},
                                     index=pd.DatetimeIndex([b.ts for b in h]))
        self._resolve_outcomes(frames, now)
        out = []
        cands: list[Candidate] = []
        # 1. rules (primary = momentum crossover; exits always allowed)
        for s, df in frames.items():
            ins = ctx.instrument(s)
            side_sig = float(momentum_primary(df["close"]).iloc[-1])
            held = ctx.portfolio.positions.get(s)
            if held and side_sig < 0 and not ctx.has_pending(s):
                i = ctx.intent(s, "sell", held.qty, "pipeline_exit")
                if i:
                    tr = {"id": uuid.uuid4().hex[:12], "ts": now.isoformat(), "symbol": s, "side": "sell", "sleeve": ins.sleeve,
                          "stages": [{"stage": "rules", "detail": "momentum flipped negative -> exit full position", "effect": "propose",
                                      "qty": held.qty},
                                     {"stage": "models", "detail": "exits bypass model stages (models can never block an exit)", "effect": "pass"}]}
                    d = engine.evaluate(i, ctx.portfolio, record_rate=False)
                    tr["stages"].append({"stage": "risk", "detail": "APPROVED" if d.approved else "REJECTED: " + "; ".join(d.reasons),
                                         "effect": "pass" if d.approved else "drop"})
                    if d.approved:
                        out.append(i)
                        tr["stages"].append({"stage": "execution", "detail": "single market child (exit)", "effect": "pass", "children": 1})
                    tr["final"] = "submitted" if d.approved else "rejected by risk engine"
                    self.trail.append(tr)
                continue
            if side_sig > 0 and not held and not ctx.has_pending(s):
                c = Candidate(s, "buy", ins.sleeve, ins, df["close"], df["volume"])
                c.log("rules", "momentum fast MA > slow MA -> long candidate", "propose")
                cands.append(c)
        if not cands:
            return out
        self._scorers(cands)
        self._factor(cands, frames, ctx)
        for c in cands:
            if c.dropped:
                continue
            self._meta(c, headlines)
            self._news(c, headlines)
        self._size(cands, ctx, frames)
        self._portfolio(cands, ctx, frames)
        for c in cands:
            if c.dropped:
                continue
            self._cost(c)
        for c in cands:
            if not c.dropped:
                out += self._risk_and_plan(c, ctx, engine)
            self._finish(c, now)
        return out

    # ------------------------------------------------------------------ stages
    def _scorers(self, cands):
        from atlas.models.quant.features import FEATURES
        for c in cands:
            sk = POLICY_TO_SCORER.get(c.sleeve)
            X = make_features(pd.DataFrame({"close": c.close, "volume": c.volume})).iloc[[-1]]
            c.features = X
            sc = self._act(f"scorer_{sk}")
            sh = self.models.shadow.get(f"scorer_{sk}")
            if sh is not None and not X[FEATURES].isna().any().any():
                try:
                    c.shadow[f"scorer_{sk}"] = float(sh.p_hit(X)[0])
                except Exception:  # noqa: BLE001
                    pass
            if sc is None or X[FEATURES].isna().any().any():
                c.mult *= 0.5
                c.log("scorer", f"no champion {sk} scorer -> rules-only half size"
                      + (f"; challenger(shadow) P(hit)={c.shadow[f'scorer_{sk}']:.2f}" if f"scorer_{sk}" in c.shadow else ""),
                      "x0.5", mult=c.mult)
                continue
            p = self._try(c, "scorer", lambda: float(sc.p_hit(X)[0]), None)
            if p is None:
                c.mult *= 0.5; continue
            thr = SLEEVES[sk]["min_p_hit"]
            c.p = p
            if p < thr:
                c.dropped = "scorer"
                c.log("scorer", f"champion P(hit)={p:.2f} < {thr} -> drop", "drop")
            else:
                drv = self._try(c, "scorer", lambda: ", ".join(f"{k} {v:+.3f}" for k, v in sc.explain(X)[0][:3]), "n/a")
                c.log("scorer", f"champion P(hit)={p:.2f} >= {thr}; drivers: {drv}", "pass")

    def _factor(self, cands, frames, ctx):
        eq = [c for c in cands if c.sleeve == "active" and not c.dropped]
        if not eq:
            return
        act_cols = [s for s in frames if ctx.instrument(s).sleeve == "active"]
        close = pd.DataFrame({s: frames[s]["close"] for s in act_cols}).dropna()
        act, sh = self._act("factor_sleeve"), self.models.shadow.get("factor_sleeve")
        for c in eq:
            if sh is not None:
                try:
                    c.shadow["factor_sleeve"] = float(sh.scores(close[act_cols]).get(c.symbol, 0.0) >= sh.min_score)
                except Exception:
                    pass
            if act is None:
                c.log("factor_sleeve", "no champion factor model -> neutral", "pass")
                continue
            sc = self._try(c, "factor_sleeve", lambda: act.scores(close[act_cols]), None)
            if sc is None:
                continue
            z = float(sc.get(c.symbol, 0.0))
            if z < act.min_score:
                c.dropped = "factor_sleeve"
                c.log("factor_sleeve", f"composite z={z:+.2f} < {act.min_score} (weights {act.weights}) -> drop", "drop")
            else:
                c.log("factor_sleeve", f"composite z={z:+.2f} >= {act.min_score}", "pass")

    def _meta_X(self, c: Candidate, headlines) -> pd.DataFrame | None:
        from atlas.models.quant.labels import causal_daily_vol
        X = c.features.copy()
        X["side"] = 1.0
        X["sigma"] = float(causal_daily_vol(c.close).iloc[-1]) if len(c.close) > 30 else np.nan
        X["news_veto"] = 0.0
        if any(h for h in headlines.get(c.symbol, [])):
            r = self.screener.provider.screen(c.symbol, headlines[c.symbol]) if getattr(self.screener, "provider", None) else {}
            X["news_veto"] = 1.0 if isinstance(r, dict) and r.get("action") == "veto" else 0.0
        return None if X[META_FEATURES].isna().any().any() else X

    def _meta(self, c: Candidate, headlines):
        X = self._meta_X(c, headlines)
        c._metaX = X
        act, sh = self._act("meta_label"), self.models.shadow.get("meta_label")
        if X is None:
            c.log("meta_label", "insufficient history for meta features -> neutral", "pass"); return
        if sh is not None:
            try:
                c.shadow["meta_label"] = float(sh.size_factor(X)[0]); c.shadow["meta_label_p"] = float(sh.p_profit(X)[0])
            except Exception:  # noqa: BLE001  shadow failures never affect orders
                pass
        if act is None:
            c.log("meta_label", "no champion meta-labeler -> neutral" +
                  (f"; challenger(shadow) P(profit)={c.shadow['meta_label_p']:.2f} size x{c.shadow['meta_label']:.2f}" if sh is not None else ""),
                  "pass"); return
        fp = self._try(c, "meta_label", lambda: (float(act.size_factor(X)[0]), float(act.p_profit(X)[0])), None)
        if fp is None:
            return
        f, p = fp
        c.p = p
        if f <= 0:
            c.dropped = "meta_label"; c.log("meta_label", f"P(profit)={p:.2f} below threshold {act.threshold} -> drop", "drop"); return
        c.mult *= f
        c.log("meta_label", f"P(profit)={p:.2f} -> size x{f:.2f}", f"x{f:.2f}", mult=c.mult)

    def _news(self, c: Candidate, headlines):
        from atlas.risk.models import OrderIntent
        dummy = OrderIntent(symbol=c.symbol, side="buy", qty=1, order_type="market", reference_price=float(c.close.iloc[-1]),
                            sleeve=c.sleeve, asset_class=c.instrument.asset_class, broker=c.instrument.broker, source="strategy")
        r = self.screener.screen(dummy, headlines.get(c.symbol, []))
        if r.intent is None:
            c.dropped = "news"
            c.log("news", f"screener VETO{(' (' + r.failure + ')') if r.failure else ''}"
                  + (f": {r.verdict.reason}" if r.verdict and getattr(r.verdict, 'reason', None) else ""), "drop"); return
        if r.applied_mult < 1:
            c.mult *= r.applied_mult
            c.log("news", f"screener downsize x{r.applied_mult:g}", f"x{r.applied_mult:g}", mult=c.mult); return
        c.log("news", f"screener pass ({len(headlines.get(c.symbol, []))} headlines)", "pass")

    def _size(self, cands, ctx, frames):
        from atlas.models.quant.labels import causal_daily_vol
        from atlas.risk.sizing import vol_target_qty
        pl = self.cfg.risk.position_limits
        regime, vol, conf = self._act("regime"), self._act("vol"), self._act("conformal")
        rm, rdesc = 1.0, "no champion regime model -> x1.0"
        if regime is not None:
            try:
                from atlas.models.quant.regime import regime_features
                idx = next(iter(frames.values()))["close"]
                rm = float(regime.risk_multiplier(regime_features(idx)).iloc[-1]); rdesc = f"regime multiplier x{rm:.2f}"
            except Exception as e:  # noqa: BLE001
                rdesc = f"regime model error -> x1.0 ({e.__class__.__name__})"
        # round-2 exposure overlays (vol-managed, trend switch): champion => multiplier in [0, 1] (down-only);
        # challenger => logged as shadow only. Computed on the market proxy (first frame).
        from atlas.strategies.sleeve_strategies.overlays import OverlayModel
        idx_close = next(iter(frames.values()))["close"] if frames else None
        odesc = []
        for k in getattr(self.models, "OVERLAY_KINDS", ()):
            if idx_close is None:
                break
            for which, store in (("act", self.models.acting), ("shadow", self.models.shadow)):
                sm = store.get(k)
                if sm is None:
                    continue
                try:
                    m = min(1.0, max(0.0, float(OverlayModel.build(sm).multiplier(idx_close))))
                except Exception as e:  # noqa: BLE001  overlay error => neutral (never increases size)
                    odesc.append(f"{k} error -> x1.0 ({e.__class__.__name__})"); continue
                if which == "act":
                    rm *= m; odesc.append(f"{k} x{m:.2f}")
                else:
                    for c in cands:
                        c.shadow[k] = round(m, 4)
        if odesc:
            rdesc += "; overlays " + ", ".join(odesc)
        for c in cands:
            if c.dropped:
                continue
            r = np.log(c.close).diff().dropna()
            if vol is not None:
                fv = self._try(c, "sizing", lambda: float(vol.forecast_ann(r)), None)
                vdesc = f"vol champion forecast {fv:.1%}" if fv else ""
            else:
                fv = None
            if not fv:
                fv = float(causal_daily_vol(c.close).iloc[-1] * math.sqrt(252)); vdesc = f"causal EWMA vol {fv:.1%} (no vol champion)"
            cf, cdesc = 1.0, "no champion conformal sizer -> x1.0"
            X = getattr(c, "_metaX", None)
            if conf is not None and X is not None:
                cf = self._try(c, "sizing", lambda: float(conf.size_factor(X)[0]), 1.0); cdesc = f"conformal x{cf:.2f}"
            if self.models.shadow.get("conformal") is not None and X is not None:
                try:
                    c.shadow["conformal"] = float(self.models.shadow["conformal"].size_factor(X)[0])
                except Exception:  # noqa: BLE001
                    pass
            px, fx = float(c.close.iloc[-1]), ctx.fx(c.instrument.currency)
            budget = ctx.bot_capital * _sleeve_pct(self.cfg, c.sleeve) / 100
            res = vol_target_qty(budget, 0.15 if c.sleeve != "high_risk" else 0.40, fv, px, fx, ctx.bot_capital,
                                 pl.max_position_pct_bot_capital, pl.max_position_notional_base,
                                 regime_mult=rm, screener_mult=min(1.0, c.mult * cf), p_hit=c.p)
            c.qty, c.vol_ann, c.budget, c.px, c.fx = res["qty"], fv, budget, px, fx
            c.log("sizing", f"{vdesc}; {rdesc}; {cdesc}; stage mults x{c.mult:.2f}; binding cap {res.get('binding')} -> "
                  f"qty {res['qty']:.4g} (notional {res.get('notional_base', 0):,.0f})", "size", qty=res["qty"])
            if res["qty"] <= 0:
                c.dropped = "sizing"; c.trail[-1]["effect"] = "drop"

    def _portfolio(self, cands, ctx, frames):
        from atlas.models.quant.stack2 import PortfolioModel
        act = self._act("portfolio")
        model, desc = (act, f"champion allocator {act.method}") if act is not None else (PortfolioModel("inverse_vol"), "no champion -> inverse-vol")
        by_sleeve: dict[str, list] = {}
        for c in cands:
            if not c.dropped:
                by_sleeve.setdefault(c.sleeve, []).append(c)
        for sleeve, cs in by_sleeve.items():
            names = sorted({c.symbol for c in cs} | {s for s, p in ctx.portfolio.positions.items() if getattr(p, "sleeve", None) == sleeve})
            rets = pd.DataFrame({s: frames[s]["close"].pct_change() for s in names if s in frames}).dropna()
            w = model.weights(rets) if len(rets) > 20 else pd.Series(1 / len(names), index=names)
            shw = self.models.shadow.get("portfolio")
            for c in cs:
                wi = float(w.get(c.symbol, 0.0))
                cap_qty = wi * c.budget / (c.px * c.fx)
                if shw is not None:
                    try:
                        sw = float(shw.weights(rets).get(c.symbol, 0.0)) * c.budget / (c.px * c.fx)
                        c.shadow["portfolio"] = min(1.0, sw / c.qty) if c.qty > 0 else 0.0
                    except Exception:
                        pass
                new = min(c.qty, cap_qty)
                eff = "pass" if new >= c.qty - 1e-12 else f"x{new / c.qty:.2f}"
                c.log("portfolio", f"{desc}: weight {wi:.1%} of {sleeve} budget -> cap qty {cap_qty:.4g}", eff, qty=new)
                c.qty = new
                if new <= 0:
                    c.dropped = "portfolio"; c.trail[-1]["effect"] = "drop"

    def _cost(self, c: Candidate):
        from atlas.execution.scheduling import pre_trade_impact_bps
        from atlas.models.quant.costmodel import expected_edge_bps
        ex = self._act("execution")
        Y = ex.impact_Y if ex is not None else 0.8
        adv = float(c.volume.tail(20).mean())
        sig = float(np.log(c.close).diff().tail(20).std())
        venue = "CRYPTO" if c.instrument.asset_class == "crypto_spot" else ("TSX" if c.instrument.currency == "CAD" else "NYSE")
        spread = self.spread_bps.get(c.instrument.asset_class, 5.0)
        imp = pre_trade_impact_bps(c.qty, adv, sig, spread, Y=Y, venue=venue)
        cost_model = self._act("cost")
        if cost_model is not None:
            rt = 2 * float(cost_model.predict_bps(spread / 2, sig * 1e4, c.qty / max(adv, 1))[0]); src = "cost champion"
        else:
            rt = 2 * imp["total_bps"]; src = "sqrt-impact model"
        p = c.p
        psrc = "model P"
        if p is None:
            p = self._hit_rate(c); psrc = "trailing rule hit-rate"
        edge = expected_edge_bps(p, c.vol_ann, self.horizon)
        c.adv, c.sig, c.venue, c.impact = adv, sig, venue, imp
        if edge <= rt * (1 + self.cost_margin):
            c.dropped = "cost"
            c.log("cost", f"edge {edge:.1f} bps ({psrc} {p:.2f}) <= round-trip cost {rt:.1f} bps x{1 + self.cost_margin} ({src}) -> drop", "drop")
        else:
            c.log("cost", f"edge {edge:.1f} bps ({psrc} {p:.2f}) > cost {rt:.1f} bps x{1 + self.cost_margin} ({src})", "pass")

    def _hit_rate(self, c: Candidate) -> float:
        from atlas.models.quant.labels import triple_barrier
        key = (c.symbol, len(c.close) // 20)
        cache = self.__dict__.setdefault("_hr", {})
        if key not in cache:
            close = c.close.tail(400)
            lab = triple_barrier(close, momentum_primary(close), 1.0, 1.0, 10, cost_bps=10)
            lab = lab[lab["t1"] <= close.index[-1]]
            cache[key] = float(lab["bin"].mean()) if len(lab) >= 30 else 0.5
        return cache[key]

    def _risk_and_plan(self, c: Candidate, ctx, engine) -> list:
        from atlas.execution.scheduling import almgren_chriss, pov_schedule
        qty = math.floor(c.qty * 1e6) / 1e6 if c.instrument.asset_class == "crypto_spot" else math.floor(c.qty)
        if qty <= 0:
            c.dropped = "rounding"; c.log("execution", "qty rounds to 0 shares -> drop", "drop"); return []
        parent = ctx.intent(c.symbol, "buy", qty, "pipeline")
        d = engine.evaluate(parent, ctx.portfolio, record_rate=False)
        if not d.approved:
            c.dropped = "risk"; c.log("risk", "REJECTED: " + "; ".join(d.reasons), "drop"); return []
        c.log("risk", "APPROVED" + (f" (warnings: {'; '.join(d.warnings)})" if d.warnings else ""), "pass")
        ex = self._act("execution")
        from atlas.models.quant.stack2 import ExecutionModel
        ex = ex or ExecutionModel()
        part = qty / max(c.adv, 1e-9)
        if c.instrument.asset_class == "crypto_spot":
            plan = pov_schedule(qty, [c.adv / 4] * 4, ex.pov_rate)
            kids = [k for k in plan.children if k > 0]
            desc = f"POV {plan.participation:.0%} over 4 intervals; unfilled {plan.unfilled:.4g} (never forced)"
        elif part > ex.single_order_max_participation:
            ac = almgren_chriss(qty, 1.0, 3, c.sig, eta=max(1e-6, c.sig * c.px / max(c.adv, 1)), risk_aversion=ex.ac_risk_aversion, price=c.px)
            kids = [math.floor(k) for k in ac["trades"]]
            kids[-1] += int(qty - sum(kids))
            desc = f"Almgren-Chriss 3 slices (participation {part:.2%})"
        else:
            kids = [qty]; desc = f"single child (participation {part:.3%} <= {ex.single_order_max_participation:.0%})"
        children = [ctx.intent(c.symbol, "buy", math.floor(k * 1e6) / 1e6, "pipeline") for k in kids if k > 0]
        children = [k for k in children if k is not None]
        c.log("execution", desc + f"; pre-trade impact {c.impact['total_bps']:.1f} bps; {len(children)} child order(s), each re-checked by risk",
              "pass", children=len(children), qty=sum(k.qty for k in children))
        c.arrival = c.px
        return children

    def _finish(self, c: Candidate, now: datetime):
        tr = {"id": uuid.uuid4().hex[:12], "ts": now.isoformat(), "symbol": c.symbol, "side": c.side, "sleeve": c.sleeve,
              "stages": c.trail, "final": f"dropped at {c.dropped}" if c.dropped else "submitted",
              "shadow": {k: round(v, 4) for k, v in c.shadow.items()}}
        self.trail.append(tr)
        self.n_decisions = getattr(self, "n_decisions", 0) + 1
        if self.trail_max is not None and len(self.trail) > self.trail_max:
            del self.trail[: len(self.trail) - self.trail_max]
        # shadow scoring: realised forward return over the horizon (resolved later)
        if c.shadow:
            self.pending_outcomes.append({"symbol": c.symbol, "t0": now, "px0": float(c.close.iloc[-1]),
                                          "acting_factor": 0.0 if c.dropped else 1.0, "shadow": dict(c.shadow), "p": c.p})

    def _resolve_outcomes(self, frames, now):
        keep = []
        for o in self.pending_outcomes:
            df = frames.get(o["symbol"])
            if df is None:
                keep.append(o); continue
            after = df["close"][df.index > pd.Timestamp(o["t0"])]
            if len(after) < self.horizon:
                keep.append(o); continue
            o["ret"] = float(after.iloc[self.horizon - 1] / o["px0"] - 1)
            self.__dict__.setdefault("resolved", []).append(o)
        self.pending_outcomes = keep

    def shadow_week_results(self) -> dict[str, dict]:
        """Per shadow kind: after-cost lift of challenger vs acting decisions (bps), Brier for meta."""
        res = self.__dict__.pop("resolved", [])
        out: dict[str, dict] = {}
        kinds = {k for o in res for k in o["shadow"] if not k.endswith("_p")}
        for k in kinds:
            rows = [o for o in res if k in o["shadow"]]
            if not rows:
                continue
            ch = np.array([min(1.0, max(0.0, o["shadow"][k])) for o in rows])
            ac = np.array([o["acting_factor"] for o in rows])
            r = np.array([o["ret"] for o in rows])
            lift = float(((ch - ac) * r).mean() * 1e4)
            eq = np.cumsum(ch * r)
            dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max() * 100) if len(eq) else 0.0
            y = (r > 0).astype(float)
            pk = rows[0]["shadow"].get(k + "_p") is not None
            pb = np.array([o["shadow"].get(k + "_p", 0.5) for o in rows]) if pk else np.full(len(rows), 0.5)
            pa = np.array([o["p"] if o["p"] is not None else 0.5 for o in rows])
            out[k] = {"n": len(rows), "lift_bps": lift, "brier": float(((pb - y) ** 2).mean()),
                      "champion_brier": float(((pa - y) ** 2).mean()), "drawdown_pct": dd}
        return out


# ---------------------------------------------------------------------- live paper service wiring


# service glue lives in pipeline_service.py; re-exported for existing imports
from atlas.ops.pipeline_service import ServiceContext, paper_pipeline_step  # noqa: E402,F401
