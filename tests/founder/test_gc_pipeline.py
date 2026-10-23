"""Gap closing 2: full pipeline wiring - monotone shrink-only, champions act, challengers shadow,
exits bypass models, fallbacks, risk re-check, service routing to the owner approval queue."""
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from atlas.research.backtest.engine import Backtester, Instrument
from atlas.control.policy import load_all
from atlas.ops.pipeline_full import FullPipeline, ModelSet, paper_pipeline_step
from atlas.research.screener.news import Headline, NewsScreener
from atlas.ops.sim import build_universe

CFG = "config/founder"


class FakeScorer:
    def __init__(self, p): self.p = p
    def p_hit(self, X): return np.full(len(X), self.p)
    def explain(self, X): return [[("ret_5", 0.1)]]


class FakeMeta:
    threshold = 0.55
    def __init__(self, f, p=0.6): self.f, self.p = f, p
    def size_factor(self, X): return np.full(len(X), self.f)
    def p_profit(self, X): return np.full(len(X), self.p)


class Boom:
    def __getattr__(self, k):
        def f(*a, **kw): raise RuntimeError("model exploded")
        return f


def _bt(models, start=date(2023, 1, 2), end=date(2023, 12, 29), seed=3, headlines=None):
    cfg = load_all(CFG)
    bars, inst = build_universe(start, end, seed)
    pipe = FullPipeline(cfg, models, NewsScreener(cfg.risk.ai_controls.llm_screener))

    class S:
        name = "t"
        def on_bar(self, ctx):
            return pipe.decide(ctx.now, ctx, list(bars), (headlines or (lambda s, t: {}))(list(bars), ctx.now), ctx._bt.engine)
    bt = Backtester(cfg, bars, inst, [S()], 100_000)
    return bt, pipe


def _qty_monotone(trail):
    for t in trail:
        if t["side"] != "buy":
            continue
        qs = [s["qty"] for s in t["stages"] if "qty" in s]
        assert all(b <= a + 1e-9 for a, b in zip(qs, qs[1:])), t


@pytest.fixture(scope="module")
def baseline():
    bt, pipe = _bt(ModelSet())
    res = bt.run()
    return bt, pipe, res


def test_full_stage_order_and_monotone_qty(baseline):
    _, pipe, res = baseline
    buys = [t for t in pipe.trail if t["side"] == "buy"]
    assert buys
    _qty_monotone(pipe.trail)
    sub = [t for t in buys if t["final"] == "submitted"]
    assert sub, "expected some submissions with rules-only fallback"
    order = [s["stage"] for s in sub[0]["stages"]]
    assert order == ["rules", "scorer"] + (["factor_sleeve"] if sub[0]["sleeve"] == "active" else []) + \
        ["meta_label", "news", "sizing", "portfolio", "cost", "risk", "execution"]
    assert res.trades > 0


def test_no_champion_means_fallbacks(baseline):
    _, pipe, _ = baseline
    t = next(t for t in pipe.trail if t["side"] == "buy")
    sc = next(s for s in t["stages"] if s["stage"] == "scorer")
    assert "rules-only half size" in sc["detail"] and sc["effect"] == "x0.5"


def test_champion_scorer_drops_and_meta_shrinks():
    ms = ModelSet(preloaded={f"scorer_{s}": FakeScorer(0.99) for s in ("core_etf", "active_equity", "crypto")} | {"meta_label": FakeMeta(0.5)})
    bt, pipe = _bt(ms, end=date(2023, 8, 31)); bt.run()
    t = next(t for t in pipe.trail if t["side"] == "buy" and any(s["stage"] == "meta_label" and "x0.50" in s["effect"] for s in t["stages"]))
    _qty_monotone(pipe.trail)
    low = ModelSet(preloaded={f"scorer_{s}": FakeScorer(0.10) for s in ("core_etf", "active_equity", "crypto")})
    bt2, pipe2 = _bt(low, end=date(2023, 8, 31)); r2 = bt2.run()
    buys = [t for t in pipe2.trail if t["side"] == "buy"]
    assert buys and all(t["final"] == "dropped at scorer" for t in buys) and r2.trades == 0


