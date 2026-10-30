"""evo-17: multi-horizon research ensemble. Synthetic data only; checks leakage-free targets, conformal coverage, live weights, the gate, and honesty."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from atlas.ai.prediction import horizons as HZ
from atlas.ai.prediction import nowcast as NC
from atlas.features.price_action.bars import Bar

T0 = 1_700_000_000


def _bars(n, dur=300, vol=0.002, seed=1, px=100.0, ar=0.0):
    rng = np.random.default_rng(seed)
    out, c, prev = [], px, 0.0
    for k in range(n):
        r = ar * prev + rng.normal(0, vol)
        o, c = c, c * math.exp(r)
        prev = r
        out.append(Bar(T0 + k * dur, dur, o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, 100.0 + rng.uniform(0, 5)))
    return out


@pytest.fixture()
def ledger(tmp_path):
    p = str(tmp_path / "hz.sqlite")
    HZ.reset(p)
    return p


def test_target_is_next_bar_return_and_features_do_not_see_it():
    bars = _bars(900)
    df = HZ.make_xy(bars, "5m", "crypto", "BTCUSDT")
    assert df is not None and len(df) > 400
    c = np.array([b.close for b in bars])
    i = HZ.WARMUP + 10
    row = df.iloc[10]
    assert row["__y"] == pytest.approx(math.log(c[i + 1] / c[i]))
    # changing the NEXT bar must not change the features at bar i
    bars2 = list(bars)
    b = bars2[i + 1]
    bars2[i + 1] = Bar(b.start, b.duration, b.open, b.high * 1.5, b.low, b.close * 1.4, b.volume)
    a2 = HZ.make_xy(bars2, "5m", "crypto", "BTCUSDT")
    feats = [c_ for c_ in df.columns if not c_.startswith("__")]
    pd.testing.assert_series_equal(df.iloc[10][feats], a2.iloc[10][feats], check_names=False)


def test_train_pool_is_research_labelled_conformal_and_persisted(tmp_path):
    frames = [HZ.make_xy(_bars(1500, seed=s, ar=0.15), "5m", "crypto", f"X{s}") for s in (1, 2, 3)]
    rows = pd.concat([f for f in frames if f is not None], ignore_index=True)
    r = HZ.train_pool(rows, "crypto", "5m", root=tmp_path)
    assert r["status"] == "ok" and r["execution_permission"] == "none" and r["label"] == "research / below gate"
    m = r["metrics_oos"]
    assert m["lgbm"]["status"] == "ok" and m["naive"]["status"] == "ok" and m["prophet"]["status"] == "unavailable"
    for name in ("lgbm", "naive"):
        assert 0.70 <= m[name]["coverage_80"] <= 0.92, (name, m[name])      # split-conformal on a chronological hold-out
    assert r["layers_total"] >= 18 and (tmp_path / "crypto-5m" / "model.pkl").exists()
    man, b = HZ.load_bundle("crypto", "5m", tmp_path)
    assert man["n_features"] == len(b["features"])
    mem = HZ.members_for(_bars(700, seed=9), "5m", "crypto", "X9", "5m", b)
    assert {"naive", "lgbm"} <= set(mem) <= {"naive", "lgbm", "xgb"}   # xgb only where the package is installed; never prophet
    for v in mem.values():
        assert v["q"][0] <= v["q"][1] <= v["q"][2] and v["lo"] < v["hi"]   # CQR may shrink as well as widen the band


def test_too_few_rows_is_reported_not_trained(tmp_path):
    r = HZ.train_pool(pd.DataFrame({"__t": range(10), "__sigma": 1.0, "__y": 0.0, "__inst": "A", "f": 1.0}), "crypto", "1m", root=tmp_path)
    assert r["status"] == "insufficient_rows" and not (tmp_path / "crypto-1m").exists()


def _score(path, pool, h, model, pins, covered=1):
    c = HZ._conn(path)
    for i, p in enumerate(pins):
        c.execute("INSERT INTO hz_member VALUES(?,?,?,?,?,?,?,?,?)", (pool, h, model, "S", i, i, p, covered, 1))
    c.commit()


def test_weights_prior_then_live_pinball_with_naive_floor(ledger):
    use = ["lgbm", "naive"]
    w0 = HZ.weights_for("crypto", "5m", use, ledger)
    assert w0["weights"] == {"lgbm": 0.5, "naive": 0.5} and w0["basis"].startswith("prior")
    _score(ledger, "crypto", "5m", "lgbm", [0.0010] * 40)
    _score(ledger, "crypto", "5m", "naive", [0.0020] * 40)
    w1 = HZ.weights_for("crypto", "5m", use, ledger)
    assert w1["basis"] == "live_pinball" and w1["weights"]["lgbm"] > w1["weights"]["naive"] and sum(w1["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert w1["weights"]["lgbm"] == pytest.approx(0.8, abs=0.01)           # (1/1)^2 vs (1/2)^2
    _score(ledger, "equity", "1d", "lgbm", [0.0001] * 40)
    _score(ledger, "equity", "1d", "naive", [0.0100] * 40)
    assert HZ.weights_for("equity", "1d", use, ledger)["weights"]["naive"] == pytest.approx(0.10, abs=1e-3)
    assert HZ.weights_for("equity", "1d", ["naive"], ledger)["weights"] == {"naive": 1.0}


def test_issue_score_cycle_with_naive_only_and_honest_live_stats(ledger):
    bars = _bars(300, dur=60, px=100.0)
    now = bars[-1].start + 60 + 5
    assert HZ.issue_one("BTCUSDT", "1m", bars, "crypto", now, ledger, root="/nonexistent") == "issued_naive_only"
    assert HZ.issue_one("BTCUSDT", "1m", bars, "crypto", now, ledger, root="/nonexistent") == "already_issued"
    be = bars[-1].start + 60
    seen = {}
    def real(sym, iv, start):
        seen["k"] = (sym, iv, start)
        return bars[-1].close * math.exp(0.0003)
    early = HZ.score_due(real, now, ledger)
    assert early["scored"] == 0                                              # the target bar has not ended
    res = HZ.score_due(real, be + 61, ledger)
    assert res["scored"] == 1 and seen["k"] == ("BTCUSDT", "1m", be)
    lt = HZ.latest("BTCUSDT", be + 61, ledger, pool="crypto")
    one = next(r for r in lt["horizons"] if r["h"] == "1m")
    assert one["status"] == "ok" and one["execution_permission"] == "none" and one["live"]["asset"]["n"] == 1 and one["live"]["asset"]["hit_rate"] is None  # naive has no direction
    assert one["applied"] is False and one["weights"]["weights"] == {"naive": 1.0}
    five = next(r for r in lt["horizons"] if r["h"] == "5m")
    assert five["status"] == "no_bars_at_interval" and "nothing is invented" in five["reason"]
    assert lt["models"]["prophet"]["available"] is False


def test_unscored_rows_wait_for_the_real_bar_and_expire(ledger):
    bars = _bars(300, dur=60)
    now = bars[-1].start + 65
    HZ.issue_one("ETHUSDT", "1m", bars, "crypto", now, ledger, root="/nonexistent")
    assert HZ.score_due(lambda *a: None, now + 200, ledger)["waiting_for_real_bar"] == 1
    assert HZ.score_due(lambda *a: None, now + 15 * 86400, ledger)["expired"] == 1


def _hz_row(h, applied, base_px=100.0, med=101.0, target_end=0):
    return {"h": h, "status": "ok", "applied": applied, "target_end": target_end, "base_px": base_px, "median": med}


def test_gate_requires_n_and_beating_naive_then_path_is_shifted_not_widened(ledger):
    _score(ledger, "crypto", "5m", "naive", [0.0020] * 150)
    c = HZ._conn(ledger)
    for i in range(150):
        c.execute("INSERT INTO hz_scored VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("S", "5m", i, i, "crypto", 0, 0, 0, 0, 1, 1, 0.0010))
    c.commit()
    assert HZ.gate("crypto", "5m", ledger)["applied"] is True
    assert HZ.gate("crypto", "1m", ledger)["applied"] is False                # no live record: not applied
    t0 = 1_000_000
    nc = {"status": "ok", "anchor": {"t": t0}, "path": [{"t": t0 + 60 * k, "t_end": t0 + 60 * (k + 1), "mid": 100.0, "lo": 99.0, "hi": 101.0} for k in range(10)]}
    used = HZ.apply_to_path(nc, {"horizons": [_hz_row("5m", True, med=100.5, target_end=t0 + 300), _hz_row("15m", False, med=130.0, target_end=t0 + 900)]})
    assert used == ["5m"] and nc["ensemble_applied"] == ["5m"]
    p = nc["path"]
    assert p[0]["mid"] > 100.0 and p[4]["mid"] == pytest.approx(100.5, rel=1e-6) and p[9]["mid"] == pytest.approx(100.5, rel=1e-6)
    assert (p[9]["hi"] - p[9]["lo"]) / p[9]["mid"] == pytest.approx(2.0 / 100.0, rel=1e-6)   # the band keeps its width
    nc2 = {"status": "ok", "anchor": {"t": t0}, "path": [{"t": t0, "t_end": t0 + 60, "mid": 100.0, "lo": 99.0, "hi": 101.0}]}
    assert HZ.apply_to_path(nc2, {"horizons": [_hz_row("5m", False)]}) == [] and nc2["path"][0]["mid"] == 100.0


def test_status_lists_every_pool_and_horizon_with_weights_and_prophet_unavailable(ledger, tmp_path):
    _score(ledger, "crypto", "1m", "naive", [0.002] * 40)
    st = HZ.status(ledger, tmp_path)
    assert len(st["cells"]) == 6 * 5 and st["execution_permission"] == "none" and st["models"]["prophet"]["available"] is False
    c = next(x for x in st["cells"] if x["pool"] == "crypto" and x["h"] == "1m")
    assert c["trained"] is False and c["weights"] == {"naive": 1.0} and c["members"]["naive"]["live"]["n"] == 40 and c["gate"]["applied"] is False
    assert all(x["execution_permission"] == "none" for x in st["cells"])


def test_5m_is_derived_from_real_1m_bars_only(tmp_path):
    from atlas.feeds.core import FeedBar
    from atlas.feeds.feed import AtlasFeed
    from atlas.feeds.store import FeedStore
    f = AtlasFeed(FeedStore(":memory:"))
    start = (T0 // 300) * 300
    f.store.ingest([FeedBar("BTCUSDT", "1m", start + 60 * k, 1.0 + k, 2.0 + k, 0.5 + k, 1.5 + k, 10.0, "coinbase", T0, True) for k in range(15)])
    b5 = HZ.load_bars(f, "BTCUSDT", "5m")
    assert len(b5) == 3 and b5[0].open == 1.0 and b5[0].close == 5.5 and b5[0].high == 6.0 and b5[0].low == 0.5 and b5[0].duration == 300


def test_endpoints_never_fail_the_nowcast_and_clock_tick_reports_horizons(monkeypatch, ledger):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from atlas.ai.prediction import clock as CK
    from atlas.api import prediction_api as A
    from atlas.feeds.core import FeedBar
    from atlas.feeds.feed import AtlasFeed
    from atlas.feeds.store import FeedStore
    f = AtlasFeed(FeedStore(":memory:"))
    now = 1_772_551_800.0
    rows, c = [], 100.0
    rng = np.random.default_rng(2)
    for k in range(600):
        o, c = c, c * math.exp(rng.normal(0, 0.001))
        rows.append(FeedBar("BTCUSDT", "1m", int(now - (600 - k) * 60), o, max(o, c), min(o, c), c, 5.0, "coinbase", now, True))
    f.store.ingest(rows)
    monkeypatch.setattr(A, "_feed", lambda: f)
    app = FastAPI()
    app.include_router(A.router)
    cl = TestClient(app)
    f.store.ingest([FeedBar("SPY", "1d", int(now) // 86400 * 86400 - (400 - k) * 86400, 500.0 + k, 502.0 + k, 499.0 + k, 501.0 + k, 1e6, "polygon", now, True) for k in range(400)])
    r = cl.get("/api/ai/predictions/nowcast", params={"symbol": "SPY", "interval": "1d", "horizon": 5}).json()
    assert r["status"] == "ok" and r["horizons"]["execution_permission"] == "none" and r.get("ensemble_applied", []) == []
    s = cl.get("/api/ai/predictions/horizons/status").json()
    assert len(s["cells"]) == 30
    assert cl.get("/api/ai/predictions/horizons", params={"symbol": "BTCUSDT"}).json()["symbol"] == "BTCUSDT"
    t = CK.tick(f, now=now + 5, symbols=["BTCUSDT"])
    assert t["horizons"]["statuses"].get("issued_naive_only", 0) + t["horizons"]["statuses"].get("issued", 0) >= 1 and t["horizons"]["errors"] == 0
    assert HZ.latest("BTCUSDT", now + 6, pool="crypto")["horizons"][0]["status"] == "ok"
