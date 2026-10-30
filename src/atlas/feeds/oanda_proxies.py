"""OANDA practice CFD proxies for assets that have no licensed intraday bars (evo-16 hotfix).

A proxy is a DIFFERENT instrument that moves with the asset (SPX500_USD is a CFD on the S&P 500 index, not SPY and not the ES future). It is
used only to nudge a forecast forward from the asset's last real bar, it is always labelled "proxy", and it is inactive until the OANDA
practice token is verified and that instrument's bars are really stored. Nothing here fetches data, stores bars or holds a key."""
from __future__ import annotations

# asset -> OANDA instrument (names as OANDA lists them; whether a given practice account offers one is only known after verification)
OANDA_PROXY: dict[str, str] = {
    "SPY": "SPX500_USD", "ES": "SPX500_USD", "MES": "SPX500_USD",
    "QQQ": "NAS100_USD", "NQ": "NAS100_USD", "MNQ": "NAS100_USD",
    "DIA": "US30_USD", "YM": "US30_USD", "MYM": "US30_USD",
    "IWM": "US2000_USD", "RTY": "US2000_USD", "M2K": "US2000_USD",
    "GLD": "XAU_USD", "GC": "XAU_USD", "MGC": "XAU_USD", "IAU": "XAU_USD",
    "SLV": "XAG_USD", "SI": "XAG_USD",
    "CL": "WTICO_USD", "MCL": "WTICO_USD", "USO": "WTICO_USD",
    "NG": "NATGAS_USD",
    "ZN": "USB10Y_USD", "ZB": "USB30Y_USD",
    "6E": "EUR_USD", "6J": "USD_JPY",     # 6J is JPY per USD inverted: the regression beta carries the (negative) sign
}


def oanda_proxy(symbol: str) -> str | None:
    return OANDA_PROXY.get(str(symbol).upper())


def proxy_candidate(feed, symbol: str, has_bars) -> dict | None:
    """Description of the mapping and whether it is live: ``has_bars(oanda_instrument) -> bool`` says if real proxy bars are stored."""
    inst = oanda_proxy(symbol)
    if inst is None:
        return None
    active = bool(has_bars(inst))
    return {"instrument": inst, "provider": "oanda", "kind": "proxy", "status": "active" if active else "needs_verification",
            "label": f"{inst} (OANDA practice CFD proxy, not {symbol})",
            "note": (f"Intraday moves of {inst} nudge the forecast forward from the last real {symbol} bar." if active else
                     f"Inactive: {inst} bars are stored only after OANDA_API_TOKEN is set and verified (practice only). Until then the forecast anchors on the last real {symbol} bar alone.")}
