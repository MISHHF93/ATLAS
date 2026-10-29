"""Setup checklist, go-live readiness (read-only) and Massive live-loop honesty. No network, no real keys."""
from __future__ import annotations

import json
import time

from atlas.feeds import AtlasFeed, FeedStore
from atlas.feeds import massive_live as ML
from atlas.integrations import checklist, golive
from atlas.integrations.registry import load_env

SECRET = "sekret-value-do-not-echo-0123456789"


def items(env, states=None):
    return checklist.build(load_env(environ=env), {} if states is None else states)   # hermetic: never read this machine's stored verification


def test_checklist_core_order_and_states():
    c = items({})
    assert [i["key"] for i in c["items"][:5]] == ["massive", "gemini", "edgar", "fred", "broker_paper"]
    assert [i["rank"] for i in c["items"]] == list(range(1, len(c["items"]) + 1))
    assert all(i["state"] == "needs_verification" for i in c["items"][:5])          # core, nothing set: it matters, so it needs action
    assert {i["state"] for i in c["items"][5:]} <= {"optional", "verified", "needs_verification"}
    assert c["paper_only"] is True and c["execution_permission"] == "none" and c["keys_set_by_atlas"] is False


def test_checklist_verified_and_failed_come_from_verification_not_from_a_key_being_present():
    st = {"polygon": {"state": "verified", "detail": "ok", "verified_at": "2026-10-29", "key_present": True}}
    c = items({"MASSIVE_API_KEY": SECRET}, st)
    assert c["items"][0]["key"] == "massive" and c["items"][0]["state"] == "verified" and c["core_verified"] >= 1
    c2 = items({"MASSIVE_API_KEY": SECRET})
    assert c2["items"][0]["state"] == "needs_verification" and c2["core_verified"] == 0   # present but unverified is not verified
    st2 = {"polygon": {"state": "failed", "detail": "HTTP 401", "key_present": True}}
    assert items({"MASSIVE_API_KEY": SECRET}, st2)["items"][0]["failed"] is True


def test_checklist_never_echoes_values():
    c = items({"MASSIVE_API_KEY": SECRET, "POLYGON_API_KEY": SECRET, "GEMINI_API_KEY": SECRET + "g", "FRED_API_KEY": SECRET + "f"})
    blob = json.dumps(c)
    assert SECRET not in blob
    assert c["secrets_echoed"] is False


def test_golive_all_pending_without_evidence_and_signoff_is_manual(tmp_path):
    class Empty:
        def weekly(self):
            return []
    r = golive.report(states={}, model_root=tmp_path, collector=Empty(), scope="test-scope")
    keys = [g["key"] for g in r["gates"]]
    assert keys == ["model_gate", "shadow_weeks", "reviewer_evidence", "broker_paper", "owner_signoff"]
    assert r["passed"] == 0 and r["total"] == 5 and r["automated_gates_pass"] is False
    assert r["gates"][-1]["state"] == "pending"
    assert r["read_only"] is True and r["execution_permission"] == "none" and r["live_endpoints"] == "refused"
    assert "config/founder/risk_policy.yaml" in r["risk_policy"]


def test_golive_signoff_never_passes_even_when_every_other_gate_does(tmp_path):
    d = tmp_path / "equity-15m"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"label": "x", "gates": [{"gate": "oos", "passed": True}, {"gate": "shadow_weeks", "passed": False}]}))

    class Weeks:
        def weekly(self):
            return [{"labelled": 5, "candidates": 9}] * 4
    st = {"oanda": {"state": "verified"}}
    r = golive.report(states=st, model_root=tmp_path, collector=Weeks(), scope="s")
    by = {g["key"]: g["state"] for g in r["gates"]}
    assert by["model_gate"] == "pass" and by["shadow_weeks"] == "pass" and by["broker_paper"] == "pass"
    assert by["owner_signoff"] == "pending" and r["passed"] < r["total"]
    assert r["execution_permission"] == "none" and r["live_endpoints"] == "refused"


