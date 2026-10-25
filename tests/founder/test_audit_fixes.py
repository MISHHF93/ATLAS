"""Regression tests for findings in trading-bot-review/audit.md."""
from __future__ import annotations

import math
import multiprocessing as mp
from datetime import date, datetime, timezone

import pytest

from founder_conftest import CONFIG_DIR, intent, state
from atlas.governance.audit import AuditLog
from atlas.risk.approvals import ApprovalQueue
from atlas.risk.engine import _loss_pct
from atlas.risk.killswitch import KillSwitch
from atlas.risk.state_store import StateStore
from atlas.risk.trail import dedupe, merge_trail, outcome_counts


# ---- risk engine edge cases
def test_loss_pct_guards():
    assert _loss_pct(0.0, 0.0) == 0.0          # no capital: nothing to lose, no ZeroDivisionError
    assert _loss_pct(100.0, math.nan) == 100.0  # non-finite => fail closed
    assert _loss_pct(math.inf, 1.0) == 100.0
    assert _loss_pct(100.0, 90.0) == pytest.approx(10.0)


def test_zero_anchor_does_not_crash_check_breaches(engine):
    s = state().model_copy(update={"start_of_day_equity": 0.0, "start_of_week_equity": 0.0, "peak_equity": 0.0})
    engine.check_breaches(s)  # used to raise ZeroDivisionError outside the fail-closed wrapper
    assert not engine.ks.engaged


class _BadFx:
    def rate(self, a, b):
        return 0.0


def test_zero_fx_rate_rejects_not_crashes(engine):
    engine.fx = _BadFx()
    d = engine.evaluate(intent(currency="USD", fx_rate_to_base=1.37), state())
    assert not d.approved and any("fx" in r for r in d.reasons)


def test_session_rolls_on_toronto_date(tmp_path):
    from atlas.mcp.trading.service import build_service
    svc = build_service(CONFIG_DIR, state_path=str(tmp_path / "s.sqlite"))
    svc.engine.roll_session("2026-10-15")
    svc.store.set("daily_halt_session", "2026-10-15")
    assert svc.engine.daily_halted
    # 2026-10-16 02:00 UTC is still Oct 15 in Toronto: no roll
    assert not svc.ensure_session(datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)) or svc.engine.session == "2026-10-15"
    assert svc.engine.session == "2026-10-15"
    assert svc.ensure_session(datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc))
    assert svc.engine.session == "2026-10-16" and not svc.engine.daily_halted
    assert svc.broker.today == date(2026, 10, 16)


def test_week_anchor_uses_iso_year():
    from atlas.mcp.trading.service import build_service
    b = build_service(CONFIG_DIR).broker
    b.roll_day(date(2026, 1, 5)); b.start_of_week_equity = 1.0
    b.roll_day(date(2027, 1, 6))  # same ISO week number, next year => new week anchor
    assert b.start_of_week_equity != 1.0


# ---- state store / approvals / kill switch races
def _claim_worker(path, aid, q):
    st = StateStore(path)
    aq = ApprovalQueue(3600, "owner", AuditLog(), store=st)
    q.put(len(aq.process_owner_approved(lambda i: {"executes": True})))


def test_approved_item_executes_once_across_processes(tmp_path):
    path = str(tmp_path / "s.sqlite")
    aq = ApprovalQueue(3600, "owner", AuditLog(), store=StateStore(path))
    p = aq.enqueue(intent())
    aq.mark_owner_approved(p.approval_id, "owner", True)
    if "fork" in mp.get_all_start_methods():
        ctx = mp.get_context("fork"); q = ctx.Queue()
        ps = [ctx.Process(target=_claim_worker, args=(path, p.approval_id, q)) for _ in range(4)]
        [x.start() for x in ps]; [x.join(30) for x in ps]
        counts = sorted(q.get() for _ in ps)
    else:
        import subprocess
        import sys
        code = (
            "import sys; from atlas.risk.state_store import StateStore; "
            "from atlas.governance.audit import AuditLog; from atlas.risk.approvals import ApprovalQueue; "
            "aq = ApprovalQueue(3600, 'owner', AuditLog(), store=StateStore(sys.argv[1])); "
            "print(len(aq.process_owner_approved(lambda i: {'executes': True})))"
        )
        ps = [subprocess.Popen([sys.executable, "-c", code, path], stdout=subprocess.PIPE, text=True) for _ in range(4)]
        counts = sorted(int(proc.communicate(timeout=30)[0].strip()) for proc in ps)
    assert counts == [0, 0, 0, 1]
    assert aq.get(p.approval_id).status == "executed"


def test_execute_exception_does_not_strand_item():
    aq = ApprovalQueue(3600, "owner", AuditLog())
    p = aq.enqueue(intent()); aq.mark_owner_approved(p.approval_id, "owner", True)
    aq.process_owner_approved(lambda i: 1 / 0)
    assert aq.get(p.approval_id).status == "rejected"


def test_reject_requires_owner():
    aq = ApprovalQueue(3600, "owner", AuditLog())
    p = aq.enqueue(intent())
    with pytest.raises(PermissionError):
        aq.reject(p.approval_id, "mallory")
    aq.reject(p.approval_id, "owner")
    assert aq.get(p.approval_id).status == "rejected"


