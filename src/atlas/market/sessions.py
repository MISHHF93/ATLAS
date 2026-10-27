"""Authoritative Market Status Engine & Official Exchange Calendars.

Implements Sections 9, 10, 11, 12, and 23 of the ATLAS Complete System Verification Directive:
- Instrument-level and venue-level market status across 17 canonical states:
  REGULAR_SESSION, PREMARKET, AFTER_HOURS, OVERNIGHT_SESSION, OPEN, PREOPEN,
  MAINTENANCE, CLOSED, HOLIDAY, EARLY_CLOSE, HALTED, LIMIT_ONLY, POST_ONLY,
  CANCEL_ONLY, VIEW_ONLY, TRADING_DISABLED, UNKNOWN.
- Strictly separates three independent concepts:
  1. SCHEDULED_MARKET_STATUS
  2. VENUE_REPORTED_TRADING_STATUS
  3. DATA_FEED_HEALTH
- Official exchange calendars:
  * Nasdaq / NYSE (https://www.nasdaq.com/market-activity/stock-market-holiday-schedule):
    Regular hours (09:30–16:00 ET), Premarket (04:00–09:30 ET), After-hours (16:00–20:00 ET),
    official holidays (2025–2027), official 13:00 ET early closes, and effective-dated
    transition to 23/5 trading beginning December 1, 2026 (never applied before its effective date).
  * Toronto Stock Exchange (TSX): Regular 09:30–16:00 ET, Pre-open 07:00–09:30 ET, Canadian holidays.
  * CME Group (https://www.cmegroup.com/trading-hours.html): Contract-specific schedules
    distinguishing standard COMEX GC / MGC / SI, CME Equity Index ES / NQ / MNQ, and NYMEX CL
    (Sun 18:00 – Fri 17:00 ET with daily maintenance window 17:00–18:00 ET).
  * Coinbase / Crypto Spot & Perps: Supports full trading (OPEN), LIMIT_ONLY, POST_ONLY,
    CANCEL_ONLY, TRADING_DISABLED, and VIEW_ONLY.
  * Solana & Pump.fun / PumpSwap: Separates blockchain/RPC health from bonding-curve state,
    migration state, PumpSwap pool availability, exit liquidity, and risk screening.
- Paper-only advisory governance: execution_permission is always "none".
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")
TORONTO_TZ = ZoneInfo("America/Toronto")
UTC_TZ = timezone.utc

VALID_MARKET_STATES: tuple[str, ...] = (
    "REGULAR_SESSION",
    "PREMARKET",
    "AFTER_HOURS",
    "OVERNIGHT_SESSION",
    "OPEN",
    "PREOPEN",
    "MAINTENANCE",
    "CLOSED",
    "HOLIDAY",
    "EARLY_CLOSE",
    "HALTED",
    "LIMIT_ONLY",
    "POST_ONLY",
    "CANCEL_ONLY",
    "VIEW_ONLY",
    "TRADING_DISABLED",
    "UNKNOWN",
)

# Effective date for Nasdaq's announced 23/5 overnight session transition (December 2026)
NASDAQ_23_5_EFFECTIVE_DATE = date(2026, 12, 1)

# Official NYSE / NASDAQ holidays (2025–2027)
US_MARKET_HOLIDAYS: dict[date, str] = {
    date(2025, 1, 1): "New Year's Day",
    date(2025, 1, 20): "Martin Luther King, Jr. Day",
    date(2025, 2, 17): "Presidents' Day",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 26): "Memorial Day",
    date(2025, 6, 19): "Juneteenth National Independence Day",
    date(2025, 7, 4): "Independence Day",
    date(2025, 9, 1): "Labor Day",
    date(2025, 11, 27): "Thanksgiving Day",
    date(2025, 12, 25): "Christmas Day",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King, Jr. Day",
    date(2026, 2, 16): "Presidents' Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth National Independence Day",
    date(2026, 7, 3): "Independence Day (Observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 18): "Martin Luther King, Jr. Day",
    date(2027, 2, 15): "Presidents' Day",
    date(2027, 3, 26): "Good Friday",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth (Observed)",
    date(2027, 7, 5): "Independence Day (Observed)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving Day",
    date(2027, 12, 24): "Christmas Day (Observed)",
}

# Official NYSE / NASDAQ 13:00 ET Early Close dates (2025–2027)
US_MARKET_EARLY_CLOSES: dict[date, str] = {
    date(2025, 7, 3): "Day Before Independence Day (13:00 ET Early Close)",
    date(2025, 11, 28): "Day After Thanksgiving / Black Friday (13:00 ET Early Close)",
    date(2025, 12, 24): "Christmas Eve (13:00 ET Early Close)",
    date(2026, 11, 27): "Day After Thanksgiving / Black Friday (13:00 ET Early Close)",
    date(2026, 12, 24): "Christmas Eve (13:00 ET Early Close)",
    date(2027, 11, 26): "Day After Thanksgiving / Black Friday (13:00 ET Early Close)",
}

# Official TSX (Canada) holidays (2025–2027)
CA_TSX_HOLIDAYS: dict[date, str] = {
    date(2025, 1, 1): "New Year's Day",
    date(2025, 2, 17): "Family Day",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 19): "Victoria Day",
    date(2025, 7, 1): "Canada Day",
    date(2025, 8, 4): "Civic Holiday",
    date(2025, 9, 1): "Labour Day",
    date(2025, 10, 13): "Thanksgiving Day (Canada)",
    date(2025, 12, 25): "Christmas Day",
    date(2025, 12, 26): "Boxing Day",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 2, 16): "Family Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 18): "Victoria Day",
    date(2026, 7, 1): "Canada Day",
    date(2026, 8, 3): "Civic Holiday",
    date(2026, 9, 7): "Labour Day",
    date(2026, 10, 12): "Thanksgiving Day (Canada)",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 28): "Boxing Day (Observed)",
    date(2027, 1, 1): "New Year's Day",
}

# CME Contract-specific specifications
CME_CONTRACT_SPECS: dict[str, dict[str, str]] = {
    "GC": {
        "contract_name": "COMEX Gold Futures (100 troy oz)",
        "exchange": "COMEX",
        "asset_class": "futures_metals",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "13:29–13:30 ET",
    },
    "MGC": {
        "contract_name": "COMEX Micro Gold Futures (10 troy oz)",
        "exchange": "COMEX",
        "asset_class": "futures_metals",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "13:29–13:30 ET",
    },
    "SI": {
        "contract_name": "COMEX Silver Futures (5,000 troy oz)",
        "exchange": "COMEX",
        "asset_class": "futures_metals",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "13:24–13:25 ET",
    },
    "ES": {
        "contract_name": "CME E-mini S&P 500 Futures",
        "exchange": "CME",
        "asset_class": "futures_index",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "15:59:30–16:00:00 ET",
    },
    "NQ": {
        "contract_name": "CME E-mini Nasdaq-100 Futures",
        "exchange": "CME",
        "asset_class": "futures_index",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "15:59:30–16:00:00 ET",
    },
    "MNQ": {
        "contract_name": "CME Micro E-mini Nasdaq-100 Futures",
        "exchange": "CME",
        "asset_class": "futures_index",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "15:59:30–16:00:00 ET",
    },
    "CL": {
        "contract_name": "NYMEX Light Sweet Crude Oil Futures",
        "exchange": "NYMEX",
        "asset_class": "futures_energy",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily Maintenance 17:00–18:00 ET)",
        "settlement_window_et": "14:28–14:30 ET",
    },
}

KNOWN_US_EQUITIES_AND_ETFS: set[str] = {
    "SPY", "QQQ", "IWM", "DIA", "GLD", "IAU", "SLV", "SIVR", "PPLT", "PALL",
    "TLT", "IEF", "SHY", "SGOV", "BIL", "MUB", "LQD", "AGG", "BND", "VTI", "VOO",
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "BRK.B", "JPM",
}
KNOWN_CANADA_TSX: set[str] = {
    "MNT.TO", "KILO.TO", "SVR.TO", "XIC.TO", "XIU.TO", "VFV.TO", "ZAG.TO", "CBIL.TO", "PSA.TO", "RY.TO", "TD.TO", "SHOP.TO",
}
KNOWN_CRYPTO: set[str] = {
    "BTC-USD", "ETH-USD", "SOL-USD", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
}
KNOWN_FX: set[str] = {
    "EUR_USD", "USD_CAD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CHF", "EUR/USD", "USD/CAD",
}


def _fmt_minutes_delta(minutes: int) -> str:
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def classify_symbol_venue(symbol: str) -> str:
    """Map an instrument symbol to its canonical market session venue."""
    s = symbol.upper().strip()
    if not s or "UNKNOWN" in s or "BOGUS" in s or "INVALID" in s:
        return "UNKNOWN"
    if s.startswith("PUMP:") or s.endswith("PUMP") or "BONK" in s:
        return "SOLANA_PUMP"
    if s in KNOWN_CRYPTO or s.endswith("-USD") or s.endswith("USDT"):
        return "CRYPTO_24_7"
    if s in CME_CONTRACT_SPECS or s.endswith("=F"):
        return "CME_COMEX_FUTURES"
    if s in KNOWN_FX or ("_" in s and len(s) == 7) or ("/" in s and len(s) == 7):
        return "GLOBAL_FX"
    if s in KNOWN_CANADA_TSX or s.endswith(".TO"):
        return "CANADA_TSX"
    if s in KNOWN_US_EQUITIES_AND_ETFS:
        return "US_EQUITIES_ETFS"
    if s.isalpha() and 1 <= len(s) <= 5:
        return "US_EQUITIES_ETFS"
    return "UNKNOWN"


def _next_us_regular_open(dt_et: datetime) -> datetime:
    cur_date = dt_et.date()
    reg_open_time = time(9, 30)
    if cur_date.weekday() < 5 and cur_date not in US_MARKET_HOLIDAYS and (dt_et.hour * 60 + dt_et.minute) < (9 * 60 + 30):
        return datetime.combine(cur_date, reg_open_time, tzinfo=ET_TZ)
    for offset in range(1, 10):
        cand = cur_date + timedelta(days=offset)
        if cand.weekday() < 5 and cand not in US_MARKET_HOLIDAYS:
            return datetime.combine(cand, reg_open_time, tzinfo=ET_TZ)
    return datetime.combine(cur_date + timedelta(days=1), reg_open_time, tzinfo=ET_TZ)


def _us_equities_session(dt_et: datetime) -> dict[str, Any]:
    d = dt_et.date()
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    pre_open = 4 * 60
    reg_open = 9 * 60 + 30
    early_close_mins = 13 * 60
    reg_close = 16 * 60
    ah_close = 20 * 60
    nasdaq_23_5_active = d >= NASDAQ_23_5_EFFECTIVE_DATE
    next_open_dt = _next_us_regular_open(dt_et)

    if d in US_MARKET_HOLIDAYS:
        h_name = US_MARKET_HOLIDAYS[d]
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": "HOLIDAY",
            "scheduled_market_status": "HOLIDAY",
            "trading_session": "HOLIDAY_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED (HOLIDAY)",
            "status_label": "CLOSED (HOLIDAY)",
            "label": f"Closed for US Market Holiday ({h_name})",
            "reason": f"Closed for US Market Holiday ({h_name})",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "countdown": f"Reopens {next_open_dt.strftime('%a %Y-%m-%d %H:%M ET')}",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
            "nasdaq_23_5_active": nasdaq_23_5_active,
        }

    if wd >= 5:
        # Check Sunday night >= 20:00 ET if Nasdaq 23/5 is effective (>= 2026-12-01)
        if nasdaq_23_5_active and wd == 6 and mins >= 20 * 60:
            rem = (24 * 60 - mins) + reg_open
            return {
                "venue_id": "US_EQUITIES_ETFS",
                "venue_name": "NYSE / NASDAQ / Arca",
                "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
                "status": "OVERNIGHT_SESSION",
                "scheduled_market_status": "OVERNIGHT_SESSION",
                "trading_session": "NASDAQ_23_5_OVERNIGHT",
                "is_open": False,
                "extended_hours_active": True,
                "badge": "OVERNIGHT (23/5)",
                "status_label": "OVERNIGHT (23/5)",
                "label": "Nasdaq 23/5 Overnight Session Active (Regular Cash Opens 09:30 ET)",
                "reason": "Nasdaq 23/5 Overnight Session Active (effective Dec 2026)",
                "schedule_et": "Nasdaq 23/5 Overnight + Regular 09:30–16:00 ET",
                "schedule_summary": "Nasdaq 23/5 Overnight + Regular 09:30–16:00 ET",
                "countdown": f"Regular open in {_fmt_minutes_delta(rem)} (09:30 ET)",
                "next_scheduled_open": next_open_dt.isoformat(),
                "next_scheduled_close": datetime.combine(next_open_dt.date(), time(16, 0), tzinfo=ET_TZ).isoformat(),
                "nasdaq_23_5_active": True,
            }
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": "CLOSED",
            "scheduled_market_status": "CLOSED",
            "trading_session": "WEEKEND_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED (WEEKEND)",
            "status_label": "CLOSED (WEEKEND)",
            "label": "Closed for Weekend",
            "reason": "Closed for Weekend",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "countdown": "Reopens Mon 09:30 ET (Pre-Market 04:00 ET)",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
            "nasdaq_23_5_active": nasdaq_23_5_active,
        }

    is_early_close_day = d in US_MARKET_EARLY_CLOSES
    effective_reg_close = early_close_mins if is_early_close_day else reg_close
    effective_ah_close = (17 * 60) if is_early_close_day else ah_close

    if reg_open <= mins < effective_reg_close:
        rem = effective_reg_close - mins
        close_dt = datetime.combine(d, time(effective_reg_close // 60, effective_reg_close % 60), tzinfo=ET_TZ)
        sched_state = "EARLY_CLOSE" if is_early_close_day else "REGULAR_SESSION"
        badge_txt = "OPEN (EARLY CLOSE 13:00 ET)" if is_early_close_day else "OPEN"
        label_txt = US_MARKET_EARLY_CLOSES[d] if is_early_close_day else "Regular Cash Session Open"
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": sched_state,
            "scheduled_market_status": sched_state,
            "trading_session": "REGULAR_SESSION",
            "is_open": True,
            "extended_hours_active": True,
            "badge": badge_txt,
            "status_label": badge_txt,
            "label": label_txt,
            "reason": label_txt,
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "countdown": f"Closes in {_fmt_minutes_delta(rem)} ({'13:00' if is_early_close_day else '16:00'} ET)",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": close_dt.isoformat(),
            "nasdaq_23_5_active": nasdaq_23_5_active,
        }

    if pre_open <= mins < reg_open:
        rem = reg_open - mins
        open_dt = datetime.combine(d, time(9, 30), tzinfo=ET_TZ)
        close_dt = datetime.combine(d, time(effective_reg_close // 60, effective_reg_close % 60), tzinfo=ET_TZ)
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": "PREMARKET",
            "scheduled_market_status": "PREMARKET",
            "trading_session": "PREMARKET",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "PRE-MKT (CASH CLOSED)",
            "status_label": "PRE-MKT (CASH CLOSED)",
            "label": "Pre-Market Session (Regular Cash Session Closed until 09:30 ET)",
            "reason": "Pre-Market Session (Regular Cash Session Closed until 09:30 ET)",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "countdown": f"Regular open in {_fmt_minutes_delta(rem)} (09:30 ET)",
            "next_scheduled_open": open_dt.isoformat(),
            "next_scheduled_close": close_dt.isoformat(),
            "nasdaq_23_5_active": nasdaq_23_5_active,
        }

    if effective_reg_close <= mins < effective_ah_close:
        rem = effective_ah_close - mins
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": "AFTER_HOURS",
            "scheduled_market_status": "AFTER_HOURS",
            "trading_session": "AFTER_HOURS",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "AFTER-HRS (CASH CLOSED)",
            "status_label": "AFTER-HRS (CASH CLOSED)",
            "label": "After-Hours Session (Regular Cash Session Closed at 16:00 ET)",
            "reason": "After-Hours Session (Regular Cash Session Closed)",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
            "countdown": f"After-hours ends in {_fmt_minutes_delta(rem)} ({effective_ah_close // 60:02d}:00 ET)",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
            "nasdaq_23_5_active": nasdaq_23_5_active,
        }

    # Overnight window (20:00–04:00 ET): only OVERNIGHT_SESSION on or after 2026-12-01 (and Mon–Thu night / early Fri)
    if nasdaq_23_5_active and not (wd == 4 and mins >= 20 * 60):
        rem = (reg_open - mins) if mins < pre_open else ((24 * 60 - mins) + reg_open)
        return {
            "venue_id": "US_EQUITIES_ETFS",
            "venue_name": "NYSE / NASDAQ / Arca",
            "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
            "status": "OVERNIGHT_SESSION",
            "scheduled_market_status": "OVERNIGHT_SESSION",
            "trading_session": "NASDAQ_23_5_OVERNIGHT",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "OVERNIGHT (23/5)",
            "status_label": "OVERNIGHT (23/5)",
            "label": "Nasdaq 23/5 Overnight Session Active (Effective Dec 2026)",
            "reason": "Nasdaq 23/5 Overnight Session Active (Effective Dec 2026)",
            "schedule_et": "Nasdaq 23/5 Overnight + Regular 09:30–16:00 ET",
            "schedule_summary": "Nasdaq 23/5 Overnight + Regular 09:30–16:00 ET",
            "countdown": f"Regular open in {_fmt_minutes_delta(rem)} (09:30 ET)",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
            "nasdaq_23_5_active": True,
        }

    if mins < pre_open:
        rem = reg_open - mins
        cd = f"Regular open in {_fmt_minutes_delta(rem)} (09:30 ET)"
    else:
        rem = (24 * 60 - mins) + reg_open
        cd = f"Next regular open in {_fmt_minutes_delta(rem)} (09:30 ET)"
    return {
        "venue_id": "US_EQUITIES_ETFS",
        "venue_name": "NYSE / NASDAQ / Arca",
        "asset_classes": ["US Equities (SPY, QQQ, NVDA, AAPL)", "Precious Metal & Bond ETFs (GLD, SLV, TLT)"],
        "status": "CLOSED",
        "scheduled_market_status": "CLOSED",
        "trading_session": "OVERNIGHT_CLOSED",
        "is_open": False,
        "extended_hours_active": False,
        "badge": "CLOSED",
        "status_label": "CLOSED",
        "label": "Overnight Closed",
        "reason": "Overnight Closed (Nasdaq 23/5 transition effective Dec 2026)",
        "schedule_et": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
        "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Market: 04:00–09:30 ET | After-Hours: 16:00–20:00 ET",
        "countdown": cd,
        "next_scheduled_open": next_open_dt.isoformat(),
        "next_scheduled_close": None,
        "nasdaq_23_5_active": False,
    }


def _canada_tsx_session(dt_et: datetime) -> dict[str, Any]:
    d = dt_et.date()
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    pre_open = 7 * 60
    reg_open = 9 * 60 + 30
    reg_close = 16 * 60
    next_open_dt = _next_us_regular_open(dt_et)

    if d in CA_TSX_HOLIDAYS:
        h_name = CA_TSX_HOLIDAYS[d]
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian ETRs & ETFs (MNT.TO, XIC.TO, VFV.TO, ZAG.TO)"],
            "status": "HOLIDAY",
            "scheduled_market_status": "HOLIDAY",
            "trading_session": "HOLIDAY_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED (HOLIDAY)",
            "status_label": "CLOSED (HOLIDAY)",
            "label": f"Closed for Canadian Holiday ({h_name})",
            "reason": f"Closed for Canadian Holiday ({h_name})",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "countdown": "Reopens Next Business Day 09:30 ET",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
        }

    if wd >= 5:
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian ETRs & ETFs (MNT.TO, XIC.TO, VFV.TO, ZAG.TO)"],
            "status": "CLOSED",
            "scheduled_market_status": "CLOSED",
            "trading_session": "WEEKEND_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED (WEEKEND)",
            "status_label": "CLOSED (WEEKEND)",
            "label": "Closed for Weekend",
            "reason": "Closed for Weekend",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "countdown": "Reopens Mon 09:30 ET",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": None,
        }

    if reg_open <= mins < reg_close:
        rem = reg_close - mins
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian ETRs & ETFs (MNT.TO, XIC.TO, VFV.TO, ZAG.TO)"],
            "status": "REGULAR_SESSION",
            "scheduled_market_status": "REGULAR_SESSION",
            "trading_session": "REGULAR_SESSION",
            "is_open": True,
            "extended_hours_active": True,
            "badge": "OPEN",
            "status_label": "OPEN",
            "label": "TSX Regular Session Open",
            "reason": "TSX Regular Session Open",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "countdown": f"Closes in {_fmt_minutes_delta(rem)} (16:00 ET)",
            "next_scheduled_open": next_open_dt.isoformat(),
            "next_scheduled_close": datetime.combine(d, time(16, 0), tzinfo=ET_TZ).isoformat(),
        }

    if pre_open <= mins < reg_open:
        rem = reg_open - mins
        return {
            "venue_id": "CANADA_TSX",
            "venue_name": "Toronto Stock Exchange (TSX)",
            "asset_classes": ["Canadian ETRs & ETFs (MNT.TO, XIC.TO, VFV.TO, ZAG.TO)"],
            "status": "PREOPEN",
            "scheduled_market_status": "PREOPEN",
            "trading_session": "PREOPEN",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "PRE-OPEN (CLOSED)",
            "status_label": "PRE-OPEN (CLOSED)",
            "label": "TSX Pre-Open Order Entry (Continuous Trading Starts 09:30 ET)",
            "reason": "TSX Pre-Open Order Entry (Continuous Trading Starts 09:30 ET)",
            "schedule_et": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
            "countdown": f"Opens in {_fmt_minutes_delta(rem)} (09:30 ET)",
            "next_scheduled_open": datetime.combine(d, time(9, 30), tzinfo=ET_TZ).isoformat(),
            "next_scheduled_close": datetime.combine(d, time(16, 0), tzinfo=ET_TZ).isoformat(),
        }

    rem = (reg_open - mins) if mins < pre_open else ((24 * 60 - mins) + reg_open)
    return {
        "venue_id": "CANADA_TSX",
        "venue_name": "Toronto Stock Exchange (TSX)",
        "asset_classes": ["Canadian ETRs & ETFs (MNT.TO, XIC.TO, VFV.TO, ZAG.TO)"],
        "status": "CLOSED",
        "scheduled_market_status": "CLOSED",
        "trading_session": "CLOSED",
        "is_open": False,
        "extended_hours_active": False,
        "badge": "CLOSED",
        "status_label": "CLOSED",
        "label": "TSX Session Closed",
        "reason": "TSX Session Closed",
        "schedule_et": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
        "schedule_summary": "Regular: 09:30–16:00 ET | Pre-Open: 07:00–09:30 ET",
        "countdown": f"Next open in {_fmt_minutes_delta(rem)} (09:30 ET)",
        "next_scheduled_open": next_open_dt.isoformat(),
        "next_scheduled_close": None,
    }


def _cme_comex_session(dt_et: datetime) -> dict[str, Any]:
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    break_start = 17 * 60
    break_end = 18 * 60

    if wd == 6 and break_start <= mins < break_end:
        rem = break_end - mins
        sun_open = datetime.combine(dt_et.date(), time(18, 0), tzinfo=ET_TZ)
        return {
            "venue_id": "CME_COMEX_FUTURES",
            "venue_name": "CME / COMEX / NYMEX Globex",
            "asset_classes": ["Gold (GC, MGC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, MNQ, CL)"],
            "status": "PREOPEN",
            "scheduled_market_status": "PREOPEN",
            "trading_session": "SUNDAY_PREOPEN",
            "is_open": False,
            "extended_hours_active": True,
            "badge": "PRE-OPEN",
            "status_label": "PRE-OPEN",
            "label": "CME Globex Sunday Pre-Open Order Entry (17:00–18:00 ET)",
            "reason": "CME Globex Sunday Pre-Open Order Entry (17:00–18:00 ET)",
            "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "schedule_summary": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "countdown": f"Opens in {_fmt_minutes_delta(rem)} (18:00 ET)",
            "next_scheduled_open": sun_open.isoformat(),
            "next_scheduled_close": None,
        }

    if wd == 5 or (wd == 4 and mins >= break_start) or (wd == 6 and mins < break_start):
        days_to_sun = (6 - wd) % 7
        sun_open = datetime.combine(dt_et.date() + timedelta(days=days_to_sun), time(18, 0), tzinfo=ET_TZ)
        return {
            "venue_id": "CME_COMEX_FUTURES",
            "venue_name": "CME / COMEX / NYMEX Globex",
            "asset_classes": ["Gold (GC, MGC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, MNQ, CL)"],
            "status": "CLOSED",
            "scheduled_market_status": "CLOSED",
            "trading_session": "WEEKEND_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "status_label": "CLOSED",
            "label": "CME Globex Weekend Closure",
            "reason": "CME Globex Weekend Closure",
            "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "schedule_summary": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "countdown": "Reopens Sun 18:00 ET",
            "next_scheduled_open": sun_open.isoformat(),
            "next_scheduled_close": None,
        }

    if wd in (0, 1, 2, 3) and break_start <= mins < break_end:
        rem = break_end - mins
        reopen_dt = datetime.combine(dt_et.date(), time(18, 0), tzinfo=ET_TZ)
        return {
            "venue_id": "CME_COMEX_FUTURES",
            "venue_name": "CME / COMEX / NYMEX Globex",
            "asset_classes": ["Gold (GC, MGC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, MNQ, CL)"],
            "status": "MAINTENANCE",
            "scheduled_market_status": "MAINTENANCE",
            "trading_session": "DAILY_MAINTENANCE",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "MAINTENANCE",
            "status_label": "MAINTENANCE",
            "label": "CME Globex Daily Maintenance Break (17:00–18:00 ET)",
            "reason": "CME Globex Daily Maintenance Break (17:00–18:00 ET)",
            "schedule_et": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "schedule_summary": "Sun 18:00 – Fri 17:00 ET (Daily maintenance 17:00–18:00 ET)",
            "countdown": f"Reopens in {_fmt_minutes_delta(rem)} (18:00 ET)",
            "next_scheduled_open": reopen_dt.isoformat(),
            "next_scheduled_close": None,
        }

    if mins < break_start:
        rem = break_start - mins
        next_close_dt = datetime.combine(dt_et.date(), time(17, 0), tzinfo=ET_TZ)
    else:
        rem = (24 * 60 - mins) + break_start
        next_close_dt = datetime.combine(dt_et.date() + timedelta(days=1), time(17, 0), tzinfo=ET_TZ)
    return {
        "venue_id": "CME_COMEX_FUTURES",
        "venue_name": "CME / COMEX / NYMEX Globex",
        "asset_classes": ["Gold (GC, MGC)", "Silver (SI)", "Index & Energy Futures (ES, NQ, MNQ, CL)"],
        "status": "OPEN",
        "scheduled_market_status": "OPEN",
        "trading_session": "GLOBEX_ELECTRONIC",
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (23/5)",
        "status_label": "OPEN (23/5)",
        "label": "CME Globex Electronic Session Open",
        "reason": "CME Globex Electronic Session Open",
        "schedule_et": "Sun 18:00 – Fri 17:00 ET (23/5)",
        "schedule_summary": "Sun 18:00 – Fri 17:00 ET (23/5)",
        "countdown": f"Next 17:00 ET maintenance break in {_fmt_minutes_delta(rem)}",
        "next_scheduled_open": None,
        "next_scheduled_close": next_close_dt.isoformat(),
    }


def _global_fx_session(dt_et: datetime) -> dict[str, Any]:
    wd = dt_et.weekday()
    mins = dt_et.hour * 60 + dt_et.minute
    close_fri = 17 * 60
    open_sun = 17 * 60

    if wd == 5 or (wd == 4 and mins >= close_fri) or (wd == 6 and mins < open_sun):
        days_to_sun = (6 - wd) % 7
        sun_open = datetime.combine(dt_et.date() + timedelta(days=days_to_sun), time(17, 0), tzinfo=ET_TZ)
        return {
            "venue_id": "GLOBAL_FX",
            "venue_name": "Global Spot FX (24/5)",
            "asset_classes": ["EUR/USD", "USD/CAD (Bank of Canada / Spot)"],
            "status": "CLOSED",
            "scheduled_market_status": "CLOSED",
            "trading_session": "WEEKEND_CLOSED",
            "is_open": False,
            "extended_hours_active": False,
            "badge": "CLOSED",
            "status_label": "CLOSED",
            "label": "FX Weekend Closure",
            "reason": "FX Weekend Closure",
            "schedule_et": "Sun 17:00 – Fri 17:00 ET (24/5)",
            "schedule_summary": "Sun 17:00 – Fri 17:00 ET (24/5)",
            "countdown": "Reopens Sun 17:00 ET",
            "next_scheduled_open": sun_open.isoformat(),
            "next_scheduled_close": None,
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
        "scheduled_market_status": "OPEN",
        "trading_session": center.upper().replace(" / ", "_").replace(" ", "_"),
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (24/5)",
        "status_label": "OPEN (24/5)",
        "label": f"Spot FX Open · {center}",
        "reason": f"Spot FX Open · {center}",
        "schedule_et": "Sun 17:00 – Fri 17:00 ET (24/5)",
        "schedule_summary": "Sun 17:00 – Fri 17:00 ET (24/5)",
        "countdown": f"Active: {center}",
        "next_scheduled_open": None,
        "next_scheduled_close": None,
    }


def _crypto_session() -> dict[str, Any]:
    return {
        "venue_id": "CRYPTO_24_7",
        "venue_name": "Crypto Spot & Perps (24/7)",
        "asset_classes": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "status": "OPEN",
        "scheduled_market_status": "OPEN",
        "trading_session": "CONTINUOUS_24_7",
        "is_open": True,
        "extended_hours_active": True,
        "badge": "OPEN (24/7)",
        "status_label": "OPEN (24/7)",
        "label": "24/7/365 Continuous Trading",
        "reason": "24/7/365 Continuous Trading",
        "schedule_et": "24/7/365 Continuous",
        "schedule_summary": "24/7/365 Continuous",
        "countdown": "Always Open (24/7)",
        "next_scheduled_open": None,
        "next_scheduled_close": None,
    }


def evaluate_instrument_market_status(
    symbol: str,
    *,
    now: datetime | None = None,
    venue_reported_status: str | None = None,
    data_feed_health: str | None = None,
    last_price: float | None = None,
    last_price_timestamp: str | int | float | None = None,
    data_source: str | None = None,
    stale_threshold_seconds: float = 900.0,
    pump_curve_state: str | None = None,
    pumpswap_pool_available: bool | None = None,
    exit_liquidity_usd: float | None = None,
    bonding_curve_complete: bool | None = None,
    migration_in_progress: bool | None = None,
    pool_liquidity_usd: float | None = None,
) -> dict[str, Any]:
    """Evaluate authoritative instrument-level market status (Sections 9–12 & 23).

    Independently tracks:
      - SCHEDULED_MARKET_STATUS
      - VENUE_REPORTED_TRADING_STATUS
      - DATA_FEED_HEALTH
    """
    now_utc = (now or datetime.now(UTC_TZ)).astimezone(UTC_TZ)
    dt_et = now_utc.astimezone(ET_TZ)
    sym = (symbol or "").upper().strip()
    vid = classify_symbol_venue(sym)

    if vid == "UNKNOWN":
        return {
            "instrument": sym or "UNKNOWN",
            "symbol": sym or "UNKNOWN",
            "venue_id": "UNKNOWN",
            "venue_name": "Unknown Exchange",
            "exchange": "UNKNOWN",
            "asset_class": "unknown",
            "status": "UNKNOWN",
            "market_status": "UNKNOWN",
            "scheduled_market_status": "UNKNOWN",
            "venue_reported_trading_status": "UNKNOWN",
            "data_feed_health": "UNAVAILABLE",
            "trading_session": "UNKNOWN",
            "is_open": False,
            "is_tradable": False,
            "badge": "STATUS UNAVAILABLE",
            "status_label": "STATUS UNAVAILABLE",
            "label": "Unknown Symbol — Status Unavailable",
            "reason": "Unknown Symbol — Status Unavailable",
            "schedule_summary": "Unavailable",
            "countdown": "—",
            "last_price": None,
            "last_price_timestamp": None,
            "data_source": "none",
            "data_freshness": "UNAVAILABLE",
            "next_scheduled_open": None,
            "next_scheduled_close": None,
            "risk_eligibility": "REJECTED_UNKNOWN_SYMBOL",
            "display_banner": f"{sym or 'UNKNOWN SYMBOL'}: STATUS UNAVAILABLE",
            "market_closed_behavior": {
                "suppress_live_predictions": True,
                "prediction_status_override": "MODEL_UNAVAILABLE",
                "execution_allowed": False,
            },
            "execution_permission": "none",
        }

    if vid == "SOLANA_PUMP":
        eff_liq = pool_liquidity_usd if pool_liquidity_usd is not None else exit_liquidity_usd
        if migration_in_progress is True:
            v_status = "HALTED"
            m_status = "HALTED"
            curve = "MIGRATING_TO_PUMPSWAP"
            banner = f"PUMP TOKEN ({sym}): MIGRATION IN PROGRESS — HALTED"
            risk_elig = "REJECTED_MIGRATION_IN_PROGRESS"
        elif bonding_curve_complete is True and (pumpswap_pool_available is False or (eff_liq is not None and float(eff_liq) < 1000.0)):
            v_status = "TRADING_DISABLED"
            m_status = "TRADING_DISABLED"
            curve = "MIGRATED"
            banner = f"PUMP TOKEN ({sym}): MIGRATED — PUMPSWAP POOL UNAVAILABLE"
            risk_elig = "REJECTED_POOL_UNAVAILABLE"
        elif bonding_curve_complete is False and not migration_in_progress and pump_curve_state is None:
            v_status = venue_reported_status.upper() if venue_reported_status else "OPEN"
            m_status = v_status
            curve = "BONDING_CURVE_ACTIVE"
            banner = f"PUMP TOKEN ({sym}): BONDING CURVE ACTIVE — GOVERNED READ-ONLY"
            risk_elig = "RISK_REJECTED_SPECULATIVE_TOKEN_POLICY"
        else:
            curve = (pump_curve_state or "CURVE_ACTIVE").upper()
            pool_ok = True if pumpswap_pool_available is None else bool(pumpswap_pool_available)
            liq_ok = (eff_liq is None) or (float(eff_liq) >= 25_000.0)
            if curve == "MIGRATED" and not pool_ok:
                v_status = "TRADING_DISABLED"
                m_status = "TRADING_DISABLED"
                banner = f"PUMP TOKEN ({sym}): MIGRATED — PUMPSWAP POOL UNAVAILABLE"
                risk_elig = "REJECTED_POOL_UNAVAILABLE"
            elif not liq_ok:
                v_status = "VIEW_ONLY"
                m_status = "VIEW_ONLY"
                banner = f"PUMP TOKEN ({sym}): {curve} — INSUFFICIENT EXIT LIQUIDITY"
                risk_elig = "REJECTED_EXIT_LIQUIDITY"
            else:
                v_status = venue_reported_status.upper() if venue_reported_status else "VIEW_ONLY"
                m_status = v_status
                banner = f"PUMP TOKEN: {curve.replace('_', ' ')} — RISK REJECTED"
                risk_elig = "RISK_REJECTED_SPECULATIVE_TOKEN_POLICY"
        return {
            "instrument": sym,
            "symbol": sym,
            "venue_id": "SOLANA_PUMP",
            "venue_name": "Solana / Pump.fun & PumpSwap (Governed Read-Only)",
            "exchange": "SOLANA",
            "asset_class": "solana_spl_token",
            "status": m_status,
            "market_status": m_status,
            "scheduled_market_status": "OPEN",
            "venue_reported_trading_status": v_status,
            "data_feed_health": data_feed_health or "HEALTHY",
            "trading_session": curve,
            "is_open": False,
            "is_tradable": False,
            "badge": "RISK REJECTED",
            "status_label": "RISK REJECTED",
            "label": banner,
            "reason": banner,
            "schedule_summary": "24/7 On-Chain (Public Execution Disabled by Authentic Assets Policy)",
            "countdown": "Execution Disabled",
            "last_price": last_price,
            "last_price_timestamp": str(last_price_timestamp) if last_price_timestamp else None,
            "data_source": data_source or "solana_rpc_readonly",
            "data_freshness": data_feed_health or "HEALTHY",
            "next_scheduled_open": None,
            "next_scheduled_close": None,
            "risk_eligibility": risk_elig,
            "display_banner": banner,
            "market_closed_behavior": {
                "suppress_live_predictions": False,
                "prediction_status_override": None,
                "execution_allowed": False,
            },
            "execution_permission": "none",
        }

    venue_map = {
        "US_EQUITIES_ETFS": _us_equities_session(dt_et),
        "CANADA_TSX": _canada_tsx_session(dt_et),
        "CME_COMEX_FUTURES": _cme_comex_session(dt_et),
        "GLOBAL_FX": _global_fx_session(dt_et),
        "CRYPTO_24_7": _crypto_session(),
    }
    base_v = venue_map[vid]
    sched_status = str(base_v["scheduled_market_status"])

    # Determine data age & data_feed_health
    age_s: float | None = None
    ts_iso: str | None = None
    if last_price_timestamp is not None:
        try:
            if isinstance(last_price_timestamp, (int, float)):
                ts_dt = datetime.fromtimestamp(float(last_price_timestamp), tz=UTC_TZ)
            else:
                ts_dt = datetime.fromisoformat(str(last_price_timestamp).replace("Z", "+00:00"))
            ts_iso = ts_dt.isoformat()
            age_s = max(0.0, (now_utc - ts_dt).total_seconds())
        except Exception:
            ts_iso = str(last_price_timestamp)

    if data_feed_health is not None:
        feed_health = data_feed_health.upper()
    elif age_s is not None and base_v["is_open"] and age_s > stale_threshold_seconds:
        feed_health = "STALE"
    else:
        feed_health = "HEALTHY"

    # Determine venue_reported_trading_status
    v_rep = (venue_reported_status or ("OPEN" if base_v["is_open"] else sched_status)).upper()

    # Effective market_status combines venue restrictions with scheduled status
    if v_rep in {"HALTED", "LIMIT_ONLY", "POST_ONLY", "CANCEL_ONLY", "VIEW_ONLY", "TRADING_DISABLED"}:
        eff_status = v_rep
        is_open = False
        is_tradable = v_rep in {"LIMIT_ONLY", "POST_ONLY"}
    elif feed_health in {"STALE", "DISCONNECTED"} and bool(base_v["is_open"]):
        eff_status = "STALE_MARKET_DATA"
        is_open = True
        is_tradable = False
    else:
        eff_status = sched_status
        is_open = bool(base_v["is_open"])
        is_tradable = is_open and feed_health == "HEALTHY"

    # Contract-specific exchange & asset class
    if vid == "CME_COMEX_FUTURES":
        cspec = CME_CONTRACT_SPECS.get(sym, CME_CONTRACT_SPECS["GC"])
        exchange = cspec["exchange"]
        asset_class = cspec["asset_class"]
        sched_summary = cspec["schedule_et"]
    elif vid == "US_EQUITIES_ETFS":
        exchange = "NASDAQ" if sym in {"QQQ", "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "TLT", "IEF", "SHY"} else "NYSE_ARCA"
        asset_class = "etf" if sym in {"SPY", "QQQ", "IWM", "DIA", "GLD", "IAU", "SLV", "SIVR", "PPLT", "PALL", "TLT", "IEF", "SHY", "SGOV", "BIL", "MUB", "LQD", "AGG", "BND", "VTI", "VOO"} else "equity"
        sched_summary = base_v["schedule_summary"]
    elif vid == "CANADA_TSX":
        exchange = "TSX"
        asset_class = "canadian_etf_etr"
        sched_summary = base_v["schedule_summary"]
    elif vid == "GLOBAL_FX":
        exchange = "FX_INTERBANK"
        asset_class = "fx_spot"
        sched_summary = base_v["schedule_summary"]
    else:
        exchange = "COINBASE" if sym.endswith("-USD") else "BINANCE"
        asset_class = "crypto"
        sched_summary = base_v["schedule_summary"]

    # Build display banner (Section 11 examples)
    if eff_status == "REGULAR_SESSION":
        banner = f"{exchange}: OPEN — REGULAR SESSION" if feed_health == "HEALTHY" else f"{exchange}: OPEN — DATA {feed_health}"
    elif eff_status == "MAINTENANCE":
        banner = f"{sym}: MAINTENANCE"
    elif vid == "CRYPTO_24_7" and eff_status == "OPEN":
        banner = f"{sym}: OPEN — DATA {feed_health}"
    elif eff_status in {"HALTED", "LIMIT_ONLY", "POST_ONLY", "CANCEL_ONLY", "VIEW_ONLY", "TRADING_DISABLED"}:
        banner = f"{sym}: {eff_status.replace('_', ' ')}"
    else:
        banner = f"{exchange}: {eff_status.replace('_', ' ')} — {base_v['badge']}"

    # Market-closed / stale behavior (Section 12)
    suppress_live = not is_open and vid != "CRYPTO_24_7"
    pred_override = None
    if feed_health in {"STALE", "DISCONNECTED"} and is_open:
        pred_override = "STALE_MARKET_DATA"
    elif not is_open and eff_status in {"CLOSED", "HOLIDAY", "MAINTENANCE"}:
        pred_override = "MARKET_CLOSED"

    risk_elig = (
        "ELIGIBLE_PAPER_CONTROL_PLANE"
        if is_tradable
        else f"BLOCKED_{feed_health}" if is_open and feed_health != "HEALTHY"
        else f"BLOCKED_{eff_status}"
    )

    return {
        "instrument": f"{exchange}:{sym}",
        "symbol": sym,
        "venue_id": vid,
        "venue_name": base_v["venue_name"],
        "exchange": exchange,
        "asset_class": asset_class,
        "status": eff_status,
        "market_status": eff_status,
        "scheduled_market_status": sched_status,
        "venue_reported_trading_status": v_rep,
        "data_feed_health": feed_health,
        "trading_session": base_v["trading_session"],
        "is_open": is_open,
        "is_tradable": is_tradable,
        "is_extended_hours": bool(base_v.get("extended_hours_active", False)) and not is_open,
        "is_holiday": sched_status == "HOLIDAY",
        "is_early_close": sched_status == "EARLY_CLOSE",
        "badge": base_v["badge"] if v_rep == "OPEN" or v_rep == sched_status else v_rep,
        "status_label": base_v["status_label"] if v_rep == "OPEN" or v_rep == sched_status else v_rep,
        "label": base_v["label"],
        "reason": base_v["reason"],
        "schedule_summary": sched_summary,
        "countdown": base_v["countdown"],
        "last_price": last_price,
        "last_price_timestamp": ts_iso,
        "data_source": data_source or ("atlas_sqlite_feed"),
        "data_freshness": f"{int(age_s)}s old ({feed_health})" if age_s is not None else feed_health,
        "next_scheduled_open": base_v.get("next_scheduled_open"),
        "next_scheduled_close": base_v.get("next_scheduled_close"),
        "risk_eligibility": risk_elig,
        "display_banner": banner,
        "nasdaq_23_5_active": base_v.get("nasdaq_23_5_active", False),
        "market_closed_behavior": {
            "preserve_last_price": True,
            "preserve_last_prediction_as_historical": not is_open,
            "suppress_live_predictions": suppress_live,
            "suppress_new_trading_candidates": not is_tradable,
            "prediction_status_override": pred_override,
            "execution_allowed": False,
            "allow_live_execution": False,
        },
        "execution_permission": "none",
    }


def get_market_sessions_status(
    now: datetime | None = None,
    symbols: Sequence[str] | None = None,
    venue_overrides: dict[str, str] | None = None,
    feed_health_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return real-time open/closed/pre-market/break status across all ATLAS venues and requested symbols."""
    now_utc = (now or datetime.now(UTC_TZ)).astimezone(UTC_TZ)
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

    default_syms = (
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "GC",
        "MGC",
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
        "MNQ",
        "CL",
        "EUR_USD",
        "USD_CAD",
    )
    target_syms = list(dict.fromkeys([*(symbols or default_syms)]))
    by_symbol: dict[str, dict[str, Any]] = {}
    for s in target_syms:
        s_up = s.upper().strip()
        by_symbol[s_up] = evaluate_instrument_market_status(
            s_up,
            now=now_utc,
            venue_reported_status=(venue_overrides or {}).get(s_up),
            data_feed_health=(feed_health_overrides or {}).get(s_up),
        )

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



