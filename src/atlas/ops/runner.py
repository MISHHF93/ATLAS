"""atlas-run: the core paper loop for Docker/systemd. Heartbeats (in-process + shared
state for the external watchdog), reconciliation, owner actions, equity history, session-aware
job scheduler (daily summary, weekly kill-switch drill, learning loop). Paper only, no network."""
from __future__ import annotations

import argparse
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from atlas.risk.safety import assert_paper_only


def _drift_all(svc, root):
    """Sunday: PSI drift check of every champion against recent data it can see (auto-demotes on drift)."""
    from atlas.models.quant.drift import DriftMonitor
    from atlas.models.quant.multi import KINDS, registry_for
    from atlas.risk.ladder import evaluate_service
    recent = svc.store.get("recent_features") or {}
    import pandas as pd
    import time as _t
    drifted = []
    for k in KINDS:
        if k in recent:
            if DriftMonitor(registry_for(root, k, svc.audit)).check(pd.DataFrame(recent[k])).get("status") == "drift":
                drifted.append(k)
    if drifted:   # the autopilot pauses for 24 h after a demotion (see autopilot/engine.py guards)
        svc.store.set("autopilot.drift_alert", {"at": _t.time(), "kinds": drifted})
    evaluate_service(svc)


CORE_ETFS = ("SPY", "QQQ", "XIC", "VFV", "ZCN", "XEF", "VCN")
CRYPTO = ("BTC", "ETH", "BTC-CAD", "ETH-CAD")


def daily_pipeline(svc, now, data_dir: str | None = None) -> dict | None:
    """After the Toronto close, run one full-pipeline decision cycle on the local Parquet bars (if any).
    Children go to the owner approval queue at autonomy L1 (nothing auto-executes). Offline only."""
    from atlas.ops.timez import TORONTO
    import pandas as pd
    from atlas.research.backtest.engine import Instrument
    from atlas.ops.pipeline_full import paper_pipeline_step
    d = Path(data_dir or os.environ.get("ATLAS_ML_PARQUET_DIR", "") or "/nonexistent")
    loc = now.astimezone(TORONTO)
    key = f"pipeline_ran:{loc.date()}"
    if not d.is_dir() or loc.weekday() >= 5 or (loc.hour, loc.minute) < (16, 30) or svc.store.get(key):
        return None
    frames = {p.stem: pd.read_parquet(p) for p in sorted(d.glob("*.parquet"))}
    inst = {s: (Instrument(s, "CAD", "high_risk", "crypto_spot", "coinbase") if s in CRYPTO else
                Instrument(s, "USD" if s in ("SPY", "QQQ") else "CAD", "core", "index_etf", "ibkr") if s in CORE_ETFS else
                Instrument(s, "CAD", "active", "ca_equity", "ibkr")) for s in frames}
    out = paper_pipeline_step(svc, frames, inst, now)
    svc.store.set(key, True)
    return out


def build_jobs(svc, config_dir: str, report_dir: str, registry_dir: str):
    from atlas.ops.drill import run_drill
    from atlas.ops.jobs import JobScheduler
    from atlas.ops.summary import write_daily_summary
    from atlas.ops.timez import TORONTO
    tor = TORONTO

    def learning_loop(now):
        """Weekend: retrain every model kind as CHALLENGERS (never champions), then drift checks + ladder evaluation."""
        from atlas.models.quant.multi import weekly_retrain_all
        from atlas.models.quant.retrain import synthetic_bars
        from atlas.risk.ladder import evaluate_service
        import pandas as pd
        data = Path(os.environ.get("ATLAS_ML_PARQUET_DIR", "") or "/nonexistent")
        if data.is_dir():
            bars = {p.stem: pd.read_parquet(p) for p in data.glob("*.parquet")}
            by_sleeve = {"core_etf": {k: v for k, v in bars.items() if k in ("SPY", "QQQ", "XIC", "VFV")},
                         "active_equity": {k: v for k, v in bars.items() if k not in ("SPY", "QQQ", "XIC", "VFV", "BTC", "ETH")},
                         "crypto": {k: v for k, v in bars.items() if k in ("BTC", "ETH")}}
            by_sleeve = {k: v for k, v in by_sleeve.items() if v}
        else:  # offline demo data (deterministic)
            by_sleeve = {"core_etf": synthetic_bars(("SPY", "XIC")), "active_equity": synthetic_bars(("AAA", "BBB"), seed=1)}
        idx = next(iter(by_sleeve.get("core_etf", next(iter(by_sleeve.values()))).values()))["close"]
        weekly_retrain_all(registry_dir, by_sleeve, idx, audit=svc.audit)
        # recent feature windows for the Sunday PSI drift check
        from atlas.models.quant.features import FEATURES, dataset
        from atlas.models.quant.sleeves import SLEEVES
        recent = {f"scorer_{k}": dataset(v, SLEEVES[k]["horizon"], SLEEVES[k]["cost_bps"])[FEATURES].tail(300).to_dict("list")
                  for k, v in by_sleeve.items()}
        svc.store.set("recent_features", recent)
        evaluate_service(svc)

    handlers = {
        "daily_summary": lambda now: write_daily_summary(svc, now.astimezone(tor).date(), report_dir),
        "kill_switch_drill": lambda now: run_drill(config_dir, svc.audit),
        "reconciliation": lambda now: svc.reconcile(),
        "model_drift_report": lambda now: _drift_all(svc, registry_dir),
        "learning_loop": learning_loop,
    }
    return JobScheduler.from_schedule(svc.cfg.schedule.model_dump(), handlers, svc.store, svc.audit)


