import pytest
from hypothesis import given, strategies as st

from founder_conftest import FakeClock
from atlas.governance.audit import AuditLog
from atlas.risk import KillSwitch, Watchdog


def test_engage_latches_and_cancels():
    a = AuditLog()
    ks = KillSwitch(a, on_engage=[lambda r: 3])
    r = ks.engage("panic", "mcp")
    assert ks.engaged and r["cancelled_orders"] == 3 and r["halted"]
    ks.engage("again", "cli")
    assert ks.reason == "panic"
    assert len(a.entries("kill_switch.engage")) == 2


def test_cancel_failure_still_halts():
    ks = KillSwitch(AuditLog(), on_engage=[lambda r: 1 / 0])
    ks.engage("x", "cli")
    assert ks.engaged


def test_reset_requires_owner_and_stepup():
    ks = KillSwitch(AuditLog())
    ks.engage("x", "cli")
    with pytest.raises(PermissionError):
        ks.reset("ai", True, "masharai")
    with pytest.raises(PermissionError):
        ks.reset("masharai", False, "masharai")
    assert ks.engaged
    ks.reset("masharai", True, "masharai")
    assert not ks.engaged


def test_watchdog_no_heartbeat_unhealthy():
    ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=FakeClock())
    assert not wd.check() and ks.engaged


def test_watchdog_boundary():
    c = FakeClock(); ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=c); wd.heartbeat()
    c.advance(15); assert wd.check()
    c.advance(0.01); assert not wd.check() and ks.engaged


def test_watchdog_latched_after_recovery():
    c = FakeClock(); ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=c); wd.heartbeat()
    c.advance(20); wd.check()
    wd.heartbeat(); assert wd.check() and ks.engaged  # healthy again but halt stays


def test_watchdog_clock_error_fails_closed():
    def bad():
        raise OSError("clock")
    ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=bad)
    assert not wd.check() and ks.engaged


def test_watchdog_clock_backwards_fails_closed():
    c = FakeClock(); ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=c); wd.heartbeat()
    c.advance(-10)
    assert not wd.healthy()


@given(gap=st.floats(0, 100))
def test_prop_watchdog(gap):
    c = FakeClock(); ks = KillSwitch(AuditLog())
    wd = Watchdog(5, 3, ks, clock=c); wd.heartbeat(); c.advance(gap)
    assert wd.check() == (gap <= 15) and ks.engaged == (gap > 15)
