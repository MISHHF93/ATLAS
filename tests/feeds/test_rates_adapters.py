"""evo-19 official rates / energy adapters: fixture-tested only, no network, no keys."""
from __future__ import annotations

import json

import pytest

from atlas.feeds.core import ProviderError
from atlas.feeds.free_sources import allowed
from atlas.feeds.providers import ALL_ADAPTERS
from atlas.feeds.providers.rates import BankOfCanadaRatesAdapter, EIAAdapter, UsTreasuryYieldAdapter
from atlas.feeds.reference_series import catalog_status, reference_series

UST = b"""<?xml version="1.0"?><feed xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns="http://www.w3.org/2005/Atom">
<entry><content type="application/xml"><m:properties><d:NEW_DATE m:type="Edm.DateTime">2026-10-02T00:00:00</d:NEW_DATE><d:BC_2YEAR m:type="Edm.Double">4.80</d:BC_2YEAR><d:BC_10YEAR m:type="Edm.Double">4.20</d:BC_10YEAR></m:properties></content></entry>
<entry><content type="application/xml"><m:properties><d:NEW_DATE m:type="Edm.DateTime">2026-10-01T00:00:00</d:NEW_DATE><d:BC_2YEAR m:type="Edm.Double">4.78</d:BC_2YEAR><d:BC_10YEAR m:type="Edm.Double">4.17</d:BC_10YEAR></m:properties></content></entry></feed>"""


def _t(body: bytes, status: int = 200, seen: list | None = None):
    def f(url, headers):
        if seen is not None:
            seen.append(url)
        return status, {}, body
    return f


def _kw(**k):
    return {"sleep": lambda s: None, "clock": lambda: 1_800_000_000, **k}


def test_us_treasury_parses_the_atom_feed_sorted_and_keyless():
    seen: list = []
    a = UsTreasuryYieldAdapter(env={}, transport=_t(UST, seen=seen), **_kw())
    assert a.enabled and a.caps.auth_env == ()
    obs = a.observations("UST_10Y", year_month="202610")
    assert [(o.date, o.value) for o in obs] == [("2026-10-01", 4.17), ("2026-10-02", 4.20)]
    assert "field_tdr_date_value_month=202610" in seen[0] and "api_key" not in seen[0]
    with pytest.raises(ProviderError):
        a.observations("UST_NOPE")


def test_us_treasury_http_error_is_a_provider_error_not_data():
    a = UsTreasuryYieldAdapter(env={}, transport=_t(b"nope", 503), **_kw())
    with pytest.raises(ProviderError) as e:
        a.observations("UST_2Y", year=2026)
    assert e.value.status == 503 and a.health().consecutive_errors == 1


def test_boc_rates_parses_valet_json():
    js = {"observations": [{"d": "2026-10-01", "BD.CDN.10YR.DQ.YLD": {"v": "3.10"}}, {"d": "2026-10-02", "BD.CDN.10YR.DQ.YLD": {"v": ""}},
                           {"d": "2026-10-05", "BD.CDN.10YR.DQ.YLD": {"v": "3.15"}}]}
    seen: list = []
    a = BankOfCanadaRatesAdapter(env={}, transport=_t(json.dumps(js).encode(), seen=seen), **_kw())
    obs = a.observations("CAN_10Y", "2026-10-01", "2026-10-05")
    assert [(o.date, o.value) for o in obs] == [("2026-10-01", 3.10), ("2026-10-05", 3.15)]
    assert "BD.CDN.10YR.DQ.YLD" in seen[0] and "start_date=2026-10-01" in seen[0]


def test_eia_needs_a_key_and_never_leaks_it_in_errors():
    assert not EIAAdapter(env={}).enabled and EIAAdapter(env={}).health().reason == "missing_env:EIA_API_KEY"
    js = {"response": {"data": [{"period": "2026-10-02", "value": "71.5"}, {"period": "2026-10-01", "value": "70.0"}, {"period": "2026-09-30", "value": None}]}}
    seen: list = []
    a = EIAAdapter(env={"EIA_API_KEY": "k-test"}, transport=_t(json.dumps(js).encode(), seen=seen), **_kw())
    obs = a.observations("EIA_WTI_SPOT")
    assert [(o.date, o.value) for o in obs] == [("2026-10-01", 70.0), ("2026-10-02", 71.5)]
    assert "petroleum/pri/spt/data" in seen[0] and "RWTC" in seen[0]
    bad = EIAAdapter(env={"EIA_API_KEY": "k-test"}, transport=_t(b"forbidden", 403), **_kw())
    with pytest.raises(ProviderError) as e:
        bad.observations("EIA_WTI_SPOT")
    assert "k-test" not in str(e.value) and "k-test" not in str(bad.health().last_error)


def test_sources_are_gated_free_and_registered():
    names = {c.caps.name for c in ALL_ADAPTERS}
    assert {"us_treasury", "boc_rates", "eia"} <= names
    for n in ("us_treasury", "boc_rates", "eia"):
        assert allowed(n, {})
    assert not allowed("tmx", {}) and not allowed("yahoo", {})   # paid / unofficial stay closed without the flags


def test_reference_catalog_is_series_only_and_never_tradable():
    cat = reference_series()
    assert len(cat) == 9 + 6 + 3
    assert all(r["trade_series"] is False and r["execution_permission"] == "none" and r["provider"] in {"us_treasury", "boc_rates", "eia"} for r in cat.values())
    assert not any("FRED" in r["provider"].upper() for r in cat.values())
    rows = {r["id"]: r for r in catalog_status({})}
    assert rows["EIA_WTI_SPOT"]["status"] == "needs_verification" and rows["EIA_WTI_SPOT"]["key_missing"] == ["EIA_API_KEY"]
    assert rows["UST_10Y"]["key_missing"] == [] and rows["UST_10Y"]["allowed"]


def test_reference_series_endpoint_exposes_no_secret(monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    monkeypatch.setenv("EIA_API_KEY", "sekret-eia-value")
    r = TestClient(app).get("/api/feeds/reference-series")
    assert r.status_code == 200 and "sekret-eia-value" not in r.text
    j = r.json()
    assert j["n"] == 18 and j["execution_permission"] == "none"
