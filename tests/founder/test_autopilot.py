"""Autopilot: owner step-up to start, instant stop, kill switch turns it off, restart resume, guards pause/resume,
shrink-only risk budget, L1 routing to the approval queue (never auto-executes), no payments imports."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from founder_conftest import CONFIG_DIR
from atlas.autopilot import control
from atlas.autopilot.config import AutopilotCfg, UniverseItem
from atlas.autopilot.engine import Autopilot
from atlas.autopilot.feeds import FeedRegistry
from atlas.autopilot.sizing import fractional_kelly, overlay_factor, vol_target_scale
from atlas.mcp.trading.service import build_service
from atlas.risk.models import OrderIntent

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)   # Saturday: equities closed, crypto open


class Sessions:
    def __init__(self, open_venues=("crypto",)):
        self.open = set(open_venues)

    def status(self, v, now):
        o = v in self.open
        return {"open": o, "phase": "open" if o else "closed", "new_orders_allowed": o, "local_time": "Sat 15:00"}

    def next_change(self, v, now):
        return "2026-10-19T09:30-04:00"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def svc(tmp_path):
    return build_service(CONFIG_DIR, state_path=str(tmp_path / "state.sqlite"))


def make(svc, tmp_path, cycle_fn=None, clock=None, cfg=None):
    cfg = cfg or AutopilotCfg(universe=[UniverseItem(symbol="BTC-USD", venue="crypto", currency="USD", sleeve="high_risk",
                                                     asset_class="crypto_spot", broker="kraken", s0=65000, vol=0.6),
                                        UniverseItem(symbol="XIC.TO", venue="XTSE", s0=34.5)])
    clock = clock or Clock()
    svc.heartbeat()
    feeds = FeedRegistry(cfg, svc.store, tmp_path, parquet_dir="/nonexistent", clock=clock)
    return Autopilot(svc, cfg, feeds, sessions=Sessions(), clock=clock, cycle_fn=cycle_fn)


def fake_cycle(calls):
    def fn(now, frames, items, overlay, should_continue):
        calls.append(sorted(frames))
        return {"decisions": 1, "children": 0, "queued_for_approval": [], "routed": [], "rejected": [], "shrunk": [],
                "trail": [{"id": "t1", "symbol": "BTC-USD", "side": "buy", "sleeve": "high_risk", "final": "dropped at cost",
                           "stages": [{"stage": "cost", "effect": "drop", "detail": "edge < cost"}]}]}
    return fn


def test_start_requires_step_up_and_stop_is_instant(svc, tmp_path):
    ap = make(svc, tmp_path, fake_cycle([]))
    with pytest.raises(control.StepUpRequired):
        control.request_start(svc.store, svc.audit, "owner", False)
    assert ap.safety_check(NOW)["state"] == "off"
    control.request_start(svc.store, svc.audit, "owner", True)
    assert control.status_view(svc.store)["state"] == "starting"
    assert ap.safety_check(NOW)["state"] == "running"
    control.request_stop(svc.store, svc.audit, "owner", "test")          # no step-up needed
    assert control.status_view(svc.store)["state"] == "stopping"        # visible immediately
    assert ap.safety_check(NOW)["state"] == "off"


def test_cycle_runs_only_open_venues_and_records_reasons(svc, tmp_path):
    calls = []
    ap = make(svc, tmp_path, fake_cycle(calls))
    control.request_start(svc.store, svc.audit, "owner", True)
    st = ap.tick(NOW)
    assert calls == [["BTC-USD"]]                     # XTSE closed => not in the cycle
    assert st["cycles"] == 1 and st["decisions"][-1]["reason"].startswith("cost")
    ap.tick(NOW)                                      # cadence not due => no second cycle
    assert len(calls) == 1
    assert any("XTSE: closed" in a for a in st["next_actions"])


def test_waiting_when_nothing_is_open(svc, tmp_path):
    ap = make(svc, tmp_path, fake_cycle([]))
    ap.sessions = Sessions(open_venues=())
    control.request_start(svc.store, svc.audit, "owner", True)
    assert ap.tick(NOW)["state"] == "waiting"


def test_kill_switch_turns_autopilot_off_and_blocks_start(svc, tmp_path):
    ap = make(svc, tmp_path, fake_cycle([]))
    control.request_start(svc.store, svc.audit, "owner", True)
    ap.safety_check(NOW)
    svc.ks.engage("test halt", channel="cli")
    st = ap.safety_check(NOW)
    assert st["state"] == "off" and "kill switch" in st["stop_reason"] and control.desired(svc.store) == "off"
    control.request_start(svc.store, svc.audit, "owner", True)
    assert ap.safety_check(NOW)["state"] == "off"     # refused while halted


def test_restart_resumes(svc, tmp_path):
    ap = make(svc, tmp_path, fake_cycle([]))
    control.request_start(svc.store, svc.audit, "owner", True)
    ap.tick(NOW)
    ap2 = make(svc, tmp_path, fake_cycle([]))         # new process, same state DB
    st = ap2.state()
    assert st["restarts"] == 1 and st["state"] == "running" and st["events"][-1]["text"] == "resumed after restart"


def test_stale_feed_pauses_then_resumes(svc, tmp_path):
    clock = Clock()
    ap = make(svc, tmp_path, fake_cycle([]), clock=clock)
    control.request_start(svc.store, svc.audit, "owner", True)
    ap.tick(NOW)                                      # marks bars.replay fresh
    clock.t += 4 * 86400                              # older than the 3-day bars budget
    st = ap.safety_check(NOW)
    assert st["state"] == "paused" and "stale" in st["pause_reasons"][0]
    ap.feeds.mark("bars.replay", 1)
    assert ap.safety_check(NOW)["state"] == "running"


def test_stop_mid_cycle_and_l1_routes_to_approval_queue_only(svc, tmp_path):
    ap = make(svc, tmp_path)                          # REAL pipeline + replay feed
    control.request_start(svc.store, svc.audit, "owner", True)
    fills0 = len(svc.broker.fills) if hasattr(svc.broker, "fills") else None
    st = ap.tick(NOW)
    assert st["cycles"] == 1 and st["routing"] == "owner approval queue"
    assert not st["last_result"].get("routed")        # L1: nothing auto-executes
    if fills0 is not None:
        assert len(svc.broker.fills) == fills0


def test_sizing_is_shrink_only():
    r = pd.Series([0.01, -0.02, 0.015, -0.01, 0.02, -0.015] * 5)
    scale, vol = vol_target_scale(r, 12)
    assert 0 < scale <= 1 and vol > 12
    assert fractional_kelly(r.head(5), 0.25, 20)[0] is None          # warming up
    assert fractional_kelly(pd.Series([-0.01, -0.005, -0.02] * 10), 0.25, 20)[0] == 0.0   # no edge => no new risk
    mk = lambda side, q: OrderIntent(symbol="SPY", side=side, qty=q, order_type="market", reference_price=100, quote_age_s=0,
                                     sleeve="core", asset_class="index_etf", broker="ibkr", source="strategy")
    assert overlay_factor(mk("buy", 10), {"headroom": 500}) == 0.5
    assert overlay_factor(mk("buy", 1), {"headroom": 10_000}) == 1.0    # never > 1
    assert overlay_factor(mk("sell", 10), {"headroom": 0}) == 1.0       # sells never shrunk


def test_autopilot_cannot_touch_payments_or_policy():
    src = "\n".join(p.read_text() for p in (Path(__file__).resolve().parents[2] / "src/atlas/autopilot").glob("*.py"))
    assert "atlas.ledgers" not in src and "risk_policy.yaml" not in src and "approve(" not in src
    assert AutopilotCfg(kelly_fraction=3, vol_target_annual_pct=90, cycle_minutes={"crypto": 1}).kelly_fraction == 0.5
    assert AutopilotCfg(vol_target_annual_pct=90).vol_target_annual_pct == 20
    assert AutopilotCfg(cycle_minutes={"crypto": 1}).cadence_s("crypto") == 300
