"""Evo7 research: an honest probe of prior_day_range_reversal (PDR), the only gross-positive evo6 lead.

Candidates come from the unchanged live detection path (``replay`` with the evo6 ``atr2_rr2`` variant, paper realism),
so detections are identical to evo6. Each detected candidate (filled by the stop entry or not) is then re-simulated
here under a grid of entry / exit / filter / cost assumptions. Every grid cell is one trial and every trial is
counted in DSR and PBO (no selection outside the grid).

Simulation rules (conservative, closed bars only):
  - detection at the close of bar i; 1-bar latency, so orders work on bars i+2 .. i+4 (3-bar entry window);
  - ``stop`` entry: fills when price crosses the detector trigger, at max(trigger, open) (long); gaps past stop/target skip;
  - ``limit_k`` entry: resting limit k*ATR better than the trigger; needs a strict trade-through; fills at the limit;
  - zero/unknown volume on the fill bar = no fill; stop = trigger -/+ 2 ATR(14) (fixed); targets are trigger + m*R0
    (R0 = 2 ATR); R is measured on the risk from the actual fill;
  - fill bar: stop only; gap through stop exits at the open; bar touching stop and target = stop; timeout at close;
  - filters use only data closed at detection: daily EMA20 from completed UTC days (``htf_with``/``htf_counter``),
    ATR%/price percentile over the trailing 200 bars (``vol_low``/``vol_high``);
  - costs: ``taker`` = venue costs from ``atlas.ml.costs``; ``maker_assumed`` (crypto only) = an ASSUMPTION, not a
    verified venue fill model: 2 bp per resting-limit leg (limit entry, target exit), 12 bp per taker leg
    (stop entry, stop/timeout exit). Maker fills assume queue position at the limit, which real books do not guarantee.
Research evidence only; nothing here grants execution (execution_permission none).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any, Sequence

import numpy as np

from atlas.ml import metrics as M
from atlas.ml.costs import VENUE_COSTS, venue_for
from atlas.ml.dataset import SeriesData
from atlas.research.setup_variants import VARIANT_BY_ID, boot_ci, hold_bars, run_variant, walk_forward_selection, _r

DETECTOR = "prior_day_range_reversal"
ENTRIES = {"stop": None, "limit_0.25": 0.25, "limit_0.5": 0.5}
EXITS = {"rr2": "target 2R0", "rr1.5": "target 1.5R0", "partial_1_2": "half at 1R0, half at 2R0 (stop unchanged)",
         "rr2_tstop": "target 2R0, time stop at half the hold"}
FILTERS = ("none", "htf_with", "htf_counter", "vol_low", "vol_high")
COSTS = ("taker", "maker_assumed")
MAKER_BPS, TAKER_BPS = 2.0, 12.0
CRYPTO_CORE = ("BTCUSDT", "ETHUSDT")
CRYPTO_ALTS = ("SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "LTCUSDT",
               "BCHUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT", "ETCUSDT", "XLMUSDT", "FILUSDT", "APTUSDT", "ARBUSDT",
               "SUIUSDT", "NEARUSDT", "OPUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "FETUSDT", "RENDERUSDT", "ALGOUSDT", "WIFUSDT")
EQUITY = ("SPY", "QQQ", "IWM")


@dataclass(frozen=True)
class ProbeConfig:
    entry: str
    exit: str
    filter: str
    cost: str

    @property
    def id(self) -> str:
        return f"{self.entry}/{self.exit}/{self.filter}/{self.cost}"


def grid(asset_class: str) -> list[ProbeConfig]:
    costs = COSTS if asset_class == "crypto" else ("taker",)
    return [ProbeConfig(*x) for x in product(ENTRIES, EXITS, FILTERS, costs)]


def _atr(bars) -> np.ndarray:
    out = np.full(len(bars), np.nan)
    a, pc = None, None
    for i, b in enumerate(bars):
        tr = b.high - b.low if pc is None else max(b.high, pc) - min(b.low, pc)
        a = tr if a is None else (a + (tr - a) / 14 if i >= 14 else a + (tr - a) / (i + 1))
        pc = b.close
        if i >= 13:
            out[i] = a
    return out


def context(bars) -> dict[str, np.ndarray]:
    """Per bar i (closed): sign(close - daily EMA20 of completed UTC days before bar i's day) and ATR% percentile."""
    n = len(bars)
    close = np.array([b.close for b in bars])
    atrp = _atr(bars) / close
    pct = np.full(n, np.nan)
    for i in range(200, n):
        w = atrp[i - 200:i + 1]
        w = w[np.isfinite(w)]
        if len(w) > 50:
            pct[i] = (w < atrp[i]).mean()
    daily_close, ema, e = {}, {}, None
    for b in bars:        # last close of each UTC day (bar ending at the day boundary closes the day)
        d = (b.end - 1) // 86400
        daily_close[d] = b.close
    for d in sorted(daily_close):
        e = daily_close[d] if e is None else e + (daily_close[d] - e) * 2 / 21
        ema[d] = e
    days = sorted(ema)
    htf = np.zeros(n)
    import bisect
    for i, b in enumerate(bars):
        cur = (b.end - 1) // 86400
        k = bisect.bisect_left(days, cur) - 1       # last completed day strictly before the current day
        if k >= 20:
            htf[i] = np.sign(close[i] - ema[days[k]])
    return {"htf": htf, "vol_pct": pct}


def _cost_price(px: float, legs: Sequence[tuple[str, float]], cfg: ProbeConfig, asset_class: str) -> float:
    """Round-trip cost in price units; legs = [(kind, weight)], kind in maker/taker."""
    vc = VENUE_COSTS[venue_for(asset_class)]
    if cfg.cost == "taker" or asset_class != "crypto":
        return px * vc["cost_bps"] / 1e4 + vc["cost_per_unit"]
    return px * sum(w * (MAKER_BPS if k == "maker" else TAKER_BPS) for k, w in legs) / 1e4


def simulate(bars, i: int, direction: str, ref: float, atr: float, cfg: ProbeConfig, hold: int, asset_class: str) -> dict | None:
    long = direction == "long"
    s = 1.0 if long else -1.0
    stop = ref - s * 2 * atr
    r0 = 2 * atr
    k = ENTRIES[cfg.entry]
    fill, fj = None, None
    for j in range(i + 2, min(i + 5, len(bars))):
        b = bars[j]
        if b.volume <= 0:
            continue
        if k is None:
            if (b.high >= ref) if long else (b.low <= ref):
                px = max(ref, b.open) if long else min(ref, b.open)
                if (px - stop) * s <= 0 or (px - (ref + s * 2 * r0)) * s >= 0:
                    return None
                fill, fj = px, j
                break
        else:
            lim = ref - s * k * atr
            if (b.low < lim) if long else (b.high > lim):
                if (lim - stop) * s <= 0:
                    return None
                fill, fj = lim, j
                break
    if fill is None:
        return None
    risk = abs(fill - stop)
    if cfg.exit == "partial_1_2":
        tg = [(ref + s * 1 * r0, 0.5), (ref + s * 2 * r0, 0.5)]
    else:
        tg = [(ref + s * (1.5 if cfg.exit == "rr1.5" else 2.0) * r0, 1.0)]
    hmax = hold // 2 if cfg.exit == "rr2_tstop" else hold
    entry_leg = "taker" if k is None else "maker"
    open_w, pnl, legs, out, exit_at = 1.0, 0.0, [], None, None
    for j in range(fj, min(fj + hmax + 1, len(bars))):
        b = bars[j]
        held = j - fj
        hs = (b.low <= stop) if long else (b.high >= stop)
        if j == fj:
            if hs:
                pnl += open_w * (stop - fill) * s; legs.append(("taker", open_w)); open_w = 0; out = "stop"; exit_at = b.start
                break
            continue
        if ((b.open <= stop) if long else (b.open >= stop)):
            pnl += open_w * (b.open - fill) * s; legs.append(("taker", open_w)); open_w = 0; out = "stop"; exit_at = b.start
            break
        if hs:                                             # stop first when a bar touches both
            pnl += open_w * (stop - fill) * s; legs.append(("taker", open_w)); open_w = 0; out = out or "stop"; exit_at = b.start
            break
        rem = []
        for px, w in tg:
            if (b.high >= px) if long else (b.low <= px):
                pnl += w * (px - fill) * s; legs.append(("maker", w)); open_w -= w; out = "target"
            else:
                rem.append((px, w))
        tg = rem
        if open_w <= 1e-9:
            exit_at = b.start
            break
        if held >= hmax:
            pnl += open_w * (b.close - fill) * s; legs.append(("taker", open_w)); open_w = 0
            out = "timeout" if out is None else "partial_timeout"; exit_at = b.start
            break
    if open_w > 1e-9:
        return None                                        # unresolved at the end of data
    cost = _cost_price(fill, [(entry_leg, 1.0)] + legs, cfg, asset_class)
    return {"fill": fill, "stop": stop, "risk": risk, "gross_r": pnl / risk, "cost_r": cost / risk,
            "r": (pnl - cost) / risk, "outcome": out, "exit_at": int(exit_at), "filled_at": int(bars[fj].start)}


def candidates(sd: SeriesData) -> list[dict]:
    """Detected PDR candidates from the evo6 atr2_rr2 replay (fills there are irrelevant here)."""
    from atlas.features.price_action.engine import EngineConfig
    from atlas.features.price_action.prior_day import PriorDayRangeConfig
    from atlas.features.price_action.replay import paper_replay_config, replay
    from atlas.features.price_action.sessions import US_EQUITY_RTH
    from atlas.ml.dataset import UTC_DAY
    v = VARIANT_BY_ID["atr2_rr2"]
    vc = VENUE_COSTS[venue_for(sd.asset_class)]
    cfg = paper_replay_config(entry_window=3, max_hold_bars=hold_bars(sd.interval, sd.asset_class) * v.hold_mult,
                              cost_per_unit=vc["cost_per_unit"], cost_bps=vc["cost_bps"], zone_rule="zone_entry_v1",
                              stop_atr_mult=v.stop_atr_mult, target_rr=v.target_rr, max_cost_r=v.max_cost_r)
    session = UTC_DAY if sd.asset_class == "crypto" else US_EQUITY_RTH
    res = replay(sd.instrument, sd.bars[0].duration, sd.bars, engine_cfg=EngineConfig(session=session, pdr=PriorDayRangeConfig()),
                 cfg=cfg, data_label="atlas-feed")
    end_idx = {b.end: i for i, b in enumerate(sd.bars)}
    out = []
    for t in res.trades:
        if t.detector != DETECTOR or t.outcome in ("no_atr", "cost_skipped") or t.detected_at not in end_idx:
            continue
        ref = (2 * t.stop + t.target) / 3                 # stop = ref -/+ 2 ATR, target = ref +/- 4 ATR
        atr = abs(t.target - t.stop) / 6
        if atr <= 0:
            continue
        out.append({"i": end_idx[t.detected_at], "t": int(t.detected_at), "direction": t.direction, "ref": ref, "atr": atr,
                    "candidate_id": t.candidate_id})
    return out


def run_series(sd: SeriesData, universe: str) -> list[dict]:
    if sd is None or len(sd.bars) < 300:
        return []
    cands = candidates(sd)
    ctx = context(sd.bars)
    hold = hold_bars(sd.interval, sd.asset_class) * 2
    rows = []
    for cfg in grid(sd.asset_class):
        for c in cands:
            i, d = c["i"], (1 if c["direction"] == "long" else -1)
            f = cfg.filter
            if f == "htf_with" and ctx["htf"][i] != d: continue
            if f == "htf_counter" and ctx["htf"][i] != -d: continue
            vp = ctx["vol_pct"][i]
            if f == "vol_low" and not (vp <= 0.5): continue
            if f == "vol_high" and not (vp > 0.5): continue
            s = simulate(sd.bars, i, c["direction"], c["ref"], c["atr"], cfg, hold, sd.asset_class)
            if s is None:
                continue
            rows.append({"universe": universe, "instrument": sd.instrument, "interval": sd.interval, "config": cfg.id,
                         "detector": DETECTOR, "variant": cfg.id, "candidate_id": c["candidate_id"], "t": c["t"],
                         "direction": c["direction"], **s})
    return rows


def summarize(rows: Sequence[dict]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    r = np.array([x["r"] for x in rows]); g = np.array([x["gross_r"] for x in rows]); c = np.array([x["cost_r"] for x in rows])
    lo, hi = boot_ci(r); glo, ghi = boot_ci(g, seed=1)
    return {"n": len(r), "win_rate": _r((r > 0).mean()), "gross_r": _r(g.mean()), "net_r": _r(r.mean()),
            "median_cost_r": _r(float(np.median(c))), "net_ci95": [_r(lo), _r(hi)], "gross_ci95": [_r(glo), _r(ghi)]}


def evaluate(rows: list[dict], min_n: int = 200, min_dsr: float = 0.95, max_pbo: float = 0.5) -> dict[str, Any]:
    """Trials = every (universe, interval, config) cell. DSR and PBO over all trials; per-universe purged WF selection."""
    for x in rows:
        x["key"] = f"{x['universe']}|{x['interval']}|{x['config']}"
    by: dict[str, list[dict]] = {}
    for x in rows:
        by.setdefault(x["key"], []).append(x)
    t0 = min(x["t"] for x in rows); t1 = max(x["t"] for x in rows)
    series = {k: M.daily_series([x["t"] for x in v], [x["r"] for x in v], t0, t1) for k, v in by.items()}
    trials = list(series.values())
    pbo = M.pbo(np.column_stack(trials)) if len(trials) > 1 else None
    configs = []
    for k, v in sorted(by.items()):
        u, iv, cid = k.split("|")
        s = summarize(v)
        dsr = float((M.dsr(series[k], trials) if len(v) > 2 else {}).get("dsr") or 0.0)
        gates = [{"gate": f"n>={min_n}", "passed": s["n"] >= min_n},
                 {"gate": "net_ci95_low>0", "passed": bool(s["net_ci95"][0] is not None and s["net_ci95"][0] > 0)},
                 {"gate": f"dsr>={min_dsr:.2f}", "passed": dsr >= min_dsr},
                 {"gate": f"pbo<={max_pbo:.2f}", "passed": bool(pbo and pbo["pbo"] <= max_pbo)}]
        configs.append({"universe": u, "interval": iv, "config": cid, **s, "dsr": _r(dsr), "gates": gates,
                        "passes_gates": all(g["passed"] for g in gates)})
    wf = {}
    for u_iv in sorted({(x["universe"], x["interval"]) for x in rows}):
        sub = [x for x in rows if (x["universe"], x["interval"]) == u_iv]
        wf["|".join(u_iv)] = walk_forward_selection(sub, sorted({x["key"] for x in sub}))
    return {"configs": configs, "n_trials": len(trials), "pbo": pbo, "walk_forward_selection": wf,
            "assumptions": {"maker_bps_per_leg": MAKER_BPS, "taker_bps_per_leg": TAKER_BPS,
                            "maker_note": "maker_assumed is an assumption (queue position at the limit), not a verified fill model"},
            "execution_permission": "none"}
