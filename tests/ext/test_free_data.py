"""Free-data layer: Alpaca crypto (keyless), BoC Valet, free/paid gate, provider tags, aliases. HTTP mocked."""
import json

from atlas.feeds.core import RateLimiter
from atlas.feeds import free_sources
from atlas.feeds.providers import alpaca as falp
from atlas.feeds.providers.boc import BankOfCanadaFXAdapter

NOW = 1_760_000_000


def _http(payload, seen):
    def t(url, headers, timeout=20.0):
        seen.append((url, dict(headers)))
        return 200, {}, json.dumps(payload).encode()
    return t


def _mk(cls, payload, seen, env=None):
    return cls(transport=_http(payload, seen), env=env or {}, clock=lambda: NOW, sleep=lambda s: None,
               limiter=RateLimiter(1000, sleep=lambda s: None))


def test_alpaca_crypto_keyless_and_tagged():
    seen = []
    p = {"bars": {"BTC/USD": [{"t": "2025-10-09T08:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 3}]}}
    a = _mk(falp.AlpacaCryptoAdapter, p, seen)
    bars = a.history("BTCUSDT", "1h", NOW - 7200, NOW)
    assert bars and bars[0].provider == "alpaca_crypto"
    assert "BTC%2FUSD" in seen[0][0] or "BTC/USD" in seen[0][0]
    assert "APCA-API-KEY-ID" not in seen[0][1]
    assert falp._crypto_pair("ETHUSDT") == "ETH/USD"


def test_alpaca_limits():
    assert falp.ALPACA_RATE_PER_MIN <= 200 and falp.ALPACA_WS_SYMBOL_CAP == 30


def test_boc_parse_and_invert():
    seen = []
    p = {"observations": [{"d": "2025-10-08", "FXUSDCAD": {"v": "1.4000"}}, {"d": "2025-10-09", "FXUSDCAD": {"v": ""}}]}
    b = _mk(BankOfCanadaFXAdapter, p, seen).history("CAD_USD", "1d", NOW - 86400 * 5, NOW)
    assert len(b) == 1 and abs(b[0].close - 1 / 1.4) < 1e-9 and b[0].provider == "boc_valet"


def test_boc_wired_to_usd_cad_instrument():
    from atlas.feeds import AtlasFeed, FeedStore, InstrumentMaster, ProviderRegistry
    from atlas.feeds.instruments import DEFAULT_INSTRUMENTS
    from atlas.feeds.universe import resolve

    assert "USD_CAD" in DEFAULT_INSTRUMENTS
    inst = InstrumentMaster().get("USD_CAD")
    assert "boc_valet" in inst.provider_priority
    assert inst.provider_symbols["boc_valet"] == "FXUSDCAD"
    assert resolve("USD_CAD") == "USD_CAD" and resolve("USD/CAD") == "USD_CAD"

    seen = []
    p = {"observations": [{"d": "2025-10-08", "FXUSDCAD": {"v": "1.3750"}}]}
    boc = _mk(BankOfCanadaFXAdapter, p, seen)
    feed = AtlasFeed(FeedStore(":memory:"), ProviderRegistry([boc]), InstrumentMaster(), clock=lambda: NOW)
    r = feed.backfill("USD_CAD", "1d", NOW - 86400 * 5, NOW, fill_gaps=False)
    assert r["provider"] == "boc_valet" and r["inserted"] == 1
    bars = feed.bars("USD_CAD", "1d", NOW - 86400 * 5, NOW)
    assert len(bars) == 1 and bars[0].close == 1.375 and bars[0].provider == "boc_valet"


def test_ecb_fx_sdmx_json_cross_rate_and_tls_xml_fallback():
    import pytest
    from atlas.feeds.core import ProviderError
    from atlas.feeds.providers.ecb import ECBFXAdapter

    sdmx_usd = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.10, 0], "1": [1.12, 0]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": "2025-10-07"}, {"id": "2025-10-08"}]}]}},
    }
    sdmx_cad = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.54, 0], "1": [1.568, 0]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": "2025-10-07"}, {"id": "2025-10-08"}]}]}},
    }

    def route_transport(url, headers, timeout=20.0):
        if "D.USD.EUR" in url:
            return 200, {}, json.dumps(sdmx_usd).encode()
        if "D.CAD.EUR" in url:
            return 200, {}, json.dumps(sdmx_cad).encode()
        raise OSError(f"unexpected url: {url}")

    ecb = ECBFXAdapter(transport=route_transport, env={}, clock=lambda: NOW, sleep=lambda s: None,
                       limiter=RateLimiter(1000, sleep=lambda s: None))
    eur_usd = ecb.history("EUR_USD", "1d", NOW - 86400 * 5, NOW)
    assert [b.close for b in eur_usd] == [1.10, 1.12]
    assert eur_usd[0].provider == "ecb_fx" and eur_usd[0].delayed is True

    usd_cad = ecb.history("USD_CAD", "1d", NOW - 86400 * 5, NOW)
    assert len(usd_cad) == 2
    assert abs(usd_cad[0].close - (1.54 / 1.10)) < 1e-9
    assert abs(usd_cad[1].close - (1.568 / 1.12)) < 1e-9

    # Simulate legacy SDW TLS failure falling back to eurofxref XML feed
    xml_body = b"""<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube><Cube time="2025-10-08"><Cube currency="USD" rate="1.1150"/><Cube currency="CAD" rate="1.5200"/></Cube></Cube>
    </gesmes:Envelope>"""

    def tls_fail_then_xml(url, headers, timeout=20.0):
        if "eurofxref" in url:
            return 200, {}, xml_body
        raise OSError("SSL: CERTIFICATE_VERIFY_FAILED")

    ecb_fb = ECBFXAdapter(transport=tls_fail_then_xml, env={}, clock=lambda: NOW, sleep=lambda s: None,
                          limiter=RateLimiter(1000, sleep=lambda s: None))
    fb_bars = ecb_fb.history("EUR_USD", "1d", NOW - 86400 * 5, NOW)
    assert len(fb_bars) == 1 and fb_bars[0].close == 1.1150

    # When both SDMX REST and XML fallback fail with TLS error, raises ProviderError cleanly
    def total_tls_fail(url, headers, timeout=20.0):
        raise OSError("SSL: CERTIFICATE_VERIFY_FAILED")

    ecb_err = ECBFXAdapter(transport=total_tls_fail, env={}, clock=lambda: NOW, sleep=lambda s: None,
                           limiter=RateLimiter(1000, sleep=lambda s: None))
    with pytest.raises(ProviderError):
        ecb_err.history("EUR_USD", "1d", NOW - 86400 * 5, NOW)


