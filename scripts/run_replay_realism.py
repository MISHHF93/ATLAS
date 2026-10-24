"""Sensitivity of the GC 15m SFP replay to execution realism (latency, trade-through limits, participation caps).
Deterministic replay of atlas-feed bars; research numbers only, not a profitability claim."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_e2e_journey as J  # noqa: E402
from atlas.features.price_action.engine import EngineConfig  # noqa: E402
from atlas.features.price_action.replay import ReplayConfig, replay  # noqa: E402
from atlas.features.price_action.suite import GoldBox, GoldConfig, StrategyToggles, SuiteConfig  # noqa: E402

OUT = Path("/workspace/shots/full1/replay_realism.json")


def main():
    feed = J.get_feed()
    bars = J.load(feed, J.INST, "15m", J.TF)
    daily = tuple((int(b.event_time), b.high, b.low, b.close) for b in feed.bars(J.INST, "1d"))
    suite = SuiteConfig(toggles=StrategyToggles(True, True, True), tick=0.1, calendar="COMEX", daily=daily, cost_price=J.COST,
                        gold=GoldConfig(boxes=(GoldBox("GOLD_OPENING_ORB", J.time(8, 20), J.time(8, 50)),)))
    base = ReplayConfig(entry_window=3, max_hold_bars=96, cost_per_unit=J.COST)
    variants = {"baseline_touch": base, "latency_1bar": replace(base, latency_bars=1),
                "trade_through": replace(base, limit_fill="trade_through"),
                "latency_1bar_trade_through": replace(base, latency_bars=1, limit_fill="trade_through"),
                "trade_through_participation_1pct_qty5": replace(base, limit_fill="trade_through", order_qty=5, max_participation=0.01)}
    out = {"data": f"atlas-feed {J.INST} 15m, {len(bars)} bars", "note": "deterministic replay; ambiguous bars resolve to stop"}
    for k, cfg in variants.items():
        s = replay(J.INST, J.TF, bars, engine_cfg=EngineConfig(suite=suite), cfg=cfg, data_label=k).summary
        out[k] = {x: s.get(x) for x in ("candidates", "filled", "target", "stop", "timeout", "still_open",
                                        "ambiguous_bars_counted_as_stop", "mean_r", "total_r", "mean_fill_ratio", "total_weighted_r")}
    OUT.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
