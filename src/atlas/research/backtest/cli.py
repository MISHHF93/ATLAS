"""atlas-backtest: run the example core rebalancer + SMA strategy on synthetic data."""
from __future__ import annotations

import argparse
import json
from datetime import date

from atlas.control.policy import load_all
from atlas.marketdata.pit.synthetic import gbm_bars
from atlas.execution.paper.broker import CostModel
from atlas.research.backtest.engine import Backtester, Instrument
from atlas.portfolio.sleeves.rebalancer import SleeveRebalancer
from atlas.research.backtest.strategies import SleeveRebalanceStrategy, SmaCrossover

CORE = [("XIC", "XTSE", "CAD"), ("ZCN", "XTSE", "CAD"), ("XEF", "XTSE", "CAD"), ("VCN", "XTSE", "CAD"),
        ("SPY", "XNYS", "USD"), ("QQQ", "XNAS", "USD")]
HIGH_RISK = [("BTC-CAD", 0.6), ("ETH-CAD", 0.4)]
ACTIVE = [("AAA", "XNYS", "USD", "tech"), ("BBB", "XTSE", "CAD", "financials"), ("CCC", "XNAS", "USD", "health")]


def build(cfg, start: date, end: date, seed: int, total_equity: float, slippage_bps: float, commission: float):
    bars, inst = {}, {}
    for sym, venue, ccy in CORE:
        bars[sym] = gbm_bars(sym, venue, start, end, s0=50, mu=0.07, sigma=0.15, seed=seed)
        inst[sym] = Instrument(sym, ccy, "core", "index_etf", "ibkr")
    for sym, venue, ccy, sector in ACTIVE:
        bars[sym] = gbm_bars(sym, venue, start, end, s0=40, mu=0.10, sigma=0.30, seed=seed)
        inst[sym] = Instrument(sym, ccy, "active", "us_equity" if ccy == "USD" else "ca_equity", "ibkr", sector)
    for sym, _ in HIGH_RISK:
        bars[sym] = gbm_bars(sym, "crypto", start, end, s0=1000, mu=0.15, sigma=0.60, seed=seed)
        inst[sym] = Instrument(sym, "CAD", "high_risk", "crypto_spot", "coinbase")
    reb = SleeveRebalancer(cfg.risk, {"core": {s: 1 / len(CORE) for s, _, _ in CORE}, "high_risk": dict(HIGH_RISK)},
                           slippage_bps=slippage_bps, commission_per_order=commission)
    strategies = [SleeveRebalanceStrategy(reb), SmaCrossover([s for s, *_ in ACTIVE], weight=0.09)]
    return Backtester(cfg, bars, inst, strategies, total_equity, CostModel(slippage_bps, commission),
                      benchmark=[s for s, _, _ in CORE])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/founder")
    ap.add_argument("--start", default="2024-01-02")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--equity", type=float, default=100_000)
    ap.add_argument("--slippage-bps", type=float, default=5)
    ap.add_argument("--commission", type=float, default=1.0)
    a = ap.parse_args(argv)
    cfg = load_all(a.config)
    bt = build(cfg, date.fromisoformat(a.start), date.fromisoformat(a.end), a.seed, a.equity, a.slippage_bps, a.commission)
    res = bt.run()
    out = res.metrics | {"top_rejections": dict(res.rejections.most_common(8)), "final_bot_equity": res.equity_curve[-1][1]}
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
