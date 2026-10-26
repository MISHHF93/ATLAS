"""Evo6 research: setup variants with wider ATR-scaled stops, higher timeframes and a cost-aware filter.

Every variant re-runs the unchanged live detection path (``replay``) with paper realism (latency 1 bar, trade-through
limits, 10% volume cap) and venue costs from ``atlas.ml.costs``. A variant only changes, per detected setup:
  - the stop: entry -/+ k * ATR(14) on closed bars at detection (``stop_atr_mult``), target at ``target_rr`` x risk;
  - the cost filter: skip the setup when round-trip cost / risk > ``max_cost_r`` (never filled, not counted);
  - the vertical barrier: ``hold_mult`` x the default one-trading-day hold.
Higher timeframes: 1h is read from the feed; 4h is derived from closed feed 1h bars (crypto only, UTC 4h buckets,
complete buckets only). Results are research evidence; gross R = net R + cost R. Nothing here grants execution.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np

from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.prior_day import PriorDayRangeConfig
from atlas.features.price_action.replay import paper_replay_config, replay, trade_cost
from atlas.ml import metrics as M
from atlas.ml.costs import VENUE_COSTS, venue_for
from atlas.ml.cv import walk_forward_splits
from atlas.ml.dataset import DETECTORS, UTC_DAY, SeriesData, load_series, resample_4h  # noqa: F401
from atlas.features.price_action.sessions import US_EQUITY_RTH


@dataclass(frozen=True)
class SetupVariant:
    id: str
    stop_atr_mult: float | None
    target_rr: float | None
    max_cost_r: float | None
    hold_mult: int
    description: str


VARIANTS: tuple[SetupVariant, ...] = (
    SetupVariant("base", None, None, None, 1, "detector's own stop/target (legacy)"),
    SetupVariant("base_cf15", None, None, 0.15, 1, "legacy stop/target, skip when cost/R > 0.15"),
    SetupVariant("atr2_rr2", 2.0, 2.0, None, 2, "stop 2 ATR, target 2R, 2-day hold"),
    SetupVariant("atr2_rr2_cf15", 2.0, 2.0, 0.15, 2, "stop 2 ATR, target 2R, cost/R <= 0.15, 2-day hold"),
    SetupVariant("atr3_rr1.5_cf15", 3.0, 1.5, 0.15, 2, "stop 3 ATR, target 1.5R, cost/R <= 0.15, 2-day hold"),
    SetupVariant("atr2.5_rr2_cf10", 2.5, 2.0, 0.10, 2, "stop 2.5 ATR, target 2R, cost/R <= 0.10, 2-day hold"),
    SetupVariant("atr3_rr2_cf08", 3.0, 2.0, 0.08, 3, "stop 3 ATR, target 2R, cost/R <= 0.08, 3-day hold"),
    SetupVariant("atr2_rr1.5_cf12", 2.0, 1.5, 0.12, 2, "stop 2 ATR, target 1.5R, cost/R <= 0.12, 2-day hold"),
)
VARIANT_BY_ID = {v.id: v for v in VARIANTS}
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM")
INTERVALS = ("15m", "1h", "4h")


def load(feed, symbol: str, interval: str, as_of: int | None = None) -> SeriesData | None:
    if interval == "4h":
        sd = load_series(feed, symbol, "1h", as_of=as_of)
        return resample_4h(sd) if sd.asset_class == "crypto" else None     # equity RTH 1h does not tile UTC 4h
    return load_series(feed, symbol, interval, as_of=as_of)


def hold_bars(interval: str, asset_class: str) -> int:
    if asset_class == "crypto":
        return {"15m": 96, "1h": 24, "4h": 6}[interval]
    return {"15m": 26, "1h": 7}[interval]


def run_variant(sd: SeriesData, v: SetupVariant) -> list[dict[str, Any]]:
    vc = VENUE_COSTS[venue_for(sd.asset_class)]
    session = UTC_DAY if sd.asset_class == "crypto" else US_EQUITY_RTH
    cfg = paper_replay_config(entry_window=3, max_hold_bars=hold_bars(sd.interval, sd.asset_class) * v.hold_mult,
                              cost_per_unit=vc["cost_per_unit"], cost_bps=vc["cost_bps"], zone_rule="zone_entry_v1",
                              stop_atr_mult=v.stop_atr_mult, target_rr=v.target_rr, max_cost_r=v.max_cost_r)
    res = replay(sd.instrument, sd.bars[0].duration, sd.bars, engine_cfg=EngineConfig(session=session, pdr=PriorDayRangeConfig()),
                 cfg=cfg, data_label="atlas-feed")
    rows = []
    for t in res.trades:
        if t.detector not in DETECTORS or t.outcome not in ("target", "stop", "timeout") or t.r_multiple is None:
            continue
        risk = abs(t.entry - t.stop)
        c = trade_cost(t, cfg) / risk
        rows.append({"instrument": sd.instrument, "interval": sd.interval, "variant": v.id, "detector": t.detector,
                     "candidate_id": t.candidate_id, "t": int(t.detected_at), "exit_at": int(t.exit_at), "outcome": t.outcome,
                     "direction": t.direction, "entry": t.entry, "stop": t.stop, "target": t.target,
                     "r": float(t.r_multiple), "cost_r": float(c), "gross_r": float(t.r_multiple + c)})
    return rows


def boot_ci(x: np.ndarray, n: int = 2000, seed: int = 0) -> tuple[float | None, float | None]:
    if len(x) < 10:
        return None, None
    rng = np.random.default_rng(seed)
    m = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def _r(x: float | None, k: int = 4) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), k)


def summarize(rows: Sequence[dict]) -> dict[str, Any]:
    r = np.array([x["r"] for x in rows], float)
    g = np.array([x["gross_r"] for x in rows], float)
    c = np.array([x["cost_r"] for x in rows], float)
    if not len(r):
        return {"n": 0}
    lo, hi = boot_ci(r)
    glo, ghi = boot_ci(g, seed=1)
    return {"n": int(len(r)), "win_rate": _r((r > 0).mean()), "net_r": _r(r.mean()), "gross_r": _r(g.mean()),
            "median_cost_r": _r(float(np.median(c))), "net_ci95": [_r(lo), _r(hi)], "gross_ci95": [_r(glo), _r(ghi)]}


def walk_forward_selection(rows: list[dict], configs: list[str], n_folds: int = 5) -> dict[str, Any]:
    """Purged + embargoed (1 day) walk-forward: in each fold pick the config with the best TRAIN net R (n>=30)
    and record its TEST trades. Reports the pooled OOS net/gross R of the selected configs."""
    if not rows:
        return {"n_oos": 0}
    rows = sorted(rows, key=lambda x: (x["t"], x["key"]))
    t = np.array([x["t"] for x in rows]); e = np.array([max(x["exit_at"], x["t"]) for x in rows])
    keys = np.array([x["key"] for x in rows]); r = np.array([x["r"] for x in rows]); g = np.array([x["gross_r"] for x in rows])
    oos_r, oos_g, picks = [], [], []
    for k, tr, te in walk_forward_splits(t, e, n_folds=n_folds, embargo=86400, min_train=30):
        best, bv = None, -np.inf
        for c in configs:
            m = keys[tr] == c
            if m.sum() >= 30 and r[tr][m].mean() > bv:
                best, bv = c, r[tr][m].mean()
        if best is None:
            continue
        m = keys[te] == best
        picks.append({"fold": k, "selected": best, "train_net_r": _r(bv), "test_n": int(m.sum()),
                      "test_net_r": _r(r[te][m].mean()) if m.any() else None})
        oos_r += list(r[te][m]); oos_g += list(g[te][m])
    a = np.array(oos_r)
    lo, hi = boot_ci(a) if len(a) else (None, None)
    return {"folds": picks, "n_oos": int(len(a)), "oos_net_r": _r(a.mean()) if len(a) else None,
            "oos_gross_r": _r(np.mean(oos_g)) if oos_g else None, "oos_net_ci95": [_r(lo), _r(hi)]}


def evaluate(all_rows: list[dict], min_n: int = 200, min_dsr: float = 0.95, max_pbo: float = 0.5) -> dict[str, Any]:
    """Per (instrument, interval, detector, variant) table, DSR over all trials, PBO (CSCV) and gates."""
    for x in all_rows:
        x["key"] = f"{x['instrument']}|{x['interval']}|{x['detector']}|{x['variant']}"
    by: dict[str, list[dict]] = {}
    for x in all_rows:
        by.setdefault(x["key"], []).append(x)
    if not by:
        return {"configs": [], "n_trials": 0}
    t0 = min(x["t"] for x in all_rows); t1 = max(x["t"] for x in all_rows)
    series = {k: M.daily_series([x["t"] for x in v], [x["r"] for x in v], t0, t1) for k, v in by.items()}
    trials = list(series.values())
    mat = np.column_stack(trials) if len(trials) > 1 else None
    pbo = M.pbo(mat) if mat is not None else None
    configs = []
    for k, v in sorted(by.items()):
        inst, iv, det, var = k.split("|")
        s = summarize(v)
        d = M.dsr(series[k], trials) if len(v) > 2 else {"dsr": 0.0}
        dsr = float(d.get("dsr") or 0.0)
        gates = [{"gate": "n>=%d" % min_n, "passed": s["n"] >= min_n},
                 {"gate": "net_ci95_low>0", "passed": bool(s.get("net_ci95") and s["net_ci95"][0] is not None and s["net_ci95"][0] > 0)},
                 {"gate": "dsr>=%.2f" % min_dsr, "passed": dsr >= min_dsr},
                 {"gate": "pbo<=%.2f" % max_pbo, "passed": bool(pbo and pbo["pbo"] <= max_pbo)}]
        configs.append({"instrument": inst, "interval": iv, "detector": det, "variant": var, **s, "dsr": _r(dsr),
                        "gates": gates, "passes_gates": all(g["passed"] for g in gates)})
    wf = {}
    for det in DETECTORS:
        sub = [x for x in all_rows if x["detector"] == det]
        wf[det] = walk_forward_selection(sub, sorted({x["key"] for x in sub}))
    return {"configs": configs, "n_trials": len(trials), "pbo": pbo, "walk_forward_selection": wf,
            "variants": [asdict(v) for v in VARIANTS]}


def aggregate(all_rows: list[dict], by: tuple[str, ...]) -> dict[str, Any]:
    g: dict[str, list[dict]] = {}
    for x in all_rows:
        g.setdefault("|".join(str(x[k]) for k in by), []).append(x)
    return {k: summarize(v) for k, v in sorted(g.items())}
