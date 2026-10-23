"""Import boundaries work in clean processes, independent of test collection order."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _fresh_python(source: str, working_directory: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["ATLAS_DISABLE_LIVE_PUBLIC"] = "1"
    env["ATLAS_ENABLE_EXPERIMENTAL_ML"] = "0"
    return subprocess.run(
        [sys.executable, "-B", "-c", source],
        cwd=working_directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("first_module", ["atlas.connectors", "atlas.control"])
def test_control_and_connectors_import_in_either_order(first_module: str, tmp_path: Path) -> None:
    result = _fresh_python(
        f"import {first_module}\n"
        "import atlas.connectors as connectors\n"
        "import atlas.control as control\n"
        "from atlas.control.gateway import ControlPlaneExecutionGateway\n"
        "assert control.ControlPlaneExecutionGateway is ControlPlaneExecutionGateway\n"
        "assert control.ControlPlaneExecutionGateway is control.ControlPlaneExecutionGateway\n"
        "assert 'ControlPlaneExecutionGateway' in dir(control)\n"
        "assert connectors.AlpacaEquitiesConnector().connector_id == 'alpaca_equities_dma'\n"
        "try:\n"
        "    control.unknown_control_export\n"
        "except AttributeError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('Unknown exports must raise AttributeError')\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_control_core_import_does_not_load_gateway_or_ai(tmp_path: Path) -> None:
    result = _fresh_python(
        "import sys\n"
        "import atlas.control\n"
        "assert 'atlas.control.gateway' not in sys.modules\n"
        "assert not any(name == 'atlas.ai' or name.startswith('atlas.ai.') for name in sys.modules)\n"
        "assert 'atlas.connectors' not in sys.modules\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_control_keeps_all_public_exports(tmp_path: Path) -> None:
    result = _fresh_python(
        "import atlas.control as control\n"
        "namespace = {}\n"
        "exec('from atlas.control import *', namespace)\n"
        "assert all(name in namespace for name in control.__all__)\n"
        "assert all(namespace[name] is getattr(control, name) for name in control.__all__)\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_api_imports_in_a_fresh_process(tmp_path: Path) -> None:
    result = _fresh_python(
        "import sys\n"
        "from atlas.api.app import app\n"
        "assert app.title == 'ATLAS'\n"
        "assert 'atlas.api.advanced_ml' not in sys.modules\n"
        "assert 'atlas.models.perfect_trader_whale' not in sys.modules\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_retired_advanced_ml_cannot_break_core_api_even_with_old_opt_in(tmp_path: Path) -> None:
    result = _fresh_python(
        "import os\n"
        "import sys\n"
        "os.environ['ATLAS_ENABLE_EXPERIMENTAL_ML'] = '1'\n"
        "from fastapi.testclient import TestClient\n"
        "from atlas.api.app import app\n"
        "client = TestClient(app)\n"
        "assert client.get('/api/health').json() == {'status': 'ok', 'trading': 'disabled'}\n"
        "response = client.post('/api/advanced-ml/transformer/forecast', json={})\n"
        "assert response.status_code == 410\n"
        "assert response.json()['detail']['state'] == 'retired'\n"
        "assert client.get('/api/research/experimental-status').json()['state'] == 'retired'\n"
        "assert 'atlas.api.advanced_ml' not in sys.modules\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
