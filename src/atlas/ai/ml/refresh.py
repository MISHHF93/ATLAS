"""Rolling refresh: incremental backfill -> PIT dataset -> purged walk-forward retrain -> registry -> drift -> shadow.

Every step is paper-only. Nothing here places, proposes or approves an order; shadow records are observations.
A model enters predict() only via ``registry.load_eligible`` and only if every pre-declared gate passed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from atlas.ai.ml import drift as D
from atlas.ai.ml import registry as R
from atlas.ai.ml.dataset import FEATURES, build_dataset
from atlas.ai.ml.train import PRIMARY, fit_final, run_training

UNIVERSE = [(i, iv) for i in ("BTCUSDT", "ETHUSDT", "SPY", "QQQ", "IWM") for iv in ("15m", "1h")]
# evo-10 chart scopes: the series the chart shows predictions for. Crypto (BTC/ETH/SOL), US equities/ETFs and gold
# (GC/MGC futures + GLD) at 1m, 15m, 1h and 1d. Gold is its own asset class so gold rules stay gold-only.
CHART_UNIVERSE = (
    [(i, iv) for i in ("BTCUSDT", "ETHUSDT", "SOLUSDT") for iv in ("1m", "15m", "1h", "1d")]
    + [(i, iv) for i in ("SPY", "QQQ", "AAPL", "NVDA", "MSFT", "TSLA") for iv in ("1m", "15m", "1h", "1d")]
    + [(i, iv) for i in ("GC", "MGC", "GLD") for iv in ("1m", "15m", "1h", "1d")]
)
UNIVERSES = {"default": UNIVERSE, "charts": CHART_UNIVERSE}
DRIFT_WINDOW_S = 30 * 86400


def incremental_backfill(feed, universe=UNIVERSE, now: int | None = None, default_days: dict[str, int] | None = None) -> list[dict]:
    """Fetch only bars after the last stored bar (or ``default_days`` of history if none)."""
    now = int(now or time.time())
    default_days = default_days or {"1m": 7, "15m": 59, "1h": 729, "1d": 729}
    out = []
    for inst, iv in universe:
        last = feed.bars(inst, iv)
        start = (int(last[-1].event_time) if last else now - default_days[iv] * 86400)
        try:
            r = feed.backfill(inst, iv, start, now)
            out.append({"instrument": inst, "interval": iv, "from": start, "result": getattr(r, "__dict__", str(r))})
        except Exception as exc:      # provider down / no network: report, keep training on what is stored
            out.append({"instrument": inst, "interval": iv, "from": start, "error": f"{type(exc).__name__}: {exc}"})
    return out


def drift_for_group(g: pd.DataFrame, oos: pd.DataFrame | None, window_s: int = DRIFT_WINDOW_S) -> dict[str, Any]:
    t1 = int(g.t.max())
    ref, cur = g[g.t < t1 - window_s], g[g.t >= t1 - window_s]
    out = {"reference_rows": int(len(ref)), "current_rows": int(len(cur)), "window_days": window_s // 86400,
           "psi": D.feature_psi(D.reference(ref, FEATURES), cur, min_n=30)}
    if oos is not None and len(oos):
        o = oos.sort_values("t")
        out["adwin_brier"] = D.adwin_report(((o["p_hgb"] - o.y) ** 2).to_numpy())
        out["adwin_hit"] = D.adwin_report((o.r > 0).astype(float).to_numpy())
    return out


def shadow_step(collector, man: dict, model, rows: pd.DataFrame) -> dict[str, int]:
    """Observe only *open* (unresolved) setups detected after the calibrator's fit window, so every shadow
    record is a genuine forward prediction made before the outcome existed; resolve them on later runs."""
    seen = {r["candidate_id"]: r for r in collector.records()}
    obs = res = 0
    elig = man["status"] == "eligible"
    fresh = rows[rows.t > int(man.get("fitted_through") or 0)]
    for _, r in fresh.iterrows():
        cid = r.candidate_id
        if cid not in seen and r.y < 0 and model is not None:
            d = model.decide(pd.DataFrame([r]))
            take = bool(d["take"][0])
            reasons = [] if elig else ["model_not_eligible"]
            reasons += [] if take else ["meta_skip_or_conformal_abstain"]
            cand = SimpleNamespace(candidate_id=cid, instrument=r.instrument, detector=r.detector, direction=r.direction,
                                   detected_at=int(r.t), entry_reference=r.entry, proposed_stop=r.stop, proposed_target=r.target)
            collector.observe(candidate=cand, decision="take" if take else "skip", reasons=reasons,
                              probability=float(d["p"][0]), expected_value_r=float(d["ev_r"][0]),
                              model_version=man["version"], data_label="atlas-feed")
            obs += 1
            seen[cid] = {"status": "observed"}
        if r.y >= 0 and cid in seen and not seen[cid].get("resolution") and seen[cid].get("status") != "resolved":
            collector.resolve(cid, outcome=r.outcome, r_multiple=float(r.r), exit_at=int(r.exit_at))
            seen[cid] = {"status": "resolved", "outcome": r.outcome}
            res += 1
    return {"observed": obs, "resolved": res}


def refresh(feed, *, universe=UNIVERSE, registry_root=None, backfill: bool = False, shadow=None,
            as_of: int | None = None, report_path: str | Path | None = None) -> dict[str, Any]:
    t0 = time.time()
    rep: dict[str, Any] = {"started_at": int(t0), "as_of": as_of}
    if backfill:
        rep["backfill"] = incremental_backfill(feed, universe, now=as_of)
    allrows, meta = build_dataset(feed, universe, as_of=as_of, include_open=True)
    data = allrows[allrows.y >= 0].reset_index(drop=True)
    rep["data_hash"], rep["n_rows"], rep["n_open"] = meta["data_hash"], int(len(data)), int((allrows.y < 0).sum())
    res = run_training(data)
    rep["n_trials"] = res["n_trials"]
    rep["groups"] = {}
    for key, out in res["groups"].items():
        ac, iv = key.split("-")
        if not out.get("variants"):
            rep["groups"][key] = {"status": "insufficient_data", "n_rows": out.get("n_rows")}
            continue
        model = fit_final(data, ac, iv, "hgb")
        man = R.register(key, out, meta, model, path=registry_root)
        g = data[(data.asset_class == ac) & (data.interval == iv)]
        dr = drift_for_group(g, out.get("_oos"))
        vdir = R.root(registry_root) / man["version"]
        (vdir / "drift.json").write_text(json.dumps(R._clean(dr), indent=1))
        (vdir / "reference.json").write_text(json.dumps(D.reference(g, FEATURES)))
        entry = {"version": man["version"], "status": man["status"], "gates": man["gates"], "drift_status": dr["psi"]["status"],
                 "adwin_brier_drift": (dr.get("adwin_brier") or {}).get("drift")}
        if shadow is not None:
            entry["shadow"] = shadow_step(shadow, man, model, allrows[(allrows.asset_class == ac) & (allrows.interval == iv)])
        rep["groups"][key] = entry
    rep["elapsed_s"] = round(time.time() - t0, 1)
    rep["primary"] = PRIMARY
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(R._clean(rep), indent=1))
    return rep