def test_kill_switch_first_engage_wins_and_reset_works(tmp_path):
    st = StateStore(str(tmp_path / "s.sqlite"))
    a, b = KillSwitch(AuditLog(), store=st), KillSwitch(AuditLog(), store=StateStore(st.path))
    a.engage("first", "cli"); b.engage("second", "watchdog")
    assert b.reason == "first" and a.engaged and b.engaged
    a.reset("owner", True, "owner")
    assert not b.engaged


def test_items_prefix_is_literal():
    st = StateStore()
    st.set("approval:1", 1); st.set("approvalX1", 2)
    assert list(st.items("approval_")) == []  # '_' no longer a LIKE wildcard


# ---- decision-trail dedupe
def _t(sym, final, ts, stages=(("cost", "drop"),)):
    return {"symbol": sym, "side": "buy", "sleeve": "core", "final": final, "ts": ts,
            "stages": [{"stage": s, "effect": e} for s, e in stages]}


def test_trail_dedupe_collapses_repeats_and_keeps_changes():
    raw = [_t("A", "dropped at cost", f"d{i}") for i in range(5)] + [_t("B", "dropped at cost", "x")] \
        + [_t("A", "submitted", "d5", (("cost", "pass"),)), _t("A", "dropped at cost", "d6")]
    out = dedupe(raw)
    assert [(t["symbol"], t["final"], t.get("repeat", 1)) for t in out] == [
        ("A", "dropped at cost", 5), ("B", "dropped at cost", 1), ("A", "submitted", 1), ("A", "dropped at cost", 1)]
    assert out[0]["first_ts"] == "d0" and out[0]["ts"] == "d4"
    assert outcome_counts(out) == {"dropped at cost": 7, "submitted": 1}


def test_trail_merge_interleaved_symbols_and_cap():
    h = merge_trail([], [_t("A", "dropped at cost", "1"), _t("B", "dropped at cost", "1")])
    h = merge_trail(h, [_t("A", "dropped at cost", "2"), _t("B", "dropped at cost", "2")])
    assert len(h) == 2 and all(t["repeat"] == 2 for t in h)
    assert len(merge_trail([], [_t(str(i), "x", "1") for i in range(20)], cap=5)) == 5


def test_dashboard_static_a11y_and_dedupe_api():
    import json as _json
    from importlib import resources
    from test_dashboard import TOKEN, free_port, req
    from atlas.ops.dashboard.server import serve_in_thread
    from atlas.mcp.trading.service import build_service
    html = resources.files("atlas.ops.dashboard").joinpath("static", "index.html").read_text()
    for needle in ('class="skip"', 'id="main"', 'aria-live="polite"', 'for="decfilter"', 'id="eqempty"', 'aria-label="Kill switch'):
        assert needle in html
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    t = {"symbol": "A", "side": "buy", "sleeve": "core", "final": "dropped at cost", "stages": [{"stage": "cost", "effect": "drop"}]}
    svc.store.set("decision_trail", [dict(t, ts=f"2026-10-0{i}") for i in range(1, 6)])  # legacy un-merged store
    port = free_port(); srv = serve_in_thread(svc, port, TOKEN)
    try:
        code, body, _ = req(port, "/api/decisions")
        d = _json.loads(body)
        assert code == 200 and len(d["decisions"]) == 1 and d["decisions"][0]["repeat"] == 5
        assert d["outcomes"] == {"dropped at cost": 5}
        code, _, _ = req(port, "/api/kill", "POST", b"{}", {"Content-Length": "abc", "Content-Type": "application/json",
                                                          "X-Dashboard-Token": TOKEN})
        assert code == 400  # malformed Content-Length: clean 400, not a handler crash
        assert not svc.ks.engaged
    finally:
        srv.shutdown(); srv.server_close()


def test_state_db_is_owner_only(tmp_path):
    import os
    p = tmp_path / "s.sqlite"; StateStore(str(p))
    assert oct(os.stat(p).st_mode)[-3:] == "600"


def test_onepager_payments_panel_is_read_only(tmp_path):
    import ast, inspect, json as _json
    from importlib import resources
    from atlas.ops.dashboard import server
    html = resources.files("atlas.ops.dashboard").joinpath("static", "index.html").read_text()
    for needle in ('role="tablist"', 'id="p-decisions"', 'id="p-audit"', 'id="paypending"', 'id="models"', 'id="eqchart"'):
        assert needle in html
    # the dashboard may import ONLY the read-only BalanceView from the payments package
    mods = {n.module for n in ast.walk(ast.parse(inspect.getsource(server))) if isinstance(n, ast.ImportFrom) and n.module}
    assert {m for m in mods if m.startswith("atlas.ledgers")} == {"atlas.ledgers.readonly"}
    assert server.payments_summary(str(tmp_path / "missing.sqlite"))["available"] is False
    from atlas.ledgers.db import connect
    p = str(tmp_path / "p.sqlite"); c = connect(p)
    from atlas.ledgers.stepup import Approvers
    from atlas.ledgers.treasury import Treasury
    Treasury(c, Approvers(tmp_path / "a.json")); c.close()
    before = open(p, "rb").read()
    s = server.payments_summary(p)
    assert s["available"] and s["read_only"] and s["kill_switch"] is False
    assert open(p, "rb").read() == before  # opened mode=ro: file untouched
    _json.dumps(s, default=str)
