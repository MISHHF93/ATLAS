import builtins
import os
import sys
import types

import pytest

from atlas.ops import procutil


def _no_psutil(monkeypatch):
    real = builtins.__import__
    def fake(name, *a, **k):
        if name == "psutil":
            raise ImportError
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)


@pytest.mark.parametrize("pid", [None, 0, -5])
def test_invalid_pid(pid):
    assert procutil.pid_alive(pid) is False


def test_uses_psutil_when_available(monkeypatch):
    fake = types.SimpleNamespace(pid_exists=lambda p: p == 42)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    assert procutil.pid_alive(42) is True
    assert procutil.pid_alive(43) is False


def test_windows_branch_never_calls_os_kill(monkeypatch):
    _no_psutil(monkeypatch)
    monkeypatch.setattr(procutil.sys, "platform", "win32")
    monkeypatch.setattr(procutil, "_pid_alive_windows", lambda p: p == 7)
    def boom(*a):
        raise AssertionError("os.kill must not be used on Windows")
    monkeypatch.setattr(procutil.os, "kill", boom)
    assert procutil.pid_alive(7) is True
    assert procutil.pid_alive(8) is False


def test_posix_branch(monkeypatch):
    _no_psutil(monkeypatch)
    monkeypatch.setattr(procutil.sys, "platform", "linux")
    def kill(pid, sig):
        assert sig == 0
        if pid == 1:
            raise PermissionError
        if pid == 2:
            raise ProcessLookupError
    monkeypatch.setattr(procutil.os, "kill", kill)
    assert procutil.pid_alive(1) is True
    assert procutil.pid_alive(2) is False
    assert procutil.pid_alive(3) is True


def test_real_current_process():
    assert procutil.pid_alive(os.getpid()) is True


def test_feeds_api_uses_helper(monkeypatch, tmp_path):
    from atlas.api import feeds_api
    from atlas.feeds import feed as feed_mod
    monkeypatch.setattr(feed_mod, "DEFAULT_STORE", str(tmp_path / "feed.sqlite"))
    (tmp_path / "live_ingest.pid").write_text("1234")
    monkeypatch.setattr(procutil, "pid_alive", lambda p: p == 1234)
    st = feeds_api._live_ingest_state()
    assert st["pid"] == 1234 and st["running"] is True
