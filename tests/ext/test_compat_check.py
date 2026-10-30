import importlib.util
import pathlib
import sqlite3

spec = importlib.util.spec_from_file_location("compat_check", pathlib.Path(__file__).parents[2] / "scripts" / "compat_check.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

SECRET = "SECRETSECRETSECRET1234"


def test_one_verify_per_configured_provider_and_no_secret_in_output(tmp_path):
    calls = []

    def verify(sid, env, throttle=False):
        calls.append(sid)
        return {"state": "verified", "detail": "practice account summary OK"}
    db = tmp_path / "f.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE bar_revisions (provider TEXT, instrument TEXT, interval TEXT, event_time INTEGER, receipt_time INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL, confirmed INTEGER, provider_symbol TEXT)")
    c.execute("INSERT INTO bar_revisions VALUES ('polygon','AAPL','1d',1000,1000,1,1,1,1,1,1,'AAPL')")
    c.commit(); c.close()
    env = {"POLYGON_API_KEY": SECRET, "OANDA_API_TOKEN": SECRET + "x", "GEMINI_API_KEY": SECRET + "y", "ATLAS_GEMINI_TIER": "paid"}
    rows = cc.run(env, verify_fn=verify, probe_fn=lambda *a, **k: (True, "3 1d bars"), flow_fn=lambda p: cc.store_flow(p, db, now=1000 + 3600))
    assert sorted(calls) == ["gemini", "oanda", "polygon"]
    by = {r["provider"].split(" (")[0]: r for r in rows}
    assert by["Massive"]["verified"] == "verified" and "1 bars stored" in by["Massive"]["data_flowing"]
    assert by["OANDA practice"]["data_flowing"] == "no bars stored yet"
    assert by["ECB FX"]["verified"] == "ok" and by["Alpaca public crypto"]["configured"] is True
    out = cc.table(rows)
    assert SECRET not in out and "| provider |" in out


def test_unconfigured_providers_are_not_verified_and_say_what_to_enter():
    calls = []
    rows = cc.run({}, verify_fn=lambda *a, **k: calls.append(a) or {}, probe_fn=lambda *a, **k: (False, "offline"), flow_fn=lambda p: {"bars": 0, "latest": None, "age_h": None})
    assert calls == []
    oanda = next(r for r in rows if r["provider"].startswith("OANDA"))
    assert oanda["configured"] is False and "OANDA_API_TOKEN" in oanda["notes"] and oanda["verified"] == "no key"
    assert next(r for r in rows if r["provider"].startswith("ECB"))["verified"] == "failed"


def test_fred_row_is_verified_once_and_never_leaks_key():
    calls = []

    def verify(sid, env, throttle=False):
        calls.append(sid)
        return {"state": "verified", "detail": "FRED OK"}
    key = "a" * 32
    rows = cc.run({"FRED_API_KEY": key}, verify_fn=verify, probe_fn=lambda *a, **k: (True, "x"), flow_fn=lambda p: {"bars": 0})
    fred = [r for r in rows if r["provider"].startswith("FRED")][0]
    assert calls == ["fred"] and fred["configured"] is True and fred["verified"] == "verified"
    assert "never enters ML training" in fred["notes"] and key not in cc.table(rows)
