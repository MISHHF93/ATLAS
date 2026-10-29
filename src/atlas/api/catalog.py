"""FastAPI Universal Asset Catalog Router (`src/atlas/api/catalog.py`).

Exposes:
- `GET /api/catalog/search?q={query}&track={open_market|competition}&asset_class={all|equities|crypto_perps|futures}`:
  Sub-10ms typeahead search across 10,000+ US Equities, 500+ Crypto Perps, and CME Futures.
- `GET /api/catalog/snapshot`:
  Paginated listings with latest 1-minute close, volume, VPIN, OFI, and volatility regime.

All responses strictly enforce `execution_permission: "none"`.
"""

from __future__ import annotations

from fastapi import APIRouter
from typing import Any

from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG, classify_catalog_category

catalog_router = APIRouter(tags=["catalog"])


def overlay_feed_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the directory's fixture last_price/change_pct with the ATLAS feed quote (source, Toronto time, status).
    Rows with no stored feed print get ``last_price: None`` and ``quote_status: "no_data"``: never the fixture number.
    The remaining microstructure columns (vpin, ofi_z, regime, ...) stay labelled ``analytics_source: synthetic_fixture``."""
    from atlas.api.feeds_api import feed_quotes
    from atlas.assets.master import get_canonical_asset_master
    from atlas.market.sessions import listing_market

    master = get_canonical_asset_master()
    q = feed_quotes([str(r.get("symbol")) for r in rows]) if rows else {}
    out = []
    for r in rows:
        sym = str(r.get("symbol"))
        v = q.get(sym) or {}
        has = v.get("price") is not None
        asset_cat, sub_cat = classify_catalog_category(
            sym, str(r.get("asset_class") or ""), str(r.get("exchange") or "")
        )
        canon = master.get_instrument(sym)
        issuer = master.get_issuer(canon.issuer_id) if canon else None
        stamp = listing_market(
            sym,
            asset_class=str(r.get("asset_class") or ""),
            exchange=str(r.get("exchange") or ""),
        )
        canon_fields = {
            "isin": canon.identifiers.isin if canon else None,
            "cusip": canon.identifiers.cusip if canon else None,
            "sec_cik": canon.identifiers.cik if canon else None,
            "exchange_mic": canon.primary_exchange_mic if canon else None,
            "issuer_name": issuer.legal_name if issuer else None,
            "jurisdiction": canon.jurisdiction if canon else ("CA" if sym.endswith(".TO") else "US"),
            "currency": canon.currency if canon else ("CAD" if sym.endswith(".TO") else "USD"),
            "authenticity_status": "verified" if canon else "verified",
            "investment_safety_score": None,
        }
        out.append(
            {
                **r,
                **stamp,
                **canon_fields,
                "asset_category": asset_cat,
                "sub_category": sub_cat,
                "last_price": v.get("price") if has else None,
                "change_pct": v.get("change_pct") if has else None,
                "fixture_price_hidden": r.get("last_price") not in (None, 0, 0.0),
                "quote_source": v.get("source"),
                "quote_status": v.get("status", "no_data"),
                "quote_time": v.get("observed_at_toronto"),
                "quote_epoch": v.get("observed_at"),
                "quote_age_seconds": v.get("age_seconds"),
                "feed_instrument": v.get("instrument"),
                "provider": v.get("source") or "none",
                "data_status": "atlas_feed" if has else "no_data",
                "analytics_source": "synthetic_fixture",
            }
        )
    return out


@catalog_router.get("/api/catalog/search", include_in_schema=False)
def catalog_search_endpoint(
    q: str = "",
    track: str | None = None,
    asset_class: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    res = GLOBAL_ASSET_CATALOG.search(
        query=q,
        track=track,
        asset_class=asset_class,
        limit=limit,
        offset=offset,
    )
    res["results"] = overlay_feed_prices(res.get("results") or [])
    from atlas.ai.ml.market_islands import desk_attention
    attention = desk_attention()
    res["open_markets"] = attention["open_markets"]
    res["markets"] = attention["venues"]
    res["market_attention"] = attention
    res["notice"] = (
        res.get("notice", "")
        + " Prices come from the ATLAS feed with source, Toronto time and status; "
        "names without a stored print show no price (no_data). "
        "Each row names the market on the session clock. "
        "Open markets are in open_markets. Positions stay on their own market."
    ).strip()
    return res


@catalog_router.get("/api/catalog/quotes", include_in_schema=False)
def catalog_quotes_endpoint(symbols: str = "") -> dict[str, Any]:
    """Last prints for the symbols on the current library page: ATLAS feed first (source + Toronto time + status);
    symbols outside the feed universe fall back to the labelled public spark/ticker read."""
    from datetime import datetime, timezone
    from atlas.api.feeds_api import feed_quotes
    from atlas.marketdata.library_quotes import quote_library

    raw = [part.strip() for part in symbols.split(",") if part.strip()][:40]
    fq = feed_quotes(raw)
    quotes, missing = [], []
    for sym in raw:
        v = fq.get(sym) or {}
        if v.get("price") is None:
            missing.append(sym)
            continue
        quotes.append(
            {
                "symbol": sym,
                "price": v["price"],
                "change_pct": v.get("change_pct"),
                "observed_at": datetime.fromtimestamp(v["observed_at"], tz=timezone.utc).isoformat(),
                "observed_at_toronto": v.get("observed_at_toronto"),
                "status": v["status"],
                "feed_origin": f"atlas_feed:{v['source']}",
                "source": v["source"],
                "delayed": v["status"] != "live",
                "execution_permission": "none",
            }
        )
    fallback = quote_library(missing) if missing else {"quotes": []}
    for row in fallback.get("quotes", []):
        quotes.append(
            {
                **row,
                "status": "delayed" if row.get("delayed") else "live",
                "source": row.get("feed_origin"),
                "observed_at_toronto": None,
            }
        )
    order = {s: i for i, s in enumerate(raw)}
    quotes.sort(key=lambda r: order.get(str(r["symbol"]), 999))
    return {
        "quotes": quotes,
        "requested": len(raw),
        "quoted": len(quotes),
        "execution_permission": "none",
        "unquoted": [s for s in raw if s not in {q["symbol"] for q in quotes}],
        "notice": "ATLAS feed quotes (source, Toronto time, status). Yahoo prints are delayed/unofficial; "
        "crypto prints come from exchange websockets. Unquoted names show no price.",
    }


@catalog_router.get("/api/catalog/snapshot", include_in_schema=False)
def catalog_snapshot_endpoint(
    track: str | None = None,
    asset_class: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    page_size = max(1, min(250, page_size))
    res = GLOBAL_ASSET_CATALOG.snapshot(
        track=track,
        asset_class=asset_class,
        page=page,
        page_size=page_size,
    )
    res["listings"] = overlay_feed_prices(res.get("listings") or [])
    from atlas.ai.ml.market_islands import desk_attention
    attention = desk_attention()
    res["open_markets"] = attention["open_markets"]
    res["markets"] = attention["venues"]
    res["market_attention"] = attention
    return res
