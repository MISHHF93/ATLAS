"""Needs verification -> Verify: no key is ever set by ATLAS; Verify makes one read-only call and records a secret-free state."""
from __future__ import annotations

import json

import pytest

from atlas.accounts.http import HttpResult
from atlas.integrations import verify as V
from atlas.integrations.registry import SERVICES, status


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "STORE", tmp_path / "verify.json")
    V._LAST.clear()


def _svc(i):
    return next(s for s in SERVICES if s.id == i)


def test_every_keyed_service_starts_as_needs_verification_with_no_key_set():
    st = status(env={})
    keyed = [r for r in st["services"] if V._required(_svc(r["id"])) and r["id"] not in V.KEYLESS]
    assert keyed and all(r["verification"]["state"] == "needs_verification" and not r["verification"]["key_present"] for r in keyed)
    for must in ("alpaca", "polygon", "alphavantage", "questrade", "tradier", "fred", "oanda", "stripe", "sentry", "healthchecks", "alerts_ntfy", "finnhub", "tiingo"):
        assert must in st["summary"]["needs_verification"], must
    assert st["stock_provider"]["primary"] == "polygon"


def test_verify_without_a_key_makes_no_call():
    calls = []
    out = V.verify("polygon", {}, http=lambda *a, **k: calls.append(a) or HttpResult(200, {}), now=1000)
    assert out["state"] == "needs_verification" and out["ok"] is None and not calls


def test_verify_ok_then_key_change_resets_and_no_secret_is_stored():
    secret = "SECRETKEYVALUE1234567890abcdef"
    seen = []

    def http(method, url, headers=None, params=None, json_body=None, timeout=10.0):
        seen.append((method, url, dict(params or {})))
        return HttpResult(200, {"status": "OK"})
    env = {"POLYGON_API_KEY": secret}
    out = V.verify("polygon", env, http=http, now=1000)
    assert out["state"] == "verified" and out["ok"] is True and len(seen) == 1 and seen[0][0] == "GET" and "massive.com" in seen[0][1]
    assert secret not in json.dumps(out) and secret not in V.STORE.read_text()
    assert V.state_for(_svc("polygon"), env)["state"] == "verified"
    assert V.state_for(_svc("polygon"), {"POLYGON_API_KEY": "ANOTHERKEYVALUE1234567890zz"})["state"] == "needs_verification"


def test_rejected_key_is_failed_with_an_honest_reason_and_throttle_protects_quota():
    http = lambda *a, **k: HttpResult(401, {})  # noqa: E731
    out = V.verify("alphavantage", {"ALPHAVANTAGE_API_KEY": "ABCDEFGHIJKLMNOP"}, http=http, now=1000)
    assert out["state"] == "failed" and out["ok"] is False and "401" in out["detail"]
    again = V.verify("alphavantage", {"ALPHAVANTAGE_API_KEY": "ABCDEFGHIJKLMNOP"}, http=http, now=1002)
    assert again.get("throttled") is True


def test_stripe_refuses_live_keys_without_contacting_stripe():
    calls = []
    out = V.verify("stripe", {"STRIPE_SECRET_KEY": "sk_live_abcdefghijklmnop"}, http=lambda *a, **k: calls.append(1) or HttpResult(200, {}), now=1000)
    assert out["state"] == "failed" and "TEST" in out["detail"] and not calls
    ok = V.verify("stripe", {"STRIPE_SECRET_KEY": "sk_test_abcdefghijklmnop"}, http=lambda *a, **k: HttpResult(200, {"livemode": False}), now=2000)
    assert ok["state"] == "verified"


def test_sentry_dsn_is_format_only_never_claims_verified():
    dsn = "https://0123456789abcdef0123456789abcdef@o1.ingest.sentry.io/12345"
    out = V.verify("sentry", {"SENTRY_DSN": dsn}, http=lambda *a, **k: pytest.fail("no network"), now=1000)
    assert out["state"] == "format_only" and out["ok"] is None


def test_keyless_and_unknown_services():
    assert V.verify("public_crypto", {}, now=1)["state"] == "keyless"
    assert V.verify("nope", {}, now=1)["state"] == "unknown_service"


def test_verify_endpoint_never_echoes_the_key(monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    secret = "ENDPOINTSECRET1234567890xyz"
    monkeypatch.setenv("FINNHUB_API_KEY", secret)
    monkeypatch.setattr(V, "fetch", lambda *a, **k: HttpResult(200, {"c": 1.0}))
    monkeypatch.setattr(V, "verify", lambda sid, env, http=None, **k: {"service": sid, "state": "verified", "ok": True, "detail": "ok"})
    c = TestClient(app)
    r = c.post("/api/integrations/verify", json={"service": "finnhub"})
    assert r.status_code == 200 and secret not in r.text
    v = c.get("/api/integrations/verification")
    assert v.status_code == 200 and secret not in v.text and v.json()["states"]["finnhub"]["key_present"] is True
