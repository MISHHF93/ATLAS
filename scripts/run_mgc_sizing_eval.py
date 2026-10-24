"""Research-only: would the E2E journey's TRADE_CANDIDATE brackets pass control-plane sizing as MGC instead of GC?

Replays the same GC 15m feed bars and detector config as run_e2e_journey.py, takes the candidates the E2E
journey served as TRADE_CANDIDATE (from /workspace/shots/full1/e2e/decisions.jsonl), and feeds each bracket
unchanged to a fresh ActionableControlPlaneEngine twice: symbol GC and symbol MGC. No rule is changed or
loosened; risk_policy.yaml is not touched. Output: /workspace/shots/full1/e2e/mgc_sizing_eval.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "scripts")
import run_e2e_journey as e2e  # noqa: E402
from run_level_research import load  # noqa: E402

from atlas.control.engine import ActionableControlPlaneEngine  # noqa: E402
from atlas.features.price_action.engine import EngineConfig  # noqa: E402
from atlas.features.price_action.replay import ReplayConfig, replay  # noqa: E402
from atlas.features.price_action.suite import GoldBox, GoldConfig, StrategyToggles, SuiteConfig  # noqa: E402
from atlas.feeds.contracts import contract_for  # noqa: E402
from atlas.feeds.feed import get_feed  # noqa: E402

OUT = Path("/workspace/shots/full1/e2e")


def main() -> dict:
    ids = {json.loads(l)["candidate_id"] for l in (OUT / "decisions.jsonl").read_text().splitlines()
           if json.loads(l)["serving_status"] == "TRADE_CANDIDATE"}
    feed = get_feed()
    bars = load(feed, e2e.INST, "15m", e2e.TF)
    daily = tuple((int(b.event_time), b.high, b.low, b.close) for b in feed.bars(e2e.INST, "1d"))
    from datetime import time
    suite = SuiteConfig(toggles=StrategyToggles(True, True, True), tick=0.1, calendar="COMEX", daily=daily, cost_price=e2e.COST,
                        gold=GoldConfig(boxes=(GoldBox("GOLD_OPENING_ORB", time(8, 20), time(8, 50)),)))
    res = replay(e2e.INST, e2e.TF, bars, engine_cfg=EngineConfig(suite=suite),
                 cfg=ReplayConfig(entry_window=3, max_hold_bars=96, cost_per_unit=e2e.COST), data_label="atlas-feed GC 15m")
    cands = [c for c in res.candidates if c.candidate_id in ids]
    rows = []
    for c in cands:
        stop_bps = abs(c.entry_reference - c.proposed_stop) / c.entry_reference * 1e4
        row = {"candidate_id": c.candidate_id, "direction": c.direction, "entry": c.entry_reference,
               "stop": c.proposed_stop, "target": c.proposed_target, "stop_distance_bps": round(stop_bps, 2)}
        for sym in ("GC", "MGC"):
            eng = ActionableControlPlaneEngine()
            eng.flatten_all_positions(reason="research_fresh_engine")
            rb = eng._rulebook_for("open_market")
            spec = contract_for(sym)
            d = eng.ingest_whale_policy_signal(
                {"symbol": sym, "direction": "BUY" if c.direction == "long" else "SELL", "execution_permission": "none",
                 "target_entry_price": c.entry_reference, "suggested_stop_loss": c.proposed_stop,
                 "suggested_take_profit": c.proposed_target, "telemetry": {"vpin": 0.0}},
                track="open_market", data_age_ms=0.0, now=datetime.fromtimestamp(c.detected_at, timezone.utc)).decision
            equity = eng.current_equity_usd
            risk_budget = equity * min(rb.max_per_trade_risk_fraction, Decimal("0.0075"))
            one = Decimal(str(spec.notional(c.entry_reference)))
            row[sym] = {"decision": d.control_plane_decision, "violations": list(d.violations),
                        "quantity_contracts": str(d.quantity), "notional_usd": str(d.notional_usd),
                        "one_contract_notional_usd": str(one),
                        "one_contract_risk_usd": str((one * Decimal(str(stop_bps)) / Decimal(10000)).quantize(Decimal("0.01"))),
                        "rulebook": {"min_stop_distance_bps": str(rb.min_stop_distance_bps),
                                     "max_position_notional_usd": str(rb.max_position_notional_usd),
                                     "max_per_trade_risk_fraction": str(rb.max_per_trade_risk_fraction),
                                     "equity_usd": str(equity), "risk_budget_usd": str(risk_budget.quantize(Decimal("0.01")))}}
        rows.append(row)
    out = {"candidates": len(rows), "rows": rows,
           "summary": {s: {"authorized": sum(r[s]["decision"] == "authorized_and_executed" for r in rows),
                           "stop_too_tight": sum(any("stop_distance_too_tight" in v for v in r[s]["violations"]) for r in rows),
                           "zero_lots": sum(any("insufficient_remaining_room_for_one_lot" in v for v in r[s]["violations"]) for r in rows)}
                       for s in ("GC", "MGC")},
           "notes": ["research only; brackets unchanged; no rule changed; fresh engine per check (no open-position interaction)",
                     "MGC cost/multiplier are contract-spec research assumptions (verified=False)"]}
    (OUT / "mgc_sizing_eval.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps(o["summary"], indent=1))
    for r in o["rows"]:
        print(r["direction"], r["stop_distance_bps"], "GC:", r["GC"]["violations"], r["GC"]["quantity_contracts"],
              "| MGC:", r["MGC"]["violations"], r["MGC"]["quantity_contracts"], r["MGC"]["one_contract_notional_usd"])
    print(o["rows"][0]["MGC"]["rulebook"] if o["rows"] else "no rows")
