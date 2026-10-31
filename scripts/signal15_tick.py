r"""15-minute clock tick for the shadow signal model. Paper / shadow only: execution_permission none, no orders.

Run it as its own process (never inside the API, ingest or roll loop), for example:

    cd C:\Users\borah\ATLAS-main
    $env:PYTHONPATH='src'
    .\.venv\Scripts\python.exe scripts\signal15_tick.py --loop --pid-file var\ml\signal15\tick.pid

It sleeps to the next 900 s boundary + --delay seconds, scores every instrument once, logs to var/ml/signal15/signals.jsonl,
resolves finished setups against real bars, issues and scores the stock nowcast (predicted, separate ledger), and writes
var/ml/signal15/heartbeat.json. Stop it by exact PID only (the PID is in the pid file and the heartbeat), e.g. Stop-Process -Id <pid>.
It never writes market data (feed DB is only read by FeedStore).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atlas.ai.ml import nowcast_xgb as N
from atlas.ai.ml import signal15 as S
from atlas.ai.ml import signal15_live as L
from atlas.feeds.store import FeedStore


def nowcast_step(feed, now: int) -> dict:
    """Issue the latest closed stock window and score due ones. Predictions go to their own ledger, never the feed store."""
    out = {"issued": 0, "scored": 0, "errors": []}
    try:
        led = N.Ledger()
    except Exception as exc:
        return out | {"errors": [f"ledger: {exc}"]}
    try:
        for g in ("stocks_15m",):
            b = N.load_bundle(g)
            if not b:
                out["errors"].append(f"{g}: no trained model")
                continue
            for t in N.PRIORITY_STOCKS:
                try:
                    if N.issue_stock(feed, led, b, g, t, now):
                        out["issued"] += 1
                except Exception as exc:
                    out["errors"].append(f"{g}/{t}: {type(exc).__name__}")
        out["scored"] = N.score_due(feed, led, now)
    finally:
        led.close()
    return out


def one_tick(db: str, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    feed = FeedStore(db)
    sig = L.tick_once(feed, now)
    resolved = L.resolve_signals(feed, now)
    nc = nowcast_step(feed, now)
    return {"issued_at": now, "n_actionable": sig["n_actionable"], "n_logged_new": sig["n_logged_new"], "resolved": resolved, "nowcast": nc}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/feeds/atlas_feed.sqlite")
    ap.add_argument("--loop", action="store_true", help="repeat on the 15-minute clock (default: one tick and exit)")
    ap.add_argument("--delay", type=int, default=45, help="seconds after each 15m boundary before scoring (bars need time to close)")
    ap.add_argument("--pid-file", default=str(L.root() / "tick.pid"))
    a = ap.parse_args()
    rt = L.root()
    rt.mkdir(parents=True, exist_ok=True)
    cmd = " ".join([Path(sys.executable).name] + sys.argv)
    if a.loop:
        Path(a.pid_file).write_text(str(os.getpid()))
    started, ticks, last = int(time.time()), 0, {}
    while True:
        try:
            last = one_tick(a.db)
            err = None
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
        ticks += 1
        L._atomic_json(rt / "heartbeat.json", {"state": "running" if a.loop else "once", "pid": os.getpid(), "command": cmd, "started_at": started,
                                              "last_tick_at": int(time.time()), "ticks": ticks, "interval_s": L.BAR, "delay_s": a.delay,
                                              "last": last, "last_error": err, "execution_permission": S.EXECUTION_PERMISSION, "mode": S.MODE})
        print(json.dumps({"tick": ticks, "at": int(time.time()), "error": err, "last": {k: v for k, v in last.items() if k != "nowcast"}}), flush=True)
        if not a.loop:
            return 0 if err is None else 1
        now = time.time()
        time.sleep(max(1.0, (now // L.BAR + 1) * L.BAR + a.delay - now))


if __name__ == "__main__":
    raise SystemExit(main())
