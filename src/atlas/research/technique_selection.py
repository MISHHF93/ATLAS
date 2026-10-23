"""Research: technique-selector walk-forward evaluation, and the range-break -> swing-level hypothesis test.

Nothing here trades or registers models; the outputs are evidence for the registry gates."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Sequence

import numpy as np

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.prior_day import PriorDayRangeConfig
from atlas.features.price_action.replay import ReplayConfig, replay, trade_cost
from atlas.features.price_action.sessions import US_EQUITY_RTH, SessionSpec
from atlas.models.quant.metrics import deflated_sharpe
from atlas.models.technique_selector import ContextTracker, TechniqueSelector, feature_row
from atlas.research.setup_evidence import COST_PER_SHARE, COSTS_BPS, UTC_DAY, load_bars

N = NormalDist()
DAY = 86400


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def binom_two_sided_p(k: int, n: int, p0: float = 0.5) -> float | None:
    """Exact two-sided binomial p-value (sum of outcomes no more likely than k)."""
    if n == 0:
        return None
    pmf = [math.comb(n, i) * p0 ** i * (1 - p0) ** (n - i) for i in range(n + 1)]
    return float(min(1.0, sum(q for q in pmf if q <= pmf[k] * (1 + 1e-9))))


# --------------------------------------------------------------------------------------------- hypothesis
def range_break_hypothesis(bars: Sequence[Bar], session: SessionSpec, lookback_sessions: int = 20,
                           skip_seconds: int = 900) -> dict[str, Any]:
    """Claim under test: "after the first 15 minutes, a break of the prior-session range level tends to reach the
    swing level". Per session: the first bar ending after open+skip_seconds whose high > range_high (or low <
    range_low) is the break. Let d = |swing - range level|. Success = price reaches the swing level before
    retreating d back through the level (symmetric barriers, so a driftless martingale gives 0.5). Bars touching
    both barriers are ambiguous and excluded; sessions ending first are 'unresolved'. Fully causal levels."""
    hist: list[tuple[float, float]] = []
    cur: dict[str, Any] | None = None
    recs: list[dict[str, Any]] = []

    def close_session():
        if cur and cur["hi"] is not None:
            hist.append((cur["hi"], cur["lo"]))
            if cur["trial"] is not None:
                recs.append(cur["trial"])

    for b in bars:
        win = session.window_for(b.start)
        if win is None:
            continue
        if cur is None or cur["sid"] != win[0]:
            close_session()
            cur = {"sid": win[0], "open": win[1], "hi": None, "lo": None, "trial": None, "lv": None}
            if hist:
                rh, rl = hist[-1]
                older = list(reversed(hist[:-1]))[:lookback_sessions]
                sh = next((h for h, _ in older if h > rh), None)
                sl = next((l_ for _, l_ in older if l_ < rl), None)
                cur["lv"] = (rh, rl, sh, sl)
        cur["hi"] = b.high if cur["hi"] is None else max(cur["hi"], b.high)
        cur["lo"] = b.low if cur["lo"] is None else min(cur["lo"], b.low)
        tr = cur["trial"]
        if tr is not None and tr["result"] == "unresolved":
            up, dn = (tr["swing"], tr["back"]) if tr["side"] == "up" else (tr["back"], tr["swing"])
            hit_up, hit_dn = b.high >= up, b.low <= dn
            if hit_up and hit_dn:
                tr["result"] = "ambiguous"
            elif hit_up or hit_dn:
                tr["result"] = "swing" if (hit_up if tr["side"] == "up" else hit_dn) else "back"
            continue
        if tr is None and cur["lv"] is not None and b.end > cur["open"] + skip_seconds:
            rh, rl, sh, sl = cur["lv"]
            brk_up, brk_dn = b.high > rh, b.low < rl
            if brk_up and brk_dn:
                cur["trial"] = {"session": cur["sid"], "side": "both", "result": "ambiguous"}
            elif brk_up or brk_dn:
                side = "up" if brk_up else "down"
                lvl, sw = (rh, sh) if brk_up else (rl, sl)
                if sw is None:
                    cur["trial"] = {"session": cur["sid"], "side": side, "result": "no_swing_level"}
                    continue
                d = abs(sw - lvl)
                back = lvl - d if brk_up else lvl + d
                t = {"session": cur["sid"], "side": side, "level": lvl, "swing": sw, "back": back, "result": "unresolved"}
                cur["trial"] = t
                # the break bar itself may already reach a barrier
                hit_sw = b.high >= sw if brk_up else b.low <= sw
                hit_bk = b.low <= back if brk_up else b.high >= back
                if hit_sw and hit_bk:
                    t["result"] = "ambiguous"
                elif hit_sw:
                    t["result"] = "swing"
                elif hit_bk:
                    t["result"] = "back"
    close_session()
    k = sum(r["result"] == "swing" for r in recs)
    n = sum(r["result"] in ("swing", "back") for r in recs)
    by = {r: sum(x["result"] == r for x in recs) for r in ("swing", "back", "unresolved", "ambiguous", "no_swing_level")}
    return {"n_sessions_with_break": len(recs), "counts": by, "n_resolved": n,
            "p_swing_first": round(k / n, 4) if n else None, "wilson95": wilson(k, n),
            "binomial_p_vs_0.5": binom_two_sided_p(k, n), "null": "0.5 (symmetric barriers, driftless martingale)"}


# --------------------------------------------------------------------------------------------- selector
def decision_rows(instrument: str, bars: Sequence[Bar], session: SessionSpec, cfg: ReplayConfig,
                  pdr: PriorDayRangeConfig | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One row per resolved candidate (any technique) with causal context at detection time."""
    tracker = ContextTracker(session)
    ctx_at = {b.end: tracker.update(b) for b in bars}
    res = replay(instrument, bars[0].duration, bars, engine_cfg=EngineConfig(session=session, pdr=pdr or PriorDayRangeConfig()),
                 cfg=cfg, data_label="real")
    rows = []
    for t in res.trades:
        if t.outcome not in ("target", "stop", "timeout") or t.r_multiple is None:
            continue
        risk = abs(t.entry - t.stop)
        if risk <= 0:
            continue
        rr, cr = abs(t.target - t.entry) / risk, trade_cost(t, cfg) / risk
        ctx = ctx_at.get(t.detected_at, {})
        rows.append({"instrument": instrument, "technique": t.detector, "t": t.detected_at, "exit_at": t.exit_at,
                     "x": feature_row(ctx, rr, cr), "y": int(t.outcome == "target"), "r": float(t.r_multiple),
                     "reward_risk": rr, "cost_r": cr})
    return rows, res.summary


