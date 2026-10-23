import pytest

import atlas.risk.safety as safety
from atlas.risk.safety import LiveTradingForbidden, assert_paper_only


def test_build_constant_false():
    assert safety.BUILD_ALLOWS_LIVE is False


@pytest.mark.parametrize("env", [
    {"TRADING_MODE": "live"}, {"LIVE_ENABLED": "true"}, {"LIVE_ENABLED": "1"}, {"APP_ENV": "live"},
    {"TRADING_MODE": "LIVE "},
])
def test_live_rejected(env):
    with pytest.raises(LiveTradingForbidden):
        assert_paper_only(env)


def test_paper_ok():
    assert_paper_only({"TRADING_MODE": "paper", "LIVE_ENABLED": "false"})
    assert_paper_only({})


def test_engine_refuses_live_env(cfg, audit, ks, clock, monkeypatch):
    from atlas.risk import RiskEngine, Watchdog
    monkeypatch.setenv("LIVE_ENABLED", "true")
    with pytest.raises(LiveTradingForbidden):
        RiskEngine(cfg.risk, cfg.brokers, audit, ks, Watchdog(5, 3, ks, clock=clock))


def test_no_live_adapter_in_codebase():
    import pathlib
    src = pathlib.Path(safety.__file__).parent
    # guards.py legitimately names live hosts/ports in its BLOCK list
    text = "".join(p.read_text() for p in src.rglob("*.py") if p.name != "guards.py")
    for url in ("api.alpaca.markets", "api-fxtrade", "requests.post", "httpx"):
        assert url not in text.replace("paper-api.alpaca.markets", "")
