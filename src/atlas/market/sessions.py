"""Real-time multi-market exchange session & open/closed status calculator.

Tracks actual market hours and session states in `America/New_York` / `America/Toronto` across:
1. `US_EQUITIES_ETFS` (`NYSE / NASDAQ / NYSE Arca`): 09:30–16:00 ET regular, 04:00–09:30 pre-market, 16:00–20:00 after-hours.
2. `CANADA_TSX` (`Toronto Stock Exchange`): 09:30–16:00 ET regular, 07:00–09:30 pre-open.
3. `CME_COMEX_FUTURES` (`CME / COMEX / NYMEX Globex` — Gold `GC`, Silver `SI`, `ES`, `NQ`, `CL`): Sun 18:00 – Fri 17:00 ET with Mon–Thu 17:00–18:00 ET maintenance break.
4. `GLOBAL_FX` (`Interbank Spot FX 24/5` — `EUR_USD`, `USD_CAD`): Sun 17:00 – Fri 17:00 ET with active regional session tags.
5. `CRYPTO_24_7` (`24/7 Digital Assets` — `BTC-USD`, `ETH-USD`, `SOL-USD`): 24/7/365 continuous.

Advisory / informational metadata only (`execution_permission: "none"`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")
TORONTO_TZ = ZoneInfo("America/Toronto")

NYSE_HOLIDAYS_2026 = frozenset(
    {
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
    }
)

TSX_HOLIDAYS_2026 = frozenset(
    {
        "2026-01-01",
        "2026-02-16",
        "2026-04-03",
        "2026-05-18",
        "2026-07-01",
        "2026-08-03",
        "2026-09-07",
        "2026-10-12",
        "2026-12-25",
        "2026-12-28",
    }
)

CME_FUTURES_SYMBOLS = frozenset(
    {"GC", "MGC", "SI", "SIL", "PL", "PA", "HG", "ES", "MES", "NQ", "MNQ", "YM", "RTY", "CL", "MCL", "NG", "ZN", "ZB", "6E", "6J"}
)

FX_SPOT_SYMBOLS = frozenset(
    {"EUR_USD", "USD_CAD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CHF", "NZD_USD", "EURUSD", "USDCAD", "GBPUSD", "USDJPY"}
)


def _fmt_minutes_delta(mins: int) -> str:
    mins = max(0, int(mins))
    h = mins // 60
    m = mins % 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def classify_symbol_venue(symbol: str) -> str:
    sym = symbol.strip().upper()
    if sym.endswith("-USD") or sym.endswith("USDT") or sym in {"BTC", "ETH", "SOL"}:
        return "CRYPTO_24_7"
    if sym.endswith(".TO") or sym.endswith(".V"):
        return "CANADA_TSX"
    if sym in FX_SPOT_SYMBOLS or ("_" in sym and len(sym) == 7):
        return "GLOBAL_FX"
    if sym in CME_FUTURES_SYMBOLS or sym.endswith("=F"):
        return "CME_COMEX_FUTURES"
    return "US_EQUITIES_ETFS"


def _us_equities_session(dt_et: datetime) -> dict[str, Any]:
    date_str = dt_et.strftime("%Y-%m-%d")
    wd = dt_et.weekday()  # 0=Mon .. 6=Sun
    mins = dt_et.hour * 60 + dt_et.minute
    is_holiday = date_str in NYSE_HOLIDAYS_2026

    if wd >= 5 or is_holiday:
        reason = "NYSE Holiday" if is_holiday else "Weekend"
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities", "ETFs (SPY, GLD, QQQ, TLT)"],
            "status": "CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "label": f"Cash Closed ({reason})",
            "schedule_et": "Mon–Fri 09:30–16:00 ET (Pre 04:00, Post 16:00–20:00)",
            "countdown": "Opens next business day 09:30 ET",
        }

    open_min = 9 * 60 + 30
    close_min = 16 * 60
    pre_min = 4 * 60
    post_min = 20 * 60

    if open_min <= mins < close_min:
        rem = close_min - mins
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities", "ETFs (SPY, GLD, QQQ, TLT)"],
            "status": "OPEN",
            "is_open": True,
            "extended_hours_active": False,
            "badge": "OPEN",
            "label": "Regular Cash Session Open",
            "schedule_et": "Mon–Fri 09:30–16:00 ET",
            "countdown": f"Cash close in {_fmt_minutes_delta(rem)} ET",
        }
    if pre_min <= mins < open_min:
        rem = open_min - mins
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities", "ETFs (SPY, GLD, QQQ, TLT)"],
            "status": "PRE_MARKET",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "PRE-MKT (CASH CLOSED)",
            "label": "Pre-Market Session (Cash Closed)",
            "schedule_et": "Regular 09:30–16:00 ET · Pre-Market 04:00–09:30 ET",
            "countdown": f"Cash open in {_fmt_minutes_delta(rem)} (09:30 ET)",
        }
    if close_min <= mins < post_min:
        rem = post_min - mins
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities", "ETFs (SPY, GLD, QQQ, TLT)"],
            "status": "AFTER_HOURS",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "AFTER-HRS (CASH CLOSED)",
            "label": "After-Hours Session (Cash Closed)",
            "schedule_et": "Regular 09:30–16:00 ET · After-Hours 16:00–20:00 ET",
            "countdown": f"After-hours ends in {_fmt_minutes_delta(rem)} ET",
        }
    rem = (pre_min - mins) if mins < pre_min else (24 * 60 - mins + pre_min)
    return {
        "venue_id": "US_EQUITIES_ETFS",
        "venue_name": "NYSE / NASDAQ / Arca",
        "asset_classes": ["US Equities", "ETFs (SPY, GLD, QQQ, TLT)"],
        "status": "CLOSED",
        "is_open": False,
        "extended_hours_active": False,
        "badge": "CLOSED",
        "label": "Overnight Closed",
        "schedule_et": "Mon–Fri 09:30–16:00 ET",
        "countdown": f"Pre-market in {_fmt_minutes_delta(rem)} (04:00 ET)",
    }


def _canada_tsx_session(dt_et: datetime) -> dict[str, Any]:
    date_str = dt_et.strftime("%Y-%m-%d")
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    is_holiday = date_str in TSX_HOLIDAYS_2026

    if wd >= 5 or is_holiday:
        reason = "TSX Holiday" if is_holiday else "Weekend"
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian Equities & ETRs (MNT.TO, XIC.TO)"],
            "status": "CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "label": f"TSX Closed ({reason})",
            "schedule_et": "Mon–Fri 09:30–16:00 America/Toronto",
            "countdown": "Opens next business day 09:30 ET",
        }

    open_min = 9 * 60 + 30
    close_min = 16 * 60
    pre_min = 7 * 60

    if open_min <= mins < close_min:
        rem = close_min - mins
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian Equities & ETRs (MNT.TO, XIC.TO)"],
            "status": "OPEN",
            "is_open": True,
            "extended_hours_active": False,
            "badge": "OPEN",
            "label": "TSX Regular Session Open",
            "schedule_et": "Mon–Fri 09:30–16:00 America/Toronto",
            "countdown": f"TSX close in {_fmt_minutes_delta(rem)} ET",
        }
    if pre_min <= mins < open_min:
        rem = open_min - mins
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian Equities & ETRs (MNT.TO, XIC.TO)"],
            "status": "PRE_MARKET",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "PRE-OPEN (CLOSED)",
            "label": "TSX Pre-Open Queuing (Cash Closed)",
            "schedule_et": "Mon–Fri 09:30–16:00 America/Toronto",
            "countdown": f"TSX open in {_fmt_minutes_delta(rem)} (09:30 ET)",
        }
    return {
        "venue_id": "CANADA_TSX",
        "venue_name": "Toronto Stock Exchange (TSX)",
        "asset_classes": ["Canadian Equities & ETRs (MNT.TO, XIC.TO)"],
        "status": "CLOSED",
        "is_open": False,
        "extended_hours_active": False,
        "badge": "CLOSED",
        "label": "TSX Closed",
        "schedule_et": "Mon–Fri 09:30–16:00 America/Toronto",
        "countdown": "Opens 09:30 America/Toronto",
    }


def _cme_comex_session(dt_et: datetime) -> dict[str, Any]:
    wd = dt_et.weekday()  # 0=Mon .. 4=Fri, 5=Sat, 6=Sun
    mins = dt_et.hour * 60 + dt_et.minute
    break_start = 17 * 60
    break_end = 18 * 60

    # Weekend closure: Fri >= 17:00, all Sat, Sun < 18:00
    if wd == 5 or (wd == 4 and mins >= break_start) or (wd == 6 and mins < break_end):
        return {
            "venue_id": "CME_COMEX_FUTURES",
            "venue_name": "CME / COMEX / NYMEX Globex",
            "asset_classes": ["Gold (GC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, CL)"],
            "status": "CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "label": "CME Globex Weekend Closure",
            "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily break 17:00–18:00 ET)",
            "countdown": "Reopens Sun 18:00 ET",
        }

    # Daily maintenance break Mon–Thu 17:00–18:00 ET
    if wd in (0, 1, 2, 3) and break_start <= mins < break_end:
        rem = break_end - mins
        return {
            "venue_id": "CME_COMEX_FUTURES",
            "venue_name": "CME / COMEX / NYMEX Globex",
            "asset_classes": ["Gold (GC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, CL)"],
            "status": "DAILY_BREAK",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "DAILY BREAK",
            "label": "CME Globex Daily Maintenance Break",
            "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily break 17:00–18:00 ET)",
            "countdown": f"Reopens in {_fmt_minutes_delta(rem)} (18:00 ET)",
        }

    # Otherwise OPEN (23/5)
    if mins < break_start:
        rem = break_start - mins
    else:
        rem = (24 * 60 - mins) + break_start
    return {
        "venue_id": "CME_COMEX_FUTURES",
        "venue_name": "CME / COMEX / NYMEX Globex",
        "asset_classes": ["Gold (GC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, CL)"],
        "status": "OPEN",
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (23/5)",
        "label": "CME Globex Electronic Session Open",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (23/5)",
        "countdown": f"Next 17:00 ET maintenance break in {_fmt_minutes_delta(rem)}",
    }


def _global_fx_session(dt_et: datetime) -> dict[str, Any]:
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    close_fri = 17 * 60
    open_sun = 17 * 60

    if wd == 5 or (wd == 4 and mins >= close_fri) or (wd == 6 and mins < open_sun):
        return {
            "venue_id": "GLOBAL_FX",
            "venue_name": "Global Spot FX (24/5)",
            "asset_classes": ["EUR/USD", "USD/CAD (Bank of Canada / Spot)"],
            "status": "CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "label": "FX Weekend Closure",
            "schedule_et": "Sun 17:00 – Fri 17:00 ET (24/5)",
            "countdown": "Reopens Sun 17:00 ET",
        }

    hour = dt_et.hour
    if 8 <= hour < 12:
        center = "London / New York Overlap"
    elif 3 <= hour < 8:
        center = "London / European Session"
    elif 12 <= hour < 17:
        center = "New York Session"
    else:
        center = "Sydney / Tokyo Asian Session"

    return {
        "venue_id": "GLOBAL_FX",
        "venue_name": "Global Spot FX (24/5)",
        "asset_classes": ["EUR/USD", "USD/CAD (Bank of Canada / Spot)"],
        "status": "OPEN",
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (24/5)",
        "label": f"Spot FX Open · {center}",
        "schedule_et": "Sun 17:00 – Fri 17:00 ET (24/5)",
        "countdown": f"Active: {center}",
    }


def _crypto_session() -> dict[str, Any]:
    return {
        "venue_id": "CRYPTO_24_7",
        "venue_name": "Crypto Spot & Perps (24/7)",
        "asset_classes": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "status": "OPEN",
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (24/7)",
        "label": "24/7/365 Continuous Trading",
        "schedule_et": "24/7/365 Continuous",
        "countdown": "Always Open (24/7)",
    }


def get_market_sessions_status(
    now: datetime | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return real-time open/closed/pre-market/break status across all ATLAS venues and requested symbols."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dt_et = now_utc.astimezone(ET_TZ)
    dt_toronto = now_utc.astimezone(TORONTO_TZ)

    venues = [
        _us_equities_session(dt_et),
        _canada_tsx_session(dt_et),
        _cme_comex_session(dt_et),
        _global_fx_session(dt_et),
        _crypto_session(),
    ]
    for v in venues:
        v.setdefault("status_label", v["badge"])
        v.setdefault("schedule_summary", v["schedule_et"])
        v.setdefault("reason", v["label"])
    venue_by_id = {v["venue_id"]: v for v in venues}

    default_syms = (
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "GC",
        "SI",
        "GLD",
        "SLV",
        "MNT.TO",
        "SPY",
        "QQQ",
        "TLT",
        "NVDA",
        "AAPL",
        "MSFT",
        "ES",
        "NQ",
        "CL",
        "EUR_USD",
        "USD_CAD",
    )
    target_syms = list(dict.fromkeys([*(symbols or default_syms)]))
    by_symbol: dict[str, dict[str, Any]] = {}
    for s in target_syms:
        vid = classify_symbol_venue(s)
        v = venue_by_id[vid]
        by_symbol[s.upper()] = {
            "symbol": s.upper(),
            "venue_id": vid,
            "venue_name": v["venue_name"],
            "status": v["status"],
            "status_label": v["badge"],
            "is_open": v["is_open"],
            "badge": v["badge"],
            "label": v["label"],
            "schedule_summary": v["schedule_et"],
            "reason": v["label"],
            "countdown": v["countdown"],
        }

    open_count = sum(1 for v in venues if v["is_open"])
    closed_count = len(venues) - open_count

    return {
        "as_of_utc": now_utc.isoformat(),
        "as_of_et": dt_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "as_of_toronto": dt_toronto.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "summary": {
            "total_venues": len(venues),
            "open_venues_count": open_count,
            "closed_or_extended_venues_count": closed_count,
            "open_venues": [v["venue_name"] for v in venues if v["is_open"]],
            "closed_or_premarket_venues": [f"{v['venue_name']} ({v['badge']})" for v in venues if not v["is_open"]],
        },
        "venues": venues,
        "by_symbol": by_symbol,
        "execution_permission": "none",
    }
