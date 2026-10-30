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
