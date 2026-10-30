"""evo-20: rolling walk-forward retraining (no leakage, champion/challenger) and the anchored 1m/5m forecast for assets without intraday bars."""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import pytest

from atlas.ai.prediction import horizons as HZ, nowcast as NC, nowcast_log as NL, roll as RL
from atlas.feeds.core import FeedBar
from atlas.feeds.feed import AtlasFeed
from atlas.feeds.store import FeedStore
from atlas.features.price_action.bars import Bar

T0 = 1_700_000_000


def _bars(n, dur=300, vol=0.002, seed=1, px=100.0, ar=0.15, t0=T0):
    rng = np.random.default_rng(seed)
    out, c, prev = [], px, 0.0
    for k in range(n):
        r = ar * prev + rng.normal(0, vol)
        o, c = c, c * math.exp(r)
        prev = r
        out.append(Bar(t0 + k * dur, dur, o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, 100.0 + rng.uniform(0, 5)))
    return out


def _rows(n, seeds=(1, 2, 3), t0=T0):
    fr = [HZ.make_xy(_bars(n, seed=s, t0=t0), "5m", "crypto", f"X{s}") for s in seeds]
    return pd.concat([f for f in fr if f is not None], ignore_index=True), [f"X{s}" for s in seeds]


def test_manifest_records_data_end_and_split_matches_trainer(tmp_path):
    rows, used = _rows(1500)
    r = HZ.train_pool(rows, "crypto", "5m", root=tmp_path, instruments=used)
    assert r["status"] == "ok" and r["data_end"] == int(rows["__t"].max()) and r["test_start"] > r["data_start"]
    sl = HZ.split_slices(len(rows))
    assert sl["cal"].start == int(len(rows) * 0.6) + 2 and sl["test"].stop == len(rows)


def test_first_cycle_promotes_then_fresh_bundle_is_skipped(tmp_path):
    rows, used = _rows(1500)
    a = RL.retrain_cell("crypto", "5m", rows, used, now=time.time(), root=tmp_path)
    assert a["decision"] == "promote" and a["reason"] == "no incumbent bundle"
    man, b = HZ.load_bundle("crypto", "5m", tmp_path)
    assert man is not None and b is not None
    b2 = RL.retrain_cell("crypto", "5m", rows, used, now=time.time() + 60, root=tmp_path)
    assert b2["decision"] == "skip"           # no new rows and the bundle is minutes old


def test_comparison_window_is_strictly_after_incumbent_data_and_unseen_by_challenger(tmp_path):
    rows, used = _rows(1500)
    RL.retrain_cell("crypto", "5m", rows, used, now=time.time() - 40 * 3600, root=tmp_path)
    man, inc = HZ.load_bundle("crypto", "5m", tmp_path)
    de = man["data_end"]
    # 1500 more bars arrive after the incumbent was trained
    rows2, _ = _rows(3000)
    srt = rows2.sort_values("__t", kind="stable").reset_index(drop=True)
    r = HZ.train_pool(rows2, "crypto", "5m", root=tmp_path / "c", instruments=used)
    _, chal = HZ.load_bundle("crypto", "5m", tmp_path / "c")
    sl = HZ.split_slices(len(srt))["test"]
    held = srt.iloc[sl]
    held = held[held["__t"] > de].iloc[RL.PURGE_ROWS:]
    cmp = RL.compare(inc, chal, srt, de, sl)
    assert cmp["n_eval"] == len(held) and cmp["n_eval"] > 0
    assert held["__t"].min() > de                      # incumbent never saw these bars
    assert held["__t"].min() >= srt.iloc[sl]["__t"].min()   # and they are inside the challenger's hold-out, which it never trained on
    assert cmp["challenger_pin_bps"] is not None and cmp["incumbent_pin_bps"] is not None


def test_decide_rules():
    c = {"n_eval": 500, "challenger_pin_bps": 3.9, "incumbent_pin_bps": 4.0, "model": "lgbm"}
    assert RL.decide(c, True, 100, 1000)[0] == "promote"
    assert RL.decide({**c, "challenger_pin_bps": 4.2}, True, 100, 1000)[0] == "keep"
    assert RL.decide({**c, "n_eval": 50}, True, 100, 1000)[0] == "keep"
    assert RL.decide({**c, "incumbent_pin_bps": None}, True, 100, 1000)[0] == "promote"
    assert RL.decide(c, False, None, 1000)[0] == "promote"


