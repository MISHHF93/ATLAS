"""OANDA v20 fxTrade PRACTICE compatibility: practice hosts only, Bearer auth, account-id discovery via /v3/accounts, candles + pricing
for FX / XAU / index CFD names, read-only account summary -> AccountSnapshot. All fixtures; no network, no real token."""
import json
import urllib.parse

import pytest

from atlas.accounts import catalog
from atlas.accounts.http import HttpResult
from atlas.broker_state import adapters as ad
from atlas.feeds.core import ProviderError, RateLimiter
from atlas.feeds.providers.oanda import OandaAdapter
from atlas.integrations import oanda_v20 as O

TOKEN = "T" * 32 + "-" + "k" * 32
ACCT = "101-004-1435156-001"
NOW = 1_800_000_000


class Fake:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        path = urllib.parse.urlsplit(url).path
        for k, v in self.routes.items():
            if path.endswith(k):
                return 200, {}, json.dumps(v(url) if callable(v) else v).encode()
        return 404, {}, b"{}"


def candle(t, c=1.5):
    return {"time": f"{t}.000000000", "complete": True, "volume": 3, "mid": {"o": "1", "h": "2", "l": "0.5", "c": str(c)}}


def adapter(routes, env=None):
    f = Fake(routes)
    a = OandaAdapter(transport=f, env={"OANDA_API_TOKEN": TOKEN, **(env or {})}, clock=lambda: NOW, sleep=lambda s: None, limiter=RateLimiter(1000, sleep=lambda s: None))
    return a, f


