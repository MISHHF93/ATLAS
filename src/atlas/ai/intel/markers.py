"""Chart opportunity markers (research signal, paper only, not advice).

Sources (both causal; a marker sits on the confirmation bar, i.e. the bar whose END == detected_at, never earlier):
  1. unified candidate engine (the replay of the default engine + every suite toggle) -> each Candidate goes through
     the unified ``proposals.evaluate`` gate (models.predict -> models.opportunity.evaluate_candidate). With no
     validated calibrated model the gate abstains: probability is shown as "uncalibrated/LOW_CONFIDENCE".
  2. the research champion of the model-evolution loop: walk-forward OUT-OF-SAMPLE calibrated p / EV_R per
     candidate (ml.evolution.oos_predictions) for its instruments; never in-sample numbers.
Classes: ml_suggested (OOS EV_R > 0 and conformal take), ml_skip, rule_only (gate abstained only for lack of a
validated model), risk_rejected (gate rejected on geometry/costs/edge). ``risk_status`` is the gate result the
deterministic control plane would receive; ML never authorizes or sizes (execution_permission none).
Outcome = replay result on real prices: target / stop / timeout / open / not_filled.
"""
from __future__ import annotations

import json
import math
from typing import Any

DISCLAIMER = "research signal, paper only, not advice"
MODEL_ABSENT = {"NO_VALIDATED_MODEL", "MODEL_UNAVAILABLE", "UNCALIBRATED", "NO_MODEL", "LOW_CONFIDENCE"}


def _model_absent(reasons) -> bool:
    return bool(reasons) and all(any(k in str(r).upper() for k in ("MODEL", "CALIBRAT", "LOW_CONFIDENCE", "VALIDATED")) for r in reasons)


def from_replay(res, tf: int, cost_per_unit: float = 0.0) -> list[dict[str, Any]]:
    from atlas.features.price_action.proposals import evaluate
    by_c = {t.candidate_id: t for t in res.trades}
    out = []
    for c in res.candidates:
        try:
            pred, ev = evaluate(c, cost_per_unit=cost_per_unit)
            reasons = list(ev.abstention_reason)
            prob = ev.probability
            mv = getattr(pred, "model_version", None)
            evr = ev.expected_value_r
        except Exception as e:  # noqa: BLE001 - gate failure is a rejection, never an approval
            reasons, prob, mv, evr = [f"gate_error:{type(e).__name__}"], None, None, None
        if not reasons:
            cls, risk = ("ml_suggested" if prob is not None else "rule_only"), "authorized_for_control_plane"
        elif _model_absent(reasons):
            cls, risk = "rule_only", "gate abstained, no validated model (not a risk rejection): " + ",".join(map(str, reasons))
        else:
            cls, risk = "risk_rejected", "rejected: " + ",".join(map(str, reasons))
        t = by_c.get(c.candidate_id)
        gain = abs(c.proposed_target - c.entry_reference)
        loss = abs(c.entry_reference - c.proposed_stop)
        out.append({"id": c.candidate_id, "source": "candidate_engine", "strategy": c.detector, "direction": c.direction,
                    "time": int(c.detected_at - tf), "detected_at": int(c.detected_at), "price": c.entry_reference,
                    "stop": c.proposed_stop, "target": c.proposed_target,
                    "probability": prob, "probability_label": f"{prob:.2f}" if prob is not None else "uncalibrated/LOW_CONFIDENCE",
                    "uncertainty": None, "ev_r": evr,
                    "gross_rr": gain / loss if loss > 0 else None, "model_version": mv or "none (no validated model)",
                    "risk_status": risk, "class": cls,
                    "outcome": (t.outcome if t else "not_filled"), "r": (t.r_multiple if t else None),
                    "filled_at": (t.filled_at if t else None), "exit_at": (t.exit_at if t else None),
                    "exit_price": (t.exit_price if t else None), "gate_reasons": [str(r) for r in reasons],
                    "zone_touched": _zone_label(getattr(c, "zone", None))})
    return out


def _zone_label(z) -> str | None:
    if not isinstance(z, dict) or not z:
        return None
    kind = z.get("zone_type") or z.get("type") or z.get("kind") or "zone"
    lo, hi = z.get("lower_bound", z.get("low")), z.get("upper_bound", z.get("high"))
    rng = f" {lo:.6g}-{hi:.6g}" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
    return f"{str(kind).replace('_', ' ')}{rng}"


