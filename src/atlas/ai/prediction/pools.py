"""Asset pools for the pooled models (evo-16): stocks/ETFs, FX, metals, indices, crypto. Futures with no pool are ``other``."""
from __future__ import annotations

POOLS = ("equity", "fx", "metal", "index", "crypto")
POOL_LABEL = {"equity": "Stocks / ETFs", "fx": "FX", "metal": "Metals", "index": "Indices", "crypto": "Crypto",
              "other": "Other futures (energy, rates, FX futures)"}
METAL_IDS = frozenset({"GLD", "SLV", "GC", "SI", "MGC", "XAUUSD", "XAGUSD", "XAU_USD", "XAG_USD", "IAU", "GDX"})
INDEX_IDS = frozenset({"ES", "NQ", "YM", "RTY", "MES", "MNQ", "MYM", "M2K", "SPX", "NDX", "DJI", "RUT", "US500", "US100"})


def pool_of(instrument_id: str, asset_class: str = "") -> str:
    s = instrument_id.upper()
    ac = (asset_class or "").lower()
    if ac == "crypto" or (not ac and s.endswith(("USDT", "-USD"))):
        return "crypto"
    if s in METAL_IDS:
        return "metal"
    if ac == "fx" or (not ac and len(s) == 7 and s[3] == "_"):
        return "fx"
    if s in INDEX_IDS or ac == "index":
        return "index"
    if ac in ("equity", "etf", ""):
        return "equity"
    return "other"


# Model feature family per pool: the layer code keys session/breadth/seasonality behaviour on these names (unchanged since evo-14).
FAMILY = {"crypto": "crypto", "equity": "equity", "metal": "gold", "index": "equity", "fx": "fx", "other": "equity"}
# Cross-asset transfer: a pool with no model of its own is scored by the nearest donor pool's model, and labelled as transfer.
TRANSFER_DONORS = {"crypto": (), "equity": (), "metal": ("equity",), "index": ("equity",), "fx": ("equity",), "other": ("equity",)}


def family_of(group: str) -> str:
    """Feature family for a pool name (or a legacy family name such as ``gold``)."""
    return FAMILY.get(group, group)


def _class_map() -> dict[str, str]:
    global _CM
    if _CM is None:
        try:
            from atlas.feeds.instruments import _default_universe
            _CM = {k: v.asset_class for k, v in _default_universe().items()}
        except Exception:
            _CM = {}
    return _CM


_CM: dict[str, str] | None = None


def pool_for_symbol(symbol: str) -> str:
    """Pool of a symbol using the catalog's asset class when it is known."""
    return pool_of(symbol, _class_map().get(symbol, ""))