def test_free_gate():
    assert free_sources.allowed("alpaca_crypto", {})
    assert not free_sources.allowed("yahoo", {})
    assert not free_sources.allowed("databento", {})
    assert not free_sources.allowed("nonexistent", {})
    assert free_sources.allowed("databento", {"ATLAS_ALLOW_PAID_DATA": "true"})
    assert free_sources.latency("boc_valet") == "daily_reference"


def test_data_providers_free_only():
    from atlas.integrations.registry import data_providers
    rows = data_providers({})
    crypto = next(r for r in rows if r["asset_class"] == "crypto")
    assert crypto["active"] == "coinbase"
    for r in rows:
        assert "yahoo" not in r["priority"] and "databento" not in r["priority"]


def test_alpaca_bars_not_configured_and_ok():
    from atlas.api.integrations_api import alpaca_bars
    assert alpaca_bars("SPY", "1h", 10, environ={})["status"] == "not_configured"
    seen = []
    p = {"bars": {"BTC/USD": [{"t": "2025-10-09T08:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 3}]}}
    r = alpaca_bars("BTCUSDT", "1h", 10, crypto=True, environ={}, transport=_http(p, seen), now=NOW)
    assert r["status"] == "ok" and r["execution_permission"] == "none"
    assert r["bars"][0]["provider"] == "alpaca_crypto" and r["latency"] == "realtime"


def test_alpaca_aliases_and_guards():
    import atlas.ext.alpaca_paper as old
    import atlas.execution.adapters.alpaca as new
    assert old.AlpacaPaperBroker is new.AlpacaPaperBroker and old.PAPER_URL == new.PAPER_URL
    assert "paper-api.alpaca.markets" in new.PAPER_URL


def test_bars_carry_router_tags_for_chart():
    from atlas.feeds.core import FeedBar
    from atlas.api.chart_overlays import provider_info
    rt = FeedBar("BTCUSDT", "1h", NOW, 1, 2, 0.5, 1.5, 1, "alpaca_crypto", NOW, True)
    assert rt.realtime is True and rt.delayed is False and rt.delay_s == 0
    eod = FeedBar("SPY", "1d", NOW, 1, 2, 0.5, 1.5, 1, "polygon", NOW, True)
    assert eod.realtime is False and eod.delay_s == 86400
    assert provider_info([rt], "x")["delay_label"] == "real-time"
    assert provider_info([eod], "x")["delay_label"].startswith("delayed")
