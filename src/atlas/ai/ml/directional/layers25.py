"""Layer features (ATLAS_MODEL_SPEC.md section 3.8): the numeric output of every chart layer that can legitimately be a feature.

One implementation feeds BOTH the chart (``/api/ai/chart/overlays``) and the model, so the number on screen is the number the
model saw. Every value at bar i uses only bars <= i, reference bars whose end <= end_i, and schedules published ahead of time.
Nothing here reads a model output or a realised outcome (those are layers 'ml_markers', 'ml_probability', 'predictions',
'prediction_zone', 'outcomes', 'trade_lines', 'marker_details', 'conviction'; they are excluded and the spec says why).

Honesty contract: a feature that cannot be computed is NaN (never 0, never invented). ``coverage`` reports which can't be.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from atlas.features.price_action.bars import Bar
from atlas.news.features import NEWS_FEATURES, news_frame

# ----------------------------------------------------------------------------- feature groups (layer id -> columns)
CB_ALPHA, CB_WINDOW = 0.2, 250
MTF_KS = (4, 16, 64, 256)
VC_HS = (4, 16, 64, 256)
VC_WINDOW = 500
VC_MIN_W = 120      # percentile needs >= this many finite values in the trailing window (the chart already used >= 100)
PROXY_EXCLUDES = {"USD_PROXY": ("EUR_USD", "USD_CAD")}   # the proxy is built from these two legs, so it is not a reference for them
SESSION_SHIFT_H = {"equity": 0, "gold": 6}   # session day = New-York date of (bar midpoint + shift); CME metals trade 18:00-17:00 ET
VP_WINDOW, VP_BINS, VP_STEP = 300, 24, 8
CORR_ROLES = {"usd": ("DXY", "UUP", "USD_PROXY"), "gold": ("GLD", "XAUUSD"), "btc": ("BTCUSDT", "BTC-USD"), "spy": ("SPY",)}
VENUES = (  # name, IANA tz, ((open_h, open_m, close_h, close_m), ...), bloc
    ("NYSE", "America/New_York", ((9, 30, 16, 0),), "us"), ("TSX", "America/Toronto", ((9, 30, 16, 0),), "us"),
    ("LSE", "Europe/London", ((8, 0, 16, 30),), "eu"), ("Xetra", "Europe/Berlin", ((9, 0, 17, 30),), "eu"),
    ("TSE", "Asia/Tokyo", ((9, 0, 11, 30), (12, 30, 15, 30)), "asia"), ("HKEX", "Asia/Hong_Kong", ((9, 30, 12, 0), (13, 0, 16, 0)), "asia"),
)

LAYER_FEATURES: dict[str, tuple[str, ...]] = {
    "conformal_bands": ("cb_qhat", "cb_halfwidth_pct", "cb_cover_64"),
    "mtf_confluence": ("mtfc_score", "mtfc_agree", "mtfc_n_up", "mtfc_slope_score"),
    "events": ("ev_hrs_to_next", "ev_hrs_since_last", "ev_in_window"),
    "market_clock": ("clk_n_open", "clk_us_open", "clk_eu_open", "clk_asia_open"),
    "cross_corr": tuple(f"xcl_{r}_{m}_64" for r in CORR_ROLES for m in ("corr", "beta")),
    "vol_cone": tuple(f"vc_pct_{h}" for h in VC_HS) + ("vc_term_slope",),
    "liquidity": ("liq_cs_spread", "liq_amihud", "liq_dvol_z", "liq_cost_r"),
    "model_disagreement": ("dis_net_vote", "dis_vote_std", "dis_agree_frac"),
    "account_size": ("acct_stop_frac", "acct_notional_per_1pct_risk"),
    "drift_alert": ("dr_vol_ratio", "dr_mean_shift_z", "dr_range_ratio"),
    # existing layers whose numbers were not yet model inputs (anchored VWAP, volume profile, prior-day zone)
    "existing_gaps": ("ex_avwap_dist_atr", "ex_vp_poc_dist_atr", "ex_vp_va_pos", "ex_pd_range_pos"),
    # layer 26 "News & filings" (evo-14b): point-in-time, source-covered; NaN for instruments without SEC filings. See atlas.news.features.
    "news": NEWS_FEATURES,
    # layers 27-32 (evo-15): context27.py supplies the market-wide inputs; all point-in-time, NaN when not computable
    "breadth": ("br_pct_above_50", "br_pct_above_200", "br_adv_share_10", "br_pct50_chg_5"),
    "overnight_intraday": ("oi_gap_z", "oi_on_20", "oi_id_20", "oi_spread_20"),
    "gap_stats": ("gp_size_atr", "gp_filled", "gp_fill_rate_20"),
    "seasonality": ("sea_bdom_frac", "sea_turn_of_month", "sea_dow_sin", "sea_dow_cos", "sea_qtr_end"),
    "implied_vol": ("iv_vix_z_252", "iv_vix_chg_5", "iv_vrp"),
    "usd_proxy": ("usd_ret_16", "usd_ret_64", "usd_z_64"),
}
LAYER27_IDS = ("breadth", "overnight_intraday", "gap_stats", "seasonality", "implied_vol", "usd_proxy")
NEW_LAYER_IDS = tuple(k for k in LAYER_FEATURES if k not in ("existing_gaps", "news", *LAYER27_IDS))   # the ten layers added in evo-14; "news" is layer 26
LAYER_FEATURE_NAMES: tuple[str, ...] = tuple(c for cols in LAYER_FEATURES.values() for c in cols)
EXPERTS = ("mom_4", "mom_16", "mom_64", "rev_pos_64", "ema_cross", "rsi_rev")
BARRIER_K = 1.0   # stop distance in sigma-sqrt(H) units for the account-size / cost-R features


def _sigma(lr: pd.Series) -> pd.Series:
    return lr.ewm(span=100, min_periods=20, adjust=False).std()


def _rank_pct(x: np.ndarray, w: int, min_w: int | None = None) -> np.ndarray:
    """Trailing percentile of x[i] among the finite values of x[i-w+1..i] (mid-rank for ties).
    NaN until ``min_w`` finite values are available (default: a full window ``w``)."""
    n = len(x)
    mw = w if min_w is None else min(min_w, w)
    out = np.full(n, np.nan)
    if n < mw:
        return out
    pad = np.concatenate([np.full(w - 1, np.nan), np.asarray(x, float)])
    win = np.lib.stride_tricks.sliding_window_view(pad, w)
    last = win[:, -1:]
    fin = np.isfinite(win)
    nfin = fin.sum(axis=1)
    pct = ((win < last).sum(axis=1) + 0.5 * ((win == last).sum(axis=1) - 1) + 0.5) / np.maximum(nfin, 1)
    ok = np.isfinite(win[:, -1]) & (nfin >= mw)
    return np.where(ok, pct, np.nan)


# ----------------------------------------------------------------------------- 1 conformal bands
def conformal_band_frame(c: pd.Series, sig: pd.Series, H: int, alpha: float = CB_ALPHA, window: int = CB_WINDOW) -> pd.DataFrame:
    """Split-conformal band for the H-bar log return: |r_{j,j+H}| / (sigma_j sqrt(H)) scored once resolved (at bar j+H);
    qhat_i is the ceil((n+1)(1-alpha))/n quantile of the last ``window`` RESOLVED scores. Coverage is measured on bands already issued."""
    lc = np.log(c)
    fwd = lc.shift(-H) - lc                           # uses bar j+H: only ever read after it exists (shifted back below)
    score = (fwd.abs() / (sig * np.sqrt(H))).shift(H)  # score of the band issued at i-H, known at i
    lvl = min(1.0, (1 - alpha) * (1 + 1.0 / window))
    qhat = score.rolling(window, min_periods=60).quantile(lvl, interpolation="higher")
    half = qhat * sig * np.sqrt(H)
    issued_half = (qhat * sig * np.sqrt(H)).shift(H)
    realised = (lc - lc.shift(H)).abs()
    hit = (realised <= issued_half).where(issued_half.notna()).astype(float)
    return pd.DataFrame({"cb_qhat": qhat, "cb_halfwidth_pct": half, "cb_cover_64": hit.rolling(64, min_periods=32).mean()})


# ----------------------------------------------------------------------------- 2 multi-timeframe confluence
def mtf_frame(c: pd.Series, sig: pd.Series) -> pd.DataFrame:
    lc = np.log(c)
    z = pd.concat([(lc - lc.shift(k)) / (sig * np.sqrt(k)) for k in MTF_KS], axis=1)
    sgn = np.sign(z)
    slopes = pd.concat([np.sign(c.ewm(span=s, adjust=False, min_periods=s).mean().diff(5)) for s in (20, 80, 320)], axis=1)
    score = sgn.mean(axis=1, skipna=False)
    return pd.DataFrame({"mtfc_score": score, "mtfc_agree": score.abs(), "mtfc_n_up": (z > 0).sum(axis=1).where(z.notna().all(axis=1)),
                         "mtfc_slope_score": slopes.mean(axis=1, skipna=False)})


# ----------------------------------------------------------------------------- 3 events
def event_frame(end: np.ndarray, events: Sequence[float] | None) -> pd.DataFrame:
    """Hours to the next / since the last scheduled release. Schedules are published ahead, so the value at bar close is known.
    NaN outside the schedule's own coverage window (we never extrapolate a calendar we do not have)."""
    n = len(end)
    nan = np.full(n, np.nan)
    cols = {c: nan.copy() for c in LAYER_FEATURES["events"]}
    ev = np.sort(np.asarray([e for e in (events or []) if e == e], float))
    if len(ev) < 2:
        return pd.DataFrame(cols)
    e = np.asarray(end, float)
    idx = np.searchsorted(ev, e, side="right")
    cov = (e >= ev[0]) & (e <= ev[-1])
    nxt = np.where(idx < len(ev), ev[np.minimum(idx, len(ev) - 1)] - e, np.nan) / 3600.0
    prv = np.where(idx > 0, e - ev[np.maximum(idx - 1, 0)], np.nan) / 3600.0
    cols["ev_hrs_to_next"] = np.where(cov, np.minimum(nxt, 168.0), np.nan)
    cols["ev_hrs_since_last"] = np.where(cov, np.minimum(prv, 168.0), np.nan)
    cols["ev_in_window"] = np.where(cov, ((np.nan_to_num(nxt, nan=1e9) <= 1.0) | (np.nan_to_num(prv, nan=1e9) <= 1.0)).astype(float), np.nan)
    return pd.DataFrame(cols)


