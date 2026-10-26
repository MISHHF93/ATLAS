"""Four-Box research view built from EXISTING detectors (no new signal logic):
  Opening  = detectors.ORBRetestDetector  (needs a session preset; uses the venue's preset)
  Breakout = detectors.DualBollingerDetector
  Anchor   = detectors.WickReversalDetector
  Event    = events.event_zone / ScheduledNewsPostReleaseDetector — DISABLED by default when no
             verified economic-event calendar feed is supplied; activates causally when verified
             ``EconomicEvent`` items are passed in ``events``.
Runs the standard PriceActionEngine over confirmed bars and groups its candidates per box. Research only."""
from __future__ import annotations

from typing import Any, Sequence

from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.events import EconomicEvent
from atlas.features.price_action.extended_strategies import ScheduledNewsPostReleaseDetector
from atlas.features.price_action.features import batch_features
from atlas.features.price_action.sessions import PRESETS

BOXES = [
    {"box": "Opening", "detector": "orb_retest", "status": "enabled"},
    {"box": "Breakout", "detector": "dual_bollinger", "status": "enabled"},
    {"box": "Anchor", "detector": "wick_reversal", "status": "enabled"},
    {"box": "Event", "detector": "event_zone", "status": "disabled", "reason": "no verified economic-event calendar feed configured"},
]
# metals and Nasdaq use the US equity RTH open as their opening box: an approximation, labelled in the response
SESSION_FOR = {
    "SPY": "us_equity_rth",
    "QQQ": "us_equity_rth",
    "ES": "us_equity_rth",
    "NQ": "us_equity_rth",
    "MNQ": "us_equity_rth",
    "GC": "us_equity_rth",
    "MGC": "us_equity_rth",
    "SI": "us_equity_rth",
}


def scan(
    inst: str,
    bars,
    now: int | None = None,
    session: str | None = None,
    events: Sequence[EconomicEvent] | None = None,
) -> dict[str, Any]:
    sess_name = session or SESSION_FOR.get(inst)
    sess = PRESETS.get(sess_name) if sess_name else None
    boxes = [dict(b) for b in BOXES]
    if sess is None:
        boxes[0].update(status="disabled", reason="no session preset for this instrument (24/7 market)")
    if events:
        boxes[3] = {"box": "Event", "detector": "event_zone", "status": "enabled"}
    if not bars:
        return {"status": "no_data", "boxes": boxes}
    eff_now = now or bars[-1].start + bars[-1].duration
    eng = PriceActionEngine(inst, bars[0].duration, EngineConfig(session=sess))
    eng.run_batch(bars, now=eff_now)
    cands = [c for c in getattr(eng, "candidates", [])]
    zones_by = {d.name: list(getattr(d, "zones", [])) for d in eng.detectors}

    if events:
        ev_det = ScheduledNewsPostReleaseDetector(inst, bars[0].duration, events=events)
        ctxs = batch_features(bars, 14)
        for b, ctx in zip(bars, ctxs):
            if b.end <= eff_now:
                ev_det.step(b, ctx)
        zones_by["event_zone"] = list(ev_det.zones)
        for c in ev_det.candidates:
            cands.append(c)

    for b in boxes:
        det_names = {b["detector"]}
        if b["detector"] == "event_zone":
            det_names.add("scheduled_news_post_release")
        mine = [c for c in cands if getattr(c, "detector", None) in det_names]
        b["n_candidates"] = len(mine) if b["status"] == "enabled" else 0
        zs = zones_by.get(b["detector"], []) if b["status"] == "enabled" else []
        b["n_zones"] = len(zs)
        b["latest_zones"] = [{"kind": z.zone_type, "direction": z.direction, "low": z.lower_bound, "high": z.upper_bound, "confirmed_at": z.confirmed_at}
                             for z in zs[-3:]] if zs else []
        b["latest"] = [{"t": getattr(c, "detected_at", None), "direction": getattr(c, "direction", None),
                        "entry": getattr(c, "entry_reference", None), "stop": getattr(c, "proposed_stop", None)} for c in mine[-3:]] if b["status"] == "enabled" else []
    return {"status": "ok", "session": sess_name if sess else None, "bars": len(bars), "boxes": boxes, "execution_permission": "none"}
