"""Fetch longer real OHLCV history from free public endpoints into var/evidence_cache/ (never committed).

Sources (no keys):
- Yahoo chart API (query1.finance.yahoo.com/v8/finance/chart): 1h for range=730d, and 1d from period1=0.
- Coinbase Exchange public candles (api.exchange.coinbase.com/products/<BASE>-USD/candles): 1h, paged forwards, 300 candles per call.
With --15m: Yahoo 15m (range=60d, the free-tier maximum) and Coinbase 15m (730 days) into var/evidence_cache_15m/,
the cache read by scripts/run_selector_evidence.py.
Usage: python scripts/fetch_public_history.py [--15m]
Stooq was tried and is not used: from this box it returns an HTML JS challenge, not CSV.
Each cache file records source URL, fetch time, and first/last bar times."""
from __future__ import annotations

import json
import sys
if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / "var" / "evidence_cache"
CACHE_15M = CACHE.parent / "evidence_cache_15m"
STEP_MS = {"1h": 3600_000, "15m": 900_000}
GRANULARITY = {"1h": 3600, "15m": 900}   # Coinbase candle granularity in seconds
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{product}/candles"

UA = {"User-Agent": "Mozilla/5.0 (research; atlas evidence fetch)"}


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def yahoo(symbol: str, interval: str) -> dict:
    q = {"1h": "range=730d", "15m": "range=60d"}.get(interval, f"period1=0&period2={int(time.time())}")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{q}&interval={interval}&includePrePost=false"
    res = _get(url)["chart"]["result"][0]
    ts, qd = res["timestamp"], res["indicators"]["quote"][0]
    bars = [[t, o, h, l, c, v or 0] for t, o, h, l, c, v in zip(ts, qd["open"], qd["high"], qd["low"], qd["close"], qd["volume"])
            if None not in (o, h, l, c)]
    return {"source": "yahoo_chart_public", "url": url, "symbol": symbol, "interval": interval,
            "gmtoffset": res["meta"].get("gmtoffset"), "bars": bars}


def coinbase(symbol: str, days: int = 730, interval: str = "1h") -> dict:
    """Coinbase Exchange public candles for an ATLAS crypto id (BTCUSDT -> BTC-USD). Rows are [t, low, high, open, close, volume],
    newest first, at most 300 per call; only closed candles are kept. A symbol with no Coinbase listing raises (no fake data)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from atlas.feeds.crypto_venues import coinbase_product
    product = coinbase_product(symbol[:-4] if symbol.endswith("USDT") else symbol)
    if not product:
        raise ValueError(f"{symbol}: no Coinbase USD listing; refusing to fabricate history")
    step = GRANULARITY[interval]
    end = int(time.time()) // step * step          # exclude the candle that is still forming
    cur = end - days * 86400
    out = []
    while cur < end:
        stop = min(cur + 300 * step, end)
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = _get(COINBASE_CANDLES.format(product=product) + f"?granularity={step}&start={iso(cur)}&end={iso(stop - 1)}")
        out += [[int(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])] for r in rows if int(r[0]) + step <= end]
        cur = stop
        time.sleep(0.2)
    out = sorted({r[0]: r for r in out}.values())
    return {"source": "coinbase_public_candles", "url": COINBASE_CANDLES.format(product=product), "symbol": symbol,
            "provider_symbol": product, "interval": interval, "bars": out}


def save(d: dict, cache: Path = CACHE) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    b = d["bars"]
    d["fetched_at"] = datetime.now(timezone.utc).isoformat()
    d["first"] = datetime.fromtimestamp(b[0][0], timezone.utc).isoformat() if b else None
    d["last"] = datetime.fromtimestamp(b[-1][0], timezone.utc).isoformat() if b else None
    p = cache / f"{d['symbol'].replace('^', '')}_{d['interval']}.json"
    p.write_text(json.dumps(d))
    print(p.name, d["source"], len(b), d["first"], d["last"])


if __name__ == "__main__":
    if "--15m" in sys.argv[1:]:
        for s in ("SPY", "QQQ", "IWM"):
            save(yahoo(s, "15m"), CACHE_15M)
        for s in ("BTCUSDT", "ETHUSDT"):
            save(coinbase(s, interval="15m"), CACHE_15M)
        sys.exit(0)
    for s in ("SPY", "QQQ", "IWM"):
        save(yahoo(s, "1h"))
        save(yahoo(s, "1d"))
    for s in ("BTCUSDT", "ETHUSDT"):
        save(coinbase(s))
    sys.exit(0)
