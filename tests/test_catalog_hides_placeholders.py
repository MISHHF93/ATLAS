"""EQ####/PERP###-USD filler ids are hidden from the catalog UI/API lists; they still resolve by exact symbol and say why they have no chart."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG, UniversalAssetCatalog

FILLER = re.compile(r"^(EQ\d{3,}|PERP\d{3,}(-USD|USDT)?)$")


def _walk(cat, **kw):
    out, off = [], 0
    while True:
        r = cat.search(query="", limit=250, offset=off, **kw)
        rows = r["results"]
        if not rows:
            return out, r
        out += rows
        off += len(rows)
        if off >= r["total_matching"]:
            return out, r


def test_default_search_lists_no_placeholder_ids():
    cat = UniversalAssetCatalog(target_equities_count=10000, target_crypto_count=520)
    rows, last = _walk(cat)
    assert rows, "the listed directory must not be empty"
    assert not [r["symbol"] for r in rows if FILLER.match(r["symbol"])]
    assert last["total_matching"] == len(rows) < 1500          # named companies, ETFs, crypto flagships, futures, FX only
    full, _ = _walk(cat, include_placeholders=True)
    assert len(full) - len(rows) == cat.universe_counts()["placeholders_hidden"] > 9000


def test_real_symbols_that_start_with_eq_or_perp_are_not_hidden():
    cat = UniversalAssetCatalog(target_equities_count=10000, target_crypto_count=520)
    syms = {r["symbol"] for r in _walk(cat)[0]}
    assert {"NVDA", "BTC-USD", "ES"} <= syms
    assert cat.search("EQIX")["total_matching"] == cat.search("EQIX", include_placeholders=True)["total_matching"]


def test_snapshot_and_counts_hide_placeholders_but_exact_lookup_still_resolves():
    cat = UniversalAssetCatalog(target_equities_count=10000, target_crypto_count=520)
    for page in (1, 2, 40):
        snap = cat.snapshot(page=page, page_size=250)
        assert not [r["symbol"] for r in snap["listings"] if FILLER.match(r["symbol"])]
    c = cat.universe_counts()
    assert c["listed_assets"] == c["total_assets"] - c["placeholders_hidden"]
    assert cat.get_asset("EQ0042") is not None            # old links still resolve (the chart then says why there is no price)


def test_api_default_hides_filler_and_opt_in_shows_it():
    c = TestClient(app)
    body = c.get("/api/catalog/search", params={"q": "EQ00", "limit": 50}).json()
    assert not [r["symbol"] for r in body["results"] if FILLER.match(r["symbol"])]
    assert body["execution_permission"] == "none"
    opt = c.get("/api/catalog/search", params={"q": "EQ00", "limit": 50, "include_placeholders": "true"}).json()
    assert any(FILLER.match(r["symbol"]) for r in opt["results"])
    snap = c.get("/api/catalog/snapshot", params={"page": 1, "page_size": 250}).json()
    assert not [r["symbol"] for r in snap["listings"] if FILLER.match(r["symbol"])]
    assert snap["universe_counts"]["placeholders_hidden"] > 9000
    assert GLOBAL_ASSET_CATALOG.get_asset("PERP011-USD") is not None
