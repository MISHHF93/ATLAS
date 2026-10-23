"""atlas-sim: end-to-end PAPER simulation on synthetic data through the FULL pipeline
(rules -> scorers -> factor -> meta-label -> news veto -> regime/vol/conformal sizing -> portfolio
-> cost filter -> risk engine -> execution plan -> paper broker), with weekly shadow scoring of
challengers, periodic challenger retrains and a per-decision explanation trail written to the
state store (dashboard: /api/decisions) and var/reports/sim_trail.json.

Offline, deterministic, paper only. Models act only as champions; with --use-challengers the
sim lets challengers act (research mode) - they still can only shrink/drop trades."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from atlas.risk.safety import assert_paper_only

CORE = [("XIC", "CAD"), ("SPY", "USD")]
ACTIVE = [("AAA", "USD", "tech"), ("BBB", "CAD", "financials"), ("CCC", "USD", "health"), ("DDD", "CAD", "energy")]
CRYPTO = ["BTC-CAD"]
VETO_HEADLINES = ["{s} trading halted pending news", "{s} faces fraud allegations"]
DOWNSIZE_HEADLINES = ["{s} announces secondary offering", "Analyst downgrade for {s}"]


def build_universe(start: date, end: date, seed: int):
    from atlas.research.backtest.engine import Instrument
    from atlas.marketdata.pit.synthetic import gbm_bars
    bars, inst = {}, {}
    for k, (s, ccy) in enumerate(CORE):
        bars[s] = gbm_bars(s, "XTSE" if ccy == "CAD" else "XNYS", start, end, s0=50, mu=0.07, sigma=0.15, seed=seed + k)
        inst[s] = Instrument(s, ccy, "core", "index_etf", "ibkr")
    for k, (s, ccy, sector) in enumerate(ACTIVE):
        bars[s] = gbm_bars(s, "XTSE" if ccy == "CAD" else "XNYS", start, end, s0=40, mu=0.10, sigma=0.30, seed=seed + 10 + k)
        inst[s] = Instrument(s, ccy, "active", "us_equity" if ccy == "USD" else "ca_equity", "ibkr", sector)
    for k, s in enumerate(CRYPTO):
        bars[s] = gbm_bars(s, "crypto", start, end, s0=1000, mu=0.15, sigma=0.60, seed=seed + 20 + k)
        inst[s] = Instrument(s, "CAD", "high_risk", "crypto_spot", "coinbase")
    return bars, inst


def _frames(bars, until=None):
    out = {}
    for s, bs in bars.items():
        rows = [b for b in bs if until is None or b.ts.date() <= until]
        out[s] = pd.DataFrame({"close": [b.close for b in rows], "volume": [b.volume for b in rows]},
                              index=pd.DatetimeIndex([b.ts for b in rows]).tz_localize(None))
    return out


def retrain(root, bars, inst, until, audit=None) -> dict:
    from atlas.models.quant.multi import weekly_retrain_all
    fr = _frames(bars, until)
    by = {"core_etf": {s: fr[s] for s in fr if inst[s].sleeve == "core"},
          "active_equity": {s: fr[s] for s in fr if inst[s].sleeve == "active"},
          "crypto": {s: fr[s] for s in fr if inst[s].sleeve == "high_risk"}}
    idx = fr[CORE[0][0]]["close"]
    return weekly_retrain_all(root, by, idx, audit=audit)


class PipelineStrategy:
    name = "full_pipeline"

    def __init__(self, pipeline, symbols, start_trading: date, headline_rate: float, seed: int, on_week=None, on_retrain=None,
                 retrain_every_weeks: int = 0):
        self.p, self.symbols, self.start = pipeline, symbols, start_trading
        self.rng = random.Random(seed)
        self.rate = headline_rate
        self.on_week, self.on_retrain, self.every = on_week, on_retrain, retrain_every_weeks
        self._week = None
        self._weeks_seen = 0

    def _headlines(self, now):
        from atlas.research.screener.news import Headline
        out = {}
        for s in self.symbols:
            if self.rng.random() < self.rate:
                tpl = self.rng.choice(VETO_HEADLINES + DOWNSIZE_HEADLINES + ["{s} hosts investor day"] * 4)
                out[s] = [Headline(now, "synthetic-wire", tpl.format(s=s))]
        return out

    def on_bar(self, ctx):
        if ctx.now.date() < self.start:
            return []
        wk = ctx.now.isocalendar()[:2]
        if wk != self._week:
            if self._week is not None:
                self._weeks_seen += 1
                if self.on_week:
                    self.on_week(f"{self._week[0]}-W{self._week[1]:02d}")
                if self.every and self._weeks_seen % self.every == 0 and self.on_retrain:
                    self.on_retrain(ctx.now.date())
            self._week = wk
        return self.p.decide(ctx.now, ctx, self.symbols, self._headlines(ctx.now), ctx._bt.engine)


def run_sim(config_dir="config", var="var/sim", start="2023-01-02", end="2025-06-30", warmup_end="2024-06-28", seed=7,
            equity=100_000.0, retrain_every_weeks=0, use_challengers=False, headline_rate=0.03, fresh=True, verbose=True) -> dict:
    assert_paper_only()
    import shutil
    from atlas.research.backtest.engine import Backtester
    from atlas.control.policy import load_all
    from atlas.execution.paper.broker import CostModel
    from atlas.models.quant.multi import models_overview, registry_for
    from atlas.models.quant.stack2 import n_trials
    from atlas.ops.pipeline_full import FullPipeline, ModelSet
    from atlas.risk.state_store import StateStore
    from atlas.research.screener.news import NewsScreener
    var = Path(var)
    root = var / "models"
    if fresh and root.exists():
        shutil.rmtree(root)
    var.mkdir(parents=True, exist_ok=True)
    cfg = load_all(config_dir)
    s0, e0, w0 = (date.fromisoformat(x) for x in (start, end, warmup_end))
    bars, inst = build_universe(s0, e0, seed)
    log = lambda *a: print(*a, flush=True) if verbose else None  # noqa: E731
    log(f"[sim] warm-up training on {start}..{warmup_end} (challengers only)")
    retrains = [{"until": warmup_end, "result": _brief(retrain(root, bars, inst, w0))}]
    screener = NewsScreener(cfg.risk.ai_controls.llm_screener)
    holder = {"p": FullPipeline(cfg, ModelSet(root, use_challengers), screener)}
    holder["p"].trail_max = None
    shadow_log = []

    def on_week(week):
        res = holder["p"].shadow_week_results()
        ms = holder["p"].models
        for kind, r in res.items():
            mid = ms.ids.get(f"{kind}:shadow")
            if mid and r["n"] > 0:
                registry_for(root, kind).record_shadow_week(mid, week, r)
                shadow_log.append({"week": week, "kind": kind, "model_id": mid, **{k: round(v, 4) for k, v in r.items()}})

    def on_retrain(d):
        log(f"[sim] retrain challengers on data <= {d}")
        retrains.append({"until": str(d), "result": _brief(retrain(root, bars, inst, d))})
        old = holder["p"]
        newp = FullPipeline(cfg, ModelSet(root, use_challengers), screener)
        newp.trail, newp.pending_outcomes, newp.trail_max = old.trail, old.pending_outcomes, None
        holder["p"] = newp
        strat.p = newp

    strat = PipelineStrategy(holder["p"], list(bars), w0 + timedelta(days=1), headline_rate, seed, on_week, on_retrain, retrain_every_weeks)
    bt = Backtester(cfg, bars, inst, [strat], equity, CostModel(5, 1.0), benchmark=[CORE[0][0]])
    log(f"[sim] paper trading {w0 + timedelta(days=1)}..{end} through the full pipeline")
    res = bt.run()
    trail = holder["p"].trail
    finals = Counter(t["final"] for t in trail)
    summary = {"mode": "paper simulation (synthetic data)", "use_challengers": use_challengers,
               "period": f"{w0 + timedelta(days=1)}..{end}", "decisions": len(trail), "outcomes": dict(finals),
               "fills": res.trades, "final_bot_equity": res.equity_curve[-1][1] if res.equity_curve else None,
               "metrics": res.metrics, "risk_rejections": dict(res.rejections.most_common(6)),
               "retrains": retrains, "shadow_weeks_recorded": len(shadow_log), "total_trials_logged": n_trials(root),
               "models": [{k: m.get(k) for k in ("kind", "status", "champion", "challenger", "shadow_weeks")} for m in models_overview(root)],
               "acting_models": sorted(holder["p"].models.acting)}
    store = StateStore(str(var / "state.sqlite"))
    from atlas.risk.trail import dedupe
    store.set("decision_trail", dedupe(trail))
    store.set("sim_summary", summary)
    rep = var / "reports"; rep.mkdir(exist_ok=True)
    (rep / "sim_trail.json").write_text(json.dumps(trail, indent=1, default=str))
    (rep / "sim_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (rep / "shadow_weeks.json").write_text(json.dumps(shadow_log, indent=1))
    return summary | {"trail": trail}


def _brief(out: dict) -> dict:
    b = {}
    for k, v in out.items():
        if k == "scorers":
            b[k] = {s: r["model_id"] for s, r in v.items()}
        elif isinstance(v, dict):
            b[k] = v.get("model_id", v.get("skipped"))
    return b


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="atlas-sim", description="End-to-end paper simulation (synthetic data, offline).")
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--var", default="var/sim")
    ap.add_argument("--start", default="2023-01-02")
    ap.add_argument("--warmup-end", default="2024-06-28")
    ap.add_argument("--end", default="2025-06-30")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--retrain-every-weeks", type=int, default=8)
    ap.add_argument("--use-challengers", action="store_true", help="research mode: challengers act (still shrink/drop only)")
    ap.add_argument("--headline-rate", type=float, default=0.03)
    a = ap.parse_args(argv)
    s = run_sim(a.config, a.var, a.start, a.end, a.warmup_end, a.seed, retrain_every_weeks=a.retrain_every_weeks,
                use_challengers=a.use_challengers, headline_rate=a.headline_rate)
    s.pop("trail")
    print(json.dumps(s, indent=1, default=str))
    print(f"\nExplanation trail: {a.var}/reports/sim_trail.json\n"
          f"Dashboard: ATLAS_STATE_DB={a.var}/state.sqlite ATLAS_MODELS_DIR={a.var}/models atlas-dashboard  -> Decisions panel")


if __name__ == "__main__":
    main()
