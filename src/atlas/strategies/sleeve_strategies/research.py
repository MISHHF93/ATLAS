"""Run every round-2 item as a challenger on OFFLINE synthetic data (or your own parquet later):
each experiment -> trial log -> Deflated Sharpe over ALL trials -> registry challenger.

    atlas-research2 --models var/models [--seed 7]

Synthetic data has no real anomalies, so most alpha items should FAIL the DSR gate. That is the
honest expected outcome; real evaluation needs real point-in-time data."""
from __future__ import annotations

import argparse
import json
from datetime import date

import numpy as np
import pandas as pd

from atlas.strategies.sleeve_strategies.harness import evaluate_challenger


def synthetic_panel(n_days: int = 900, symbols=("A", "B", "C", "D"), seed: int = 7, mu: float = 0.06, sigma: float = 0.20,
                    start: date = date(2022, 1, 3)) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days)
    common = rng.normal(0, sigma / np.sqrt(252) * 0.7, n_days)
    out = {}
    for s in symbols:
        r = mu / 252 + common + rng.normal(0, sigma / np.sqrt(252) * 0.7, n_days)
        out[s] = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame(out, index=idx)


def run_all(root, seed: int = 7) -> list[dict]:
    from atlas.strategies.sleeve_strategies import cash_yield, crypto_factors, fx_cost, overlays, pairs, timing
    px = synthetic_panel(seed=seed)
    idx_close = px.mean(1)
    res = []
    # 1 cash yield: idle fraction 30-60% at 2.5% (deterministic carry; still logged + deflated)
    rng = np.random.default_rng(seed)
    idle = np.clip(0.45 + rng.normal(0, 0.05, len(px)), 0.2, 0.7)
    res.append(evaluate_challenger(root, "cash_yield", cash_yield.backtest(idle, np.full(len(px), 0.025)),
                                   {"buffer_pct": 5.0, "instrument": "best-yield allowed"}, "synthetic idle cash"))
    # 2 fx cost: monthly conversions 2k-20k
    conv = rng.uniform(2_000, 20_000, 36)
    res.append(evaluate_challenger(root, "fx_cost", fx_cost.savings_series(conv), {"routes": ["ibkr_spot", "norberts_gambit"]},
                                   "saving vs retail spread"))
    # 3 overlays: small grid (every grid point is a logged trial)
    for tv in (0.10, 0.15):
        vm = overlays.VolManaged(target_vol=tv)
        ex = overlays.overlay_returns(idx_close, vm.multipliers(idx_close)) - idx_close.pct_change().fillna(0)
        res.append(evaluate_challenger(root, "vol_managed", ex.values, {"target_vol": tv, "lookback": 21, "band": 0.1}, "excess vs buy&hold"))
    ts = overlays.TrendSwitch()
    ex = overlays.overlay_returns(idx_close, ts.multipliers(idx_close)) - idx_close.pct_change().fillna(0)
    res.append(evaluate_challenger(root, "trend_switch", ex.values, {"sma": 200, "mom_days": 252}, "excess vs buy&hold"))
    # 4 timing
    res.append(evaluate_challenger(root, "timing_tom", timing.tom_backtest(idx_close).values, {"before": 1, "after": 3}, "TOM-only vs always-in"))
    res.append(evaluate_challenger(root, "timing_auction", rng.normal(1.5e-5, 1e-5, len(px)), {"style": "closing_auction"},
                                   "assumed 1.5bp/day saving vs mid-day execution (cost model, not alpha)"))
    # 8 crypto factors (on synthetic crypto-like vol)
    cpx = synthetic_panel(seed=seed + 1, sigma=0.70, symbols=("BTC", "ETH", "SOL", "ADA"))
    cr = crypto_factors.CryptoFactorModel().backtest(cpx)
    res.append(evaluate_challenger(root, "crypto_factors", cr.values, {"ts": 28, "xs": 21, "maker_only": True}, "synthetic"))
    # 9 pairs
    pr = pairs.PairSwitcher().backtest(px["A"], px["B"])
    res.append(evaluate_challenger(root, "pairs", pr.values, {"lookback": 120, "entry_z": 1.5}, "excess vs equal-weight pair"))
    return res


def main(argv=None) -> None:
    from atlas.risk.safety import assert_paper_only
    assert_paper_only()
    ap = argparse.ArgumentParser(prog="atlas-research2")
    ap.add_argument("--models", default="var/models")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    for r in run_all(a.models, a.seed):
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}))
    print("All registered as CHALLENGERS (shadow only). Promotion needs DSR gate + >= 4 shadow weeks + owner sign-off.")


if __name__ == "__main__":
    main()
