"""evo-20: rolling walk-forward retraining of the 1m / 5m horizon bundles on new real bars (research only, execution_permission none).

A challenger is trained on the newest real bars (``horizons.train_pool``: chronological fit / calibration / hold-out with an embargo), then compared with
the incumbent ONLY on real bars that arrived after the incumbent's last training bar plus a purge gap, and that the challenger itself never saw (its
hold-out block). Both models therefore score on bars neither trained on: no leakage in the comparison.  The challenger is promoted when its pinball loss
is no worse; otherwise the incumbent stays and the decision is logged.  The previous bundle is kept as ``.prev`` for rollback.
Nothing here writes to the bar store; no keyed FRED data is used (the context columns come from the same keyless sources as the trainer)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from atlas.ai.prediction import horizons as HZ

PURGE_ROWS = 5               # extra purge on top of the 2-row embargo between the incumbent's last training bar and the comparison window
MIN_EVAL_ROWS = 200          # fewer unseen rows than this and the incumbent stays (no decision on noise)
MAX_AGE_S = {"1m": 6 * 3600, "5m": 12 * 3600}
MIN_NEW_ROWS = {"1m": 1200, "5m": 400}       # new pooled rows since the incumbent's data_end before a retrain is worth running
LOG = "roll.jsonl"
STATUS_NAME = "roll_status.json"
SUPERVISOR_NAME = "roll_supervisor.json"
# A full 1m pass can run a long time. The cap stops a stuck iteration; the heartbeat
# shows a live one. 0 disables the cap. Promotion rules are unchanged.
DEFAULT_ITERATION_TIMEOUT_S = 4 * 3600
HEARTBEAT_S = 30.0
TIMED_OUT = 124


def cell_dir(pool: str, h: str, root=None) -> Path:
    return HZ.root_path(root) / f"{pool}-{h}"


def _bundle_pin(bundle: dict, rows: pd.DataFrame, model: str) -> tuple[float | None, int]:
    feats = bundle.get("features") or []
    if model not in bundle.get("models", {}) or any(f not in rows.columns for f in feats):
        return None, 0
    X = rows[feats].to_numpy(float)
    sig, y = rows["__sigma"].to_numpy(float), rows["__y"].to_numpy(float)
    q = HZ._pred(bundle["models"][model], X) * sig[:, None]
    return HZ.pinball_mean(y, q), int(len(y))


def compare(incumbent: dict | None, challenger: dict, rows: pd.DataFrame, data_end: int | None, test_slice: slice) -> dict[str, Any]:
    """Pinball (bps) of both bundles on the challenger's hold-out rows that are also strictly after the incumbent's data (+ purge). Leak-free by construction."""
    held = rows.iloc[test_slice]
    if incumbent is not None and data_end is not None:
        held = held[held["__t"] > data_end]
        held = held.iloc[PURGE_ROWS:] if len(held) > PURGE_ROWS else held.iloc[0:0]
    out: dict[str, Any] = {"n_eval": int(len(held)), "model": None, "incumbent_pin_bps": None, "challenger_pin_bps": None}
    if len(held) == 0:
        return out
    for model in ("lgbm", "xgb"):
        c, n = _bundle_pin(challenger, held, model)
        if c is None:
            continue
        out.update(model=model, challenger_pin_bps=round(c * 1e4, 4))
        if incumbent is not None:
            i, _ = _bundle_pin(incumbent, held, model)
            out["incumbent_pin_bps"] = None if i is None else round(i * 1e4, 4)
        break
    return out


def decide(cmp: dict, inc_exists: bool, age_s: float | None, max_age_s: float) -> tuple[str, str]:
    if not inc_exists:
        return "promote", "no incumbent bundle"
    if cmp["challenger_pin_bps"] is None:
        return "keep", "challenger has no comparable model"
    if cmp["incumbent_pin_bps"] is None:
        return "promote", "incumbent features/model not comparable (feature set changed)"
    if cmp["n_eval"] < MIN_EVAL_ROWS:
        return "keep", f"only {cmp['n_eval']} unseen rows (need {MIN_EVAL_ROWS}); incumbent stays"
    if cmp["challenger_pin_bps"] <= cmp["incumbent_pin_bps"]:
        return "promote", f"challenger pinball {cmp['challenger_pin_bps']} <= incumbent {cmp['incumbent_pin_bps']} bps on {cmp['n_eval']} unseen real bars"
    return "keep", f"challenger pinball {cmp['challenger_pin_bps']} > incumbent {cmp['incumbent_pin_bps']} bps on {cmp['n_eval']} unseen real bars"


def build_rows(feed, pool: str, h: str, max_bars: int, ref_loader: Callable | None, events, extra, symbols: list[str]) -> tuple[pd.DataFrame | None, list[str]]:
    iv = HZ.HORIZONS[h][0]
    frames, used = [], []
    for ins in symbols:
        try:
            bars = HZ.load_bars(feed, ins, iv)[-max_bars:]
            f = HZ.make_xy(bars, iv, pool, ins, ref_loader, events, extra)
        except Exception:  # noqa: BLE001
            continue
        if f is not None and len(f):
            frames.append(f)
            used.append(ins)
    return (pd.concat(frames, ignore_index=True) if frames else None), used


def retrain_cell(pool: str, h: str, rows: pd.DataFrame, used: list[str], now: float | None = None, root=None, force: bool = False) -> dict[str, Any]:
    """Train a challenger from ``rows`` and promote it only if it beats the incumbent on unseen real bars. ``rows`` is a pooled ``make_xy`` frame."""
    now = float(time.time() if now is None else now)
    d = cell_dir(pool, h, root)
    man, inc = HZ.load_bundle(pool, h, root)
    res: dict[str, Any] = {"pool": pool, "horizon": h, "at": int(now), "execution_permission": "none"}
    de = (man or {}).get("data_end") or (man or {}).get("created_at")     # a pre-evo-20 manifest has no data_end: its creation time is a safe upper bound
    if man is not None and not force:
        new_rows = int((rows["__t"] > (de or 0)).sum())
        age = now - float(man.get("created_at") or 0)
        if new_rows < MIN_NEW_ROWS[h] and age < MAX_AGE_S[h]:
            return {**res, "decision": "skip", "reason": f"{new_rows} new rows since data_end (< {MIN_NEW_ROWS[h]}) and bundle is {age / 3600:.1f} h old"}
    cand_root = d.parent / ".cand"
    r = HZ.train_pool(rows, pool, h, root=cand_root, instruments=used)
    if r.get("status") != "ok":
        return {**res, "decision": "keep", "reason": f"challenger not trained: {r.get('status')}", "detail": {k: r.get(k) for k in ("rows", "need")}}
    _, chal = HZ.load_bundle(pool, h, cand_root)
    n = len(rows.sort_values("__t", kind="stable"))
    srt = rows.sort_values("__t", kind="stable").reset_index(drop=True)
    cmp = compare(inc, chal, srt, de, HZ.split_slices(n)["test"])
    decision, why = decide(cmp, man is not None, (now - float(man["created_at"])) if man else None, MAX_AGE_S[h])
    if decision == "promote":
        cdir = cand_root / f"{pool}-{h}"
        if d.exists():
            prev = d.with_name(d.name + ".prev")
            if prev.exists():
                shutil.rmtree(prev)
            shutil.move(str(d), str(prev))
        shutil.move(str(cdir), str(d))
        HZ._CACHE.pop(str(d), None)
    else:
        shutil.rmtree(cand_root / f"{pool}-{h}", ignore_errors=True)
    out = {**res, "decision": decision, "reason": why, "compare": cmp, "data_end": r.get("data_end"), "n_rows": r.get("n_rows"), "instruments": len(used)}
    log = HZ.root_path(root) / LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        fh.write(json.dumps(out) + "\n")
    return out


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def write_status(payload: dict, root=None, name: str = STATUS_NAME) -> Path:
    """Atomically replace a small status file. Never raises past a disk error print."""
    p = HZ.root_path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {**payload, "execution_permission": "none", "heartbeat_at": payload.get("heartbeat_at", time.time())}
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(body, default=str))
    os.replace(tmp, p)
    return p


def append_event(event: dict, root=None) -> None:
    """One JSON line on the roll log. Lifecycle events (start, error, timeout) so a long fit is not silence."""
    try:
        log = HZ.root_path(root) / LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {"execution_permission": "none", **event}
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError as exc:
        print(f"roll log write failed: {type(exc).__name__}: {exc}", flush=True)


class Heartbeat:
    """Refresh ``roll_status.json`` while a cycle is inside a long fit (the log line is written only at the end)."""

    def __init__(self, root=None, interval: float = HEARTBEAT_S):
        self.root = root
        self.interval = interval
        self.state: dict[str, Any] = {"state": "running", "phase": "start", "pid": os.getpid(), "started_at": time.time()}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _flush(self) -> None:
        try:
            write_status({**self.state, "heartbeat_at": time.time()}, self.root, STATUS_NAME)
        except OSError as exc:
            print(f"roll status write failed: {type(exc).__name__}: {exc}", flush=True)

    def start(self) -> None:
        self._flush()
        self._thread = threading.Thread(target=self._run, name="roll-heartbeat", daemon=True)
        self._thread.start()

    def update(self, **kw: Any) -> None:
        self.state.update(kw)
        self._flush()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._flush()

    def stop(self, **kw: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if kw:
            self.state.update(kw)
        self._flush()


def supervise(command: list[str], *, timeout_s: float, env: dict | None = None, root=None, iteration: int = 1,
              heartbeat_s: float = HEARTBEAT_S) -> int:
    """Run one cycle in a child interpreter. Write a start line immediately, heartbeat while it runs, kill it at ``timeout_s``.

    The child is the worker. This process only supervises, so a stuck LightGBM fit cannot freeze the loop.
    ``timeout_s <= 0`` waits without a cap. Returns 124 on timeout, the child code otherwise.
    Does not promote anything; the child runs the same pinball rule as ``retrain_cell``.
    """
    started = time.time()
    append_event({"event": "cycle_start", "at": started, "iteration": iteration, "pid": os.getpid(), "timeout_s": timeout_s}, root)
    sup = {"state": "running", "iteration": iteration, "pid": os.getpid(), "started_at": started, "timeout_s": timeout_s, "phase": "spawn"}
    try:
        write_status(sup, root, SUPERVISOR_NAME)
    except OSError as exc:
        print(f"roll supervisor status failed: {type(exc).__name__}: {exc}", flush=True)
    try:
        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        append_event({"event": "cycle_error", "at": time.time(), "iteration": iteration, "error": f"{type(exc).__name__}: {exc}"}, root)
        try:
            write_status({**sup, "state": "error", "error": f"{type(exc).__name__}: {exc}"}, root, SUPERVISOR_NAME)
        except OSError:
            pass
        return 1
    t0 = time.monotonic()
    out = err = ""
    code: int | None = None
    timed_out = False
    while True:
        wait = heartbeat_s if timeout_s <= 0 else min(heartbeat_s, max(0.05, timeout_s - (time.monotonic() - t0)))
        try:
            out, err = proc.communicate(timeout=wait)
            code = proc.returncode
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t0
            try:
                write_status({**sup, "state": "running", "child_pid": proc.pid, "elapsed_s": round(elapsed, 1), "phase": "cycle"}, root, SUPERVISOR_NAME)
            except OSError:
                pass
            if timeout_s > 0 and elapsed >= timeout_s:
                timed_out = True
                proc.kill()
                try:
                    out, err = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    out, err = "", ""
                code = proc.returncode
                break
    tail_err = (err or "")[-800:]
    if timed_out:
        append_event({"event": "cycle_timeout", "at": time.time(), "iteration": iteration, "timeout_s": timeout_s,
                      "child_pid": proc.pid, "stderr": tail_err}, root)
        try:
            write_status({"state": "timeout", "iteration": iteration, "pid": os.getpid(), "child_pid": proc.pid,
                          "started_at": started, "timeout_s": timeout_s, "phase": "killed"}, root, STATUS_NAME)
            write_status({"state": "timeout", "iteration": iteration, "pid": os.getpid(), "child_pid": proc.pid,
                          "started_at": started, "timeout_s": timeout_s}, root, SUPERVISOR_NAME)
        except OSError:
            pass
        print(f"cycle timed out after {timeout_s:.0f}s (child {proc.pid}); loop continues", flush=True)
        return TIMED_OUT
    if code not in (0, None):
        append_event({"event": "cycle_exit", "at": time.time(), "iteration": iteration, "returncode": code,
                      "stderr": tail_err, "stdout_tail": (out or "")[-400:]}, root)
        try:
            write_status({"state": "error", "iteration": iteration, "pid": os.getpid(), "child_pid": proc.pid,
                          "returncode": code, "started_at": started}, root, SUPERVISOR_NAME)
        except OSError:
            pass
        if tail_err:
            print(tail_err, flush=True)
        return int(code)
    append_event({"event": "cycle_done", "at": time.time(), "iteration": iteration, "returncode": 0}, root)
    try:
        write_status({"state": "idle", "iteration": iteration, "pid": os.getpid(), "child_pid": proc.pid,
                      "started_at": started, "last_ok_at": time.time()}, root, SUPERVISOR_NAME)
    except OSError:
        pass
    if out:
        print(out, end="" if out.endswith("\n") else "\n", flush=True)
    return 0


def roll_status(root=None, tail: int = 50) -> dict[str, Any]:
    log = HZ.root_path(root) / LOG
    rows = []
    if log.exists():
        for ln in log.read_text().splitlines()[-tail:]:
            try:
                rows.append(json.loads(ln))
            except ValueError:
                continue
    cells = {}
    for pool in ("crypto",):
        for h in ("1m", "5m"):
            man, _ = HZ.load_bundle(pool, h, root)
            last = next((r for r in reversed(rows) if r.get("pool") == pool and r.get("horizon") == h), None)
            cells[f"{pool}-{h}"] = {"trained_at": (man or {}).get("created_at"), "data_end": (man or {}).get("data_end"), "last_decision": last}
    base = HZ.root_path(root)
    return {"cells": cells, "recent": rows[-10:], "worker": _read_json(base / STATUS_NAME), "supervisor": _read_json(base / SUPERVISOR_NAME),
            "rule": f"promote only if pinball <= incumbent on >= {MIN_EVAL_ROWS} real bars neither model trained on; "
            f"previous bundle kept as .prev", "execution_permission": "none", "label": HZ.LABEL,
            "loop": "each iteration writes cycle_start before training, heartbeats roll_status.json, and is killed after the timeout"}
