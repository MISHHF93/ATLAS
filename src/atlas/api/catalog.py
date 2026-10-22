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

from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG

catalog_router = APIRouter(tags=["catalog"])


@catalog_router.get("/api/catalog/search", include_in_schema=False)
def catalog_search_endpoint(
    q: str = "",
    track: str | None = None,
    asset_class: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    return GLOBAL_ASSET_CATALOG.search(
        query=q,
        track=track,
        asset_class=asset_class,
        limit=limit,
        offset=offset,
    )


@catalog_router.get("/api/catalog/quotes", include_in_schema=False)
def catalog_quotes_endpoint(symbols: str = "") -> dict[str, Any]:
    """Public last prints for the symbols on the current library page."""
    from atlas.marketdata.library_quotes import quote_library

    raw = [part.strip() for part in symbols.split(",") if part.strip()]
    return quote_library(raw[:40])


@catalog_router.get("/api/catalog/snapshot", include_in_schema=False)
def catalog_snapshot_endpoint(
    track: str | None = None,
    asset_class: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    page_size = max(1, min(250, page_size))
    return GLOBAL_ASSET_CATALOG.snapshot(
        track=track,
        asset_class=asset_class,
        page=page,
        page_size=page_size,
    )
