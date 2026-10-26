"""Four-Box research view built from EXISTING detectors (no new signal logic):
  Opening  = detectors.ORBRetestDetector  (needs a session preset; uses the venue's preset)
  Breakout = detectors.DualBollingerDetector
  Anchor   = detectors.WickReversalDetector
  Event    = events.event_zone — DISABLED: no verified economic-event calendar feed is configured.
Runs the standard PriceActionEngine over confirmed bars and groups its candidates per box. Research only."""
from __future__ import annotations

from typing import Any

from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.sessions import PRESETS

BOXES = [
    {"box": "Opening", "detector": "orb_retest", "status": "enabled"},
    {"box": "Breakout", "detector": "dual_bollinger", "status": "enabled"},
    {"box": "Anchor", "detector": "wick_reversal", "status": "enabled"},
    {"box": "Event", "detector": "event_zone", "status": "disabled", "reason": "no verified economic-event calendar feed configured"},
]
# metals use the US equity RTH open as their opening box: an approximation, labelled in the response
SESSION_FOR = {"SPY": "us_equity_rth", "ES": "us_equity_rth", "GC": "us_equity_rth", "MGC": "us_equity_rth", "SI": "us_equity_rth"}


def scan(inst: str, bars, now: int | None = None, session: str | None = None) -> dict[str, Any]:
    sess_name = session or SESSION_FOR.get(inst)
    sess = PRESETS.get(sess_name) if sess_name else None
    boxes = [dict(b) for b in BOXES]
    if sess is None:
        boxes[0].update(status="disabled", reason="no session preset for this instrument (24/7 market)")
    if not bars:
        return {"status": "no_data", "boxes": boxes}
    eng = PriceActionEngine(inst, bars[0].duration, EngineConfig(session=sess))
    eng.run_batch(bars, now=now or bars[-1].start + bars[-1].duration)
    cands = [c for c in getattr(eng, "candidates", [])]
    zones_by = {d.name: list(getattr(d, "zones", [])) for d in eng.detectors}
    for b in boxes:
        mine = [c for c in cands if getattr(c, "detector", None) == b["detector"]]
        b["n_candidates"] = len(mine) if b["status"] == "enabled" else 0
        zs = zones_by.get(b["detector"], []) if b["status"] == "enabled" else []
        b["n_zones"] = len(zs)
        b["latest_zones"] = [{"kind": z.zone_type, "direction": z.direction, "low": z.lower_bound, "high": z.upper_bound, "confirmed_at": z.confirmed_at}
                             for z in zs[-3:]] if zs else []
        b["latest"] = [{"t": getattr(c, "detected_at", None), "direction": getattr(c, "direction", None),
                        "entry": getattr(c, "entry_reference", None), "stop": getattr(c, "proposed_stop", None)} for c in mine[-3:]] if b["status"] == "enabled" else []
    return {"status": "ok", "session": sess_name if sess else None, "bars": len(bars), "boxes": boxes, "execution_permission": "none"}