def main(argv=None) -> None:
    assert_paper_only()
    ap = argparse.ArgumentParser(prog="atlas-run")
    ap.add_argument("--config", default=os.environ.get("ATLAS_CONFIG_DIR", "config/founder"))
    ap.add_argument("--var", default=os.environ.get("ATLAS_VAR", "var"))
    ap.add_argument("--iterations", type=int, default=None)
    a = ap.parse_args(argv)
    from atlas.mcp.trading.service import build_service
    from atlas.risk.watchdog_proc import watchdog_alive, write_core_heartbeat
    var = Path(a.var); var.mkdir(parents=True, exist_ok=True)
    svc = build_service(a.config, str(var / "audit.sqlite"), str(var / "state.sqlite"), tax_db_path=str(var / "tax.sqlite"))
    if os.environ.get("ATLAS_REQUIRE_EXTERNAL_WATCHDOG", "false").lower() == "true":
        win = svc.watchdog.window_s
        svc.engine.external_watchdog = lambda: watchdog_alive(svc.store, win)
    svc.models_root = str(var / "models")
    jobs = build_jobs(svc, a.config, str(var / "reports"), str(var / "models"))
    from atlas.autopilot.engine import build_autopilot
    ap = build_autopilot(svc, a.config, str(var))
    stop = threading.Event()
    print("atlas-run: PAPER ONLY core loop started", flush=True)
    if a.iterations is not None:                    # deterministic, single-threaded (tests, one-shot runs)
        for _ in range(a.iterations):
            now = datetime.now(timezone.utc)
            safety_step(svc, now, write_core_heartbeat, ap)
            work_step(svc, jobs, now, ap=ap)
        return
    run_forever(svc, jobs, stop, write_core_heartbeat, ap)


def safety_step(svc, now, write_hb, ap=None) -> None:
    svc.ensure_session(now)  # ET date change => roll daily anchors / latch
    svc.heartbeat(); write_hb(svc.store)
    svc.watchdog.check(); svc.reconcile(); svc.process_owner_actions()
    from atlas.ops.equity import record_equity
    record_equity(svc, now)
    if ap is not None:
        try:
            ap.safety_check(now)                    # honours Stop within one heartbeat; pauses on guards
        except Exception as e:  # noqa: BLE001
            svc.audit.append("autopilot.safety_error", {"error": repr(e)[:300]})
    svc.persist()


def work_step(svc, jobs, now, lock=None, ap=None) -> None:
    """Slow work: scheduled jobs (retrain, drill, summary), the autopilot cycles (when it is on) or the once-a-day
    pipeline (when it is off). A failure never stops the safety loop."""
    try:
        jobs.tick(now)                              # retrain / drill / summary use their own data, not the live book
    except Exception as e:  # noqa: BLE001
        svc.audit.append("jobs.error", {"error": repr(e)[:300]})
    from atlas.autopilot.control import desired

    def step():
        if ap is not None:
            ap.tick(now)                            # runs cycles when on; keeps the status card fresh when off
        if ap is None or desired(svc.store) != "on":
            daily_pipeline(svc, now)                # the once-a-day pipeline only runs while the autopilot is off
    try:
        if lock is None:
            step()
        else:
            with lock:                              # touches the paper book: serialised with the safety loop
                step()
    except Exception as e:  # noqa: BLE001  a pipeline failure must never stop the safety loop
        svc.audit.append("pipeline.error", {"error": repr(e)[:300]})


def run_forever(svc, jobs, stop, write_hb, ap=None) -> None:
    """Safety loop on this thread, slow work on a worker thread, so a long retrain can never starve the heartbeat
    (the external watchdog halts trading after 3 missed beats). If the safety step itself cannot run for a full watchdog
    window (book lock held too long), heartbeats stop and the watchdog halts trading: fail closed."""
    lock = threading.RLock()
    interval = svc.watchdog.interval_s
    window = svc.watchdog.window_s

    def worker() -> None:
        while not stop.is_set():
            work_step(svc, jobs, datetime.now(timezone.utc), lock, ap)
            stop.wait(interval)
    threading.Thread(target=worker, name="core-work", daemon=True).start()
    import time as _t
    last_ok = _t.monotonic()
    while not stop.is_set():
        if lock.acquire(timeout=interval):
            try:
                safety_step(svc, datetime.now(timezone.utc), write_hb, ap)
                last_ok = _t.monotonic()
            finally:
                lock.release()
        elif _t.monotonic() - last_ok < window:
            write_hb(svc.store)                     # briefly blocked by the pipeline; still within the window
        else:
            svc.audit.append("core.safety_step_blocked", {"seconds": round(_t.monotonic() - last_ok, 1)})
        stop.wait(interval)
