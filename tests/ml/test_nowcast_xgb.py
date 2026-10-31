"""Nowcast workers: predictions are separate, labelled, scored against real bars, and never lookahead."""
from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from atlas.ai.ml import nowcast_xgb as NX
from atlas.ai.ml import train as ML_TRAIN
from atlas.feeds.core import FeedBar
from atlas.feeds.store import FeedStore

NY = ZoneInfo("America/New_York")
THU, FRI = date(2026, 10, 29), date(2026, 10, 30)


def et(d: date, h: int, m: int = 0) -> int:
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=NY).timestamp())


def session_bars(d: date, start_px: float, seed: int, instrument="SPY", provider="polygon", receipt=None):
    rng = np.random.default_rng(seed)
    out, px = [], start_px
    for i in range(26):
        t = et(d, 9, 30) + i * 900
        nxt = px * math.exp(rng.normal(0, 0.002))
        out.append(FeedBar(instrument, "15m", t, px, max(px, nxt), min(px, nxt), nxt, 1000.0, provider, receipt or t + 900, True))
        px = nxt
    return out


def crypto_bars(start: int, end: int, instrument: str, seed: int):
    rng = np.random.default_rng(seed)
    out, px = [], 100.0
    for t in range(start // 900 * 900, end, 900):
        nxt = px * math.exp(rng.normal(0, 0.003))
        out.append(FeedBar(instrument, "15m", t, px, max(px, nxt), min(px, nxt), nxt, 5.0, "coinbase", t + 900, True))
        px = nxt
    return out


def make_feed(include_today=True, mutate_after=None):
    fs = FeedStore(":memory:")
    bars = session_bars(THU, 500.0, 1)
    fri = session_bars(FRI, bars[-1].close, 2)
    if include_today:
        bars += fri
    fs.ingest(bars)
    for i, ins in enumerate(NX.PROXY_MAJOR + NX.PROXY_ALT):
        fs.ingest(crypto_bars(et(THU, 0) - 86400, et(FRI, 20), ins, 10 + i))
    return fs, fri


def fake_predict(bundle, row):
    return {"q10": -0.002, "q50": 0.0005, "q90": 0.003, "lo": -0.0025, "hi": 0.0035, "base_q": [-0.003, 0.0, 0.003]}


def count_rows(fs):
    return fs._fetchall("SELECT COUNT(*) FROM bar_revisions", [])[0][0]


def test_gates_are_the_unchanged_training_gates():
    assert NX.GATES is ML_TRAIN.GATES
    assert ML_TRAIN.GATES["min_oos"] == 200 and ML_TRAIN.GATES["min_dsr"] == 0.95
    assert ML_TRAIN.GATES["max_pbo"] == 0.5 and ML_TRAIN.GATES["min_shadow_weeks"] == 4


def test_t_plus_1_knowledge_time_is_the_next_et_midnight():
    assert NX.known_at(THU) == et(FRI, 0)
    assert NX.known_at(date(2026, 10, 31)) == int(datetime(2026, 11, 1, tzinfo=NY).timestamp())
    assert NX.known_at(THU) > et(THU, 16)          # never known on the session day itself


def test_assert_real_labels_rejects_predictions_and_unofficial_sources():
    good = pd.DataFrame({"y": [0.1], "label_source": ["real_bar"], "provider": ["polygon"]})
    NX.assert_real_labels(good)
    with pytest.raises(ValueError):
        NX.assert_real_labels(good.assign(label_source="predicted"))
    with pytest.raises(ValueError):
        NX.assert_real_labels(good.assign(provider="yahoo"))
    with pytest.raises(ValueError):
        NX.assert_real_labels(good.assign(pred_q50=0.1))
    with pytest.raises(ValueError):
        NX.assert_real_labels(good.drop(columns=["label_source"]))


def test_ledger_rejects_anything_not_flagged_predicted():
    led = NX.Ledger(":memory:")
    led.issue("stocks_15m", "SPY", et(FRI, 10), "m1", 900, 500.0, fake_predict(None, None), "research_only", et(FRI, 10))
    assert led.issued_rows()[0][-1] == 1
    with pytest.raises(sqlite3.IntegrityError):
        led._c.execute("UPDATE issued SET predicted=0")


def test_issue_then_score_against_the_real_bar_and_feed_is_untouched(monkeypatch):
    monkeypatch.setattr(NX, "predict_row", fake_predict)
    fs, fri = make_feed(include_today=False)
    led = NX.Ledger(":memory:")
    n0 = count_rows(fs)
    now = et(FRI, 10, 20)
    out = NX.issue_stock(fs, led, {"model_id": "m1", "gate_pass": True}, "stocks_15m", "SPY", now)
    assert out is not None and out["predicted"] is True and out["label"] == NX.LABEL and out["window_end"] == et(FRI, 10, 15)
    assert out["status"] != "live"                                    # nothing is promoted without the live gate
    assert count_rows(fs) == n0                                        # a prediction never enters the feed store
    assert NX.score_due(fs, led, now) == 0                             # the real bar has not arrived (T+1): nothing to score
    assert led.summary("stocks_15m")["scored"] == 0
    # the real bar arrives the next day; only then is the prediction scored
    fs.ingest(fri)
    anchor = led.issued_rows()[0][6]
    assert NX.score_due(fs, led, et(date(2026, 10, 31), 2)) == 1
    real = next(b for b in fri if b.event_time + 900 == out["window_end"])
    s = led.summary("stocks_15m")
    assert s["scored"] == 1 and s["live_gate_pass"] is False
    assert math.isclose(led._c.execute("SELECT actual FROM scored").fetchone()[0], math.log(real.close / anchor))
    assert NX.score_due(fs, led, et(date(2026, 10, 31), 3)) == 0     # idempotent


def test_no_prediction_outside_rth_or_before_the_previous_session_is_known(monkeypatch):
    monkeypatch.setattr(NX, "predict_row", fake_predict)
    fs, _ = make_feed(include_today=False)
    led = NX.Ledger(":memory:")
    assert NX.issue_stock(fs, led, {"model_id": "m"}, "stocks_15m", "SPY", et(FRI, 8)) is None
    assert NX.issue_stock(fs, led, {"model_id": "m"}, "stocks_15m", "SPY", et(FRI, 17)) is None
    assert NX.issue_stock(fs, led, {"model_id": "m"}, "stocks_15m", "SPY", et(date(2026, 10, 31), 11)) is None   # Saturday
    # the previous session (Thursday) is only known from Friday 00:00 ET: a decision before that has nothing to stand on
    assert NX.issue_stock(fs, led, {"model_id": "m"}, "stocks_15m", "SPY", et(THU, 10, 20)) is None
    assert led.issued_rows() == []


def test_sample_features_never_depend_on_data_after_the_window():
    """End to end: build training rows from the full feed and from a feed truncated at window T; the row at T must be identical."""
    fs_full, fri = make_feed(include_today=True)
    full = NX.stock_samples(fs_full, "SPY", "stocks_15m", et(FRI, 0), et(FRI, 20))
    j = 10
    T = int(full.iloc[j]["window_end"])
    fs_cut = FeedStore(":memory:")
    fs_cut.ingest([b for b in fs_full.bars("SPY", "15m", provider="polygon") if b.event_time + 900 <= T])
    for ins in NX.PROXY_MAJOR + NX.PROXY_ALT:
        fs_cut.ingest([b for b in fs_full.bars(ins, "15m", provider="coinbase") if b.event_time + 900 <= T])
    cut = NX.stock_samples(fs_cut, "SPY", "stocks_15m", et(FRI, 0), et(FRI, 20))
    a = full[full["window_end"] == T].iloc[0]
    b = cut[cut["window_end"] == T].iloc[0]
    for f in NX.STOCK_FEATURES + ("y",):
        assert (pd.isna(a[f]) and pd.isna(b[f])) or math.isclose(a[f], b[f], rel_tol=1e-12), f
    # the label is the real bar close of the window ending at T over the previous session's last close (never a prediction)
    real = next(x for x in fri if x.event_time + 900 == T)
    assert math.isclose(a["y"], math.log(real.close / session_bars(THU, 500.0, 1)[-1].close))
    assert set(full["label_source"]) == {"real_bar"} and set(full["provider"]) == {"polygon"}
    # every row of Friday is anchored to Thursday's last REAL close (T+1 knowledge), never to a Friday value
    assert np.allclose(full["anchor"], session_bars(THU, 500.0, 1)[-1].close)


def test_proxy_levels_do_not_bridge_missing_bars():
    fs = FeedStore(":memory:")
    bars = crypto_bars(1_800_000_000, 1_800_000_000 + 8 * 900, "BTCUSDT", 3)
    fs.ingest([b for i, b in enumerate(bars) if i != 4])
    p = NX.ProxyLevels(fs, ["BTCUSDT"], 1_799_999_000, 1_800_100_000)
    missing_end = bars[4].event_time + 900
    assert math.isnan(p.ret("BTCUSDT", missing_end - 900, missing_end))
    assert not math.isnan(p.ret("BTCUSDT", bars[1].event_time + 900, bars[2].event_time + 900))


def synth_training_frame(n_days=90, seed=4):
    rng = np.random.default_rng(seed)
    rows = []
    d0 = date(2026, 1, 5)
    for di in range(n_days):
        d = (d0 + timedelta(days=di)).isoformat()
        for k in range(1, 27):
            r = {f: float(rng.normal()) for f in NX.STOCK_FEATURES}
            r.update(k=float(k), mins_in=15.0 * k, dow=float(di % 5), target="SPY", window_end=di * 86400 + k * 900, date=d, anchor=500.0,
                     y=float(rng.normal(0, 0.003)), label_source="real_bar", provider="polygon")
            rows.append(r)
    return pd.DataFrame(rows)


def test_smoke_train_reports_gate_fields_and_does_not_promote_noise(tmp_path):
    rep = NX.train_group("stocks_15m", synth_training_frame(), root=tmp_path)
    assert rep["rows"] >= NX.MIN_ROWS["stocks_15m"]
    assert rep["n_test"] >= ML_TRAIN.GATES["min_oos"]
    assert rep["gate_pass"] is False and rep["status"] == "research_only"      # random labels: no skill, must not pass
    assert rep["baseline"].startswith("same XGBoost class")
    b = NX.load_bundle("stocks_15m", tmp_path)
    assert b["model_id"] == rep["model_id"]
    row = {f: 0.0 for f in NX.STOCK_FEATURES}
    p = NX.predict_row(b, row)
    assert p["lo"] <= p["q50"] <= p["hi"]


def test_insufficient_overlap_is_reported_not_faked():
    rep = NX.train_group("stocks_1m", synth_training_frame(n_days=3), save=False)
    assert rep["status"] == "insufficient_data" and rep["gate_pass"] is False


def test_training_refuses_prediction_labels():
    bad = synth_training_frame(n_days=10).assign(label_source="predicted")
    with pytest.raises(ValueError):
        NX.train_group("stocks_15m", bad, save=False)
