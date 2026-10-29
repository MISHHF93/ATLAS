import pytest
import yaml

from atlas.control.policy import ConfigError, load_all


def edit(d, name, fn):
    p = d / name
    data = yaml.safe_load(p.read_text())
    fn(data)
    p.write_text(yaml.safe_dump(data))


def errs(d):
    with pytest.raises(ConfigError) as e:
        load_all(d)
    return "\n".join(e.value.errors)


def test_app_config_valid(cfg):
    assert cfg.risk.capital.allocation_cap_pct == 20
    assert {k: v.target_pct for k, v in cfg.risk.sleeves.items()} == {"core": 60, "active": 30, "high_risk": 10, "derivatives": 0}


def test_original_spec_config_fails_closed(cfg_dir):
    """The pre-fix spec referenced a sleeve and a broker that do not exist. It must fail closed."""
    edit(cfg_dir, "schedule.yaml", lambda d: d["intraday_rules"].__setitem__("hold_overnight_allowed_sleeves", ["core", "active_swing"]))
    edit(cfg_dir, "schedule.yaml", lambda d: d["venues"]["fx"].__setitem__("brokers", ["ibkr", "oanda"]))
    e = errs(cfg_dir)
    assert "active_swing" in e and "oanda" in e


def test_undefined_sleeve(cfg_dir):
    edit(cfg_dir, "schedule.yaml", lambda d: d["intraday_rules"].__setitem__("hold_overnight_allowed_sleeves", ["core", "active_swing"]))
    assert "undefined sleeve 'active_swing'" in errs(cfg_dir)


def test_disabled_broker_in_routing(cfg_dir):
    edit(cfg_dir, "brokers.yaml", lambda d: d["routing"].__setitem__("crypto", ["coinbase", "robinhood_crypto"]))
    assert "disabled broker 'robinhood_crypto'" in errs(cfg_dir)


def test_disabled_broker_in_venue(cfg_dir):
    edit(cfg_dir, "schedule.yaml", lambda d: d["venues"]["fx"].__setitem__("brokers", ["ibkr", "oanda"]))
    assert "disabled broker 'oanda'" in errs(cfg_dir)


def test_unknown_broker(cfg_dir):
    edit(cfg_dir, "brokers.yaml", lambda d: d["routing"].__setitem__("us_equity", ["wealthsimple"]))
    assert "unknown broker 'wealthsimple'" in errs(cfg_dir)


def test_db_name_mismatch(cfg_dir):
    p = cfg_dir / ".env.example"
    p.write_text(p.read_text().replace("@localhost:5432/tradingbot", "@localhost:5432/trading"))
    assert "DB name mismatch" in errs(cfg_dir)


def test_live_mode_in_brokers_rejected(cfg_dir):
    edit(cfg_dir, "brokers.yaml", lambda d: d["platforms"]["alpaca"].__setitem__("mode", "live"))
    assert "brokers.yaml" in errs(cfg_dir)


def test_live_mode_in_policy_rejected(cfg_dir):
    edit(cfg_dir, "risk_policy.yaml", lambda d: d["mode"].__setitem__("default", "live"))
    assert "risk_policy.yaml" in errs(cfg_dir)


def test_live_env_rejected(cfg_dir):
    p = cfg_dir / ".env.example"
    p.write_text(p.read_text().replace("LIVE_ENABLED=false", "LIVE_ENABLED=true"))
    assert "live" in errs(cfg_dir)


def test_ibkr_live_port_rejected(cfg_dir):
    p = cfg_dir / ".env.example"
    p.write_text(p.read_text().replace("IBKR_GATEWAY_PORT=4002", "IBKR_GATEWAY_PORT=4001"))
    assert "LIVE port" in errs(cfg_dir)


@pytest.mark.parametrize("path,value,needle", [
    (("capital", "allocation_cap_pct"), 40, "allocation_cap"),
    (("capital", "profits_raise_cap"), True, "profits_raise_cap"),
    (("loss_limits", "daily_pct"), 5.0, "daily <= weekly"),
    (("loss_limits", "max_drawdown_pct"), 15.0, "max_drawdown_pct must be <= 10"),
    (("position_limits", "max_gross_exposure_pct"), 150, "max_gross_exposure_pct"),
    (("position_limits", "max_orders_per_minute"), 0, "max_orders_per_minute"),
    (("position_limits", "price_collar_pct"), -1, "price_collar_pct"),
    (("sleeves", "core", "target_pct"), 65, "sum to 100"),
    (("sleeves", "derivatives", "locked"), False, "locked"),
    (("ai_controls", "ai_can_change_policy"), True, "ai_can_change_policy"),
    (("ai_controls", "ai_can_approve_orders"), True, "ai_can_approve_orders"),
    (("kill_switch", "enabled"), False, "kill_switch"),
    (("watchdog", "fail_mode"), "open", "fail_mode"),
    (("watchdog", "deadman_timeout_s"), 5, "deadman"),
    (("autonomy", "level"), 2, "autonomy.level"),
    (("position_limits", "max_position_pct_bot_capital"), 60, "smallest core/active"),
])
def test_limit_sanity(cfg_dir, path, value, needle):
    def f(d):
        node = d
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    edit(cfg_dir, "risk_policy.yaml", f)
    assert needle in errs(cfg_dir)


def test_missing_required_sleeve(cfg_dir):
    edit(cfg_dir, "risk_policy.yaml", lambda d: d["sleeves"].pop("high_risk"))
    assert "high_risk" in errs(cfg_dir)


def test_missing_file(cfg_dir):
    (cfg_dir / "schedule.yaml").unlink()
    assert "schedule.yaml: missing" in errs(cfg_dir)


def test_malformed_yaml(cfg_dir):
    (cfg_dir / "brokers.yaml").write_text("platforms: [unclosed")
    assert "brokers.yaml" in errs(cfg_dir)


def test_withdrawal_permission_rejected(cfg_dir):
    edit(cfg_dir, "brokers.yaml", lambda d: d["platforms"]["alpaca"]["permissions"].__setitem__("withdrawals", True))
    assert "withdrawals" in errs(cfg_dir)


def test_bad_timezone(cfg_dir):
    edit(cfg_dir, "schedule.yaml", lambda d: d["venues"]["XTSE"].__setitem__("tz", "Mars/Olympus"))
    assert "unknown timezone" in errs(cfg_dir)


def test_watchdog_env_disagrees(cfg_dir):
    p = cfg_dir / ".env.example"
    p.write_text(p.read_text().replace("WATCHDOG_MISSED_BEATS_TO_HALT=3", "WATCHDOG_MISSED_BEATS_TO_HALT=9"))
    assert "WATCHDOG_MISSED_BEATS_TO_HALT" in errs(cfg_dir)


def test_policy_frozen(cfg):
    with pytest.raises(Exception):
        cfg.risk.loss_limits.daily_pct = 50
