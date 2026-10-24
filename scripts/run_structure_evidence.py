"""Run the structure engine + gold session models on real feed bars; print JSON summary (no var/ written)."""
import json, sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from atlas.feeds.feed import get_feed
from atlas.features.price_action.indicators import atr_batch
from atlas.features.price_action.structure import analyze_structure
from atlas.features.price_action.gold_models import session_day_ranges
sys.path.insert(0, "scripts")
from run_level_research import load

feed = get_feed(); out = {}
for inst in ("GC", "ES", "BTCUSDT"):
    bars = load(feed, inst, "15m", 900)
    ev = analyze_structure(bars, inst)
    out[inst] = {"bars": len(bars), "events": dict(Counter(e.kind for e in ev)),
                 "sample": ev[-1].to_dict() if ev else None}
b1 = load(feed, "GC", "1m", 60); NY = ZoneInfo("America/New_York")
atr = atr_batch([b.high for b in b1], [b.low for b in b1], [b.close for b in b1], 14)
days = sorted({datetime.fromtimestamp(b.start, NY).date() for b in b1})
gd = []
for d in days:
    dt = datetime(d.year, d.month, d.day, tzinfo=NY)
    r = session_day_ranges("GC", b1, dt, b1[-1].end, atr=atr[-1])
    gd.append({"day": str(d), "opening_orb": r.get("opening_orb"), "orb_alignment": r.get("orb_alignment"),
               "insufficient": r.get("insufficient")})
out["GC_1m"] = {"bars": len(b1), "days": gd}
print(json.dumps(out, indent=1, default=str))
