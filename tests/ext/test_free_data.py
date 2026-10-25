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
    assert crypto["active"] == "alpaca_crypto"
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