_LIVE_WF_CACHE: dict[tuple[Any, ...], tuple[list[dict[str, Any]], dict[str, Any]]] = {}


def _live_walk_forward_oos(
    inst: str,
    interval: str,
    bars: list[Any],
    rule_markers: list[dict[str, Any]] | None,
    run: dict[str, Any],
    has_champion: bool,
    tf: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute causal walk-forward out-of-sample calibrated probabilities and EV_R on closed bars & setups."""
    import copy
    from atlas.ai.ml import metrics as M
    import numpy as np

    n_bars = len(bars)
    if n_bars < 45:
        return [], {}

    cache_key = (
        inst,
        interval,
        n_bars,
        int(bars[0].start),
        int(bars[-1].start),
        len(rule_markers or []),
        str(run.get("run_id")),
        bool(has_champion),
    )
    if cache_key in _LIVE_WF_CACHE:
        cached_m, cached_meta = _LIVE_WF_CACHE[cache_key]
        return copy.deepcopy(cached_m), dict(cached_meta)

    best = run.get("best_passing_strict_gate") or run.get("best_beating_baseline") or run.get("best") or {}
    mv = f"evolution:{run['run_id']}:{best.get('genome_id') or 'hgb|full|none|time'}:live_wf"
    risk_status = (
        "not_submitted (research champion only; ML cannot authorize)"
        if has_champion
        else "research-only (no research champion; failed strict gate; ML cannot authorize)"
    )

    closes = np.array([float(b.close) for b in bars], dtype=float)
    opens = np.array([float(b.open) for b in bars], dtype=float)
    highs = np.array([float(b.high) for b in bars], dtype=float)
    lows = np.array([float(b.low) for b in bars], dtype=float)
    vols = np.array([float(getattr(b, "volume", 0.0) or 0.0) for b in bars], dtype=float)
    times = np.array([int(b.start) for b in bars], dtype=np.int64)

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    atr = np.empty(n_bars, dtype=float)
    atr[0] = max(highs[0] - lows[0], closes[0] * 0.002)
    for i in range(1, n_bars):
        w = tr[max(0, i - 14) : i]
        atr[i] = float(w.mean()) if len(w) else atr[0]

    X_all = np.zeros((n_bars, 7), dtype=float)
    X_all[:, 0] = 1.0
    for i in range(12, n_bars):
        c_i = max(closes[i], 1e-9)
        a_i = max(atr[i], c_i * 0.0005)
        r1 = (closes[i] - closes[i - 1]) / a_i
        r3 = (closes[i] - closes[i - 3]) / (a_i * 1.732)
        r12 = (closes[i] - closes[i - 12]) / (a_i * 3.464)
        rng_i = max(highs[i] - lows[i], a_i * 0.1)
        body = (closes[i] - opens[i]) / rng_i
        ema_fast = float(closes[max(0, i - 10) : i + 1].mean())
        ema_slow = float(closes[max(0, i - 30) : i + 1].mean())
        ema_sp = (ema_fast - ema_slow) / a_i
        v_win = vols[max(0, i - 20) : i + 1]
        v_std = float(v_win.std()) if len(v_win) > 2 else 0.0
        vz = float((vols[i] - v_win.mean()) / v_std) if v_std > 0 else 0.0
        X_all[i, 1:] = np.clip([r1, r3, r12, body, ema_sp, vz], -3.5, 3.5)

    bar_idx_by_time = {int(t): idx for idx, t in enumerate(times)}
    events: list[dict[str, Any]] = []
    used_times: set[int] = set()

    for m in rule_markers or []:
        t_bar = int(m.get("time", 0))
        idx = bar_idx_by_time.get(t_bar)
        if idx is None or idx < 24:
            continue
        used_times.add(t_bar)
        events.append(
            {
                "idx": idx,
                "time": t_bar,
                "detected_at": int(m.get("detected_at", t_bar + tf)),
                "candidate_id": str(m.get("id", f"{inst}:{interval}:{t_bar}")),
                "strategy": str(m.get("strategy", "orb_retest")),
                "direction": str(m.get("direction", "long")),
                "price": float(m.get("price", closes[idx])),
                "stop": float(m.get("stop", closes[idx] - atr[idx])),
                "target": float(m.get("target", closes[idx] + 1.8 * atr[idx])),
                "outcome": str(m.get("outcome", "open")),
                "r": m.get("r"),
            }
        )

    horizon = 6
    step = max(3, min(12, (n_bars - 36) // 48)) if n_bars > 60 else 3
    for idx in range(28, n_bars - 1, step):
        t_bar = int(times[idx])
        if t_bar in used_times:
            continue
        dir_long = bool(X_all[idx, 2] + 0.5 * X_all[idx, 5] >= 0.0)
        direction = "long" if dir_long else "short"
        entry = float(closes[idx])
        stop_dist = max(float(atr[idx]), entry * 0.0025)
        target_dist = 1.65 * stop_dist
        stop_px = entry - stop_dist if dir_long else entry + stop_dist
        target_px = entry + target_dist if dir_long else entry - target_dist

        outcome = "open"
        r_val: float | None = None
        if idx + horizon < n_bars:
            outcome = "timeout"
            for j in range(idx + 1, idx + horizon + 1):
                if dir_long:
                    if lows[j] <= stop_px:
                        outcome, r_val = "stop", -1.04
                        break
                    if highs[j] >= target_px:
                        outcome, r_val = "target", 1.60
                        break
                else:
                    if highs[j] >= stop_px:
                        outcome, r_val = "stop", -1.04
                        break
                    if lows[j] <= target_px:
                        outcome, r_val = "target", 1.60
                        break
            if outcome == "timeout":
                move = (closes[idx + horizon] - entry) if dir_long else (entry - closes[idx + horizon])
                r_val = float(np.clip(move / stop_dist - 0.04, -1.04, 1.60))

        events.append(
            {
                "idx": idx,
                "time": t_bar,
                "detected_at": t_bar + tf,
                "candidate_id": f"wf:{inst}:{interval}:{t_bar}",
                "strategy": "walk_forward_barrier",
                "direction": direction,
                "price": round(entry, 6),
                "stop": round(stop_px, 6),
                "target": round(target_px, 6),
                "outcome": outcome,
                "r": round(float(r_val), 4) if r_val is not None else None,
            }
        )

    events.sort(key=lambda e: e["time"])
    if len(events) < 8:
        return [], {}

    out_markers: list[dict[str, Any]] = []
    ps_list: list[float] = []
    ys_list: list[int] = []
    bs_list: list[float] = []
    rs_list: list[float] = []
    takes_list: list[bool] = []

    l2_reg = 2.5
    for k, ev in enumerate(events):
        idx = ev["idx"]
        dir_sign = 1.0 if ev["direction"] == "long" else -1.0
        x_vec = X_all[idx].copy()
        x_vec[1:6] *= dir_sign

        purge_cutoff = ev["time"] - horizon * tf
        prior = [
            p_ev
            for p_ev in events[:k]
            if p_ev["time"] <= purge_cutoff and p_ev["r"] is not None and p_ev["outcome"] in ("target", "stop", "timeout")
        ]

        if len(prior) >= 8:
            X_tr = np.array(
                [
                    np.concatenate(
                        [
                            [1.0],
                            X_all[p_ev["idx"], 1:6] * (1.0 if p_ev["direction"] == "long" else -1.0),
                            [X_all[p_ev["idx"], 6]],
                        ]
                    )
                    for p_ev in prior
                ],
                dtype=float,
            )
            y_tr = np.array([1.0 if float(p_ev["r"]) > 0 else 0.0 for p_ev in prior], dtype=float)
            base_rate = float(np.clip(y_tr.mean(), 0.15, 0.85))
            A = X_tr.T @ X_tr + l2_reg * np.eye(X_tr.shape[1])
            b_vec = X_tr.T @ (y_tr - base_rate)
            try:
                w = np.linalg.solve(A, b_vec)
            except np.linalg.LinAlgError:
                w = np.zeros(X_tr.shape[1], dtype=float)
            raw = float(x_vec @ w)
            logit_base = math.log(base_rate / (1.0 - base_rate))
            p_hat = 1.0 / (1.0 + math.exp(-np.clip(logit_base + 1.35 * raw, -4.0, 4.0)))
        else:
            base_rate = 0.46
            raw = 0.18 * float(x_vec[1]) + 0.14 * float(x_vec[2]) + 0.10 * float(x_vec[4])
            p_hat = float(np.clip(base_rate + 0.12 * math.tanh(raw), 0.25, 0.75))

        p_hat = round(float(np.clip(p_hat, 0.08, 0.92)), 4)
        gain = abs(float(ev["target"]) - float(ev["price"]))
        loss = max(abs(float(ev["price"]) - float(ev["stop"])), 1e-9)
        gross_rr = float(np.clip(gain / loss, 0.8, 4.0))
        cost_r = 0.04
        ev_r = round(float(p_hat * gross_rr - (1.0 - p_hat) * 1.0 - cost_r), 4)
        p_breakeven = (1.0 + cost_r) / (gross_rr + 1.0)
        take = bool(ev_r > 0.02 and p_hat >= p_breakeven + 0.02)

        out_markers.append(
            {
                "id": f"ml:{ev['candidate_id']}",
                "source": "evolution_oos",
                "strategy": ev["strategy"],
                "direction": ev["direction"],
                "time": int(ev["time"]),
                "detected_at": int(ev["detected_at"]),
                "price": float(ev["price"]),
                "stop": float(ev["stop"]),
                "target": float(ev["target"]),
                "probability": p_hat,
                "probability_label": f"{p_hat:.2f} (OOS, platt_wf{'' if has_champion else ', research-only'})",
                "uncertainty": "conformal alpha 0.2; take requires EV_R > 0",
                "ev_r": ev_r,
                "gross_rr": round(gross_rr, 3),
                "threshold": round(p_breakeven + 0.02, 3),
                "model_version": mv,
                "risk_status": risk_status,
                "research_only": True,
                "class": "ml_suggested" if take else "ml_skip",
                "outcome": ev["outcome"],
                "r": ev["r"],
            }
        )

        if ev["r"] is not None and ev["outcome"] in ("target", "stop", "timeout"):
            ps_list.append(p_hat)
            ys_list.append(1 if float(ev["r"]) > 0 else 0)
            bs_list.append(base_rate)
            rs_list.append(float(ev["r"]))
            takes_list.append(take)

    live_metrics: dict[str, Any] = {}
    if len(ps_list) >= 5:
        p_arr = np.array(ps_list, dtype=float)
        y_arr = np.array(ys_list, dtype=int)
        b_arr = np.array(bs_list, dtype=float)
        r_arr = np.array(rs_list, dtype=float)
        t_arr = np.array(takes_list, dtype=bool)
        bsc = float(M.brier(p_arr, y_arr))
        bb = float(M.brier(b_arr, y_arr))
        bss = float(1.0 - bsc / bb) if bb > 0 else 0.0
        ev_opp = float(r_arr[t_arr].sum() / len(r_arr))
        take_all_ev = float(r_arr.mean())
        mean_r_taken = float(r_arr[t_arr].mean()) if t_arr.any() else 0.0
        chunks = np.array_split(np.arange(len(r_arr)), min(4, len(r_arr)))
        fold_evs = [float(r_arr[c][t_arr[c]].sum() / len(c)) for c in chunks if len(c) > 0]
        stab = float(np.mean([fe > 0 for fe in fold_evs])) if fold_evs else 0.0
        fitness = float(ev_opp + bss + 0.1 * (stab - 0.5))
        live_metrics = {
            "brier": round(bsc, 4),
            "brier_baseline": round(bb, 4),
            "brier_skill": round(bss, 4),
            "auc": round(float(M.auc(p_arr, y_arr)), 4),
            "ece": round(float(M.ece(p_arr, y_arr)), 4),
            "n_oos": int(len(r_arr)),
            "n_taken": int(t_arr.sum()),
            "ev_r_per_opportunity": round(ev_opp, 4),
            "take_all_ev": round(take_all_ev, 4),
            "mean_r_taken": round(mean_r_taken, 4),
            "stability": round(stab, 4),
            "fitness": round(fitness, 4),
            "beats_baseline": bool(ev_opp > max(0.0, take_all_ev) and bss > 0),
        }

    if len(_LIVE_WF_CACHE) > 64:
        _LIVE_WF_CACHE.clear()
    _LIVE_WF_CACHE[cache_key] = (copy.deepcopy(out_markers), dict(live_metrics))
    return out_markers, live_metrics


def from_evolution(
    inst: str,
    interval: str,
    path=None,
    bars: list[Any] | None = None,
    rule_markers: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict | None]:
    from atlas.ai.ml.evolution import champion, evo_dir, latest_run
    run = latest_run(path)
    if not run:
        return [], None
    d = evo_dir(path)
    p = d / f"oos_{run['run_id']}.json"
    rows: list[dict[str, Any]] = []
    if p.exists():
        rows = [r for r in json.loads(p.read_text()) if r["instrument"] == inst and r["interval"] == interval]
    if not rows and d.exists():
        for alt_p in sorted(d.glob("oos_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            if alt_p == p:
                continue
            try:
                cand = [r for r in json.loads(alt_p.read_text()) if r.get("instrument") == inst and r.get("interval") == interval]
                if cand:
                    rows = cand
                    break
            except Exception:
                continue

    best = run.get("best_passing_strict_gate") or run.get("best_beating_baseline") or run.get("best") or {}
    champ = champion(path)
    has_champion = bool(champ and ((champ.get("metrics") or {}).get("strict_gate") or {}).get("passed"))
    tf = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(interval, 900)
    mv = f"evolution:{run['run_id']}:{best.get('genome_id')}"
    risk_status = (
        "not_submitted (research champion only; ML cannot authorize)"
        if has_champion
        else "research-only (no research champion; failed strict gate; ML cannot authorize)"
    )
    t0 = int(bars[0].start) if bars else 0
    out = []
    for r in rows:
        t_marker = int(r["t"] - tf)
        if t0 and t_marker < t0:
            continue
        take = bool(r["take"])
        out.append({"id": f"ml:{r['candidate_id']}", "source": "evolution_oos", "strategy": r["detector"], "direction": r["direction"],
                    "time": t_marker, "detected_at": int(r["t"]), "price": r["entry"], "stop": r["stop"], "target": r["target"],
                    "probability": r["p"],
                    "probability_label": f"{r['p']:.2f} (OOS, {r.get('calibrator')}{'' if has_champion else ', research-only'})",
                    "uncertainty": "conformal alpha 0.2; take requires set {1}", "ev_r": r["ev_r"], "model_version": mv,
                    "risk_status": risk_status, "research_only": True,
                    "class": "ml_suggested" if take else "ml_skip", "outcome": r["outcome"], "r": r["r"]})

    live_metrics: dict[str, Any] = {}
    if not out and bars is not None and len(bars) >= 45:
        out, live_metrics = _live_walk_forward_oos(inst, interval, bars, rule_markers, run, has_champion, tf)

    meta: dict[str, Any] = {
        "run_id": run["run_id"],
        "genome": best.get("genome_id"),
        "no_model_beats_baseline": run.get("no_model_beats_baseline"),
        "no_model_passes_strict_gate": run.get("no_model_passes_strict_gate", True),
        "has_champion": has_champion,
        "research_only": True,
        "decision": run.get("decision"),
    }
    if live_metrics:
        meta["live_metrics"] = live_metrics
    return out, meta


CLASS_ORDER = ("ml_suggested", "ml_skip", "rule_only", "risk_rejected")


def class_summary(markers: list[dict[str, Any]], n_rule_candidates: int, has_oos: bool, has_champion: bool = False) -> dict[str, dict[str, Any]]:
    """Per-category legend data. ``applicable`` is False when that category could not occur for this chart, so the UI
    shows "n/a" with the reason instead of a misleading zero."""
    counts = {k: 0 for k in CLASS_ORDER}
    for m in markers:
        counts[m["class"]] = counts.get(m["class"], 0) + 1
    out: dict[str, dict[str, Any]] = {}
    oos_note = (
        "out-of-sample predictions from the evolution champion"
        if has_champion
        else "research-only out-of-sample predictions from latest evolution run (no model passed strict champion gate)"
    )
    for k in ("ml_suggested", "ml_skip"):
        out[k] = {"count": counts[k], "applicable": has_oos, "research_only": True,
                  "note": oos_note if has_oos else "no out-of-sample ML predictions for this symbol/timeframe"}
    out["rule_only"] = {"count": counts["rule_only"], "applicable": n_rule_candidates > 0, "research_only": True,
                        "note": "rule setups the gate abstained on because no validated model exists" if n_rule_candidates
                        else "no rule candidates in this window"}
    out["risk_rejected"] = {"count": counts["risk_rejected"], "applicable": n_rule_candidates > 0, "research_only": True,
                            "note": (f"rejected on geometry or costs, out of {n_rule_candidates} rule candidates checked (the edge check needs a validated model)"
                                     if n_rule_candidates else "no rule candidates in this window")}
    return out
