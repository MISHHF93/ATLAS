"""Build-level safety interlock.

LIVE trading is impossible in this build: the constant below is not read from
config or env, and every entry point calls `assert_paper_only`. There is no
live broker adapter in the codebase at all.
"""
from __future__ import annotations

import os
from typing import Mapping

BUILD_ALLOWS_LIVE: bool = False  # hard-coded. Do not make configurable.
PAPER = "paper"


class LiveTradingForbidden(RuntimeError):
    pass


def assert_paper_only(env: Mapping[str, str] | None = None) -> None:
    """Fail closed if anything asks for live mode."""
    env = os.environ if env is None else env
    if BUILD_ALLOWS_LIVE:  # pragma: no cover - guarded constant
        raise LiveTradingForbidden("build constant tampered: live is not supported")
    mode = str(env.get("TRADING_MODE", PAPER)).strip().lower()
    live_flag = str(env.get("LIVE_ENABLED", "false")).strip().lower()
    app_env = str(env.get("APP_ENV", "dev")).strip().lower()
    if mode != PAPER or live_flag not in ("false", "0", "", "no") or app_env == "live":
        raise LiveTradingForbidden(
            f"paper-only build: TRADING_MODE={mode!r} LIVE_ENABLED={live_flag!r} APP_ENV={app_env!r} rejected"
        )
