"""Paper setup autopilot + shadow collector. All bars are hand-built SYNTHETIC fixtures; the registry used for
proposals is the constant-probability TEST FIXTURE from test_predict (not a fitted model)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.autopilot.control import StepUpRequired
from atlas.autopilot.setups import SetupAutopilot, Stream
from atlas.control.setup_autopilot_approval import approve_request
from atlas.features.price_action.replay import ReplayConfig
from atlas.models.shadow import ShadowCollector, iso_week
from atlas.risk.safe_stop import new_safe_stop
from tests.price_action.test_price_action import O, _orb_long_bars
from tests.price_action.test_predict import synthetic_setup_registry
from tests.price_action.test_replay import B

BARS = _orb_long_bars() + [B(O + 3 * 3600, 103.2, 103.5, 102.5, 103.1), B(O + 4 * 3600, 103.1, 107.5, 103.0, 107.2)]
END = O + 6 * 3600


def _approve(ap, rid, actor, verified):
    return approve_request(ap.store, ap.audit, rid, actor, verified, ap.expected_owner, ap.safe_stop.engaged)


def _ap(tmp_path, registry=None, model_version=None, bars=BARS, **kw):
    # These SYNTHETIC bars carry no volume, so the section-25 paper realism default would (correctly) never fill.
    # The legacy idealized fill model is pinned here to keep exercising the decision/booking path.
    kw.setdefault("replay_cfg", ReplayConfig(cost_bps=0.0))
    return SetupAutopilot(lambda s, tf: list(bars), [Stream("SPY", 3600, "us_equity_rth")],
                          shadow=ShadowCollector(tmp_path / "shadow.jsonl"), registry=registry,
                          model_version=model_version, cost_bps=0.0, **kw)


def _on(ap):
    rid = ap.request_on("owner", "test")["id"]
    _approve(ap, rid, "owner", True)


def test_off_by_default_and_on_requires_owner_step_up(tmp_path):
    ap = _ap(tmp_path)
    assert ap.tick(END)["state"] == "off" and not ap.engines[ap.streams[0]].events
    rid = ap.request_on("mcp-client")["id"]
    with pytest.raises(StepUpRequired):
        _approve(ap, rid, "owner", False)
    with pytest.raises(StepUpRequired):
        _approve(ap, rid, "someone", True)
    assert not ap.is_on()
    _approve(ap, rid, "owner", True)
    assert ap.is_on() and ap.status()["mode"] == "paper"
    ap.switch_off("owner")
    assert not ap.is_on() and ap.tick(END)["state"] == "off"
    events = [e["event"] for e in ap.audit.entries()]
    assert events.count("setup_autopilot.approve_refused") == 2 and "setup_autopilot.switched_on" in events
    assert ap.audit.verify() > 0


def test_empty_registry_runs_and_abstains_with_reasons(tmp_path):
    ap = _ap(tmp_path); _on(ap)
    out = ap.tick(END)
    assert out["state"] == "on" and out["bars"] == len(BARS)
    assert out["decisions"] and all(d["decision"] == "abstain" for d in out["decisions"])
    assert all("no_validated_model" in d["reasons"] for d in out["decisions"])
    assert ap.connector.receipts == [] and ap.cp.order_history == []
    recs = ap.shadow.records()
    assert recs and recs[0]["decision"] == "abstain" and recs[0]["resolution"]["outcome"] == "target"  # counterfactual
    wk = ap.shadow.weekly()[0]
    assert wk["abstained"] == wk["candidates"] and wk["abstain_reasons"]["no_validated_model"] >= 1
    assert ap.shadow.registry_record(wk["week"]) is None          # nothing scored -> nothing invented
    assert ap.tick(END)["bars"] == 0                              # bars are consumed once


def test_real_founder_rulebook_authorizes_paper_order(tmp_path):
    """REAL pinned founder rulebook (max_holding_seconds=86400, owner decision 2026-10-23) + the labelled TEST-ONLY
    constant-probability model fixture: the control plane approves, a paper order is placed, the target exit is booked."""
    ap = _ap(tmp_path, registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1"); _on(ap)
    assert ap.cp.open_rulebook.max_holding_seconds == 86400
    (d,) = [x for x in ap.tick(END)["decisions"] if x["detector"].startswith("orb")]
    assert d["decision"] == "proposal_authorized", d
    assert ap.connector.receipts[0]["execution_mode"] == "paper"
    assert ap.cp.current_equity_usd > Decimal("100000")             # target hit -> paper gain booked
    assert not any(p.status == "open" for p in ap.cp.open_positions)
    rec = ap.shadow.registry_record(iso_week(BARS[0].end))
    assert rec is not None and rec["n"] == 1 and rec["brier"] == pytest.approx(0.16)


def test_real_founder_rulebook_force_closes_after_one_day(tmp_path):
    """SYNTHETIC bars that fill and then drift between stop (101) and target (107) for 30 h. The replay bar-count
    timeout is widened (test-only) so the only exit can be the founder 1-day holding limit."""
    from atlas.features.price_action.replay import ReplayConfig
    drift = [B(O + 3 * 3600, 103.2, 103.5, 102.5, 103.1)] + [B(O + h * 3600, 103.1, 103.8, 102.6, 103.4) for h in range(4, 34)]
    bars = _orb_long_bars() + drift
    ap = _ap(tmp_path, registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1", bars=bars); _on(ap)
    ap.rcfg = ReplayConfig(cost_bps=0.0, max_hold_bars=10_000)
    (d,) = [x for x in ap.tick(O + 40 * 3600)["decisions"] if x["detector"].startswith("orb")]
    assert d["decision"] == "proposal_authorized", d
    assert ap.connector.receipts and ap.connector.receipts[0]["execution_mode"] == "paper"
    (r,) = ap.shadow.records()
    res = r["resolution"]
    assert res["outcome"] == "max_holding", res
    assert res["exit_at"] == O + 26 * 3600     # fill bar starts O+3h; the bar ending at fill+24h triggers the close
    assert not any(p.status == "open" for p in ap.cp.open_positions)


def test_founder_safe_stop_trips_flattens_and_blocks_restart(tmp_path):
    ks = new_safe_stop()
    ap = _ap(tmp_path, safe_stop=ks); _on(ap)
    ap.cp.current_equity_usd = Decimal("97900")                   # 2.1% below start of day (synthetic)
    out = ap.tick(END)
    assert out["state"] == "halted" and out["halted"].startswith("founder_daily_loss")
    assert ks.engaged and not ap.is_on()
    with pytest.raises(PermissionError):
        _approve(ap, ap.request_on("owner")["id"], "owner", True)


def test_drawdown_limit_and_external_safe_stop(tmp_path):
    ap = _ap(tmp_path); _on(ap)
    ap.cp.start_of_day_equity_usd = ap.cp.current_equity_usd = Decimal("89000")   # 11% below initial (synthetic)
    assert ap.tick(END)["halted"].startswith("founder_drawdown")
    ks = new_safe_stop(); ap2 = _ap(tmp_path, safe_stop=ks); _on(ap2)
    ks.engage("owner_button", channel="test")
    assert ap2.tick(END)["halted"].startswith("safe_stop_engaged") and not ap2.is_on()


def test_feed_error_is_audited_not_traded(tmp_path):
    def bad(s, tf):
        raise RuntimeError("feed down")
    ap = SetupAutopilot(bad, [Stream("SPY", 3600, "us_equity_rth")]); _on(ap)
    assert ap.tick(END)["bars"] == 0
    assert any(e["event"] == "setup_autopilot.feed_error" for e in ap.audit.entries())


def test_owner_cli_approval_switches_on_through_shared_state(tmp_path):
    import time as _t
    from atlas.control.owner_cli import run
    from atlas.risk.stepup import totp
    from pathlib import Path
    CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "founder"
    PW = "correct horse battery staple"   # test-only passphrase
    st, au = str(tmp_path / "state.sqlite"), str(tmp_path / "audit.sqlite")
    base = ["--config", str(CONFIG_DIR), "--state", st, "--audit", au, "--stepup", str(tmp_path / "su.json")]
    out: list[str] = []
    run(base + ["init-stepup"], prompt=lambda: (PW, PW), out=out.append)
    secret = out[-1].rsplit(" ", 1)[-1]
    ap = SetupAutopilot(lambda s, tf: list(BARS), [Stream("SPY", 3600, "us_equity_rth")], state_db=st, audit_db=au,
                        expected_owner="masharai")
    rid = ap.request_on("key:x")["id"]
    assert run(base + ["setup-autopilot-approve", rid], prompt=lambda: ("wrong passphrase!!", "000000"), out=out.append) == 3
    assert not ap.is_on()
    assert run(base + ["setup-autopilot-approve", rid], prompt=lambda: (PW, totp(secret, _t.time())), out=out.append) == 0
    assert ap.is_on()


def test_paper_realism_is_default_and_zero_volume_never_fills(tmp_path):
    """Section 25: with no replay_cfg the autopilot uses latency + trade-through + participation. Zero-volume
    SYNTHETIC bars therefore never fill: no paper P&L is invented."""
    ap = SetupAutopilot(lambda s, tf: list(BARS), [Stream("SPY", 3600, "us_equity_rth")],
                        shadow=ShadowCollector(tmp_path / "shadow.jsonl"), registry=synthetic_setup_registry(0.6),
                        model_version="synthetic-setup-v1", cost_bps=0.0)
    assert ap.rcfg.latency_bars == 1 and ap.rcfg.limit_fill == "trade_through"
    _on(ap)
    ap.tick(END)
    assert ap.cp.current_equity_usd == Decimal("100000")
    assert "reentry_loss_governor" in ap.risk_view()


def test_oms_loss_cap_blocks_after_realized_losses(tmp_path):
    """Section 13 at the OMS: realized paper losses for the day (fed via record_outcome) refuse new proposals."""
    from datetime import datetime, timezone
    ap = _ap(tmp_path, registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1"); _on(ap)
    day = datetime.fromtimestamp(BARS[0].end, tz=timezone.utc).date().isoformat()
    for fam in ("a", "b", "c"):
        ap.loss_gov.record_outcome(fam, day, -1.1)
    ds = ap.tick(END)["decisions"]
    assert ds and all(d["decision"] == "reentry_loss_cap" for d in ds)
    assert ap.connector.receipts == [] and ap.cp.current_equity_usd == Decimal("100000")
    assert any(e["event"] == "setup_autopilot.decision" for e in ap.audit.entries())


def test_partial_entry_books_real_filled_quantity(tmp_path):
    """Section 25 + control plane partial close: a volume-capped partial entry cancels the unfilled remainder via
    the reduce-only partial close (zero P&L) and the exit is booked on the REAL filled notional."""
    ap = _ap(tmp_path, registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1"); _on(ap)
    from atlas.features.price_action.replay import try_fill as real_try_fill
    import atlas.autopilot.setups as S

    def half_fill(t, b, cfg=None, age=0):
        ok = real_try_fill(t, b, cfg, age)
        if ok:
            t.fill_ratio = 0.5
        return ok
    S.try_fill, orig = half_fill, S.try_fill
    try:
        ap.tick(END)
    finally:
        S.try_fill = orig
    log = " ".join(ap.cp.audit_log)
    assert "position_reduced" in log and "reason=partial_fill_remainder_cancelled" in log
    events = [e for e in ap.audit.entries() if e["event"] == "setup_autopilot.partial_fill"]
    assert events and events[0]["payload"]["fill_ratio"] == 0.5 and events[0]["payload"]["control_plane"] == "reduced"
    assert not any(p.status == "open" for p in ap.cp.open_positions)
    full = _ap(tmp_path / "full", registry=synthetic_setup_registry(0.6), model_version="synthetic-setup-v1"); _on(full)
    full.tick(END)
    gain_half, gain_full = ap.cp.current_equity_usd - Decimal("100000"), full.cp.current_equity_usd - Decimal("100000")
    assert gain_full > 0 and abs(gain_half - gain_full / 2) <= Decimal("0.02")   # real half quantity -> half the P&L