# ---- hosts / auth ----
def test_only_practice_hosts_and_bearer_auth():
    assert O.REST == "https://api-fxpractice.oanda.com" and O.STREAM == "https://stream-fxpractice.oanda.com"
    a, f = adapter({"/candles": {"candles": [candle(NOW - 3600)]}})
    a.history("EUR_USD", "1h", NOW - 7200, NOW)
    url, hdr = f.calls[0]
    assert urllib.parse.urlsplit(url).hostname == "api-fxpractice.oanda.com" and hdr["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in url                                  # the token never goes in a URL


@pytest.mark.parametrize("env", [{"OANDA_ENV": "live"}, {"OANDA_ENV": "fxtrade"}, {"OANDA_ACCOUNT_ID": "001-004-1435156-001"}])
def test_live_is_refused_before_any_request(env):
    a, f = adapter({"/candles": {"candles": []}}, env)
    with pytest.raises(ProviderError) as ei:
        a.history("EUR_USD", "1h", NOW - 7200, NOW)
    assert not ei.value.retryable and f.calls == []
    with pytest.raises(ProviderError):
        a.quotes(["EUR_USD"])
    assert f.calls == []


def test_no_live_host_anywhere_in_the_oanda_modules():
    import atlas.feeds.providers.oanda as m1
    src = open(m1.__file__).read()
    assert "api-fxtrade" not in src and "stream-fxtrade" not in src


# ---- candles: FX / XAU / index, paging ----
@pytest.mark.parametrize("inst", ["EUR_USD", "USD_CAD", "XAU_USD", "SPX500_USD", "NAS100_USD", "DE30_EUR"])
def test_candles_for_fx_gold_and_index_names(inst):
    a, f = adapter({f"/instruments/{inst}/candles": {"candles": [candle(NOW - 3600)]}})
    (b,) = a.history(inst, "1h", NOW - 7200, NOW)
    assert b.close == 1.5 and b.confirmed and b.provider == "oanda" and f"/{inst}/" in f.calls[0][0]


def test_bad_instrument_name_is_rejected_without_a_request():
    a, f = adapter({})
    with pytest.raises(ProviderError):
        a.history("../accounts", "1h", NOW - 7200, NOW)
    assert f.calls == []


def test_long_ranges_are_paged_at_5000_candles():
    seen = []

    def route(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        seen.append((int(q["from"]), int(q["to"])))
        return {"candles": [candle(int(q["from"]))]}
    a, _ = adapter({"/candles": route})
    bars = a.history("EUR_USD", "1m", NOW - 60 * 12000, NOW)
    assert len(seen) == 3 and all(t - s <= 60 * 5000 for s, t in seen) and seen[0][0] == NOW - 60 * 12000 and seen[-1][1] == NOW
    assert len(bars) == 3


# ---- account id discovery + pricing ----
def test_account_id_is_discovered_via_v3_accounts_and_cached():
    a, f = adapter({"/v3/accounts": {"accounts": [{"id": ACCT, "tags": []}, {"id": "001-004-1-001"}]}})
    assert a.account_id() == ACCT and a.account_id() == ACCT
    assert len(f.calls) == 1 and f.calls[0][0] == "https://api-fxpractice.oanda.com/v3/accounts"     # live-shaped ids are dropped


def test_configured_account_id_skips_discovery_and_pricing_parses_bid_ask():
    prices = {"prices": [{"instrument": "XAU_USD", "time": "1800000000.0", "tradeable": True, "bids": [{"price": "2000.10"}], "asks": [{"price": "2000.50"}]},
                         {"instrument": "EUR_USD", "bids": [], "asks": []}]}
    a, f = adapter({"/pricing": prices}, {"OANDA_ACCOUNT_ID": ACCT})
    (q,) = a.quotes(["XAU_USD", "EUR_USD"])
    assert q["instrument"] == "XAU_USD" and q["bid"] == 2000.10 and q["mid"] == pytest.approx(2000.30) and q["tradeable"]
    assert len(f.calls) == 1 and f"/v3/accounts/{ACCT}/pricing" in f.calls[0][0] and "instruments=XAU_USD%2CEUR_USD" in f.calls[0][0]


def test_stream_url_is_the_practice_stream_host():
    a, _ = adapter({}, {"OANDA_ACCOUNT_ID": ACCT})
    u = a.stream_url(["EUR_USD", "XAU_USD"])
    assert u.startswith("https://stream-fxpractice.oanda.com/v3/accounts/" + ACCT + "/pricing/stream")


# ---- Verify test (catalog) ----
class Http:
    def __init__(self, accounts, summary_status=200):
        self.calls, self.accounts, self.ss = [], accounts, summary_status

    def __call__(self, method, url, headers=None, **kw):
        self.calls.append((method, url, dict(headers or {})))
        if url.endswith("/v3/accounts"):
            return HttpResult(200, {"accounts": [{"id": i} for i in self.accounts]})
        return HttpResult(self.ss, {"account": {}})


def run_test(values, http):
    return catalog.BY_ID["oanda"].test(values, catalog.TestContext(http=http))


def test_verify_hits_v3_accounts_on_practice_host_and_discovers_the_id():
    h = Http([ACCT])
    r = run_test({"api_token": TOKEN}, h)
    assert r.ok and "auto-discovered" in r.detail and TOKEN not in r.detail
    assert [c[0] for c in h.calls] == ["GET", "GET"] and h.calls[0][1] == "https://api-fxpractice.oanda.com/v3/accounts"
    assert h.calls[1][1] == f"https://api-fxpractice.oanda.com/v3/accounts/{ACCT}/summary" and h.calls[0][2]["Authorization"] == "Bearer " + TOKEN


def test_verify_with_configured_id_and_with_a_foreign_id():
    assert run_test({"api_token": TOKEN, "account_id": ACCT}, Http([ACCT])).ok
    bad = run_test({"api_token": TOKEN, "account_id": "101-004-9999999-001"}, Http([ACCT]))
    assert not bad.ok and "not one of" in bad.detail


def test_verify_fails_cleanly_on_401_and_on_a_token_with_no_practice_account():
    class Deny:
        def __call__(self, *a, **k):
            return HttpResult(401, None)
    assert "401" in run_test({"api_token": TOKEN}, Deny()).detail
    assert not run_test({"api_token": TOKEN}, Http([])).ok


def test_setup_fields_account_id_optional_env_is_practice_constant():
    spec = catalog.BY_ID["oanda"]
    assert spec.field("api_token").required and not spec.field("account_id").required
    assert dict(spec.constants) == {"OANDA_ENV": "practice"}
    assert catalog.validate_values(spec, {"api_token": TOKEN}) == {"api_token": TOKEN}
    with pytest.raises(Exception):
        catalog.validate_values(spec, {"api_token": TOKEN, "account_id": "001-001-1234567-001"})


# ---- account summary -> AccountSnapshot with discovery ----
def test_snapshot_discovers_account_id(monkeypatch):
    monkeypatch.setattr(ad, "verification_state", lambda s, env: {"state": "verified", "detail": ""})
    urls = []

    def get(url, headers):
        urls.append(url)
        assert "api-fxpractice.oanda.com" in url and headers["Authorization"] == "Bearer " + TOKEN
        if url.endswith("/v3/accounts"):
            return {"accounts": [{"id": ACCT}]}
        if url.endswith("/summary"):
            return {"account": {"currency": "CAD", "balance": "100000", "NAV": "100010.5", "marginUsed": "0", "marginAvailable": "100000", "marginRate": "0.02"}}
        if url.endswith("/openPositions"):
            return {"positions": []}
        if url.endswith("/pendingOrders"):
            return {"orders": []}
        return {"instruments": []}
    snap = ad.OandaPracticeStateAdapter(get_json=get).fetch({"OANDA_API_TOKEN": TOKEN})
    assert snap.usable and snap.balances.equity == 100010.5 and snap.environment == "practice"
    assert urls[0].endswith("/v3/accounts") and any(f"/accounts/{ACCT}/summary" in u for u in urls)
    assert ACCT not in json.dumps(snap.to_dict()) and TOKEN not in json.dumps(snap.to_dict())


def test_snapshot_only_get_urls_and_no_account_means_not_configured(monkeypatch):
    monkeypatch.setattr(ad, "verification_state", lambda s, env: {"state": "verified", "detail": ""})
    snap = ad.OandaPracticeStateAdapter(get_json=lambda u, h: {"accounts": []}).fetch({"OANDA_API_TOKEN": TOKEN})
    assert snap.status == "not_configured"
    assert ad.OandaPracticeStateAdapter(get_json=lambda u, h: 1 / 0).fetch({}).status in ("not_configured", "needs_verification")


def test_checklist_row_names_the_oanda_fields_and_where_to_enter_them():
    from atlas.integrations import checklist, registry
    env = {}
    rows = checklist.build(env, states={})["items"]
    row = next(r for r in rows if r["key"] == "broker_paper")
    names = {v["name"]: v for v in row["vars"]}
    assert names["OANDA_API_TOKEN"]["required"] and not names["OANDA_ACCOUNT_ID"]["required"] and names["OANDA_ENV"]["fixed"] == "practice"
    assert "Manage API Access" in row["enter_in"] and "GET /v3/accounts" in row["enter_in"]
    assert registry.mode_for(next(s for s in registry.SERVICES if s.id == "oanda"), {"OANDA_ENV": "live"}) == "live_refused"