def test_golive_failing_model_is_labelled_below_gate(tmp_path):
    d = tmp_path / "equity-15m"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"label": "research / below gate", "gates": [{"gate": "dsr", "passed": False}]}))
    g = golive.model_gate(tmp_path)
    assert g["state"] == "fail" and "research / below gate" in g["detail"]


def test_broker_gate_alpaca_counts_only_if_verified_and_unverified_is_not_a_pass():
    assert golive.broker_gate({"alpaca": {"state": "needs_verification"}})["state"] == "pending"
    assert golive.broker_gate({"ibkr": {"state": "verified"}})["state"] == "pass"


# ---- Massive live loop ----
def test_capability_free_is_end_of_day_and_says_no_realtime():
    cap = ML.capability({"MASSIVE_API_KEY": SECRET})
    assert cap["mode"] == "eod_lag" and cap["realtime"] is False and cap["websocket"] is False
    assert "previous completed" in cap["detail"] and "paid" in cap["detail"]
    assert SECRET not in json.dumps(cap)
    assert ML.capability({})["mode"] == "off"


def test_capability_paid_is_flagged_untested():
    cap = ML.capability({"MASSIVE_API_KEY": SECRET, "ATLAS_POLYGON_PLAN": "paid"})
    assert cap["mode"] == "delayed_poll" and cap["paid_path_tested"] is False and cap["websocket"] is False


def test_snapshot_not_called_on_free_plan(tmp_path):
    feed = AtlasFeed(FeedStore(tmp_path / "f.sqlite"))

    def boom(_):
        raise AssertionError("free plan must never call the snapshot")
    assert ML.poll_snapshot(feed, {"MASSIVE_API_KEY": SECRET}, ["AAPL"], transport=boom)["status"] == "skipped"


def test_paid_snapshot_parses_and_stores_delayed_quote(tmp_path):
    feed = AtlasFeed(FeedStore(tmp_path / "f.sqlite"))
    now = time.time()
    payload = {"tickers": [{"ticker": "AAPL", "lastTrade": {"p": 201.5, "t": int((now - 900) * 1e9)}, "prevDay": {"c": 200.0}}]}
    r = ML.poll_snapshot(feed, {"MASSIVE_API_KEY": SECRET, "ATLAS_POLYGON_PLAN": "paid"}, ["AAPL"], now=now, transport=lambda s: payload)
    assert r["status"] == "ok" and r["quotes"] == 1
    q = feed.store.last_quotes("AAPL")[0]
    assert q["provider"] == "polygon" and q["price"] == 201.5 and 890 < now - q["event_time"] < 910


def test_status_for_reports_age_and_capability(tmp_path):
    feed = AtlasFeed(FeedStore(tmp_path / "f.sqlite"))
    s = ML.status_for(feed, "AAPL", {"MASSIVE_API_KEY": SECRET})
    assert s["last_bar"] is None and s["capability"]["mode"] == "eod_lag" and s["execution_permission"] == "none"


def test_equity_live_prediction_uses_15m_and_is_honest_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ML_DIRECTIONAL", str(tmp_path / "none"))
    feed = AtlasFeed(FeedStore(tmp_path / "f.sqlite"))
    rows = ML.live_predictions(feed, ["BTCUSDT", "AAPL"], {"MASSIVE_API_KEY": SECRET})
    by = {r["symbol"]: r for r in rows}
    assert by["AAPL"]["interval"] == "15m" and by["AAPL"]["asset"] == "stock" and "End-of-day" in by["AAPL"]["delay"]
    assert by["BTCUSDT"]["interval"] == "15m" and by["BTCUSDT"]["asset"] == "crypto"
    assert all(r["execution_permission"] == "none" for r in rows)
    assert all(r["direction"] is None for r in rows)         # nothing invented without a model or bars


def test_provider_info_says_end_of_day_for_massive_bars():
    from atlas.feeds.core import FeedBar
    from atlas.api.chart_overlays import provider_info
    NOW = int(time.time())
    eod = FeedBar("SPY", "1d", NOW, 1, 2, 0.5, 1.5, 1, "polygon", NOW, True)
    pi = provider_info([eod], "x")
    assert pi["delay_label"].startswith("delayed") and "end-of-day" in pi["delay_label"]
    assert pi["realtime"] is False
