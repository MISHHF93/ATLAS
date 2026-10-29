import pytest

from atlas.accounts import catalog, connectors, safety
from atlas.accounts.catalog import BY_ID, CATALOG, CATEGORIES, TestContext
from atlas.risk.safety import LiveTradingForbidden

from .conftest import mkuser, signup

PK = "PK" + "A" * 18
SEC = "s" * 40


def test_catalog_matches_brief():
    ids = {c.id for c in CATALOG}
    assert ids == {"alpaca", "oanda", "ibkr", "tiingo", "finnhub", "twelvedata", "alphavantage", "fmp", "massive", "coingecko", "fred", "bls",
                   "sec_edgar", "telegram", "discord", "ntfy", "healthchecks", "sentry"}
    cats = {c[0] for c in CATEGORIES}
    for c in CATALOG:
        assert c.category in cats and c.docs_url.startswith("https://") and c.free_tier and callable(c.test) and c.fields
        assert all(f.env for f in c.fields)


def test_public_spec_has_no_values_and_is_json_safe():
    import json
    json.dumps([c.public() for c in CATALOG])


def test_paper_constants():
    assert "paper-api.alpaca.markets" in dict(BY_ID["alpaca"].constants)["ALPACA_BASE_URL"]
    assert dict(BY_ID["oanda"].constants)["OANDA_ENV"] == "practice"


@pytest.mark.parametrize("vals", [
    {"key_id": "AK" + "A" * 18, "secret_key": SEC},               # live Alpaca key prefix
    {"key_id": PK, "secret_key": SEC, "data_feed": "x" * 300},
])
def test_alpaca_live_or_bad_refused(vals):
    with pytest.raises((LiveTradingForbidden, ValueError)):
        catalog.validate_values(BY_ID["alpaca"], vals)


def test_alpaca_paper_ok():
    out = catalog.validate_values(BY_ID["alpaca"], {"key_id": PK, "secret_key": SEC})
    assert out["key_id"] == PK


@pytest.mark.parametrize("acct", ["001-001-1234567-001", "001-004-1234567-001", "1234"])
def test_oanda_live_account_refused(acct):
    with pytest.raises((LiveTradingForbidden, ValueError)):
        catalog.validate_values(BY_ID["oanda"], {"api_token": "t" * 40, "account_id": acct})


def test_oanda_practice_ok():
    catalog.validate_values(BY_ID["oanda"], {"api_token": "t" * 40, "account_id": "101-001-1234567-001"})


@pytest.mark.parametrize("vals", [
    {"host": "127.0.0.1", "port": "4001", "account_id": "DU1234567"},   # live gateway port
    {"host": "127.0.0.1", "port": "7496", "account_id": "DU1234567"},   # live TWS port
    {"host": "127.0.0.1", "port": "4002", "account_id": "U1234567"},    # live account
    {"host": "10.0.0.5", "port": "4002", "account_id": "DU1234567"},    # not loopback
    {"host": "169.254.169.254", "port": "4002", "account_id": "DU1234567"},
])
def test_ibkr_live_or_nonloopback_refused(vals):
    with pytest.raises((LiveTradingForbidden, ValueError)):
        catalog.validate_values(BY_ID["ibkr"], vals)


def test_ibkr_paper_ok():
    catalog.validate_values(BY_ID["ibkr"], {"host": "127.0.0.1", "port": "4002", "account_id": "DU1234567"})


def test_api_blocks_live_alpaca_and_audits(client, acct_env):
    h = signup(client)
    r = client.post("/api/account/connectors/alpaca/save", json={"values": {"key_id": "AK" + "A" * 18, "secret_key": SEC}}, headers=h)
    assert r.status_code == 422 and r.json()["error"] == "refused_live_trading"
    assert SEC not in r.text
    ev = client.get("/api/account/audit").json()["events"]
    assert any(e["action"] == "connector.refused" for e in ev) and SEC not in str(ev)
    assert [c for c in client.get("/api/account/connectors").json()["connectors"] if c["id"] == "alpaca"][0]["state"] is None


def test_live_endpoint_strings_refused():
    with pytest.raises(safety.SafetyRefusal):
        safety.refuse_live_strings({"base": "https://api.alpaca.markets/v2"})
    with pytest.raises(safety.SafetyRefusal):
        safety.refuse_live_strings({"base": "https://api-fxtrade.oanda.com"})


@pytest.mark.parametrize("perm", ["withdraw", "WITHDRAW", "transfer", "funds_transfer"])
def test_withdraw_permission_refused(perm):
    with pytest.raises(safety.SafetyRefusal):
        safety.check_permissions(["read", perm])


def _resolver(ip):
    return lambda host, port=443, **kw: [(2, 1, 6, "", (ip, port))]


@pytest.mark.parametrize("url,ip", [("http://example.com/x", "93.184.216.34"), ("https://user:pw@example.com/", "93.184.216.34"),
                                    ("https://example.com/", "127.0.0.1"), ("https://example.com/", "169.254.169.254"),
                                    ("https://example.com/", "10.0.0.1"), ("https://example.com/", "192.168.1.1")])
def test_ssrf_guard_rejects(url, ip):
    with pytest.raises((safety.SafetyRefusal, ValueError)):
        safety.assert_public_https(url, _resolver(ip))


def test_ssrf_guard_allows_public():
    safety.assert_public_https("https://ntfy.sh/", _resolver("93.184.216.34"))


def test_ntfy_custom_server_must_be_public_https(conn):
    u = mkuser(conn)
    with pytest.raises((LiveTradingForbidden, ValueError, connectors.ConnectorError)):
        connectors.save(conn, u.id, "ntfy", {"server_url": "http://127.0.0.1:8080", "topic": "mytopic123"})


def test_discord_webhook_host_pinned():
    with pytest.raises(ValueError):
        catalog.validate_values(BY_ID["discord"], {"webhook_url": "https://evil.example/api/webhooks/1/abc"})


def test_sec_user_agent_must_identify():
    with pytest.raises(ValueError):
        catalog.validate_values(BY_ID["sec_edgar"], {"user_agent": "python-requests"})
    catalog.validate_values(BY_ID["sec_edgar"], {"user_agent": "ATLAS Research masharai@example.com"})


def test_ibkr_test_is_owner_only(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "ibkr", {"host": "127.0.0.1", "port": "4002", "account_id": "DU1234567"})
    res = connectors.run_test(conn, u.id, "ibkr", TestContext(http=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")), is_owner=False))
    assert res["status"] == "failed" and res["light"] == "red"


def test_connector_test_uses_injected_http_and_scrubs_secret(conn):
    from atlas.accounts.http import HttpResult
    u = mkuser(conn)
    key = "tiingoKEY123456789"
    connectors.save(conn, u.id, "tiingo", {"api_key": key})
    seen = {}

    def fake(method, url, headers=None, params=None, json_body=None, timeout=10):
        seen.update(url=url)
        raise RuntimeError("boom " + key)
    res = connectors.run_test(conn, u.id, "tiingo", TestContext(http=fake, is_owner=False))
    assert res["status"] == "failed" and key not in str(res)
    assert seen["url"].startswith("https://api.tiingo.com")


def test_safe_permissions_pass():
    safety.check_permissions(["read", "trade_paper"])
    safety.check_permissions(None)
