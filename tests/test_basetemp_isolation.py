"""The suite must not depend on a fixed, reusable basetemp (Windows WinError 32 on locked leftovers)."""

import os
import time
from pathlib import Path

import importlib.util


def _conftest():
    # Load this directory's conftest by path: a bare `import conftest` is ambiguous with nested conftest.py files.
    spec = importlib.util.spec_from_file_location("atlas_root_conftest", Path(__file__).with_name("conftest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_basetemp_is_unique_per_run(request):
    base = Path(request.config.option.basetemp)
    assert base.parent.name == ".test-runs"
    assert base.name.startswith("run-") and str(os.getpid()) in base.name
    assert base.name != "pytest-default"


def test_prune_old_runs_keeps_newest_and_ignores_other_dirs(tmp_path):
    for i in range(5):
        d = tmp_path / f"run-{i}"
        d.mkdir()
        os.utime(d, (time.time() - 100 + i, time.time() - 100 + i))
    other = tmp_path / "visual-audit"
    other.mkdir()
    _conftest()._prune_old_runs(tmp_path, 2)
    assert sorted(p.name for p in tmp_path.glob("run-*")) == ["run-3", "run-4"]
    assert other.exists()
