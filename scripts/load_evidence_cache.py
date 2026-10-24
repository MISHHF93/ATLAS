"""Load the orphaned public-history artifacts (var/evidence_cache/*.json, var/evidence_cache_15m/*.json, written by
scripts/fetch_public_history.py for the model-evidence scripts) into the ATLAS feed store, so the UI/feed serve them too.

Bars keep their original provider (yahoo_chart_public -> yahoo, binance_public_klines -> binance). The final bar of
each file is skipped when it may still have been forming at fetch time. Idempotent: the store's ingest dedupes.
Usage: python scripts/load_evidence_cache.py [--var /workspace/atlas/var] [--db var/feeds/atlas_feed.sqlite]"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from atlas.feeds.store import FeedBar, FeedStore
from atlas.feeds.universe import resolve

SECONDS = {"15m": 900, "1h": 3600, "1d": 86400}
PROVIDER = {"yahoo_chart_public": "yahoo", "binance_public_klines": "binance"}


def load(var: Path, store: FeedStore) -> list[dict]:
    report = []
    for f in sorted(list((var / "evidence_cache").glob("*.json")) + list((var / "evidence_cache_15m").glob("*.json"))):
        d = json.loads(f.read_text())
        iid, iv, prov = resolve(d["symbol"]), d["interval"], PROVIDER.get(d.get("source"))
        if not iid or iv not in SECONDS or not prov:
            report.append({"file": f.name, "loaded": 0, "skipped": "unknown symbol/interval/source"})
            continue
        fa = d.get("fetched_at")
        try:
            fetched = int(datetime.fromisoformat(str(fa).replace("Z", "+00:00")).timestamp()) if fa else None
        except ValueError:
            fetched = None
        bars = []
        for row in d["bars"]:
            t, o, h, l, c, v = row[:6]
            start = int(t if t < 1e12 else t // 1000)
            if fetched and start + SECONDS[iv] > fetched:
                continue
            bars.append(FeedBar(iid, iv, start, float(o), float(h), float(l), float(c), float(v or 0), prov,
                                fetched or start + SECONDS[iv], True, d["symbol"]))
        if not fetched and bars:
            bars = bars[:-1]  # unknown fetch time: drop the possibly-forming last bar
        res = store.ingest(bars, note=f"evidence_cache:{f.name}")
        report.append({"file": f.name, "instrument": iid, "interval": iv, "provider": prov, "bars": len(bars), "ingest": res})
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", default="/workspace/atlas/var")
    ap.add_argument("--db", default="var/feeds/atlas_feed.sqlite")
    a = ap.parse_args()
    for r in load(Path(a.var), FeedStore(a.db)):
        print(json.dumps(r, default=str))
