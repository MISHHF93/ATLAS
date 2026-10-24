"""Alert formatter + dispatcher for Telegram, Discord and Slack webhooks. DISABLED BY DEFAULT.

Sending needs ALL of: ATLAS_ALERTS_ENABLED=true, a per-channel destination (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID,
DISCORD_WEBHOOK_URL, SLACK_WEBHOOK_URL) in the environment or local .env, and not running under pytest. Otherwise
``dispatch`` returns a dry-run record with the formatted text and sends nothing. Alerts are research notices; they
never carry an order instruction."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import ADVISORY

CHANNELS = ("telegram", "discord", "slack")
_KEYS = ("ATLAS_ALERTS_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL")


def format_alert(d: dict[str, Any]) -> str:
    """One plain-text alert from a dossier (or any dict with symbol + conviction + trade_levels)."""
    c, lv = d.get("conviction") or {}, d.get("trade_levels") or {}
    lines = [f"ATLAS research alert: {d.get('symbol', '?')}", f"Conviction {c.get('score', '—')}/100 → {c.get('label', '—')}"]
    if lv.get("side"):
        lines.append(f"{lv['side']} idea: entry {lv['entry']:.4g} ({lv['entry_ref']}), stop {lv['stop']:.4g}, target {lv['target']:.4g} ({lv['target_ref']})")
    top = sorted(c.get("components", []), key=lambda x: -abs(x["points"]))[:3]
    lines += [f"• {x['rule']}: {x['points']:+.0f} ({x['why']})" for x in top]
    lines.append(f"[{ADVISORY}; paper only]")
    return "\n".join(lines)


def config(env_file: str | Path = ".env") -> dict[str, str]:
    from atlas.control.policy.loader import parse_env_file
    f = parse_env_file(Path(env_file))
    return {k: os.environ.get(k) or f.get(k, "") for k in _KEYS}


def status(cfg: dict[str, str] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else config()
    ready = {"telegram": bool(cfg.get("TELEGRAM_BOT_TOKEN") and cfg.get("TELEGRAM_CHAT_ID")),
             "discord": bool(cfg.get("DISCORD_WEBHOOK_URL")), "slack": bool(cfg.get("SLACK_WEBHOOK_URL"))}
    enabled = cfg.get("ATLAS_ALERTS_ENABLED", "").lower() == "true"
    return {"enabled": enabled, "channels_configured": ready, "under_test": "PYTEST_CURRENT_TEST" in os.environ,
            "default": "disabled", "note": "set ATLAS_ALERTS_ENABLED=true and a channel destination in the local .env to send"}


def _post(url: str, body: dict) -> int:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - owner-configured webhook
        return r.status


def dispatch(text: str, channels: tuple[str, ...] = CHANNELS, cfg: dict[str, str] | None = None,
             post: Callable[[str, dict], int] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else config()
    st = status(cfg)
    results = []
    for ch in channels:
        if ch not in CHANNELS:
            results.append({"channel": ch, "sent": False, "reason": "unknown channel"}); continue
        if not st["enabled"]:
            results.append({"channel": ch, "sent": False, "reason": "alerts disabled (default)"}); continue
        if st["under_test"]:
            results.append({"channel": ch, "sent": False, "reason": "never sends under pytest"}); continue
        if not st["channels_configured"][ch]:
            results.append({"channel": ch, "sent": False, "reason": "channel not configured"}); continue
        if ch == "telegram":
            url, body = f"https://api.telegram.org/bot{cfg['TELEGRAM_BOT_TOKEN']}/sendMessage", {"chat_id": cfg["TELEGRAM_CHAT_ID"], "text": text}
        elif ch == "discord":
            url, body = cfg["DISCORD_WEBHOOK_URL"], {"content": text[:1900]}
        else:
            url, body = cfg["SLACK_WEBHOOK_URL"], {"text": text}
        try:
            code = (post or _post)(url, body)
            results.append({"channel": ch, "sent": 200 <= code < 300, "http_status": code})
        except Exception as e:
            results.append({"channel": ch, "sent": False, "reason": f"{type(e).__name__}"})
    return {"text": text, "results": results, "any_sent": any(r["sent"] for r in results)}