CANDIDATE_GATE_STATES: tuple[str, ...] = (
    "MARKET_OPEN",
    "MARKET_CLOSED",
    "MARKET_HALTED",
    "MARKET_MAINTENANCE",
    "MARKET_RESTRICTED",
    "DATA_STALE",
    "BROKER_UNAVAILABLE",
    "STATUS_UNKNOWN",
)


def evaluate_candidate_market_gate(
    symbol: str,
    *,
    now: datetime | None = None,
    venue_reported_status: str | None = None,
    data_feed_health: str | None = None,
    data_age_seconds: float | None = None,
    max_stale_seconds: float = 3600.0,
    broker_available: bool = True,
    instrument_permitted: bool = True,
    account_restricted: bool = False,
) -> dict[str, Any]:
    """Section 21 Market Status Intelligence gate before any live strategy candidate is considered."""
    inst = evaluate_instrument_market_status(
        symbol,
        now=now,
        venue_reported_status=venue_reported_status,
        data_feed_health=data_feed_health,
    )
    eff = str(inst.get("venue_reported_trading_status") or inst.get("market_status") or "UNKNOWN").upper()

    if not broker_available:
        gate_state = "BROKER_UNAVAILABLE"
        eligible = False
        gate_reason = "Broker connectivity or paper session is unavailable."
    elif data_feed_health and str(data_feed_health).upper() in {"STALE", "DISCONNECTED", "ERROR", "NO_DATA"}:
        gate_state = "DATA_STALE"
        eligible = False
        gate_reason = f"Market data feed reported {data_feed_health}."
    elif data_age_seconds is not None and data_age_seconds > max_stale_seconds and inst.get("is_open"):
        gate_state = "DATA_STALE"
        eligible = False
        gate_reason = f"Latest bar age ({data_age_seconds:.0f}s) exceeds staleness threshold ({max_stale_seconds:.0f}s)."
    elif not instrument_permitted or account_restricted:
        gate_state = "MARKET_RESTRICTED"
        eligible = False
        gate_reason = "Instrument permission denied or account restriction active."
    elif eff == "HALTED":
        gate_state = "MARKET_HALTED"
        eligible = False
        gate_reason = str(inst.get("reason") or "Instrument trading is halted.")
    elif eff == "MAINTENANCE":
        gate_state = "MARKET_MAINTENANCE"
        eligible = False
        gate_reason = str(inst.get("reason") or "Venue is in scheduled maintenance break.")
    elif eff in {"LIMIT_ONLY", "POST_ONLY", "CANCEL_ONLY", "VIEW_ONLY", "TRADING_DISABLED"}:
        gate_state = "MARKET_RESTRICTED"
        eligible = eff in {"LIMIT_ONLY", "POST_ONLY"}
        gate_reason = f"Venue restriction active: {eff}."
    elif eff in {"CLOSED", "HOLIDAY"}:
        gate_state = "MARKET_CLOSED"
        eligible = False
        gate_reason = str(inst.get("reason") or "Exchange session is closed.")
    elif eff in {"OPEN", "REGULAR_SESSION", "PREMARKET", "AFTER_HOURS", "OVERNIGHT_SESSION", "EARLY_CLOSE", "PREOPEN"}:
        gate_state = "MARKET_OPEN"
        eligible = eff != "PREOPEN"
        gate_reason = str(inst.get("reason") or "Exchange session is open.")
    else:
        gate_state = "STATUS_UNKNOWN"
        eligible = False
        gate_reason = "Market session status could not be determined."

    return {
        "symbol": inst["symbol"],
        "exchange": inst["exchange"],
        "exchange_mic": inst.get("venue_id"),
        "candidate_gate_status": gate_state,
        "candidate_eligible": eligible,
        "gate_reason": gate_reason,
        "scheduled_market_status": inst["scheduled_market_status"],
        "trading_session": inst["trading_session"],
        "effective_status": eff,
        "data_feed_health": inst["data_feed_health"],
        "data_age_seconds": data_age_seconds,
        "broker_available": broker_available,
        "instrument_permitted": instrument_permitted,
        "account_restricted": account_restricted,
        "instrument_status": inst,
        "execution_permission": "none",
    }