def test_challenger_in_shadow_never_changes_orders(baseline):
    _, pipe0, res0 = baseline
    ms = ModelSet()
    ms.shadow = {"meta_label": FakeMeta(0.0, 0.1), "scorer_active_equity": FakeScorer(0.0)}
    ms.ids = {"meta_label:shadow": "mX", "scorer_active_equity:shadow": "mY"}
    bt, pipe = _bt(ms); res = bt.run()
    assert res.trades == res0.trades and [t["final"] for t in pipe.trail] == [t["final"] for t in pipe0.trail]
    assert any("challenger(shadow)" in s["detail"] for t in pipe.trail for s in t["stages"])
    assert any(t.get("shadow", {}).get("meta_label") == 0.0 for t in pipe.trail)


def test_model_error_falls_back_and_is_logged():
    ms = ModelSet(preloaded={"scorer_core_etf": Boom(), "scorer_active_equity": Boom(), "scorer_crypto": Boom(), "meta_label": Boom()})
    bt, pipe = _bt(ms, end=date(2023, 6, 30)); bt.run()
    assert any(s["effect"] == "fallback" for t in pipe.trail for s in t["stages"])
    _qty_monotone(pipe.trail)


def test_news_veto_drops():
    def hl(syms, now): return {s: [Headline(now, "x", f"{s} trading halted")] for s in syms}
    bt, pipe = _bt(ModelSet(), end=date(2023, 6, 30), headlines=hl); r = bt.run()
    buys = [t for t in pipe.trail if t["side"] == "buy"]
    assert buys and all(t["final"] in ("dropped at news",) for t in buys) and r.trades == 0


def test_exits_bypass_models(baseline):
    _, pipe, _ = baseline
    ex = [t for t in pipe.trail if t["side"] == "sell"]
    assert ex and all(any("exits bypass" in s["detail"] for s in t["stages"]) for t in ex)


def test_service_step_queues_children_for_owner_approval():
    from atlas.mcp.trading.service import build_service
    from atlas.ops.sim import _frames
    svc = build_service(CFG); svc.heartbeat()
    bars, inst = build_universe(date(2023, 1, 2), date(2023, 9, 29), 3)
    fr = _frames(bars)
    out = {"decisions": 0}
    for d in pd.bdate_range("2023-06-01", "2023-09-28"):
        now = datetime(d.year, d.month, d.day, 21, tzinfo=timezone.utc)
        svc.heartbeat()
        out = paper_pipeline_step(svc, fr, inst, now)
        if out["queued_for_approval"]:
            break
    assert svc.approval_required and out["queued_for_approval"] and not out["routed"]
    assert len(svc.broker.fills) == 0                   # nothing executes without the owner
    trail = svc.store.get("decision_trail")
    assert trail and trail[-1]["routing"] == "owner_approval_queue"


def test_runner_daily_pipeline_once_per_day_after_close(tmp_path):
    from atlas.mcp.trading.service import build_service
    from atlas.ops.runner import daily_pipeline
    from atlas.ops.sim import _frames
    bars, _ = build_universe(date(2023, 1, 2), date(2023, 9, 29), 3)
    for s, df in _frames(bars).items():
        df.to_parquet(tmp_path / f"{s}.parquet")
    svc = build_service(CFG); svc.heartbeat()
    pre = datetime(2023, 9, 29, 15, 0, tzinfo=timezone.utc)          # 11:00 ET: too early
    assert daily_pipeline(svc, pre, str(tmp_path)) is None
    post = datetime(2023, 9, 29, 21, 0, tzinfo=timezone.utc)         # 17:00 ET
    out = daily_pipeline(svc, post, str(tmp_path))
    assert out is not None and out["decisions"] >= 0 and not out["routed"]
    assert daily_pipeline(svc, post, str(tmp_path)) is None           # once per day
