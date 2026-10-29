
import os
import pathlib
import sys
import pytest


if sys.platform == "win32":
    _win_modes: dict[str, int] = {}
    _orig_chmod = os.chmod
    _orig_open = os.open
    _orig_mkdir = os.mkdir
    _orig_replace = os.replace
    _orig_rename = os.rename
    _orig_stat = os.stat
    _orig_path_mkdir = pathlib.Path.mkdir
    _orig_path_stat = pathlib.Path.stat

    def _wkey(p) -> str | None:
        if isinstance(p, (str, bytes, os.PathLike)):
            try:
                return os.path.normcase(os.path.abspath(os.fspath(p)))
            except Exception:
                return None
        return None

    def _chmod_win(path, mode, *a, **kw):
        _orig_chmod(path, mode, *a, **kw)
        k = _wkey(path)
        if k is not None:
            _win_modes[k] = mode & 0o777

    def _open_win(path, flags, mode=0o777, *a, **kw):
        fd = _orig_open(path, flags, mode, *a, **kw)
        if (flags & os.O_CREAT) and (mode & 0o777) != 0o777:
            k = _wkey(path)
            if k is not None:
                _win_modes[k] = mode & 0o777
        return fd

    def _mkdir_win(path, mode=0o777, *a, **kw):
        _orig_mkdir(path, mode, *a, **kw)
        if (mode & 0o777) != 0o777:
            k = _wkey(path)
            if k is not None:
                _win_modes[k] = mode & 0o777

    def _path_mkdir_win(self, mode=0o777, parents=False, exist_ok=False):
        _orig_path_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)
        if (mode & 0o777) != 0o777:
            k = _wkey(self)
            if k is not None:
                _win_modes[k] = mode & 0o777

    def _replace_win(src, dst, *a, **kw):
        import time as _t
        for attempt in range(5):
            try:
                _orig_replace(src, dst, *a, **kw)
                break
            except PermissionError:
                if attempt == 4:
                    pathlib.Path(dst).write_bytes(pathlib.Path(src).read_bytes())
                    pathlib.Path(src).unlink(missing_ok=True)
                else:
                    _t.sleep(0.02 * (attempt + 1))
        ks, kd = _wkey(src), _wkey(dst)
        if ks in _win_modes and kd is not None:
            _win_modes[kd] = _win_modes.pop(ks)

    def _rename_win(src, dst, *a, **kw):
        _orig_rename(src, dst, *a, **kw)
        ks, kd = _wkey(src), _wkey(dst)
        if ks in _win_modes and kd is not None:
            _win_modes[kd] = _win_modes.pop(ks)

    def _stat_win(path, *a, **kw):
        res = _orig_stat(path, *a, **kw)
        k = _wkey(path)
        if k in _win_modes:
            return os.stat_result(((res.st_mode & ~0o777) | _win_modes[k], *res[1:]))
        return res

    def _path_stat_win(self, *a, **kw):
        res = _orig_path_stat(self, *a, **kw)
        k = _wkey(self)
        if k in _win_modes:
            return os.stat_result(((res.st_mode & ~0o777) | _win_modes[k], *res[1:]))
        return res

    os.chmod = _chmod_win
    os.open = _open_win
    os.mkdir = _mkdir_win
    os.replace = _replace_win
    os.rename = _rename_win
    os.stat = _stat_win
    pathlib.Path.mkdir = _path_mkdir_win
    pathlib.Path.stat = _path_stat_win



_KEEP_RUN_DIRS = 3


