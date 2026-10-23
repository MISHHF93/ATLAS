"""Item 7: Canadian alt-data adapters - disabled by default, fixtures, PIT, PIPEDA minimisation."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.marketdata.pit.altdata import (ADAPTERS, BankOfCanadaValet, CIROShortSales, GDELTDoc, SEDARPlusFilings,
                                     SEDIInsiderTrades, StatCanWDS, as_of, to_featurestore)
from atlas.marketdata.pit.featurestore import FeatureStore
from atlas.marketdata.pit.providers.base import FixtureTransport, ProviderDisabled

FX = Path(__file__).parent / "fixtures"
ALT = FX / "altdata"
UTC = timezone.utc


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_disabled_by_default_and_need_env(name, monkeypatch):
    cls = ADAPTERS[name]
    monkeypatch.delenv(f"ATLAS_ALTDATA_{name.upper()}", raising=False)
    for a in (cls(), cls(enabled=True)):
        assert not a.enabled
    monkeypatch.setenv(f"ATLAS_ALTDATA_{name.upper()}", "1")
    assert not cls().enabled and cls(enabled=True).enabled


def test_enabled_without_transport_stays_offline(monkeypatch):
    monkeypatch.setenv("ATLAS_ALTDATA_BOC", "1")
    with pytest.raises(ProviderDisabled, match="network disabled"):
        BankOfCanadaValet(enabled=True).observations(["FXUSDCAD"], "2026-01-01", "2026-01-31")
    with pytest.raises(ProviderDisabled):
        BankOfCanadaValet().observations(["FXUSDCAD"], "2026-01-01", "2026-01-31")


def test_boc_statcan_gdelt_fixtures(monkeypatch):
    for n in ("BOC", "STATCAN", "GDELT"):
        monkeypatch.setenv(f"ATLAS_ALTDATA_{n}", "1")
    boc = BankOfCanadaValet(True, FixtureTransport({"/json": (FX / "boc_valet_fx.json").read_text()})).observations(["FXUSDCAD"], "2025-12-29", "2026-01-31")
    assert boc and boc[0].entity == "FXUSDCAD" and boc[0].available_at > boc[0].event_ts
    sc = StatCanWDS(True, FixtureTransport({"LatestNPeriods": (ALT / "statcan_wds.json").read_text()})).vectors([41690973])
    assert len(sc) == 2 and sc[1].available_at == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
    # PIT: on 2026-10-16 the September CPI print is not yet known
    assert [r.event_ts.month for r in as_of(sc, datetime(2026, 10, 16, tzinfo=UTC))] == [8]
    g = GDELTDoc(True, FixtureTransport({"/doc": (ALT / "gdelt_artlist.json").read_text()})).articles("Shopify")
    assert g[1].values["tone"] == -5.1 and "url" not in g[0].values


def test_file_sources_and_pipeda_minimisation(monkeypatch):
    for n in ("SEDARPLUS", "SEDI", "CIRO"):
        monkeypatch.setenv(f"ATLAS_ALTDATA_{n}", "1")
    f = SEDARPlusFilings(True).read(ALT / "sedarplus_filings.csv")
    assert f[0].values["material"] and f[1].event_ts < f[1].available_at
    s = SEDIInsiderTrades(True).read(ALT / "sedi_insider.csv")
    blob = json.dumps([r.values for r in s])
    assert "Jane" not in blob and "insider_name" not in blob and s[0].values["filing_delay_days"] == 5
    flow = SEDIInsiderTrades.net_insider_flow(s, "EXM", datetime(2026, 10, 5, tzinfo=UTC))
    assert flow == -5000 * 1.35          # Oct-01 buy not filed until Oct-06 -> invisible on Oct-05
    c = CIROShortSales(True).read(ALT / "ciro_short_sales.csv")
    assert c[0].values["short_ratio"] == 0.3
    with pytest.raises(ProviderDisabled):
        CIROShortSales().read(ALT / "ciro_short_sales.csv")


def test_feeds_point_in_time_featurestore(monkeypatch):
    monkeypatch.setenv("ATLAS_ALTDATA_CIRO", "1")
    fs = FeatureStore()
    to_featurestore(fs, CIROShortSales(True).read(ALT / "ciro_short_sales.csv"), "short")
    assert fs.get("EXM", "short", datetime(2026, 10, 15, 11, tzinfo=UTC)) is None
    assert fs.get("EXM", "short", datetime(2026, 10, 15, 13, tzinfo=UTC))["short_ratio"] == 0.3