def walk_forward_selector(rows: list[dict[str, Any]], kinds: Sequence[str] = ("logistic", "gbm"), n_folds: int = 5,
                          embargo: int = DAY, min_train: int = 60) -> dict[str, Any]:
    """Expanding walk-forward over decision times. Training rows are purged (exit before test start - embargo).
    At each decision time (instrument, t) the selector picks one candidate or abstains. Baselines on the same test
    decisions: always-abstain (0), best-single-technique chosen on the training window by mean R (takes all of
    that technique's candidates), take-everything, and each fixed technique (reported, hindsight)."""
    rows = sorted(rows, key=lambda r: (r["t"], r["instrument"], r["technique"]))
    keys = sorted({(r["t"], r["instrument"]) for r in rows})
    n = len(keys)
    edges = [int(n * k / (n_folds + 1)) for k in range(1, n_folds + 2)]
    techs = sorted({r["technique"] for r in rows})
    series: dict[str, list[tuple[int, float]]] = {f"selector_{k}": [] for k in kinds}
    series |= {"always_abstain": [], "best_single_trained": [], "take_all": []} | {f"fixed_{t}": [] for t in techs}
    folds = []
    for f in range(n_folds):
        lo, hi = edges[f], edges[f + 1]
        if lo >= hi:
            continue
        t0, t1 = keys[lo][0], keys[hi - 1][0]
        test = [r for r in rows if t0 <= r["t"] <= t1]
        train = [r for r in rows if r["t"] < t0 and r["exit_at"] < t0 - embargo]
        if len(train) < min_train:
            folds.append({"fold": f, "skipped": "insufficient_train", "n_train": len(train)})
            continue
        mean_r = {t: float(np.mean([r["r"] for r in train if r["technique"] == t])) for t in techs
                  if sum(r["technique"] == t for r in train) >= 10}
        best = max(mean_r, key=mean_r.get) if mean_r else None
        best = best if best is not None and mean_r[best] > 0 else None     # a trained best-single may itself abstain
        groups: dict[tuple[int, str], list[dict]] = {}
        for r in test:
            groups.setdefault((r["t"], r["instrument"]), []).append(r)
        fold = {"fold": f, "n_train": len(train), "n_test_rows": len(test), "n_test_decisions": len(groups),
                "test_from": _iso(t0), "test_to": _iso(t1), "best_single_trained": best,
                "train_mean_r": {k: round(v, 4) for k, v in mean_r.items()}}
        sels = {k: TechniqueSelector(kind=k, min_train=min_train // 2).fit(train, fitted_through=train[-1]["exit_at"]) for k in kinds}
        for k, sel in sels.items():
            fold[f"trained_{k}"] = sorted(sel.models)
        for key, opts in sorted(groups.items()):
            t = key[0]
            series["always_abstain"].append((t, 0.0))
            series["take_all"].append((t, sum(o["r"] for o in opts)))
            series["best_single_trained"].append((t, sum(o["r"] for o in opts if o["technique"] == best)))
            for tech in techs:
                series[f"fixed_{tech}"].append((t, sum(o["r"] for o in opts if o["technique"] == tech)))
            for k, sel in sels.items():
                ch, _ = sel.choose(opts)
                series[f"selector_{k}"].append((t, ch["r"] if ch else 0.0))
                fold.setdefault(f"n_taken_{k}", 0)
                fold[f"n_taken_{k}"] += ch is not None
        folds.append(fold)
    return {"n_rows": len(rows), "n_decisions": n, "techniques": techs, "folds": folds, "_series": series}


def daily(series: list[tuple[int, float]]) -> tuple[list[int], np.ndarray]:
    agg: dict[int, float] = {}
    for t, r in series:
        agg[t // DAY] = agg.get(t // DAY, 0.0) + r
    days = sorted(agg)
    return days, np.array([agg[d] for d in days], float)


def summarize(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """DSR across ALL strategies tried in every group (selectors, baselines, fixed techniques), on daily R sums
    over a common calendar per group (days with no decision count as 0)."""
    trials = []
    for g, wf in groups.items():
        s = wf["_series"]
        alldays = sorted({t // DAY for v in s.values() for t, _ in v})
        for name, v in s.items():
            dd, vals = daily(v)
            m = dict(zip(dd, vals))
            arr = np.array([m.get(d, 0.0) for d in alldays])
            wf.setdefault("_daily", {})[name] = arr
            if name != "always_abstain":
                sr = float(arr.mean() / arr.std(ddof=1)) if len(arr) > 2 and arr.std(ddof=1) > 0 else 0.0
                trials.append(sr)
    out = {"n_trials": len(trials), "groups": {}}
    for g, wf in groups.items():
        stats = {}
        for name, v in wf["_series"].items():
            arr = wf["_daily"][name]
            r = np.array([x for _, x in v])
            st = {"n_decisions": len(v), "n_taken": int((r != 0).sum()), "total_r_after_cost": round(float(r.sum()), 3),
                  "mean_r_per_decision": round(float(r.mean()), 5) if len(r) else None, "n_days": len(arr)}
            if name != "always_abstain" and len(arr) > 2:
                st["dsr"] = {k: round(x, 5) if isinstance(x, float) else x for k, x in deflated_sharpe(arr, trials).items()}
            stats[name] = st
        gates = {}
        for k in [n for n in stats if n.startswith("selector_")]:
            s = stats[k]
            gates[k] = [
                {"gate": "beats_always_abstain_after_cost", "passed": s["total_r_after_cost"] > 0, "value": s["total_r_after_cost"]},
                {"gate": "beats_best_single_trained_after_cost",
                 "passed": s["total_r_after_cost"] > stats["best_single_trained"]["total_r_after_cost"],
                 "value": [s["total_r_after_cost"], stats["best_single_trained"]["total_r_after_cost"]]},
                {"gate": "deflated_sharpe_all_trials", "passed": (s.get("dsr") or {}).get("dsr", 0.0) > 0.95,
                 "value": (s.get("dsr") or {}).get("dsr"), "threshold": "> 0.95"},
                {"gate": "min_taken", "passed": s["n_taken"] >= 100, "value": s["n_taken"], "threshold": ">= 100"},
                {"gate": "shadow_weeks", "passed": False, "value": 0, "threshold": "offline evidence cannot satisfy"},
            ]
        out["groups"][g] = {"n_rows": wf["n_rows"], "n_decisions": wf["n_decisions"], "techniques": wf["techniques"],
                            "folds": wf["folds"], "strategies": stats, "registry_gates": gates,
                            "register": any(all(x["passed"] for x in gl) for gl in gates.values())}
        wf.pop("_series"); wf.pop("_daily")
    return out


def run(cache: Path, max_hold_bars: int = 32) -> dict[str, Any]:
    datasets, groups_rows, hyp = [], {}, {}
    for f in sorted(cache.glob("*_15m.json")):
        bars, meta = load_bars(f)
        asset = "crypto" if meta["source"].startswith("binance") else "equity"
        session = UTC_DAY if asset == "crypto" else US_EQUITY_RTH
        cfg = ReplayConfig(entry_window=3, max_hold_bars=max_hold_bars, cost_per_unit=COST_PER_SHARE[asset],
                           cost_bps=COSTS_BPS[asset], zone_rule="zone_entry_v1")
        rows, summ = decision_rows(meta["symbol"], bars, session, cfg)
        by_t = {}
        for r in rows:
            d = by_t.setdefault(r["technique"], {"n": 0, "wins": 0, "total_r": 0.0})
            d["n"] += 1; d["wins"] += r["y"]; d["total_r"] += r["r"]
        meta |= {"asset_class": asset, "session": session.name, "replay_summary": summ,
                 "resolved_by_technique": {k: {**v, "total_r": round(v["total_r"], 3)} for k, v in by_t.items()}}
        datasets.append(meta)
        groups_rows.setdefault(asset, []).extend(rows)
        hyp[meta["symbol"]] = range_break_hypothesis(bars, session)
    groups = {g: walk_forward_selector(rs) for g, rs in groups_rows.items()}
    out = summarize(groups)
    k = sum(h["counts"]["swing"] for h in hyp.values()); n = sum(h["n_resolved"] for h in hyp.values())
    hyp["pooled"] = {"n_resolved": n, "p_swing_first": round(k / n, 4) if n else None, "wilson95": wilson(k, n),
                     "binomial_p_vs_0.5": binom_two_sided_p(k, n)}
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "datasets": datasets, "selector": out,
            "range_break_hypothesis": hyp,
            "method": {"timeframe": "15m", "labels": "triple barrier, conservative_ohlc_v1 replay, stop entries for PDR",
                       "max_hold_bars": max_hold_bars, "costs_bps_round_trip": COSTS_BPS, "cost_per_share": COST_PER_SHARE,
                       "cv": "expanding walk-forward over decision times, 5 test folds, purged by exit, 1-day embargo",
                       "selector": "per-technique classifier (logistic / HistGBM) on causal context + reward_risk + cost_r; "
                                   "choose argmax EV_R = p*G-(1-p)-C if > 0 else abstain",
                       "dsr": "daily R sums; trials = every non-abstain strategy in every group",
                       "groups": "pooled per asset class (equity: SPY/QQQ/IWM; crypto: BTC/ETH)"}}
