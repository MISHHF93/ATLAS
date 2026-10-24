"""Research lab: tracked, reproducible experiments over the existing replay engine.

Each experiment replays one instrument/timeframe under several named variants (strategy toggles), then reports, per
variant: n trades, mean R, seeded bootstrap CI of mean R, cost sensitivity (R recomputed at 0x..3x the assumed cost),
plus across variants: Deflated Sharpe (models.quant.metrics) of the best variant against all trials, and PBO
(ml.metrics.pbo / CSCV) on a day x variant matrix. Runs are appended to a JSONL log under var/ (never committed) and
keyed by a report_id = sha256(bars hash, variants, replay config, seed, code sha), so the same inputs give the same id.
Descriptive research only: none of these numbers are validated performance estimates.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.replay import ReplayConfig, replay, trade_cost
from atlas.features.price_action.suite import StrategyToggles, SuiteConfig

from .data import SPEC, bars_hash, stable_hash

DEFAULT_VARIANTS: dict[str, dict[str, bool]] = {
    "sfp_only": {"sfp": True},
    "snapback_only": {"gold_snapback": True},
    "orb_only": {"gold_orb_breakout": True},
    "all_three": {"sfp": True, "gold_snapback": True, "gold_orb_breakout": True},
}
COST_MULTS = (0.0, 1.0, 2.0, 3.0)


def lab_dir() -> Path:
    return Path(os.environ.get("ATLAS_LAB_DIR", "var/lab"))


def _code_sha() -> str:
    from atlas.ml.registry import code_sha
    return code_sha()


def bootstrap_mean_ci(x, n_boot: int = 2000, seed: int = 7, alpha: float = 0.05) -> dict[str, Any] | None:
    x = np.asarray(x, float)
    if len(x) < 5:
        return None
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    return {"mean": float(x.mean()), "lo": float(np.quantile(means, alpha / 2)), "hi": float(np.quantile(means, 1 - alpha / 2)),
            "n_boot": n_boot, "seed": seed, "p_mean_le_0": float((means <= 0).mean())}


def _variant_engine(inst: str, bars, toggles: dict[str, bool], daily) -> EngineConfig:
    cal, tick, cpu, cbps, _ = SPEC.get(inst, ("crypto", 0.01, 0.0, 0.0, 96))
    allowed = {k: v for k, v in toggles.items() if k in StrategyToggles.__dataclass_fields__}
    sc = SuiteConfig(toggles=StrategyToggles(**allowed), tick=tick, calendar=cal, daily=daily,
                     cost_price=cpu + cbps * 1e-4 * bars[-1].close)
    return EngineConfig(suite=sc)


GOLD_TOGGLES = ("gold_snapback", "gold_orb_breakout")


def gold_alignment(tf: int, boxes=None) -> dict[str, Any]:
    """Gold opening boxes are built from bars that tile the box exactly; a timeframe that does not divide the box
    start/length can never build one (the detector then reports INSUFFICIENT_DATA, by design)."""
    boxes = boxes if boxes is not None else SuiteConfig().gold.boxes
    bad = []
    for bx in boxes:
        s = bx.start.hour * 3600 + bx.start.minute * 60
        e = bx.end.hour * 3600 + bx.end.minute * 60
        if s % tf or (e - s) % tf or e - s < tf:
            bad.append(f"{bx.name} {bx.start:%H:%M}-{bx.end:%H:%M} NY is not tiled by {tf // 60}m bars")
    return {"aligned": not bad, "problems": bad}


def run_experiment(inst: str, bars, *, daily=(), variants: dict[str, dict[str, bool]] | None = None, seed: int = 7,
                   n_boot: int = 2000, data_label: str = "real:atlas_feed", record: bool = True, name: str = "") -> dict[str, Any]:
    variants = variants or DEFAULT_VARIANTS
    if not bars:
        return {"status": "no_data", "instrument": inst, "note": "no confirmed bars available"}
    _, _, cpu, cbps, hold = SPEC.get(inst, ("crypto", 0.01, 0.0, 0.0, 96))
    rc = ReplayConfig(entry_window=3, max_hold_bars=hold, cost_per_unit=cpu, cost_bps=cbps)
    tf = bars[0].duration
    code = _code_sha()
    report_id = stable_hash({"bars": bars_hash(bars), "inst": inst, "tf": tf, "variants": variants, "rc": asdict(rc),
                             "seed": seed, "n_boot": n_boot, "code": code})[:16]
    per: dict[str, dict[str, Any]] = {}
    series: dict[str, np.ndarray] = {}
    by_day: dict[str, dict[int, float]] = {}
    for vname, tog in variants.items():
        res = replay(inst, tf, bars, engine_cfg=_variant_engine(inst, bars, tog, tuple(daily)), cfg=rc, data_label=data_label)
        done = [t for t in res.trades if t.r_multiple is not None and t.outcome in ("target", "stop", "timeout")]
        r = np.array([t.r_multiple for t in done], float)
        series[vname] = r
        by_day[vname] = {}
        for t in done:
            d = int(t.exit_at // 86400)
            by_day[vname][d] = by_day[vname].get(d, 0.0) + float(t.r_multiple)
        sens = []
        for k in COST_MULTS:
            rk = [t.r_multiple + (1.0 - k) * trade_cost(t, rc) / abs(t.entry - t.stop) for t in done if abs(t.entry - t.stop) > 0]
            sens.append({"cost_mult": k, "mean_r": float(np.mean(rk)) if rk else None, "n": len(rk)})
        zr = None
        if any(tog.get(g) for g in GOLD_TOGGLES) and not len(r):
            ga = gold_alignment(tf)
            if not ga["aligned"]:
                zr = "timeframe_mismatch: " + "; ".join(ga["problems"]) + " (run gold variants on 1m)"
            elif not res.candidates:
                zr = "no_setups: boxes buildable but no breakout/retest occurred in this sample"
        elif not len(r):
            zr = "no_setups" if not res.candidates else "candidates_not_filled_or_unresolved"
        per[vname] = {"toggles": tog, "zero_trade_reason": zr, "refused": res.refused, "n_trades": int(len(r)), "n_candidates": len(res.candidates),
                      "mean_r": float(r.mean()) if len(r) else None,
                      "win_rate": float((r > 0).mean()) if len(r) else None,
                      "sharpe_per_trade": float(r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else None,
                      "bootstrap_mean_r": bootstrap_mean_ci(r, n_boot, seed), "cost_sensitivity": sens}
    # deflated Sharpe: best variant vs all variants tried (per-trade series)
    from atlas.ml.metrics import dsr, pbo
    ranked = [v for v in per if per[v]["sharpe_per_trade"] is not None]
    dsr_out = None
    if ranked and len(ranked) >= 2:
        best = max(ranked, key=lambda v: per[v]["sharpe_per_trade"])
        d = dsr(series[best], [series[v] for v in ranked])
        dsr_out = {"best_variant": best, "basis": "per-trade R series (no annualisation)", **{k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in d.items() if k != "sr_annual"}}
    days = sorted({d for v in by_day.values() for d in v})
    pbo_out = None
    pbo_note = None
    if days and len(variants) >= 2:
        M = np.array([[by_day[v].get(d, 0.0) for v in variants] for d in days], float)
        nb = 8 if len(days) >= 16 else 0
        pbo_raw = pbo(M, n_blocks=nb) if nb else None
        if pbo_raw is None:
            pbo_note = f"too few active days ({len(days)}) for CSCV PBO (needs >= 16)"
        else:
            pbo_out = {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in pbo_raw.items()
                       if not isinstance(v, (list, np.ndarray))}
    out = {"status": "ok", "report_id": report_id, "name": name or f"{inst}-{tf // 60}m-variants", "instrument": inst,
           "timeframe_s": tf, "bars": len(bars), "bars_hash": bars_hash(bars), "first_bar": bars[0].start,
           "last_bar_end": bars[-1].start + bars[-1].duration, "data_label": data_label, "code_sha": code, "seed": seed,
           "replay_config": asdict(rc), "variants": per, "deflated_sharpe": dsr_out, "pbo": pbo_out, "pbo_note": pbo_note,
           "created_at": datetime.now(timezone.utc).isoformat(), "execution_permission": "none",
           "note": "descriptive OHLC replay; costs are research assumptions; not a validated performance estimate"}
    if record:
        record_run(out)
    return out


def record_run(rep: dict[str, Any]) -> Path:
    d = lab_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "experiments.jsonl"
    with p.open("a") as f:
        f.write(json.dumps(rep, default=str) + "\n")
    (d / f"report_{rep['report_id']}.md").write_text(render_md(rep))
    return p


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    p = lab_dir() / "experiments.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return rows[-limit:][::-1]


def render_md(rep: dict[str, Any]) -> str:
    L = [f"# Experiment {rep['report_id']} — {rep['name']}", "",
         f"- instrument {rep['instrument']} tf {rep['timeframe_s']}s bars {rep['bars']} data `{rep['data_label']}`",
         f"- bars_hash `{rep['bars_hash'][:16]}` code `{rep['code_sha']}` seed {rep['seed']}", f"- {rep['note']}", "",
         "| variant | n | mean R | 95% boot CI | R @0x/1x/2x/3x cost |", "|---|---|---|---|---|"]
    fmt = lambda v: "—" if v is None else f"{v:.3f}"  # noqa: E731
    for v, s in rep["variants"].items():
        b = s["bootstrap_mean_r"]
        L.append(f"| {v} | {s['n_trades']} | {fmt(s['mean_r'])} | {'—' if not b else f'{b[chr(108)+chr(111)]:.3f}..{b[chr(104)+chr(105)]:.3f}'} | "
                 + " / ".join(fmt(c["mean_r"]) for c in s["cost_sensitivity"]) + " |")
    L += ["", f"Deflated Sharpe: {rep['deflated_sharpe']}", f"PBO: {rep['pbo'] or rep['pbo_note']}"]
    return "\n".join(L) + "\n"
