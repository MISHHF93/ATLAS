"""Cross-file validation. Returns a list of errors; any error => fail closed.

Covers the inconsistencies in trading-bot-review/review.md §2:
  #3 undefined sleeve references (e.g. active_swing)
  #2/#routing  disabled or unknown broker referenced by routing / venues
  #4 Postgres DB name mismatch between POSTGRES_DB and DATABASE_URL
  #5 limits sanity (and small-live profile not defined -> live impossible anyway)
  plus: base currency agreement, watchdog env vs policy, live flags in env.
"""
from __future__ import annotations

from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from atlas.control.policy.loader import LoadedConfig


def cross_validate(cfg: LoadedConfig) -> list[str]:
    errs: list[str] = []
    rp, br, sc, env = cfg.risk, cfg.brokers, cfg.schedule, cfg.env_example
    sleeves = set(rp.sleeves)
    platforms = br.platforms

    # sleeves referenced in schedule must exist
    for s in sc.intraday_rules.hold_overnight_allowed_sleeves:
        if s not in sleeves:
            errs.append(f"schedule.intraday_rules.hold_overnight_allowed_sleeves: undefined sleeve {s!r} (defined: {sorted(sleeves)})")

    def check_broker(ref: str, where: str) -> None:
        if ref not in platforms:
            errs.append(f"{where}: unknown broker {ref!r}")
        elif not platforms[ref].enabled:
            errs.append(f"{where}: references disabled broker {ref!r}")

    for route, brokers in br.routing.items():
        if isinstance(brokers, list):
            for b in brokers:
                check_broker(b, f"brokers.routing.{route}")
    for vname, v in sc.venues.items():
        if not v.enabled:
            continue
        for b in v.brokers:
            check_broker(b, f"schedule.venues.{vname}.brokers")

    # currencies
    if rp.base_currency != br.base_currency:
        errs.append(f"base_currency mismatch: risk_policy={rp.base_currency} brokers={br.base_currency}")
    if env.get("BASE_CURRENCY") and env["BASE_CURRENCY"] != rp.base_currency:
        errs.append(f".env BASE_CURRENCY={env['BASE_CURRENCY']} != risk_policy {rp.base_currency}")

    # timezones
    for name, tz in [("owner_timezone", sc.owner_timezone)] + [(f"venues.{k}.tz", v.tz) for k, v in sc.venues.items()]:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            errs.append(f"schedule.{name}: unknown timezone {tz!r}")

    # DB name consistency
    db, url = env.get("POSTGRES_DB"), env.get("DATABASE_URL")
    if db and url:
        path_db = urlparse(url).path.lstrip("/")
        if path_db != db:
            errs.append(f".env DB name mismatch: POSTGRES_DB={db!r} but DATABASE_URL points at {path_db!r}")

    # limits sanity
    cap = rp.capital
    pl, ll = rp.position_limits, rp.loss_limits
    if pl.max_gross_exposure_pct > 100:
        errs.append("position_limits.max_gross_exposure_pct > 100 implies leverage")
    if pl.max_position_pct_bot_capital > min(s.max_pct for k, s in rp.sleeves.items() if k in ("core", "active")):
        errs.append("max_position_pct_bot_capital exceeds the smallest core/active sleeve max")
    if sum(s.min_pct for s in rp.sleeves.values()) > 100:
        errs.append("sleeve min_pct values sum to > 100")
    if pl.max_open_orders < 1 or pl.max_orders_per_minute < 1:
        errs.append("order rate limits must be >= 1")
    if cap.allocation_cap_hard_ceiling_pct > 30:
        errs.append("allocation_cap_hard_ceiling_pct must be <= 30 per BRD")
    if ll.max_drawdown_pct > 10:
        errs.append("max_drawdown_pct must be <= 10 per BRD")
    wd = rp.watchdog
    if wd.deadman_timeout_s < wd.heartbeat_interval_s * wd.missed_beats_to_halt:
        errs.append("watchdog.deadman_timeout_s shorter than heartbeat halt window")
    for k, pk in (("WATCHDOG_HEARTBEAT_INTERVAL_S", "heartbeat_interval_s"), ("WATCHDOG_MISSED_BEATS_TO_HALT", "missed_beats_to_halt"), ("WATCHDOG_DEADMAN_TIMEOUT_S", "deadman_timeout_s")):
        if k in env:
            try:
                if float(env[k]) != float(getattr(wd, pk)):
                    errs.append(f".env {k}={env[k]} disagrees with risk_policy.watchdog.{pk}={getattr(wd, pk)}")
            except ValueError:
                errs.append(f".env {k} not numeric")

    # paper-only build: env template must not request live
    if env.get("TRADING_MODE", "paper") != "paper" or env.get("LIVE_ENABLED", "false").lower() != "false":
        errs.append(".env requests live mode; this build is paper-only")
    if env.get("OANDA_ENV", "practice") != "practice":
        errs.append(".env OANDA_ENV must be practice")
    if env.get("IBKR_GATEWAY_PORT") and env["IBKR_GATEWAY_PORT"] in ("4001", "7496"):
        errs.append(".env IBKR_GATEWAY_PORT is a LIVE port")
    alp = env.get("ALPACA_BASE_URL")
    if alp and "paper" not in alp:
        errs.append(".env ALPACA_BASE_URL is not the paper endpoint")
    return errs