def _prune_old_runs(root, keep: int) -> None:
    """Best-effort removal of older per-run dirs; a locked dir (WinError 32) is skipped, never fatal."""
    import shutil

    runs = sorted((d for d in root.glob("run-*") if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for old in runs[: max(0, len(runs) - keep)]:
        shutil.rmtree(old, ignore_errors=True)


def pytest_configure(config):
    """Give every pytest run its own unique basetemp under .test-runs/.

    A fixed basetemp is wiped by pytest at start; on Windows any handle still open on the previous
    run (WinError 32) then breaks the whole session. A unique per-run directory never collides with
    a locked predecessor. An explicit --basetemp on the command line is respected untouched.
    """
    import time
    from pathlib import Path

    if config.option.basetemp:
        Path(config.option.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)
        return
    root = Path(config.rootpath) / ".test-runs"
    root.mkdir(parents=True, exist_ok=True)
    _prune_old_runs(root, _KEEP_RUN_DIRS - 1)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    config.option.basetemp = root / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{worker}"


@pytest.fixture(autouse=True)
def explicit_mock_market_data_permission(request, monkeypatch):
    """Grant only isolated test fixtures; production admission never inspects pytest.

    These modules supply deterministic data or mock provider responses. Their
    local evidence is a test double, not permission to fetch actual market data.
    Admission-denial tests deliberately receive no grant from this fixture.
    """
    if request.module.__name__.split(".")[-1] not in {
        "test_live_capture", "test_live_view", "test_live_observer",
        "test_observer_integrity", "test_observer_service", "test_stream_gaps",
        "test_market_bars", "test_second_tape",
    }:
        return
    import hashlib
    import json

    directory = request.getfixturevalue("tmp_path")
    evidence = directory / "mock_market_data_permission.txt"
    evidence.write_text(
        "TEST DOUBLE ONLY: in-memory synthetic provider responses for this test. "
        "This document conveys no rights to actual Coinbase, Yahoo, or other market data.",
        encoding="utf-8",
    )
    symbols = [
        "BTC-USD", "ETH-USD", "SOL-USD", "CAPTURE-USD", "CAPTURE-OBSERVER-USD",
        "GAP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LTC-USD",
        "NVDA", "AAPL", "MSFT", "SPY", "QQQ", "TSLA", "AMD",
        "T", "M", "BAD", "OLD", "ATOMIC", "GAP",
    ]
    grants = [
        {
            "grant_id": "mock-fixture-only:" + provider,
            "provider_id": provider,
            "symbols": symbols,
            "resolutions_seconds": [1, 60, 300, 900, 3600, 86400],
            "allowed_uses": ["training", "retention"],
            "license_ref": "internal:synthetic-test-fixture-only",
            "reviewed_by": "pytest fixture for synthetic responses only",
            "approved_at": "2020-01-01T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "evidence_path": evidence.name,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "written_permission_confirmed": True,
        }
        for provider in (
            "coinbase_exchange_public", "yahoo_chart_public", "test_public", "real_test_provider"
        )
    ]
    policy = directory / "mock_data_use_policy.json"
    policy.write_text(json.dumps({"schema_version": 1, "grants": grants}), encoding="utf-8")
    monkeypatch.setenv("ATLAS_DATA_USE_POLICY", str(policy))

@pytest.fixture(autouse=True)
def explicit_legacy_demo_gateway(request, monkeypatch):
    if request.module.__name__.split(".")[-1] in {
        "test_strategies", "test_catalog_and_stream", "test_live_stream", "test_live_stream_module02", "test_whale_policy_intake"
    }:
        from atlas.api.app import live_market_gateway
        monkeypatch.setattr(live_market_gateway, "demo_mode", True)


@pytest.fixture(autouse=True)
def _reset_default_atlas_feed():
    """Keep a lazily created on-disk AtlasFeed singleton from leaking between tests."""
    from atlas.feeds import feed as _feed_mod

    old = _feed_mod._DEFAULT
    yield
    _feed_mod._DEFAULT = old


@pytest.fixture(autouse=True)
def _no_live_context_network(request, monkeypatch):
    """Keep tests hermetic: the keyless context sources (BLS/Treasury/EDGAR/RSS) are never fetched over the network by a test that
    does not inject its own fetcher. Tests that pass ``fetch=`` are unaffected."""
    from atlas.ext import keyless_context as kc

    if request.module.__name__.split(".")[-1] == "test_keyless_context":
        return   # that module injects its own fetchers and tests the real host allow-list (which raises before any network use)

    def _blocked(url, headers):
        raise OSError("network disabled in tests")
    monkeypatch.setattr(kc, "_default_fetch", _blocked)
    kc._CACHE.clear()
