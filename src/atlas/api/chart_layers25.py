"""Ten chart layers added in evo-14 (all off by default in the UI). Computed server-side from CLOSED bars only, by the same
functions that build the model's training features (``atlas.ai.ml.directional.layers25``), so the number on screen is the number the model saw.
Every payload carries ``status`` and, when not ok, a plain-language ``reason``. Read-only: no order, no limit change, no profitability claim."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml.directional import layers25 as L

IDS = ("conformal_bands", "mtf_confluence", "events", "market_clock", "cross_corr", "vol_cone", "liquidity", "model_disagreement", "account_size", "drift_alert")
VIEW_POINTS = 300


def _f(x, nd=4):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _unavail(reason: str, **kw) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, **kw}


def _last(f: pd.DataFrame, cols) -> dict[str, float | None]:
    return {c: _f(f[c].iloc[-1]) for c in cols}


class Ctx:
    """Everything the ten layers share, computed once per request."""
    def __init__(self, sym, interval, bars, now, feed, tz, group, cost_bps, horizon, corr_avail, events, mp, dp):
        self.sym, self.interval, self.now, self.tz = sym, interval, now, tz
        self.bars = [b for b in bars if b.start + b.duration <= now]
        self.group, self.cost_bps, self.H, self.mp, self.dp, self.events = group, cost_bps, horizon, mp, dp, events
        self.corr_avail = corr_avail
        self.f = L.layer_features(self.bars, interval, group, sym, horizon, cost_bps, corr_avail, events) if len(self.bars) >= 30 else None


def build_ctx(sym, interval, bars, now, feed, tz="America/Toronto", mp=None, dp=None, events=None, events_ok=False) -> Ctx:
    from atlas.ai.ml.dataset import load_series
    from atlas.ai.ml.directional import pipeline as P
    group = P.group_of(sym)
    avail = {}
    for cands in L.CORR_ROLES.values():
        for s in cands:
            if s == sym:
                continue
            try:
                rb = load_series(feed, s, interval).bars
            except Exception:
                rb = []
            if len(rb) >= 300:
                avail[s] = (np.array([x.end for x in rb]), np.array([x.close for x in rb]))
    ctx = Ctx(sym, interval, bars, now, feed, tz, group, P.cost_bps(group), P.horizon_for(interval, group), avail, events if events_ok else None, mp, dp)
    return ctx


def _need(ctx: Ctx):
    if ctx.f is None:
        raise ValueError(f"only {len(ctx.bars)} closed bars; at least 30 needed")


# ------------------------------------------------------------------------------------------------ 1
def conformal_bands(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    cols = L.LAYER_FEATURES["conformal_bands"]
    last = _last(ctx.f, cols)
    if last["cb_halfwidth_pct"] is None:
        return _unavail(f"needs at least {60 + ctx.H} closed bars of resolved forecasts; have {len(ctx.bars)}", features=last)
    bars = ctx.bars[-VIEW_POINTS:]
    half = ctx.f["cb_halfwidth_pct"].iloc[-len(bars):].to_numpy()
    pts = [{"time": b.start, "upper": _f(b.close * math.exp(h), 6), "lower": _f(b.close * math.exp(-h), 6)} for b, h in zip(bars, half) if math.isfinite(h)]
    c = ctx.bars[-1].close
    h = ctx.f["cb_halfwidth_pct"].iloc[-1]
    return {"status": "ok", "reason": f"Split-conformal {int((1 - L.CB_ALPHA) * 100)}% band for the {ctx.H}-bar move, from the last {L.CB_WINDOW} resolved forecasts. Not a price target.",
            "alpha": L.CB_ALPHA, "horizon_bars": ctx.H, "forward": {"upper": _f(c * math.exp(h), 6), "lower": _f(c * math.exp(-h), 6), "as_of_end": ctx.bars[-1].end},
            "points": pts, "realised_coverage_64": last["cb_cover_64"], "features": last,
            "meaning": "A band that contained the realised move about this often over the last 64 resolved bars; coverage can drift in a new regime."}


# ------------------------------------------------------------------------------------------------ 2
def mtf_confluence(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    last = _last(ctx.f, L.LAYER_FEATURES["mtf_confluence"])
    if last["mtfc_score"] is None:
        return _unavail(f"needs {max(L.MTF_KS) + 1} closed bars; have {len(ctx.bars)}", features=last)
    c = pd.Series([b.close for b in ctx.bars])
    lc = np.log(c)
    lr = lc.diff()
    sig = L._sigma(lr)
    z = {k: _f(((lc - lc.shift(k)) / (sig * np.sqrt(k))).iloc[-1], 2) for k in L.MTF_KS}
    s = last["mtfc_score"]
    return {"status": "ok", "reason": "Agreement of volatility-normalised trend over 4/16/64/256 bars of this chart's own interval (bar multiples, not calendar timeframes).",
            "score": s, "agreement": last["mtfc_agree"], "n_up": last["mtfc_n_up"], "z": z, "bias": "up" if s > 0.25 else ("down" if s < -0.25 else "mixed"),
            "features": last, "meaning": "1 = every horizon trending up, -1 = every horizon down. Descriptive, not a forecast."}


# ------------------------------------------------------------------------------------------------ 3
def events(ctx: Ctx, cal: dict[str, Any] | None) -> dict[str, Any]:
    earn = {"status": "unavailable", "reason": "No earnings-calendar source is configured (needs a Finnhub/FMP key, none set; SEC EDGAR 8-K item 2.02 only shows results after the fact)."}
    if not cal:
        return _unavail("economic calendar was not loaded", earnings=earn)
    evs = cal.get("events") or []
    srcs = [{"id": s.get("id"), "status": s.get("status"), "n": s.get("in_window")} for s in cal.get("sources", [])]
    if not evs:
        bad = "; ".join(f"{s.get('id')}: {s.get('reason') or s.get('status')}" for s in cal.get("sources", []) if s.get("status") != "ok") or "sources reachable but list nothing in window"
        return _unavail(f"no scheduled releases returned ({bad})", sources=srcs, earnings=earn)
    tz = ZoneInfo(ctx.tz)
    up = [{"ts": e["ts"], "when": datetime.fromtimestamp(e["ts"], tz).strftime("%a %b %d %H:%M %Z"), "title": e.get("title") or e.get("name"), "source": e.get("source"),
           "important": e.get("important"), "all_day": e.get("all_day")} for e in evs if e["ts"] >= ctx.now - 3600][:12]
    nxt = next((e for e in up if e["ts"] >= ctx.now), None)
    feat = _last(ctx.f, L.LAYER_FEATURES["events"]) if ctx.f is not None else {}
    return {"status": "ok", "reason": "Official release schedules only (BLS, Treasury; FRED when keyed). Times shown in your timezone.", "timezone": ctx.tz,
            "next": nxt, "upcoming": up, "sources": srcs, "earnings": earn, "features": feat,
            "meaning": "Shows when scheduled data lands; it does not say which way price will move."}


# ------------------------------------------------------------------------------------------------ 4
def market_clock(ctx: Ctx) -> dict[str, Any]:
    tz = ZoneInfo(ctx.tz)
    now = int(ctx.now)
    grid = now + 60 * np.arange(0, 8 * 1440 + 1)
    st = L.venue_open(grid)
    rows = []
    for name, vtz, spans, bloc in L.VENUES:
        col = st[name].to_numpy()
        flips = np.flatnonzero(col[1:] != col[:-1])
        nxt = int(grid[flips[0] + 1]) if len(flips) else None
        rows.append({"venue": name, "bloc": bloc, "open": bool(col[0]), "local_tz": vtz, "hours_local": " + ".join(f"{a:02d}:{b:02d}-{c:02d}:{d:02d}" for a, b, c, d in spans),
                     "next_change": None if nxt is None else {"event": "closes" if col[0] else "opens", "at": datetime.fromtimestamp(nxt, tz).strftime("%a %H:%M %Z"), "ts": nxt}})
    rows.append({"venue": "Crypto", "bloc": "24x7", "open": True, "local_tz": "UTC", "hours_local": "24/7", "next_change": None})
    feat = _last(ctx.f, L.LAYER_FEATURES["market_clock"]) if ctx.f is not None else {}
    return {"status": "ok", "reason": "Regular-session hours by exchange, converted to your timezone. Exchange holidays and early closes are NOT modelled.", "timezone": ctx.tz,
            "now_local": datetime.fromtimestamp(now, tz).strftime("%a %Y-%m-%d %H:%M %Z"), "venues": rows, "n_open": sum(1 for r in rows if r["open"] and r["bloc"] != "24x7"), "features": feat,
            "meaning": "Which major exchanges are trading now. Liquidity and volatility differ by session; this is context, not a signal."}


# ------------------------------------------------------------------------------------------------ 5
def cross_corr(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    roles = L.role_refs(ctx.corr_avail, ctx.sym)
    missing = {r: f"no stored {'/'.join(c)} bars at {ctx.interval}" for r, c in L.CORR_ROLES.items() if r not in roles and ctx.sym not in c}
    if not roles:
        return _unavail("no proxy series are stored for this interval (" + "; ".join(missing.values()) + ")", missing=missing)
    names = {r: next(s for s in L.CORR_ROLES[r] if s in ctx.corr_avail and s != ctx.sym) for r in roles}
    feat = _last(ctx.f, L.LAYER_FEATURES["cross_corr"])
    rows = [{"role": r, "proxy": names[r], "corr_64": feat[f"xcl_{r}_corr_64"], "beta_64": feat[f"xcl_{r}_beta_64"]} for r in roles]
    note = "DXY is not stored; UUP (dollar ETF) is used when present. " if "usd" not in roles else ""
    return {"status": "ok", "reason": f"{note}Rolling 64-bar correlation and beta of 1-bar returns, using the last proxy bar that closed at or before each of this chart's bars.",
            "proxies": rows, "missing": missing, "features": feat, "meaning": "How tied this instrument has recently been to dollar, gold, Bitcoin and the S&P 500. Correlations move; they are not causal."}


# ------------------------------------------------------------------------------------------------ 6
def vol_cone(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["vol_cone"])
    lr = np.log(pd.Series([b.close for b in ctx.bars])).diff()
    rows, wmin = [], None
    for h in L.VC_HS:
        rv = np.sqrt((lr ** 2).rolling(h, min_periods=h).mean()).to_numpy()
        fin = rv[np.isfinite(rv)]
        w = min(L.VC_WINDOW, len(fin))                      # the chart holds ~600 bars, so the history can be shorter than the 500 used for training
        if w < 100 or not np.isfinite(rv[-1]):
            continue
        hist = fin[-w:]
        now_v = float(rv[-1])
        pct = float(((hist < now_v).sum() + 0.5 * (hist == now_v).sum()) / w)
        wmin = w if wmin is None else min(wmin, w)
        rows.append({"horizon_bars": h, "now_bps": _f(now_v * 1e4, 1), "p10_bps": _f(np.quantile(hist, 0.1) * 1e4, 1), "p50_bps": _f(np.quantile(hist, 0.5) * 1e4, 1),
                     "p90_bps": _f(np.quantile(hist, 0.9) * 1e4, 1), "percentile": _f(pct, 3), "history_bars": int(w)})
    if not rows:
        return _unavail(f"needs about {max(L.VC_HS) + 100} closed bars for volatility history; have {len(ctx.bars)}", features=feat)
    slope = feat.get("vc_term_slope")
    return {"status": "ok", "reason": f"Realised per-bar volatility over {'/'.join(str(r['horizon_bars']) for r in rows)} bars against its own last {wmin}+ values "
                                       f"(training features use a 500-bar window and are blank until 500 are available).",
            "cone": rows, "term_slope": slope, "features": feat,
            "meaning": "Percentile 0.9 = volatility is higher than 90% of recent history. Says how big moves have been, not their direction."}


# ------------------------------------------------------------------------------------------------ 7
def liquidity(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["liquidity"])
    if feat["liq_cs_spread"] is None:
        return _unavail("not enough bars for the high-low spread estimate", features=feat)
    has_vol = any(b.volume for b in ctx.bars[-200:])
    return {"status": "ok", "reason": "Spread is ESTIMATED from high/low (Corwin-Schultz 2012); no quote or order-book feed is connected. Cost is the assumed round-trip venue cost, "
                                       "not a measured fill. US per-share fees are not modelled." + ("" if has_vol else " Source bars carry no volume, so Amihud and dollar-volume are blank."),
            "est_spread_bps": feat["liq_cs_spread"], "assumed_cost_bps": ctx.cost_bps, "cost_in_R": feat["liq_cost_r"], "amihud_log10": feat["liq_amihud"], "dollar_volume_z": feat["liq_dvol_z"],
            "features": feat, "meaning": "cost_in_R is the assumed round-trip cost as a fraction of one stop-distance of risk; above ~0.25 most of the edge would go to costs."}


# ------------------------------------------------------------------------------------------------ 8
def model_disagreement(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["model_disagreement"])
    if feat["dis_net_vote"] is None:
        return _unavail(f"experts need 65 closed bars; have {len(ctx.bars)}", features=feat)
    votes = L.expert_votes(pd.DataFrame({"high": [b.high for b in ctx.bars], "low": [b.low for b in ctx.bars], "close": [b.close for b in ctx.bars]}),
                           L._sigma(np.log(pd.Series([b.close for b in ctx.bars])).diff())).iloc[-1]
    experts = [{"expert": k, "vote": int(v)} for k, v in votes.items()]
    ml = []
    mp, dp = ctx.mp or {}, ctx.dp or {}
    if isinstance(mp, dict) and mp.get("status") == "ok" and mp.get("p_long") is not None:
        ml.append({"model": "walk-forward meta-model", "p_up": _f(mp["p_long"]), "label": mp.get("label")})
    if isinstance(dp, dict) and dp.get("status") == "ok" and dp.get("probability") is not None:
        ml.append({"model": "evo-14 directional (HGB)", "p_up": _f(dp["probability"]), "label": dp.get("label")})
    spread = _f(max(m["p_up"] for m in ml) - min(m["p_up"] for m in ml)) if len(ml) >= 2 else None
    return {"status": "ok", "reason": "Dispersion of six fixed rule experts (momentum 4/16/64, range reversal, EMA cross, RSI reversal). Learned-model dispersion is shown only when 2+ models have a score.",
            "experts": experts, "net_vote": feat["dis_net_vote"], "vote_std": feat["dis_vote_std"], "agree_frac": feat["dis_agree_frac"],
            "learned_models": ml, "learned_spread": spread,
            **({} if spread is not None else {"learned_note": "fewer than two learned models have a score here, so no learned-model dispersion is reported"}),
            "features": feat, "meaning": "High dispersion = the experts disagree, so any single call deserves less weight. Learned-model dispersion is display-only: it is a model output and is not fed back as a training feature."}


# ------------------------------------------------------------------------------------------------ 9
def account_size(ctx: Ctx, snap: dict[str, Any] | None) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["account_size"])
    if feat["acct_stop_frac"] is None:
        return _unavail("volatility not available yet", features=feat)
    if not snap:
        return _unavail("account snapshot not available from the control plane", features=feat)
    sn = snap.get("snapshot") or {}
    sz = snap.get("sizing") or {}
    eq = (sn.get("balances") or {}).get("equity")
    if sn.get("status") != "ok" or not eq:
        return _unavail(f"account snapshot is not usable ({sn.get('status') or 'no status'}: {sn.get('reason') or 'no equity reported'})", features=feat, broker=sn.get("broker"))
    stop = feat["acct_stop_frac"]
    risk = 0.005
    notional = eq * risk / stop
    mn = sz.get("min_order_notional")
    fit = None if mn is None else bool(notional >= mn)
    return {"status": "ok", "reason": "Read-only sizing context from the control plane (" + str(sn.get("broker")) + "). Sizing stays with the deterministic risk policy; the ML only reads this.",
            "broker": sn.get("broker"), "equity": _f(eq, 2), "risk_fraction": risk, "stop_frac": stop, "ideal_notional": _f(notional, 2), "min_order_notional": mn,
            "min_order_fits": fit, "features_note": "Only the bar-derived part (stop_frac, notional per 1% risk) is a training feature; equity and minimums have no history, so they are not.",
            "features": feat, "execution_permission": "none",
            "meaning": "What a policy-sized position would be at this stop distance. It is not an order and does not change any limit."}


# ------------------------------------------------------------------------------------------------ 10
def drift_alert(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["drift_alert"])
    if feat["dr_vol_ratio"] is None or feat["dr_mean_shift_z"] is None:
        return _unavail(f"needs about 320 closed bars; have {len(ctx.bars)}", features=feat)
    vr, mz, rr = abs(feat["dr_vol_ratio"]), abs(feat["dr_mean_shift_z"]), abs(feat["dr_range_ratio"] or 0)
    level = "alert" if (vr > 0.5 or mz > 3 or rr > 0.5) else ("watch" if (vr > 0.3 or mz > 2 or rr > 0.3) else "stable")
    why = [t for t, c in (("volatility changed by more than 65% vs the prior 256 bars", vr > 0.5), ("average return shifted by more than 3 standard errors", mz > 3), ("bar range changed by more than 65%", rr > 0.5)) if c]
    return {"status": "ok", "reason": "Market-data drift: last 32/64 bars against the prior 256. Model drift (live errors, ADWIN) needs resolved live predictions and is not reported here.",
            "level": level, "triggers": why, "features": feat, "thresholds": {"alert": {"vol_ratio_log": 0.5, "mean_z": 3, "range_ratio_log": 0.5}, "watch": {"vol_ratio_log": 0.3, "mean_z": 2, "range_ratio_log": 0.3}},
            "meaning": "An alert means recent data looks unlike the history a model was fitted on, so its output deserves less trust. It is not a trade signal."}


# ------------------------------------------------------------------------------------------------ 26 News & filings (evo-14b)
NEWS_ID = "news"
ALL_IDS = IDS + (NEWS_ID,)


def news_layer(sym: str, now: float, t0: float, env=None) -> dict[str, Any]:
    """Layer 26: official filings and open-source headlines for this ticker from the local store, each linking to its source, with rule / LLM
    annotation where one exists. Advisory only. Everything is read from what was collected; nothing is generated here."""
    from atlas.news import features as NF
    from atlas.news import llm as NL
    from atlas.news import reviewer as RV
    from atlas.news import store as S
    ticker = NF.ticker_of(sym)
    base = {"execution_permission": "none", "layer": 26, "ticker": ticker}
    if ticker is None:
        return {**base, **_unavail(f"{sym} has no SEC filings or issuer news in this layer: it covers SEC-registered US equities only (not crypto, FX, ETFs, futures).")}
    scope = S.current_scope()
    cov_f, cov_n = S.coverage_start(ticker, "sec_edgar"), S.coverage_start(ticker, "gdelt")
    st = NL.llm_status()
    cov = {"filings_since": cov_f, "news_since": cov_n}
    items = S.items_for([ticker], since=t0, until=now, limit=200)
    if cov_f is None and cov_n is None:
        return {**base, **_unavail("Nothing has been collected for this ticker yet. Add it to your watchlist and press Refresh in Research \u2192 News (EDGAR also needs ATLAS_SEC_USER_AGENT; GDELT and official RSS need no key).",
                                   coverage=cov, llm={"enabled": st["enabled"], "reason": st["reason"]})}
    ann = S.annotations_for([(i["id"], i["ticker"]) for i in items], scope)
    from atlas.news.service import _pick
    out = []
    for i in sorted(items, key=lambda r: r["published_at"]):
        a = _pick(ann.get((i["id"], i["ticker"]), []))
        out.append({"time": int(i["published_at"]), "id": i["id"], "source": i["source"], "tier": i["tier"], "tier_label": "official" if i["tier"] == 1 else "unverified news", "kind": i["kind"],
                    "title": i["title"], "url": i["url"], "event_type": a["event_type"], "sentiment": a["sentiment"], "materiality": a["materiality"], "grounded": a["grounded"],
                    "hype_flags": [f["type"] for f in a["hype_flags"]], "analyzer": a["analyzer"]})
    ni = NF.news_input(ticker, scope)
    feat = {}
    if ni is not None:
        fr = NF.news_frame(np.array([now], float), ni)
        feat = {c: _f(fr[c].iloc[0]) for c in NF.NEWS_FEATURES}
    return {**base, "status": "ok", "reason": ("" if out else "No collected items fall inside the visible window."), "items": out, "coverage": cov, "features": feat,
            "llm": {"enabled": st["enabled"], "reason": st["reason"], "model": st.get("model")}, "reviewer_mode": RV.mode(env),
            "note": "Tier 1 = official source (SEC, central banks). Tier 2 = third-party headline, unverified. Sentiment / materiality appear only when a verified LLM scored the item with a verbatim evidence quote; otherwise they are blank, never guessed."}


def attach_reviews(markers: list[dict[str, Any]]) -> dict[str, Any]:
    """Show the LLM Reviewer's verdict in each marker's details and feed paper outcomes back to the reviewer's audit log."""
    from atlas.news import reviewer as RV
    from atlas.news import store as S
    scope = S.current_scope()
    ids = [m["id"] for m in markers if m.get("id")]
    if not ids:
        return {"status": "ok", "n": 0}
    done = [{"marker_id": m["id"], "outcome": {"target": "win", "stop": "loss"}.get(m.get("outcome"), "flat"), "r": m.get("r")}
            for m in markers if m.get("id") and m.get("outcome") in ("target", "stop", "timeout") and m.get("r") is not None]
    RV.record_outcomes(done)
    latest: dict[str, dict[str, Any]] = {}
    for r in RV.reviews_for(scope, 500, ids):
        latest.setdefault(r["marker_id"], r)
    for m in markers:
        r = latest.get(m.get("id"))
        if r:
            m["llm_review"] = {"review_id": r["review_id"], "verdict": r["verdict"], "status": r["status"], "mode": r["mode"], "applied": r["applied"], "reason": r["reason"],
                               "recommendation": r["recommendation"], "confidence_multiplier": r["confidence_multiplier"], "model": r["model"], "ts": r["ts"],
                               "sources": [s for s in r["sources"] if s["id"] in r["citations"]], "execution_permission": "none"}
    return {"status": "ok", "n": len(latest)}