# ----------------------------------------------------------------------------- 4 market clock
def venue_open(ts: np.ndarray) -> pd.DataFrame:
    """Boolean frame (one column per venue) for UTC epoch seconds. Regular hours Mon-Fri only; exchange holidays are NOT modelled."""
    idx = pd.to_datetime(np.asarray(ts, np.int64), unit="s", utc=True)
    out = {}
    for name, tz, spans, _ in VENUES:
        loc = idx.tz_convert(tz)
        mins = loc.hour * 60 + loc.minute
        wk = loc.day_of_week < 5
        o = np.zeros(len(idx), bool)
        for oh, om, ch, cm in spans:
            o |= (mins >= oh * 60 + om) & (mins < ch * 60 + cm)
        out[name] = o & np.asarray(wk)
    return pd.DataFrame(out)


def clock_frame(end: np.ndarray) -> pd.DataFrame:
    v = venue_open(end)
    bloc = {b: [n for n, _, _, bb in VENUES if bb == b] for b in ("us", "eu", "asia")}
    return pd.DataFrame({"clk_n_open": v.sum(axis=1).astype(float), "clk_us_open": v[bloc["us"]].any(axis=1).astype(float),
                         "clk_eu_open": v[bloc["eu"]].any(axis=1).astype(float), "clk_asia_open": v[bloc["asia"]].any(axis=1).astype(float)})