def test_keep_leaves_the_incumbent_files_untouched(tmp_path, monkeypatch):
    rows, used = _rows(1500)
    RL.retrain_cell("crypto", "5m", rows, used, now=time.time() - 40 * 3600, root=tmp_path)
    before = (tmp_path / "crypto-5m" / "model.pkl").read_bytes()
    monkeypatch.setattr(RL, "decide", lambda *a, **k: ("keep", "forced for test"))
    r = RL.retrain_cell("crypto", "5m", rows, used, now=time.time(), root=tmp_path, force=True)
    assert r["decision"] == "keep" and (tmp_path / "crypto-5m" / "model.pkl").read_bytes() == before
    assert not (tmp_path / ".cand" / "crypto-5m").exists()


# ---------------------------------------------------------------------------- anchored 1m / 5m for assets with no intraday bars
NOW = 1_772_551_800.0     # Tue 2026-03-03 10:30 New York


def _fb(inst, iv, n, last_end, vol, prov, px=100.0, seed=3):
    rng = np.random.default_rng(seed)
    d = NC.DUR[iv]
    c, out = px, []
    for k in range(n):
        o = c
        c = c * math.exp(rng.normal(0, vol))
        out.append(FeedBar(inst, iv, int(last_end - (n - k) * d), o, max(o, c) * 1.0005, min(o, c) * 0.9995, c, 100.0, prov, NOW, True))
    return out


@pytest.fixture()
def feed(tmp_path):
    NC._BARS.clear()
    NL.reset()
    HZ.reset(str(tmp_path / "hz.sqlite"))
    f = AtlasFeed(FeedStore(":memory:"))
    f.store.ingest(_fb("BTCUSDT", "1m", 1500, NOW - 60, 0.0008, "binance") + _fb("SPY", "1d", 600, NOW - 18 * 3600, 0.01, "polygon", 500.0, 7))
    return f, str(tmp_path / "hz.sqlite")


def test_asset_without_intraday_bars_gets_an_anchored_unscored_forecast_every_tick(feed, tmp_path):
    f, path = feed
    out = HZ.tick(f, NOW, symbols=["SPY"], path=path, root=tmp_path)
    assert out["anchored"]["anchored"] == 2
    lat = HZ.latest("SPY", NOW, path)
    by = {r["h"]: r for r in lat["horizons"]}
    for h in ("1m", "5m"):
        r = by[h]
        assert r["status"] == "anchored" and r["anchor"]["interval"] == "1d" and r["anchor"]["provider"] == "polygon"
        assert r["lo"] < r["median"] < r["hi"] and r["live"]["asset"]["n"] == 0 and r["execution_permission"] == "none"
        assert "unscored" in r["reason"] and "no intraday source" in r["reason"]
    # one latest row per (asset, horizon), not a growing ledger
    HZ.tick(f, NOW + 60, symbols=["SPY"], path=path, root=tmp_path)
    n = HZ._conn(path).execute("SELECT COUNT(*) FROM hz_anchor WHERE symbol='SPY'").fetchone()[0]
    assert n == 2
    # and nothing about it reached the bar store
    assert not f.store._fetchall("SELECT 1 FROM bar_revisions WHERE instrument='SPY' AND interval='1m'")


def test_stale_anchor_row_is_not_shown_as_current(feed, tmp_path):
    f, path = feed
    HZ.tick(f, NOW, symbols=["SPY"], path=path, root=tmp_path)
    assert HZ.anchored_row("SPY", "1m", NOW + 3600, path) is None


def test_asset_with_live_intraday_bars_is_scored_not_anchored(feed, tmp_path):
    f, path = feed
    out = HZ.tick(f, NOW, symbols=["BTCUSDT"], path=path, root=tmp_path)
    assert out["anchored"]["anchored"] == 0
    st = {r["h"]: r["status"] for r in HZ.latest("BTCUSDT", NOW, path)["horizons"]}
    assert st["1m"] == "ok" and st["5m"] == "ok"
