"""Ticker dossier + deterministic conviction score (1-100, BUY/WATCH/SELL) + entry/stop/target suggestions.

Every point of the score comes from a named, inspectable rule over closed feed bars (and SEC fundamentals when they
are configured). No LLM, no news or sentiment (both reported "unavailable" rather than invented). The label is a
research-only advisory: it cannot place, size or approve an order; only the deterministic control plane can."""
from __future__ import annotations

from typing import Any, Sequence

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.indicators import atr_batch, rsi_batch
from atlas.features.price_action.library import adx_batch, macd_batch, realized_vol_batch, sma_batch

from . import ADVISORY
from .pricevol import classic_pivots, sr_zones, volume_profile

BUY_AT, SELL_AT = 65, 35


def _last(x):
    return next((v for v in reversed(x) if v is not None), None)


def technicals(daily: Sequence[Bar]) -> dict[str, Any]:
    c = [b.close for b in daily]; h = [b.high for b in daily]; l = [b.low for b in daily]
    if len(c) < 2:
        return {"status": "no_data", "bars": len(c)}
    ret = lambda n: (c[-1] / c[-1 - n] - 1) if len(c) > n and c[-1 - n] else None  # noqa: E731
    _, _, hist = macd_batch(c)
    _, _, adx = adx_batch(h, l, c)
    win = daily[-252:]
    return {"status": "ok", "bars": len(c), "close": c[-1], "ret_1m": ret(21), "ret_3m": ret(63), "ret_12m": ret(252),
            "sma50": _last(sma_batch(c, 50)), "sma200": _last(sma_batch(c, 200)), "rsi14": _last(rsi_batch(c, 14)),
            "macd_hist": _last(hist), "adx14": _last(adx), "atr14": _last(atr_batch(h, l, c, 14)),
            "realized_vol_20d_ann": _last(realized_vol_batch(c, 20, 252.0)),
            "high_52w": max(b.high for b in win), "low_52w": min(b.low for b in win), "last_bar_end": daily[-1].end}


def conviction(t: dict[str, Any], fundamentals_metrics: dict[str, Any] | None = None,
               profile: dict[str, Any] | None = None) -> dict[str, Any]:
    comps: list[dict[str, Any]] = []

    def add(rule: str, pts: float, why: str):
        comps.append({"rule": rule, "points": pts, "why": why})
    if t.get("status") != "ok":
        return {"score": None, "label": "NO_DATA", "components": [], "advisory": ADVISORY}
    close, s50, s200 = t["close"], t.get("sma50"), t.get("sma200")
    if s50 and s200:
        add("trend", 15 if close > s50 > s200 else -15 if close < s50 < s200 else 0,
            f"close {close:.4g} vs SMA50 {s50:.4g} vs SMA200 {s200:.4g}")
    elif s50:
        add("trend", 7 if close > s50 else -7, f"close vs SMA50 {s50:.4g} (SMA200 needs 200 bars)")
    r3 = t.get("ret_3m")
    if r3 is not None:
        add("momentum_3m", max(-10.0, min(10.0, r3 * 50)), f"3-month return {r3:+.1%} (x50 points, capped ±10)")
    mh = t.get("macd_hist")
    if mh is not None:
        add("macd", 5 if mh > 0 else -5, f"MACD histogram {mh:+.4g}")
    rsi = t.get("rsi14")
    if rsi is not None:
        add("rsi_extreme", -5 if rsi > 75 else 5 if rsi < 25 else 0, f"RSI14 {rsi:.1f} (>75 stretched, <25 washed-out)")
    adx = t.get("adx14")
    if adx is not None and s50:
        add("trend_strength", (5 if close > s50 else -5) if adx > 25 else 0, f"ADX14 {adx:.1f} (>25 confirms the trend side)")
    vol = t.get("realized_vol_20d_ann")
    if vol is not None:
        add("volatility", -5 if vol > 0.6 else 0, f"20d realised vol {vol:.0%} (>60% penalised)")
    if profile and profile.get("vah") and profile.get("val"):
        add("value_area", 3 if close > profile["vah"] else -3 if close < profile["val"] else 0,
            f"close vs value area {profile['val']:.4g}–{profile['vah']:.4g}")
    fm = fundamentals_metrics or {}
    if fm:
        q = 0
        q += 3 if (fm.get("roe") or 0) > 0.15 else -3 if (fm.get("roe") is not None and fm["roe"] < 0) else 0
        q += 3 if (fm.get("fcf") or 0) > 0 else -3 if fm.get("fcf") is not None else 0
        q += 2 if fm.get("debt_to_equity") is not None and fm["debt_to_equity"] < 1 else -2 if (fm.get("debt_to_equity") or 0) > 2 else 0
        q += 2 if (fm.get("revenue_growth") or 0) > 0.05 else -2 if (fm.get("revenue_growth") is not None and fm["revenue_growth"] < 0) else 0
        add("fundamental_quality", q, "SEC filings: ROE>15%, positive FCF, D/E<1, revenue growth>5% (each ±)")
    else:
        add("fundamental_quality", 0, "SEC fundamentals unavailable for this symbol (0 points, not guessed)")
    add("sentiment", 0, "news/sentiment unavailable: no licensed source configured (0 points)")
    raw = 50 + sum(c["points"] for c in comps)
    score = int(round(max(1, min(100, raw))))
    label = "BUY" if score >= BUY_AT else "SELL" if score <= SELL_AT else "WATCH"
    return {"score": score, "label": label, "thresholds": {"BUY": f">={BUY_AT}", "SELL": f"<={SELL_AT}"}, "base": 50,
            "components": comps, "method": "deterministic additive rules v1", "advisory": ADVISORY}


