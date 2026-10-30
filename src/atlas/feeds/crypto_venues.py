"""Crypto venue symbol mapping for Canada: Coinbase and Kraken only (USD quote).

ATLAS keeps its stable internal series ids (``BTCUSDT``, ``ETHUSDT``, ...) so stored history, model folders and URLs stay
valid, but the data behind every id is the USD spot market of a venue that serves Canadian residents:

* Coinbase Exchange product ``<BASE>-USD`` (REST candles, ``ticker`` websocket).
* Kraken pair ``<BASE>USD`` (REST) and ``<BASE>/USD`` (websocket v2; ``XBT``/``XDG`` are REST-only names).

An asset with no Coinbase/Kraken USD listing, or one on Kraken's Canada restricted list, gets no symbol for that venue. An
asset with no symbol at all has an empty provider chain, which the feed reports as an empty state (never a made-up price).
The listing snapshot below was read from the public Coinbase ``/products`` and Kraken ``/AssetPairs`` endpoints on 2026-10-30.
"""
from __future__ import annotations

from pathlib import Path

LISTING_SNAPSHOT = "2026-10-30"
COINBASE_USD = frozenset(
    "BTC ETH SOL BNB XRP DOGE ADA AVAX LINK SUI DOT NEAR LTC UNI APT ICP ARB OP INJ AAVE TIA PEPE WIF RENDER FET SEI "
    "ATOM FIL TON HBAR BCH XLM ALGO ETC".split())
KRAKEN_USD = COINBASE_USD
# Kraken REST pair names use XBT and XDG; websocket v2 uses BTC and DOGE.
KRAKEN_REST_BASE = {"BTC": "XBT", "DOGE": "XDG"}
# Used when config/founder/blocklists/kraken_ca.yaml cannot be read: fail closed with the known partial list.
_FALLBACK_BLOCKED = frozenset({"USDT", "USDG", "DAI", "WBTC", "XMR"})
_BLOCKLIST = Path(__file__).resolve().parents[3] / "config" / "founder" / "blocklists" / "kraken_ca.yaml"


def kraken_blocked_assets(path: Path | None = None) -> frozenset[str]:
    """Assets Kraken restricts for Canadian clients (the synced ``kraken_ca`` file; fallback list if unreadable)."""
    try:
        import yaml
        doc = yaml.safe_load((path or _BLOCKLIST).read_text(encoding="utf-8")) or {}
        got = {str(a.get("symbol", "")).upper() for a in doc.get("assets") or [] if isinstance(a, dict)}
        return frozenset(got - {""}) or _FALLBACK_BLOCKED
    except Exception:  # noqa: BLE001
        return _FALLBACK_BLOCKED


def coinbase_product(base: str) -> str | None:
    return f"{base}-USD" if base in COINBASE_USD else None


def kraken_pair(base: str, blocked: frozenset[str] | None = None) -> str | None:
    """REST pair, e.g. BTC -> XBTUSD."""
    if base not in KRAKEN_USD or base in (kraken_blocked_assets() if blocked is None else blocked):
        return None
    return f"{KRAKEN_REST_BASE.get(base, base)}USD"


def kraken_ws_symbol(base: str, blocked: frozenset[str] | None = None) -> str | None:
    """Websocket v2 symbol, e.g. BTC -> BTC/USD."""
    return f"{base}/USD" if kraken_pair(base, blocked) else None


def crypto_fields(base: str) -> dict:
    """provider_symbols / provider_priority / sanity_providers for a crypto base (Coinbase first, Kraken second)."""
    cb, kr = coinbase_product(base), kraken_pair(base)
    syms = {"alpaca_crypto": f"{base}/USD", "yahoo": f"{base}-USD"}
    prio: list[str] = []
    if cb:
        syms["coinbase"] = cb
        prio.append("coinbase")
    if kr:
        syms["kraken"] = kr
        prio.append("kraken")
    if not prio:
        return {"provider_symbols": {}, "provider_priority": (), "sanity_providers": (),
                "description": f"{base}/USD: no Coinbase or Kraken USD listing for Canadian clients; no data is shown"}
    prio.append("alpaca_crypto")
    return {"provider_symbols": syms, "provider_priority": tuple(prio), "sanity_providers": tuple(p for p in ("coinbase", "kraken") if p in syms),
            "description": f"{base}/USD spot (Coinbase, Kraken; series id keeps the legacy {base}USDT name)"}



def ws_symbol_from_pair(pair: str) -> str:
    """Kraken REST pair -> websocket v2 symbol (XBTUSD -> BTC/USD, XDGUSD -> DOGE/USD)."""
    base = pair[:-3] if pair.endswith("USD") else pair
    back = {v: k for k, v in KRAKEN_REST_BASE.items()}
    return f"{back.get(base, base)}/USD"
