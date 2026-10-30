"""Inventory of stored bars and the all-asset universe for the directional pipeline."""
from __future__ import annotations

from typing import Any

from atlas.ai.ml.directional import pipeline as P

INTERVALS = ("1m", "15m", "1h", "1d")


def inventory(feed) -> dict[str, Any]:
    rows = feed.store.summary()
    series = [{k: r.get(k) for k in ("provider", "instrument", "interval", "bars", "first", "last", "confirmed_rows")} for r in rows]
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in series:
        k = (r["instrument"], r["interval"])
        if k not in best or (r["bars"] or 0) > (best[k]["bars"] or 0):
            best[k] = r
    usable = {k: v for k, v in best.items() if (v["bars"] or 0) >= P.CONFIG["min_bars"] and v["interval"] in INTERVALS}
    return {"n_series_rows": len(series), "n_instruments": len({r["instrument"] for r in series}), "n_usable": len(usable),
            "by_interval": {iv: sum(1 for (_, i) in usable if i == iv) for iv in INTERVALS},
            "by_group": {g: sorted({i for (i, _) in usable if P.group_of(i) == g}) for g in ("crypto", "equity", "fx", "metal", "index", "other")},
            "usable": [{"instrument": i, "interval": iv, "group": P.group_of(i), "bars": v["bars"], "first": v["first"], "last": v["last"]} for (i, iv), v in sorted(usable.items())],
            "too_short": [{"instrument": i, "interval": iv, "bars": v["bars"]} for (i, iv), v in sorted(best.items()) if (i, iv) not in usable]}


def universe(inv: dict[str, Any]) -> list[tuple[str, str]]:
    return [(u["instrument"], u["interval"]) for u in inv["usable"]]