# ----------------------------------------------------------------------------- 5 cross-asset correlation
def role_refs(avail: Mapping[str, tuple[np.ndarray, np.ndarray]], instrument: str | None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """role -> the first candidate symbol that exists and is not the instrument itself."""
    out = {}
    for role, cands in CORR_ROLES.items():
        for s in cands:
            if s in avail and s != instrument and instrument not in cands and instrument not in PROXY_EXCLUDES.get(s, ()):
                out[role] = avail[s]
                break
    return out


def corr_frame(end: np.ndarray, c: pd.Series, roles: Mapping[str, tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    own = np.log(c).diff()
    left = pd.DataFrame({"end": np.asarray(end, np.int64)})
    cols = {name: np.full(len(c), np.nan) for name in LAYER_FEATURES["cross_corr"]}
    for role, (r_end, r_close) in roles.items():
        right = pd.DataFrame({"end": np.asarray(r_end, np.int64), "c": np.asarray(r_close, float)}).sort_values("end")
        m = pd.merge_asof(left, right, on="end", direction="backward")          # last reference bar with end <= own end
        rr = np.log(m["c"]).diff()
        cols[f"xcl_{role}_corr_64"] = own.rolling(64, min_periods=32).corr(rr).to_numpy()
        cols[f"xcl_{role}_beta_64"] = (own.rolling(64, min_periods=32).cov(rr) / rr.rolling(64, min_periods=32).var().replace(0, np.nan)).to_numpy()
    return pd.DataFrame(cols).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- 6 volatility cone
def vol_frame(lr: pd.Series) -> pd.DataFrame:
    r2 = lr ** 2
    rv = {h: np.sqrt(r2.rolling(h, min_periods=h).mean()) for h in VC_HS}
    out = {f"vc_pct_{h}": _rank_pct(rv[h].to_numpy(float), VC_WINDOW, VC_MIN_W) for h in VC_HS}
    out["vc_term_slope"] = np.log(rv[256] / rv[16]).replace([np.inf, -np.inf], np.nan).to_numpy()
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- 7 liquidity and spread cost (OHLCV estimates)
def liquidity_frame(df: pd.DataFrame, sig: pd.Series, H: int, cost_bps: float) -> pd.DataFrame:
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    k = 3 - 2 * np.sqrt(2)
    beta = np.log(h / l) ** 2 + np.log(h.shift() / l.shift()) ** 2
    gamma = np.log(np.maximum(h, h.shift()) / np.minimum(l, l.shift())) ** 2
    a = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    s = (2 * (np.exp(a) - 1) / (1 + np.exp(a))).clip(lower=0)               # Corwin-Schultz (2012) high-low spread, fraction of price
    dv = (c * v).where(v > 0)
    amihud = (np.log(c).diff().abs() / dv).ewm(span=20, min_periods=10, adjust=False).mean()
    ldv = np.log(dv)
    width = BARRIER_K * sig * np.sqrt(H)
    return pd.DataFrame({
        "liq_cs_spread": (s.ewm(span=20, min_periods=10, adjust=False).mean() * 1e4).to_numpy(),
        "liq_amihud": np.log10(amihud.replace(0, np.nan)).to_numpy(),
        "liq_dvol_z": ((ldv - ldv.rolling(64, min_periods=32).mean()) / ldv.rolling(64, min_periods=32).std()).to_numpy(),
        "liq_cost_r": (cost_bps / 1e4 / width).to_numpy()}).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- 27-32 (evo-15)
def _ny_local(mid: np.ndarray, shift_h: int = 0) -> pd.DatetimeIndex:
    ny = pd.to_datetime(np.asarray(mid, float), unit="s", utc=True).tz_convert("America/New_York")
    return ny + pd.Timedelta(hours=shift_h) if shift_h else ny


def breadth_frame(end: np.ndarray, ctx: pd.DataFrame | None, group: str | None, instrument: str | None) -> pd.DataFrame:
    """Share of the STORED equity universe above its 50/200-day mean etc. (context27.breadth_context). Equities only: the other groups are NaN."""
    from atlas.ai.ml.directional.context27 import asof_join, is_stock_like
    cols = LAYER_FEATURES["breadth"]
    if group != "equity" or not (instrument and is_stock_like(instrument)):
        return pd.DataFrame({c: np.full(len(end), np.nan) for c in cols})
    return asof_join(end, ctx, cols)


def implied_vol_frame(end: np.ndarray, ctx: pd.DataFrame | None) -> pd.DataFrame:
    from atlas.ai.ml.directional.context27 import asof_join
    return asof_join(end, ctx, LAYER_FEATURES["implied_vol"])


def usd_frame(end: np.ndarray, proxy: tuple[np.ndarray, np.ndarray] | None, instrument: str | None) -> pd.DataFrame:
    cols = LAYER_FEATURES["usd_proxy"]
    nan = pd.DataFrame({c: np.full(len(end), np.nan) for c in cols})
    if proxy is None or instrument in PROXY_EXCLUDES["USD_PROXY"]:
        return nan
    left = pd.DataFrame({"end": np.asarray(end, np.int64)})
    right = pd.DataFrame({"end": np.asarray(proxy[0], np.int64), "u": np.asarray(proxy[1], float)}).sort_values("end")
    lu = np.log(pd.merge_asof(left, right, on="end", direction="backward")["u"])
    z = (lu - lu.rolling(64, min_periods=32).mean()) / lu.rolling(64, min_periods=32).std()
    return pd.DataFrame({"usd_ret_16": lu - lu.shift(16), "usd_ret_64": lu - lu.shift(64), "usd_z_64": z}).replace([np.inf, -np.inf], np.nan)


def seasonality_frame(start: np.ndarray, end: np.ndarray, group: str | None) -> pd.DataFrame:
    """Calendar position of the bar: business-day-of-month fraction, turn-of-month window (last business day and first 3), weekday as sin/cos,
    last-5-business-days-of-a-quarter. Crypto uses the UTC calendar, everything else New York. Pure calendar arithmetic: no lookahead, no fitting."""
    mid = (np.asarray(start, float) + np.asarray(end, float)) / 2.0
    loc = (pd.to_datetime(mid, unit="s", utc=True) if group == "crypto" else _ny_local(mid)).tz_localize(None)
    d = loc.normalize().to_numpy("datetime64[D]")
    m0 = d.astype("datetime64[M]").astype("datetime64[D]")
    m1 = (d.astype("datetime64[M]") + np.timedelta64(1, "M")).astype("datetime64[D]")
    idx = np.busday_count(m0, d + np.timedelta64(1, "D")).astype(float)                 # business days elapsed in the month, inclusive of today
    tot = np.busday_count(m0, m1).astype(float)
    idx = np.where(np.is_busday(d), idx, np.maximum(idx, 1.0))     # weekends count as the last business day passed
    to_end = tot - idx
    dow = loc.day_of_week.to_numpy().astype(float)
    month = loc.month.to_numpy()
    return pd.DataFrame({
        "sea_bdom_frac": np.where(tot > 1, (idx - 1) / np.maximum(tot - 1, 1), np.nan),
        "sea_turn_of_month": ((to_end == 0) | (idx <= 3)).astype(float),
        "sea_dow_sin": np.sin(2 * np.pi * dow / 7.0), "sea_dow_cos": np.cos(2 * np.pi * dow / 7.0),
        "sea_qtr_end": (np.isin(month, (3, 6, 9, 12)) & (to_end <= 4)).astype(float)})


def session_frame(df: pd.DataFrame, interval: str, group: str | None, instrument: str | None) -> pd.DataFrame:
    """Overnight-vs-intraday and opening-gap features for session markets (equity, gold). A 'day' is the session day; a gap is
    open(first bar of the day) vs close(last bar of the previous day), both known by the time the first bar OPENS, so every row may use today's gap
    but only COMPLETED days' close-to-open / open-to-close history. NaN for crypto and FX (no session gap)."""
    names = LAYER_FEATURES["overnight_intraday"] + LAYER_FEATURES["gap_stats"]
    n = len(df)
    nan = pd.DataFrame({c: np.full(n, np.nan) for c in names})
    if group not in SESSION_SHIFT_H or "_" in (instrument or "") or n < 40:
        return nan
    mid = ((df["start"].to_numpy(float) + df["end"].to_numpy(float)) / 2.0)
    loc = _ny_local(mid, SESSION_SHIFT_H[group])
    key = pd.Series((loc.year * 10000 + loc.month * 100 + loc.day).to_numpy(np.int64))
    new_day = key.ne(key.shift()).to_numpy()
    di = np.cumsum(new_day) - 1                                    # day ordinal per bar (bars are time-ordered)
    g = df.assign(di=di).groupby("di", sort=True)
    o_d, c_d, h_d, l_d = g["open"].first(), g["close"].last(), g["high"].max(), g["low"].min()
    if len(o_d) < 40:
        return nan
    pc = c_d.shift(1)
    gap = np.log(o_d / pc)
    idr = np.log(c_d / o_d)
    gsd = gap.shift(1).ewm(span=60, min_periods=20, adjust=False).std()
    sd_cc = np.log(c_d / pc).rolling(60, min_periods=30).std().shift(1)
    atr = ((h_d - l_d) / pc).rolling(14, min_periods=10).mean().shift(1)
    filled_day = pd.Series(np.where(gap > 0, (l_d <= pc), np.where(gap < 0, (h_d >= pc), np.nan)), index=o_d.index).where(gap.abs() > 0)
    done = 0 if interval in ("1d", "1D", "1w") else 1             # intraday rows must not see today's unfinished close
    on20 = (gap.rolling(20, min_periods=10).mean() / sd_cc).shift(done)
    id20 = (idr.rolling(20, min_periods=10).mean() / sd_cc).shift(done)
    fr20 = filled_day.rolling(20, min_periods=8).mean().shift(done)
    d_gz = (gap / gsd).replace([np.inf, -np.inf], np.nan)
    d_size = (gap / atr).replace([np.inf, -np.inf], np.nan)
    # running 'gap filled' flag through the day, using only bars up to and including this one
    pcb = pc.reindex(di).to_numpy()
    gb = gap.reindex(di).to_numpy()
    run_lo = df.assign(di=di).groupby("di")["low"].cummin().to_numpy()
    run_hi = df.assign(di=di).groupby("di")["high"].cummax().to_numpy()
    filled = np.where(gb > 0, run_lo <= pcb, np.where(gb < 0, run_hi >= pcb, np.nan)).astype(float)
    filled = np.where(np.isfinite(gb) & (gb != 0), filled, np.nan)
    take = lambda s: s.reindex(di).to_numpy()
    return pd.DataFrame({"oi_gap_z": take(d_gz), "oi_on_20": take(on20), "oi_id_20": take(id20), "oi_spread_20": take(on20) - take(id20),
                         "gp_size_atr": take(d_size), "gp_filled": filled, "gp_fill_rate_20": take(fr20)}).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- 8 model disagreement (rule-based expert ensemble)
def expert_votes(df: pd.DataFrame, sig: pd.Series) -> pd.DataFrame:
    """Six fixed, untrained experts voting {-1,0,+1}. Dispersion of a *learned* ensemble is a model output and so cannot be a training
    feature without nested out-of-sample stacking; dispersion of fixed rules is, and it is what the model sees."""
    c = df["close"]
    lc = np.log(c)
    z = lambda k: (lc - lc.shift(k)) / (sig * np.sqrt(k))
    hi, lo = df["high"].rolling(64, min_periods=64).max(), df["low"].rolling(64, min_periods=64).min()
    pos = (c - lo) / (hi - lo).replace(0, np.nan)
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    e20, e50 = c.ewm(span=20, adjust=False, min_periods=20).mean(), c.ewm(span=50, adjust=False, min_periods=50).mean()
    v = pd.DataFrame({"mom_4": np.sign(z(4)), "mom_16": np.sign(z(16)), "mom_64": np.sign(z(64)), "rev_pos_64": -np.sign(pos - 0.5),
                      "ema_cross": np.sign(e20 - e50), "rsi_rev": -np.sign(rsi - 50)})
    return v


def disagreement_frame(votes: pd.DataFrame) -> pd.DataFrame:
    ok = votes.notna().all(axis=1)
    up, dn = (votes > 0).sum(axis=1), (votes < 0).sum(axis=1)
    return pd.DataFrame({"dis_net_vote": votes.mean(axis=1).where(ok), "dis_vote_std": votes.std(axis=1, ddof=0).where(ok),
                         "dis_agree_frac": (np.maximum(up, dn) / len(votes.columns)).where(ok)})


# ----------------------------------------------------------------------------- 9 account-aware size (account-agnostic, bar-derived part only)
def account_frame(sig: pd.Series, H: int) -> pd.DataFrame:
    """Stop distance as a fraction of price and the notional/equity multiple that risks 1% of equity at that stop.
    The snapshot itself (equity, buying power, minimum order) is NOT here: a snapshot has no history, so training on it would
    mean learning today's account for every past bar. It stays an inference-time read-only context (live.account_context)."""
    stop = BARRIER_K * sig * np.sqrt(H)
    return pd.DataFrame({"acct_stop_frac": stop.to_numpy(), "acct_notional_per_1pct_risk": np.minimum(0.01 / stop, 50.0).to_numpy()}).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- 10 drift alert
def drift_frame(df: pd.DataFrame, lr: pd.Series) -> pd.DataFrame:
    s32 = lr.rolling(32, min_periods=32).std()
    ref = lr.shift(32).rolling(256, min_periods=128)
    m64 = lr.rolling(64, min_periods=64).mean()
    ref64 = lr.shift(64).rolling(256, min_periods=128)
    tr = (df["high"] - df["low"]) / df["close"]
    return pd.DataFrame({
        "dr_vol_ratio": np.log(s32 / ref.std()).to_numpy(),
        "dr_mean_shift_z": ((m64 - ref64.mean()) / (ref64.std() / np.sqrt(64))).to_numpy(),
        "dr_range_ratio": np.log(tr.rolling(64, min_periods=64).mean() / tr.shift(64).rolling(256, min_periods=128).mean()).to_numpy()}).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- existing-layer gaps
def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def anchored_vwap_causal(df: pd.DataFrame, n: int = 5) -> np.ndarray:
    """VWAP accumulated from the latest swing pivot that is CONFIRMED by bar i (pivot p is known at p+n). Matches the chart's anchor rule."""
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    N = len(df)
    ph = pd.Series(h)
    is_hi = (ph > ph.shift(1).rolling(n).max()) & (ph >= ph.shift(-1).rolling(n).max().shift(-(n - 1)))
    pl = pd.Series(l)
    is_lo = (pl < pl.shift(1).rolling(n).min()) & (pl <= pl.shift(-1).rolling(n).min().shift(-(n - 1)))
    piv = np.flatnonzero((is_hi | is_lo).to_numpy())
    anchor = np.full(N, -1)
    for p in piv:
        if p + n < N:
            anchor[p + n] = p
    anchor = np.maximum.accumulate(anchor)
    tp = (df["high"] + df["low"] + df["close"]).to_numpy(float) / 3
    v = df["volume"].to_numpy(float)
    cpv, cv = np.cumsum(tp * v), np.cumsum(v)
    a = np.maximum(anchor - 1, 0)
    num = cpv - np.where(anchor >= 1, cpv[a], 0.0)
    den = cv - np.where(anchor >= 1, cv[a], 0.0)
    return np.where((anchor >= 0) & (den > 0), num / np.where(den > 0, den, 1), np.nan)


def volume_profile_levels(df: pd.DataFrame, window: int = VP_WINDOW, bins: int = VP_BINS, step: int = VP_STEP) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """POC / value-area low / high of the trailing ``window`` bars, recomputed every ``step`` bars and held (stale by < step bars, never ahead)."""
    N = len(df)
    poc, val, vah = (np.full(N, np.nan) for _ in range(3))
    tp = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy(float)
    v = df["volume"].to_numpy(float)
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    for i in range(window - 1, N, step):
        s = slice(i - window + 1, i + 1)
        if v[s].sum() <= 0:
            continue
        top, bot = hi[s].max(), lo[s].min()
        if top <= bot:
            continue
        hist, edges = np.histogram(tp[s], bins=bins, range=(bot, top), weights=v[s])
        k = int(hist.argmax())
        l_, r_, tot = k, k, hist[k]
        while tot < 0.7 * hist.sum() and (l_ > 0 or r_ < bins - 1):
            lv = hist[l_ - 1] if l_ > 0 else -1
            rv = hist[r_ + 1] if r_ < bins - 1 else -1
            if lv >= rv:
                l_ -= 1; tot += hist[l_]
            else:
                r_ += 1; tot += hist[r_]
        end = min(i + step, N)
        poc[i:end], val[i:end], vah[i:end] = (edges[k] + edges[k + 1]) / 2, edges[l_], edges[r_ + 1]
    return poc, val, vah


def gaps_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    c, atr = df["close"], _atr(df)
    av = anchored_vwap_causal(df)
    poc, val, vah = volume_profile_levels(df)
    day = (df["end"].to_numpy(np.int64) - 1) // 86400
    if interval in ("1d", "1D", "1w"):
        pdpos = np.full(len(df), np.nan)
    else:
        g = pd.DataFrame({"day": day, "high": df["high"], "low": df["low"]})
        dh, dl = g.groupby("day")["high"].max(), g.groupby("day")["low"].min()
        days = dh.index.to_numpy()
        pos = np.searchsorted(days, day, side="left") - 1                 # previous trading day present in the data
        ok = pos >= 0
        ph, pl_ = np.where(ok, dh.to_numpy()[np.maximum(pos, 0)], np.nan), np.where(ok, dl.to_numpy()[np.maximum(pos, 0)], np.nan)
        pdpos = (c.to_numpy() - pl_) / np.where(ph - pl_ > 0, ph - pl_, np.nan)
    return pd.DataFrame({"ex_avwap_dist_atr": ((c - av) / atr).to_numpy(), "ex_vp_poc_dist_atr": ((c - poc) / atr).to_numpy(),
                         "ex_vp_va_pos": ((c.to_numpy() - val) / np.where(vah - val > 0, vah - val, np.nan)), "ex_pd_range_pos": pdpos}).replace([np.inf, -np.inf], np.nan)


# ----------------------------------------------------------------------------- the whole frame
def layer_features(bars: Sequence[Bar], interval: str, group: str | None, instrument: str | None, horizon: int, cost_bps: float,
                   corr_refs: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None,
                   events: Sequence[float] | None = None, news: Mapping | None = None, extra: Mapping | None = None) -> pd.DataFrame:
    """Frame with LAYER_FEATURE_NAMES columns, row-aligned to ``bars``. Row i depends only on bars[0..i] (+ ref bars ending <= bars[i].end)."""
    df = pd.DataFrame({"start": [b.start for b in bars], "end": [b.end for b in bars], "open": [b.open for b in bars], "high": [b.high for b in bars],
                       "low": [b.low for b in bars], "close": [b.close for b in bars], "volume": [b.volume for b in bars]})
    c = df["close"]
    lr = np.log(c).diff()
    sig = _sigma(lr)
    end = df["end"].to_numpy(np.int64)
    parts = [conformal_band_frame(c, sig, horizon), mtf_frame(c, sig), event_frame(end, events), clock_frame(end),
             corr_frame(end, c, role_refs(corr_refs or {}, instrument)),
             vol_frame(lr), liquidity_frame(df, sig, horizon, cost_bps), disagreement_frame(expert_votes(df, sig)), account_frame(sig, horizon),
             drift_frame(df, lr), gaps_frame(df, interval), news_frame(end, news),
             breadth_frame(end, (extra or {}).get("breadth"), group, instrument), session_frame(df, interval, group, instrument),
             seasonality_frame(df["start"].to_numpy(), df["end"].to_numpy(), group), implied_vol_frame(end, (extra or {}).get("vix")),
             usd_frame(end, (corr_refs or {}).get("USD_PROXY"), instrument)]
    out = pd.concat([p.reset_index(drop=True) for p in parts], axis=1)
    return out.reindex(columns=list(LAYER_FEATURE_NAMES)).replace([np.inf, -np.inf], np.nan)


def coverage(f: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    """Per layer: finite fraction of rows, per column. A group that is entirely NaN is reported, not hidden."""
    out = {}
    for layer, cols in LAYER_FEATURES.items():
        fr = {c: float(f[c].notna().mean()) if c in f and len(f) else 0.0 for c in cols}
        out[layer] = {"n_features": len(cols), "n_all_nan": sum(1 for v in fr.values() if v == 0.0), "min_finite_frac": min(fr.values()), "finite_frac": fr}
    return out
