"""Decision-trail storage helpers (dedupe of repeated candidates).

The pipeline re-evaluates the same candidate every cycle; when nothing changes the trail used to fill
with identical "buy X -> dropped at cost" rows. `merge_trail` collapses a new decision into the most
recent stored decision for the same (symbol, side, sleeve) when the outcome AND the stage sequence
(stage, effect) are the same: the stored entry gets `repeat` += 1, `first_ts` kept, `ts` bumped and
it moves to the end. Any change in outcome or in which stage passed/shrank/dropped starts a new row,
so the trail still shows every state change. Counts by outcome stay exact via `repeat`."""
from __future__ import annotations

from collections import Counter

MAX_TRAIL = 1000


def _key(t: dict) -> tuple:
    return (t.get("symbol"), t.get("side"), t.get("sleeve"))


def _sig(t: dict) -> tuple:
    return (t.get("final"), t.get("routing"),
            tuple((s.get("stage"), s.get("effect")) for s in t.get("stages") or []))


def merge_trail(hist: list[dict], new: list[dict], cap: int = MAX_TRAIL) -> list[dict]:
    out = list(hist)
    for t in new:
        t = dict(t)
        idx = next((i for i in range(len(out) - 1, -1, -1) if _key(out[i]) == _key(t)), None)
        if idx is not None and _sig(out[idx]) == _sig(t):
            prev = out.pop(idx)
            t["repeat"] = int(prev.get("repeat", 1)) + int(t.get("repeat", 1))
            t["first_ts"] = prev.get("first_ts", prev.get("ts"))
        out.append(t)
    return out[-cap:]


def dedupe(trail: list[dict], cap: int = MAX_TRAIL) -> list[dict]:
    return merge_trail([], trail, cap)


def outcome_counts(trail: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for t in trail:
        c[str(t.get("final"))] += int(t.get("repeat", 1))
    return dict(c)
