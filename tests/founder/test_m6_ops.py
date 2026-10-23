"""M6 ops: sessions (follow-the-sun), jobs, daily summary, kill-switch drill, health,
dashboard equity/audit/markets, runner, Docker files (static checks; no daemon in CI)."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from founder_conftest import CONFIG_DIR
from atlas.mcp.trading import build_service
from atlas.ops.drill import run_drill
from atlas.ops.equity import equity_series, record_equity
from atlas.ops.health import health
from atlas.ops.jobs import JobScheduler, last_slot, parse
from atlas.ops.sessions import SessionModel
from atlas.ops.summary import daily_summary, write_daily_summary
from atlas.risk.state_store import StateStore

ROOT = Path(__file__).resolve().parents[1]
TOR = ZoneInfo("America/Toronto")
U = lambda *a: datetime(*a, tzinfo=timezone.utc)  # noqa: E731
ORDER = dict(symbol="SPY", side="buy", qty=10, order_type="limit", limit_price=100, reference_price=100,
             sleeve="core", asset_class="index_etf", broker="alpaca", quote_age_s=1.0)


@pytest.fixture(scope="module")
def sm():
    from atlas.control.policy import load_all
    return SessionModel(load_all(CONFIG_DIR).schedule.model_dump())


# ---------------------------------------------------------------- sessions
def test_weekday_midday_toronto(sm):
    s = {r["venue"]: r for r in sm.strip(U(2026, 10, 14, 15, 0), with_next=False)["venues"]}
    assert s["XNYS_XNAS"]["open"] and s["XNYS_XNAS"]["phase"] == "regular" and s["XTSE"]["open"]
    assert s["crypto"]["open"] and s["fx"]["open"] and not s["XTKS"]["open"]
    assert "cme_globex" not in s  # disabled (Phase 5)


def test_weekend_mode_only_crypto_new_orders(sm):
    st = sm.strip(U(2026, 10, 17, 15, 0), with_next=False)
    assert st["weekend_mode"] and st["active"] == ["crypto"]
    c = next(r for r in st["venues"] if r["venue"] == "crypto")
    assert c["size_mult"] == 0.5  # weekend low liquidity


def test_tokyo_lunch_break_closed(sm):
    assert sm.can_trade("XTKS", U(2026, 10, 14, 3, 0))[0] is False   # 12:00 JST
    ok, mult = sm.can_trade("XTKS", U(2026, 10, 14, 1, 0))           # 10:00 JST
    assert ok and mult == 1.0


def test_us_holiday_closed_and_unknown_venue_fails_closed(sm):
    assert sm.can_trade("XNYS_XNAS", U(2026, 11, 26, 15, 0)) == (False, 0.0)  # Thanksgiving
    assert sm.can_trade("NOPE", U(2026, 10, 14, 15, 0)) == (False, 0.0)


def test_follow_the_sun_ordering_and_next_change(sm):
    st = sm.strip(U(2026, 10, 14, 15, 0))
    opens = [r["open"] for r in st["venues"]]
    assert opens == sorted(opens, reverse=True)
    nyse = next(r for r in st["venues"] if r["venue"] == "XNYS_XNAS")
    assert nyse["next_change_et"].startswith("2026-10-14T16:00")


def test_crypto_overnight_low_liquidity(sm):
    assert sm.can_trade("crypto", U(2026, 10, 14, 3, 0)) == (True, 0.5)
    assert sm.can_trade("crypto", U(2026, 10, 14, 12, 0)) == (True, 1.0)


# ---------------------------------------------------------------- jobs
def test_parse_and_slots():
    assert parse("17:30") == ("daily", None, 17, 30) and parse("Sat 11:00 (paper)") == ("weekly", 5, 11, 0)
    assert parse(60) == ("interval", 60.0)
    now = datetime(2026, 10, 16, 15, 7, tzinfo=TOR)  # Fri
    assert last_slot(parse("17:30"), now) == datetime(2026, 10, 15, 17, 30, tzinfo=TOR)
    assert last_slot(parse("Sat 11:00"), now) == datetime(2026, 10, 10, 11, 0, tzinfo=TOR)


def test_scheduler_runs_once_per_slot_and_persists(tmp_path):
    from atlas.control.policy import load_all
    sched = load_all(CONFIG_DIR).schedule.model_dump()
    runs = []
    store = StateStore(str(tmp_path / "s.sqlite"))
    handlers = {k: (lambda k: lambda now: runs.append(k))(k) for k in ("daily_summary", "kill_switch_drill", "learning_loop")}
    js = JobScheduler.from_schedule(sched, handlers, store)
    t = datetime(2026, 10, 16, 17, 31, tzinfo=TOR)
    assert js.tick(t) == ["daily_summary"] and js.tick(t + timedelta(minutes=5)) == []
    js2 = JobScheduler.from_schedule(sched, handlers, StateStore(str(tmp_path / "s.sqlite")))  # restart
    assert js2.tick(t + timedelta(minutes=10)) == []
    sat = datetime(2026, 10, 17, 11, 5, tzinfo=TOR)
    assert set(js2.tick(sat)) == {"kill_switch_drill", "learning_loop"}
    assert js2.tick(datetime(2026, 10, 18, 9, 0, tzinfo=TOR)) == []  # Sat slots too old (grace)


def test_failing_job_is_audited_not_raised():
    from atlas.governance.audit import AuditLog
    a = AuditLog(":memory:")
    js = JobScheduler(StateStore(), a)
    js.add("boom", "17:30", lambda now: 1 / 0)
    assert js.tick(datetime(2026, 10, 16, 17, 31, tzinfo=TOR)) == ["boom"]
    assert "error" in a.entries("ops.job")[0]["payload"]["status"]


# ---------------------------------------------------------------- service-based
@pytest.fixture
def svc():
    s = build_service(CONFIG_DIR)
    s.broker.clock = lambda: datetime.now(TOR)
    s.heartbeat()
    return s


def _buy(s):
    r = s.propose_order(**ORDER)
    s.owner_approve(r["approval_id"], "masharai", True)


def test_daily_summary(svc, tmp_path):
    _buy(svc)
    svc.broker.mark("SPY", 101)
    today = datetime.now(TOR).date()
    s = daily_summary(svc, today)
    assert s["fills"] == 1 and s["sleeves"]["core"]["positions"] == 1 and s["sleeves"]["core"]["unrealized"] > 0
    assert s["autonomy"]["live_locked"] and s["mode"] == "paper"
    md = write_daily_summary(svc, today, tmp_path)
    assert md.read_text().startswith(f"# Daily summary {today}") and (tmp_path / f"daily-{today}.json").exists()


def test_kill_switch_drill_isolated(svc):
    r = run_drill(CONFIG_DIR, svc.audit)
    assert r["passed"], r
    assert not svc.ks.engaged  # the real service is untouched
    assert svc.audit.entries("ops.drill")[0]["payload"]["passed"]


def test_equity_series_bounded_and_coalesced(svc):
    t = U(2026, 10, 16, 15, 0)
    record_equity(svc, t); record_equity(svc, t + timedelta(seconds=10)); record_equity(svc, t + timedelta(minutes=2))
    assert len(equity_series(svc)) == 2


def test_health(tmp_path, svc):
    from atlas.risk.watchdog_proc import write_core_heartbeat
    p = str(tmp_path / "state.sqlite")
    write_core_heartbeat(StateStore(p))
    h = health(svc, p, str(CONFIG_DIR))
    assert h["ok"], h
    write_core_heartbeat(StateStore(p), now=0)
    assert not health(None, p, str(CONFIG_DIR))["ok"]


def test_health_cli_exit_codes(tmp_path):
    from atlas.ops.health import main
    with pytest.raises(SystemExit) as e:
        main(["--config", str(CONFIG_DIR), "--state", str(tmp_path / "x.sqlite")])
    assert e.value.code == 1  # no core heartbeat yet


def test_runner_one_iteration(tmp_path):
    from atlas.ops.runner import main
    main(["--config", str(CONFIG_DIR), "--var", str(tmp_path), "--iterations", "1"])
    st = StateStore(str(tmp_path / "state.sqlite"))
    assert st.get("core_heartbeat") and st.get("equity_series")
    assert (tmp_path / "audit.sqlite").exists() and (tmp_path / "tax.sqlite").exists()


# ---------------------------------------------------------------- dashboard
def test_dashboard_new_endpoints(svc):
    from test_dashboard import free_port, req
    from atlas.ops.dashboard.server import serve_in_thread
    record_equity(svc, U(2026, 10, 16, 15, 0))
    port = free_port(); srv = serve_in_thread(svc, port, None)
    try:
        c, b, _ = req(port, "/api/equity"); assert c == 200 and len(json.loads(b)) == 1
        c, b, _ = req(port, "/api/audit?limit=5"); rows = json.loads(b)
        assert c == 200 and 1 <= len(rows) <= 5 and rows[0]["seq"] >= rows[-1]["seq"]
        c, b, _ = req(port, "/api/markets"); m = json.loads(b)
        assert c == 200 and "venues" in m and "weekend_mode" in m
        c, b, _ = req(port, "/healthz"); assert c == 200 and json.loads(b)["ok"]
        svc.kill_switch("t")
        assert req(port, "/healthz")[0] == 503
        c, b, _ = req(port, "/"); assert b"eqchart" in b and b"markets" in b and b"audit" in b
    finally:
        srv.shutdown(); srv.server_close()


def test_dashboard_refuses_non_loopback_bind_outside_container(svc, monkeypatch):
    from atlas.ops.dashboard.server import make_server
    monkeypatch.delenv("ATLAS_IN_CONTAINER", raising=False)
    with pytest.raises(ValueError, match="loopback"):
        make_server(svc, 0, None, bind="0.0.0.0")


# ---------------------------------------------------------------- docker (static)
@pytest.mark.skip(reason="Lola Docker packaging not ported; ATLAS ships no Dockerfile/compose")
def test_compose_is_paper_offline_and_secret_free():
    raw = (ROOT / "docker-compose.yml").read_text()
    c = yaml.safe_load(raw)
    s = c["services"]
    assert set(s) == {"app", "watchdog", "dashboard"}
    assert s["app"]["network_mode"] == "none" and s["watchdog"]["network_mode"] == "none"
    assert all(p.startswith("127.0.0.1:") for p in s["dashboard"]["ports"])
    for name, svc_ in s.items():
        env = svc_.get("environment", {})
        assert env.get("LIVE_ENABLED") == "false" and env.get("TRADING_MODE") == "paper"
        for k, v in env.items():
            if any(w in k for w in ("TOKEN", "SECRET", "KEY", "PASSWORD")):
                assert v in ("${DASHBOARD_TOKEN:-}",), f"{name}.{k} must not hold a literal secret"
        assert svc_.get("read_only") and "ALL" in svc_.get("cap_drop", [])
    assert "env_file" not in raw


@pytest.mark.skip(reason="Lola Docker packaging not ported; ATLAS ships no Dockerfile/compose")
def test_dockerfile_non_root_no_secrets():
    d = (ROOT / "Dockerfile").read_text()
    assert "USER bot" in d and "HEALTHCHECK" in d and "atlas-run" in d
    assert "COPY .env" not in d and "COPY config/.env " not in d
    ign = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in ign and "var" in ign and "*.pem" in ign


def test_slow_job_never_starves_the_core_heartbeat(tmp_path, monkeypatch):
    """A long retrain on the worker thread must not stop heartbeats (the external watchdog would halt trading)."""
    import threading
    import time as _t
    from atlas.mcp.trading.service import build_service
    from atlas.ops import runner
    from atlas.risk.watchdog_proc import write_core_heartbeat
    svc = build_service(CONFIG_DIR, state_path=str(tmp_path / "state.sqlite"))
    svc.watchdog.interval_s = 0.05
    beats, started = [], threading.Event()

    class SlowJobs:
        def tick(self, now):
            started.set(); _t.sleep(0.6)                  # e.g. the Saturday learning loop
    monkeypatch.setattr(runner, "daily_pipeline", lambda svc, now: None)
    stop = threading.Event()
    t = threading.Thread(target=runner.run_forever, args=(svc, SlowJobs(), stop, lambda st: (beats.append(_t.monotonic()), write_core_heartbeat(st))), daemon=True)
    t.start()
    assert started.wait(5)
    _t.sleep(0.5)
    stop.set(); t.join(5)
    during = [b for b in beats if b >= beats[0] + 0.1]
    assert len(during) >= 4                               # kept beating while the job was still running
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.3


def test_blocked_safety_step_stops_heartbeats_fail_closed(tmp_path, monkeypatch):
    import threading
    import time as _t
    from atlas.mcp.trading.service import build_service
    from atlas.ops import runner
    svc = build_service(CONFIG_DIR, state_path=str(tmp_path / "state.sqlite"))
    svc.watchdog.interval_s = 0.05
    svc.watchdog.missed_beats = 6                          # window 0.3 s
    beats = []
    monkeypatch.setattr(runner, "daily_pipeline", lambda svc, now: _t.sleep(1.5))   # holds the book lock too long

    class NoJobs:
        def tick(self, now):
            pass
    stop = threading.Event()
    t = threading.Thread(target=runner.run_forever, args=(svc, NoJobs(), stop, lambda st: beats.append(_t.monotonic())), daemon=True)
    t0 = _t.monotonic(); t.start(); _t.sleep(1.2); t_stop = _t.monotonic(); stop.set(); t.join(5)
    assert beats and max(beats) - t0 < 0.6                # heartbeats stopped once the window passed ...
    assert t_stop - max(beats) > 0.5                      # ... so the external watchdog would halt trading
