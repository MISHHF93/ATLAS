"""Per-marker context for the unified chart (research only, paper only, execution_permission none).

Everything here is CAUSAL: the indicator snapshot attached to a marker is the state of incremental indicators after
consuming bars[0..i] where bar i is the marker's confirmation bar (the bar whose end == detected_at). No later bar is
ever read. ``snapshots(bars)[i]`` therefore equals ``snapshots(bars[:i+1])[-1]`` (tested).

Also builds the forward "prediction zone" (model estimate, not a forecast guarantee) and a running calibration readout.
"""
from __future__ import annotations

import math
from typing import Any

from atlas.features.price_action.indicators import EMA, WilderATR, WilderRSI

PREDICTION_LABEL = "model estimate, not a forecast guarantee"
RESOLVED = {"target": "hit_target", "stop": "stopped_out", "timeout": "timed_out", "open": "open",
            "unfilled": "not_filled", "not_filled": "not_filled"}


class _ADX:
    """Wilder ADX(n), incremental."""

    def __init__(self, n: int = 14):
        self.n, self.prev, self.k, self.tr, self.pdm, self.mdm, self.dx, self.value = n, None, 0, 0.0, 0.0, 0.0, [], None

    def update(self, h: float, l: float, c: float) -> float | None:
        if self.prev is None:
            self.prev = (h, l, c)
            return None
        ph, pl, pc = self.prev
        self.prev = (h, l, c)
        up, dn = h - ph, pl - l
        pdm = up if up > dn and up > 0 else 0.0
        mdm = dn if dn > up and dn > 0 else 0.0
        tr = max(h - l, abs(h - pc), abs(l - pc))
        n = self.n
        self.k += 1
        if self.k <= n:
            self.tr += tr; self.pdm += pdm; self.mdm += mdm
            if self.k < n:
                return None
        else:
            self.tr = self.tr - self.tr / n + tr
            self.pdm = self.pdm - self.pdm / n + pdm
            self.mdm = self.mdm - self.mdm / n + mdm
        if self.tr <= 0:
            return self.value
        pdi, mdi = 100 * self.pdm / self.tr, 100 * self.mdm / self.tr
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0
        if self.value is None:
            self.dx.append(dx)
            if len(self.dx) == n:
                self.value = sum(self.dx) / n
            return self.value
        self.value = (self.value * (n - 1) + dx) / n
        return self.value


def _r(x, d=4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), d)


def snapshots(bars) -> list[dict[str, Any]]:
    """Indicator state at the close of each bar, using only bars up to and including it."""
    from atlas.ai.intel.regime import classify
    rsi, atr, adx = WilderRSI(14), WilderATR(14), _ADX(14)
    e12, e26, sig = EMA(12), EMA(26), EMA(9)
    regimes = classify(bars)
    out: list[dict[str, Any]] = []
    pv = vv = 0.0
    day = None
    for i, b in enumerate(bars):
        r = rsi.update(b.close); a = atr.update(b.high, b.low, b.close); x = adx.update(b.high, b.low, b.close)
        f, s = e12.update(b.close), e26.update(b.close)
        macd = (f - s) if f is not None and s is not None else None
        sg = sig.update(macd) if macd is not None else None
        d = b.start // 86400
        if d != day:
            pv = vv = 0.0; day = d
        tp = (b.high + b.low + b.close) / 3
        pv += tp * (b.volume or 0.0); vv += b.volume or 0.0
        vwap = pv / vv if vv > 0 else None
        out.append({"bar_time": b.start, "close": b.close, "rsi": _r(r, 2), "adx": _r(x, 2), "atr": _r(a, 6),
                    "macd_hist": _r(macd - sg, 6) if macd is not None and sg is not None else None,
                    "vwap": _r(vwap, 6), "vwap_dist_atr": _r((b.close - vwap) / a, 3) if vwap is not None and a else None,
                    "vwap_dist_pct": _r((b.close - vwap) / vwap * 100, 3) if vwap else None,
                    "regime": regimes[i]["label"] if i < len(regimes) else None})
    return out


def outcome_label(outcome: str | None) -> str:
    return RESOLVED.get(str(outcome or "not_filled"), str(outcome))


def _why(m: dict[str, Any], threshold: float | None) -> str:
    cls = m.get("class")
    p = m.get("probability")
    if cls == "ml_suggested":
        return (f"ML took it: p(win) {p:.2f} cleared the threshold {threshold:.2f} and the conformal set was {{1}}"
                if p is not None and threshold is not None else "gate passed")
    if cls == "ml_skip":
        return (f"ML skipped it: p(win) {p:.2f} vs threshold {threshold:.2f}, or the conformal set was not {{1}}"
                if p is not None and threshold is not None else "ML skipped it")
    if cls == "risk_rejected":
        return "Risk gate rejected it: " + (", ".join(m.get("gate_reasons") or []) or str(m.get("risk_status")))
    return f"Rule setup {str(m.get('strategy', '')).replace('_', ' ')} fired; no validated model, so no ML opinion"


def breakeven_threshold(m: dict[str, Any]) -> float | None:
    """p(win) at which EV is zero for this geometry: 1 / (1 + RR). Derived from the marker's own entry/stop/target."""
    try:
        e, s, t = float(m["price"]), float(m["stop"]), float(m["target"])
    except (KeyError, TypeError, ValueError):
        return None
    risk, reward = abs(e - s), abs(t - e)
    return round(1.0 / (1.0 + reward / risk), 4) if risk > 0 and reward > 0 else None


