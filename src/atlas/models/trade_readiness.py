"""Whether the measured sample is ready for a later paper review.

Live money stays disabled. A clear research sample is not permission to trade,
and this module cannot submit an order.

The latest 30 days of costed stances have to agree with a supported sample.
SR 11-7 calls for outcomes analysis to continue after a model is built, so a
full-sample pass whose recent month reversed does not clear.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

HALF_FORECAST_BRIER = 0.25
RECENT_WINDOW_DAYS = 30
MIN_RECENT_STANCES = 8


def _check(check_id: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "detail": detail}


def _parse_time(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recent_proof(ledger: dict[str, Any], track: str) -> list[tuple[datetime, float]]:
    decisions = ledger.get("decisions") if isinstance(ledger.get("decisions"), list) else []
    dated: list[tuple[datetime, float]] = []
    for row in decisions:
        if not isinstance(row, dict) or row.get("track") != track or not row.get("counts_toward_proof"):
            continue
        when = _parse_time(row.get("resolve_timestamp"))
        try:
            net = float(row.get("net_return"))
        except (TypeError, ValueError):
            continue
        if when is None:
            continue
        dated.append((when, net))
    if not dated:
        return []
    latest = max(when for when, _net in dated)
    cutoff = latest - timedelta(days=RECENT_WINDOW_DAYS)
    return [(when, net) for when, net in dated if when >= cutoff]


def _recent_month_check(ledger: dict[str, Any], track: str, judgment: str) -> dict[str, str]:
    """The latest month can withhold a full-sample pass. It cannot open live money."""
    window = _recent_proof(ledger, track)
    count = len(window)
    mean = sum(net for _when, net in window) / count if window else None
    shown = "no costed stance" if mean is None else f"{mean * 100:.2f}%"
    check_id = f"{track}_recent_month"
    if judgment != "supported_on_this_sample":
        return _check(
            check_id,
            "closed",
            (
                f"The full sample is not supported. The latest {RECENT_WINDOW_DAYS} days show "
                f"{shown} on {count} costed stances."
            ),
        )
    if count < MIN_RECENT_STANCES or mean is None or mean <= 0:
        return _check(
            check_id,
            "closed",
            (
                f"The latest {RECENT_WINDOW_DAYS} days show {shown} on {count} costed stances. "
                f"{MIN_RECENT_STANCES} stances and a positive costed mean are required before that month can agree."
            ),
        )
    return _check(
        check_id,
        "met",
        (
            f"The latest {RECENT_WINDOW_DAYS} days show {shown} on {count} costed stances. "
            "Agreement with the full sample does not open live money."
        ),
    )


def build_trade_readiness(ledger: dict[str, Any]) -> dict[str, Any]:
    """Score the ledger. Live money is closed even when every research check is met."""
    checks: list[dict[str, str]] = [
        _check(
            "live_money",
            "closed",
            "Live-money trading is off. A research result cannot open it.",
        )
    ]
    tracks = ledger.get("tracks") if isinstance(ledger.get("tracks"), dict) else {}
    for track in ("competition", "open_market"):
        row = tracks.get(track) if isinstance(tracks.get(track), dict) else {}
        reliability = row.get("reliability") if isinstance(row.get("reliability"), dict) else {}
        supported = row.get("judgment") == "supported_on_this_sample"
        checks.append(
            _check(
                f"{track}_costed_sample",
                "met" if supported else "closed",
                str(row.get("notice") or "This track has no costed judgment yet."),
            )
        )
        brier = reliability.get("brier_score")
        try:
            brier_value = float(brier) if brier is not None else None
        except (TypeError, ValueError):
            brier_value = None
        confident = (
            reliability.get("confidence") == "scored"
            and brier_value is not None
            and brier_value < HALF_FORECAST_BRIER
        )
        shown = "—" if brier_value is None else f"{brier_value:.3f}"
        checks.append(
            _check(
                f"{track}_confidence",
                "met" if confident else "closed",
                (
                    f"Brier {shown} on {reliability.get('calibration_rows') or 0} forecasts. "
                    "A constant one-half forecast scores 0.25. Confidence is met only below that."
                ),
            )
        )
        checks.append(_recent_month_check(ledger, track, str(row.get("judgment") or "")))
    checks.append(
        _check(
            "broker_audit",
            "closed",
            "No live broker audit is on file. Paper research is not that audit.",
        )
    )
    checks.append(
        _check(
            "human_approval",
            "closed",
            "No scoped live-money approval is on file. A process default is not an approval.",
        )
    )
    research_ids = {
        "competition_costed_sample",
        "open_market_costed_sample",
        "competition_confidence",
        "open_market_confidence",
        "competition_recent_month",
        "open_market_recent_month",
    }
    research_clear = all(item["status"] == "met" for item in checks if item["id"] in research_ids)
    if research_clear:
        notice = (
            "The measured research checks are met on this sample, including the latest 30 days. "
            "Live money stays disabled. This page cannot open it."
        )
    else:
        notice = (
            "Withheld means this measured sample is not ready. "
            "Live money stays disabled even if a later sample clears the research checks."
        )
    return {
        "light": "research_clear" if research_clear else "withheld",
        "live_money": "disabled",
        "trading": "disabled",
        "checks": checks,
        "orders_submitted": 0,
        "may_propose_order": False,
        "execution_permission": "none",
        "notice": notice,
    }
