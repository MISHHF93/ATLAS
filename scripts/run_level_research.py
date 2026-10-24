"""Replay research for the price-level suite (gold slice first, then SFP on other instruments) + selector comparison.

Usage: PYTHONPATH=src ATLAS_FEED_DB=... python scripts/run_level_research.py [--quick]
Writes docs/research/levels-2026-10-24.json (results only; no var/ data is committed).
Cost assumptions (round trip, NOT measured fills): GC/MGC/SI/ES futures 2 ticks + commission -> see COSTS;
crypto 24 bp; US equity 4 bp + $0.01 (ml/costs.py).
"""
from __future__ import annotations

import json
import sys
import time as T
from dataclasses import replace
from datetime import time

import numpy as np
import pandas as pd

from atlas.feeds.feed import get_feed
from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.replay import ReplayConfig
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.suite import GoldBox, GoldConfig, SFPConfig, StrategyToggles, SuiteConfig
from atlas.ml.selector import _stats, build_rows, evaluate
if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)


FAM = {"sfp_reversal": "sfp", "gold_snapback": "snapback", "gold_orb_breakout": "orb"}
from atlas.intel.data import SPEC  # noqa: E402  single source: futures rows derive from atlas.feeds.contracts


def load(feed, inst, iv, dur):
    out, last = [], None
    for b in feed.bars(inst, iv):
        if last is not None and b.event_time <= last:
            continue
        try:
            out.append(Bar(int(b.event_time), dur, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = b.event_time
    return out


def run(feed, inst, scfg_kw, toggles, label, cost_mult=1.0, bars=None, daily=None):
    cal, tick, cpu, cbps, hold = SPEC[inst]
    bars = bars or load(feed, inst, "15m", 900)
    daily = daily if daily is not None else tuple((int(b.event_time), b.high, b.low, b.close) for b in feed.bars(inst, "1d"))
    sc = SuiteConfig(toggles=toggles, tick=tick, calendar=cal, daily=daily, cost_price=cpu + cbps * 1e-4 * bars[-1].close, **scfg_kw)
    rc = ReplayConfig(entry_window=3, max_hold_bars=hold, cost_per_unit=cpu * cost_mult, cost_bps=cbps * cost_mult)
    df = build_rows(inst, bars, EngineConfig(suite=sc), rc, FAM)
    if len(df):
        df["variant"] = label
    return df, bars, daily


def report(df):
    if df is None or df.empty:
        return {"n": 0}
    out = {"all": _stats(df.r.to_numpy())}
    for col in ("family", "session", "vol_regime", "htf_bias", "instrument"):
        out[f"by_{col}"] = {str(k): _stats(g.r.to_numpy()) for k, g in df.groupby(col)}
    mid = df.t.median()
    out["window_stability"] = {"first_half": _stats(df[df.t <= mid].r.to_numpy()), "second_half": _stats(df[df.t > mid].r.to_numpy())}
    out["span_utc"] = [int(df.t.min()), int(df.t.max())]
    return out


def main(quick=False):
    feed = get_feed()
    res: dict = {"generated": int(T.time()), "fill_model": "conservative_ohlc_v1", "label_horizon": "max 1 day", "gold": {}, "sfp": {}}
    gold_boxes = (GoldBox("GOLD_OPENING_ORB", time(8, 20), time(8, 50)), GoldBox("GOLD_OPENING_ORB_0830", time(8, 30), time(9, 0)))
    pool = []
    for inst in ("GC", "MGC"):
        g = res["gold"][inst] = {}
        bars = daily = None
        for stop in ("box_opposite", "box_mid", "two_box_heights", "retest_extreme"):
            df, bars, daily = run(feed, inst, {"gold": GoldConfig(boxes=gold_boxes, stop=stop)}, StrategyToggles(False, True, True),
                                  f"gold_{stop}", bars=bars, daily=daily)
            g[f"stop={stop}"] = report(df)
            if stop == "box_opposite":
                pool.append(df)
                for m in (0.0, 2.0):
                    d2, *_ = run(feed, inst, {"gold": GoldConfig(boxes=gold_boxes, stop=stop)}, StrategyToggles(False, True, True),
                                 "cost", cost_mult=m, bars=bars, daily=daily)
                    g[f"cost_x{m:g}"] = report(d2)
        for mode in ("none", "next_bar", "displacement", "structure"):
            for htf in (False, True):
                df, *_ = run(feed, inst, {"sfp": SFPConfig(confirm=mode), "htf_filter": htf}, StrategyToggles(True, False, False),
                             f"sfp_{mode}_htf{int(htf)}", bars=bars, daily=daily)
                g[f"sfp confirm={mode} htf_filter={htf}"] = report(df)
                if mode == "none" and not htf:
                    pool.append(df)
    for inst in (("SI", "ES", "SPY") if quick else ("SI", "ES", "SPY", "ETHUSDT", "BTCUSDT")):
        df, *_ = run(feed, inst, {"sfp": SFPConfig(confirm="none")}, StrategyToggles(True, False, False), "sfp_none")
        res["sfp"][inst] = report(df)
        res["sfp"][inst]["bars"] = None
        pool.append(df)
    data = pd.concat([p for p in pool if p is not None and len(p)], ignore_index=True)
    data.to_pickle("/workspace/shots/sfp1/selector_rows.pkl")   # scratch cache, outside the repo
    sel = evaluate(data, n_folds=4, kinds=("logit", "hgb", "xgb", "lgbm"))
    res["selector"] = sel
    res["selector_rows"] = int(len(data))
    return res


if __name__ == "__main__":
    t0 = T.time()
    r = main("--quick" in sys.argv)
    r["runtime_s"] = round(T.time() - t0, 1)
    with open("docs/research/levels-2026-10-24.json", "w") as f:
        json.dump(r, f, indent=1, default=lambda o: o if not isinstance(o, (np.floating, np.integer)) else o.item())
    print(json.dumps({k: r["selector"]["variants"][k] for k in r["selector"]["variants"]}, indent=0, default=str)[:4000])
