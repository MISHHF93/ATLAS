"""Crypto cost assumption and evidence-history sources are Coinbase/Kraken only (no Binance/Bybit/OKX)."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from atlas.ai.intel.data import SPEC
from atlas.ai.ml.costs import VENUE_COSTS, venue_for
from atlas.research.setup_evidence import COSTS_BPS, CRYPTO_SOURCES

ROOT = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_crypto_cost_is_one_value_everywhere_and_not_the_old_binance_figure():
    c = VENUE_COSTS[venue_for("crypto")]["cost_bps"]
    assert c == 124.0 == COSTS_BPS["crypto"] == SPEC["BTCUSDT"][3] == SPEC["ETHUSDT"][3]
    assert "binance" not in VENUE_COSTS and c > 24.0


def test_crypto_sources_include_coinbase_and_kraken():
    assert "coinbase_public_candles".startswith(CRYPTO_SOURCES) and "kraken_public_ohlc".startswith(CRYPTO_SOURCES)
    assert not "yahoo_chart_public".startswith(CRYPTO_SOURCES)


def test_fetch_public_history_coinbase_maps_symbol_orders_columns_and_drops_forming_candle(monkeypatch):
    m = _script("fetch_public_history")
    now = int(time.time()) // 3600 * 3600
    calls = []

    def fake_get(url):
        calls.append(url)
        # Coinbase rows: [time, low, high, open, close, volume], newest first
        return [[now - 3600, 9.0, 12.0, 10.0, 11.0, 5.0], [now - 7200, 8.0, 11.0, 9.0, 10.0, 4.0], [now, 1, 1, 1, 1, 1]]

    monkeypatch.setattr(m, "_get", fake_get)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    d = m.coinbase("BTCUSDT", days=1, interval="1h")
    assert d["source"] == "coinbase_public_candles" and d["provider_symbol"] == "BTC-USD" and d["symbol"] == "BTCUSDT"
    assert all("/products/BTC-USD/candles" in u and "binance" not in u for u in calls)
    assert d["bars"] == [[now - 7200, 9.0, 11.0, 8.0, 10.0, 4.0], [now - 3600, 10.0, 12.0, 9.0, 11.0, 5.0]]   # [t,o,h,l,c,v]
    json.dumps(d)


def test_fetch_public_history_refuses_unlisted_symbol(monkeypatch):
    m = _script("fetch_public_history")
    monkeypatch.setattr(m, "_get", lambda url: pytest.fail("must not call the network for an unlisted asset"))
    with pytest.raises(ValueError):
        m.coinbase("USDTUSDT", days=1)


def test_load_evidence_cache_accepts_coinbase_and_skips_legacy_binance():
    m = _script("load_evidence_cache")
    assert m.PROVIDER["coinbase_public_candles"] == "coinbase" and "binance_public_klines" not in m.PROVIDER