def enrich(markers: list[dict[str, Any]], bars, snaps: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Attach the causal indicator snapshot of each marker's confirmation bar, outcome label, threshold, why and
    resolution path (bars from fill to exit; empty while open). Additive: existing keys are untouched."""
    snaps = snaps if snaps is not None else snapshots(bars)
    idx = {b.start: i for i, b in enumerate(bars)}
    for m in markers:
        i = idx.get(m.get("time"))
        snap = dict(snaps[i]) if i is not None else None
        thr = breakeven_threshold(m)
        m["indicators"] = snap
        m["threshold"] = thr
        m["outcome_label"] = outcome_label(m.get("outcome"))
        m["why"] = _why(m, thr)
        m["setup"] = str(m.get("strategy", "")).replace("_", " ")
        m["resolution_path"] = _path(m, bars, i)
    return markers


def _path(m: dict[str, Any], bars, i: int | None, cap: int = 200) -> list[dict[str, Any]]:
    """Closes from the bar after confirmation to the exit. Uses the replay's exit_at when present; otherwise walks real
    bars until the high/low first crosses stop or target (stop wins a same-bar tie), as the replay labels it. Empty
    when never filled. Display only."""
    if i is None or m.get("outcome") in ("not_filled", "unfilled"):
        return []
    xa = m.get("exit_at")
    st, tg, d = m.get("stop"), m.get("target"), m.get("direction")
    out: list[dict[str, Any]] = [{"time": bars[i].start, "value": m.get("price")}]
    for b in bars[i + 1: i + 1 + cap]:
        if xa is not None and b.start >= xa:
            break
        out.append({"time": b.start, "value": b.close})
        if xa is None and st is not None and tg is not None:
            hit_s = b.low <= st if d == "long" else b.high >= st
            hit_t = b.high >= tg if d == "long" else b.low <= tg
            if hit_s or hit_t:
                out[-1] = {"time": b.start, "value": st if hit_s else tg, "exit": True}
                break
    if xa is not None and m.get("exit_price") is not None and out:
        out[-1] = {"time": out[-1]["time"], "value": m["exit_price"], "exit": True}
    return out


def calibration(preds: list[dict[str, Any]]) -> dict[str, Any]:
    """Running calibration over the visible window: resolved predictions only (target/stop/timeout)."""
    res = [p for p in preds if p.get("outcome") in ("target", "stop", "timeout") and p.get("p") is not None]
    if not res:
        return {"status": "unavailable", "n": 0, "reason": "no resolved predictions in view"}
    ys = [1.0 if (p.get("r") or 0) > 0 else 0.0 for p in res]
    ps = [float(p["p"]) for p in res]
    n = len(res)
    brier = sum((a - b) ** 2 for a, b in zip(ps, ys)) / n
    base = sum(ys) / n
    return {"status": "ok", "n": n, "mean_p": round(sum(ps) / n, 4), "hit_rate": round(base, 4), "brier": round(brier, 4),
            "brier_base_rate": round(sum((base - y) ** 2 for y in ys) / n, 4),
            "taken_hit_rate": (round(sum(y for y, p in zip(ys, res) if p.get("take")) / max(1, sum(1 for p in res if p.get("take"))), 4)
                               if any(p.get("take") for p in res) else None)}


def forward_zone(bars, snaps, markers: list[dict[str, Any]], horizon: int = 8) -> dict[str, Any]:
    """Prediction zone at the right edge for the latest CLOSED bar.

    Band: empirical quantiles (10/25/50/75/90%) of the realized ``horizon``-bar forward return in ATR units over the
    replay window (each sample uses ATR known at its start bar and the close ``horizon`` bars later, all strictly in
    the past), scaled by the current ATR. Active candidates: markers confirmed on the latest closed bar or still open."""
    if len(bars) < horizon + 60:
        return {"status": "unavailable", "reason": "not enough closed bars for a horizon distribution", "label": PREDICTION_LABEL}
    last = bars[-1]
    a_now = snaps[-1].get("atr")
    samples = []
    for i in range(len(bars) - horizon):
        a = snaps[i].get("atr")
        if a:
            samples.append((bars[i + horizon].close - bars[i].close) / a)
    if not a_now or len(samples) < 50:
        return {"status": "unavailable", "reason": "ATR not warmed up", "label": PREDICTION_LABEL}
    samples.sort()
    q = lambda f: samples[min(len(samples) - 1, max(0, int(round(f * (len(samples) - 1)))))]  # noqa: E731
    qs = {k: q(v) for k, v in (("p10", .10), ("p25", .25), ("p50", .50), ("p75", .75), ("p90", .90))}
    t_end = last.start + last.duration * horizon
    band = {k: round(last.close + v * a_now, 6) for k, v in qs.items()}
    end = last.start + last.duration
    active = [m for m in markers if m.get("detected_at") == end or m.get("outcome") == "open"]
    cands = [{"id": m["id"], "setup": m.get("setup") or m.get("strategy"), "direction": m.get("direction"), "class": m.get("class"),
              "p_win": m.get("probability"), "calibrated": m.get("source") == "evolution_oos" and m.get("probability") is not None,
              "threshold": m.get("threshold"), "entry": m.get("price"), "stop": m.get("stop"), "target": m.get("target"),
              "source": m.get("source")} for m in active[-6:]]
    return {"status": "ok", "label": PREDICTION_LABEL, "as_of_bar": last.start, "as_of_close": last.close, "horizon_bars": horizon,
            "horizon_end": t_end, "atr": a_now, "quantiles_atr": {k: round(v, 3) for k, v in qs.items()}, "band": band,
            "n_samples": len(samples), "method": f"empirical {horizon}-bar forward return / ATR(14) quantiles over {len(samples)} past closed bars",
            "active_candidates": cands,
            "no_active_candidate": None if cands else "No active candidate on the latest closed bar."}