def trade_levels(label: str, close: float, atr: float | None, zones: list, profile: dict | None,
                 reference_levels: Sequence[tuple[str, float]] = ()) -> dict[str, Any]:
    """Entry/stop/target from observed levels. Long for BUY, short for SELL, none for WATCH."""
    if label not in ("BUY", "SELL") or not atr:
        return {"side": None, "why": "WATCH / no ATR: no trade levels suggested"}
    refs: list[tuple[str, float]] = list(reference_levels)
    for z in zones:
        refs += [(f"{z.zone_type}:{z.touch_count}t:low", z.lower_bound), (f"{z.zone_type}:{z.touch_count}t:high", z.upper_bound)]
    if profile:
        refs += [("POC", profile["poc"]), ("VAH", profile["vah"]), ("VAL", profile["val"])]
    below = sorted([r for r in refs if r[1] < close], key=lambda r: -r[1])
    above = sorted([r for r in refs if r[1] > close], key=lambda r: r[1])
    if label == "BUY":
        entry = below[0] if below and close - below[0][1] < 1.5 * atr else ("last_close", close)
        stop = entry[1] - 1.0 * atr
        tgt = next((r for r in above if r[1] - entry[1] >= 1.5 * (entry[1] - stop)), ("2R", entry[1] + 2 * (entry[1] - stop)))
        side = "long"
    else:
        entry = above[0] if above and above[0][1] - close < 1.5 * atr else ("last_close", close)
        stop = entry[1] + 1.0 * atr
        tgt = next((r for r in below if entry[1] - r[1] >= 1.5 * (stop - entry[1])), ("2R", entry[1] - 2 * (stop - entry[1])))
        side = "short"
    risk = abs(entry[1] - stop)
    return {"side": side, "entry": entry[1], "entry_ref": entry[0], "stop": stop, "stop_ref": "entry ∓ 1×ATR14",
            "target": tgt[1], "target_ref": tgt[0], "reward_risk": abs(tgt[1] - entry[1]) / risk if risk else None,
            "stop_distance_bps": risk / entry[1] * 1e4 if entry[1] else None, "advisory": ADVISORY}


def build_dossier(symbol: str, daily: Sequence[Bar], intraday: Sequence[Bar] = (), fundamentals: dict | None = None,
                  fundamentals_metrics: dict | None = None, reference_levels: Sequence[tuple[str, float]] = ()) -> dict[str, Any]:
    t = technicals(daily)
    zones = sr_zones(daily, symbol) if len(daily) >= 30 else []
    prof = volume_profile(list(daily[-60:]))
    piv = classic_pivots(daily[-1].high, daily[-1].low, daily[-1].close) if daily else None
    conv = conviction(t, fundamentals_metrics, prof)
    lv = trade_levels(conv["label"], t.get("close") or 0, t.get("atr14"), zones, prof, reference_levels) if t.get("status") == "ok" else {"side": None}
    return {"symbol": symbol.upper(), "technicals": t, "conviction": conv, "trade_levels": lv,
            "zones": [z.to_dict() for z in zones], "volume_profile_60d": None if not prof else {k: prof[k] for k in ("poc", "vah", "val", "value_area_pct", "bars")},
            "next_session_pivots": piv,
            "fundamentals": {"status": (fundamentals or {}).get("status", "not_requested"), "entity": (fundamentals or {}).get("entity"),
                             "metrics": fundamentals_metrics or {}, "latest_period": ((fundamentals or {}).get("periods") or [None])[0]},
            "news": {"status": "unavailable", "reason": "no licensed news source configured; nothing is summarised or invented"},
            "sentiment": {"status": "unavailable", "reason": "no sentiment source configured"},
            "advisory": ADVISORY, "execution_permission": "none"}
