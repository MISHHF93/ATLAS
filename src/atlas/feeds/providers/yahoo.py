from __future__ import annotations

from ..core import Capabilities, ProviderAdapter, ProviderError

IV = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
RANGE = {"1m": "7d", "5m": "60d", "15m": "60d", "1h": "730d", "1d": "10y"}  # range=max silently downgrades 1d to monthly bars


class YahooAdapter(ProviderAdapter):
    caps = Capabilities(
        name="yahoo", title="Yahoo Finance chart endpoint (UNOFFICIAL fallback)", status="working",
        asset_classes=("equity", "etf", "index", "fx", "crypto", "future"), schemas=("bars",), intervals=tuple(IV),
        history_depth="Intraday limited: 1m=7d, 5m/15m=60d, 60m=730d; daily=max",
        live_stream="none (polling only)",
        rate_limits="Undocumented; ATLAS self-limits to 1 req/s and backs off on 429",
        auth_env=(), unofficial=True,
        official_docs=("https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",),
        terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
        notes="No official public API/docs; endpoint query1.finance.yahoo.com/v8/finance/chart is unofficial and may change. "
              "Labelled fallback only; personal/research use per Yahoo terms. Bars are 15m-delayed-ish; last bar may be partial.")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        from ..core import RateLimiter
        self.limiter = RateLimiter(1, 1.0, sleep=self.sleep)

    def _history(self, instrument, interval, start, end, now):
        sym = self.provider_symbol(instrument)
        js = self.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                           {"interval": IV[interval], "range": RANGE[interval], "includePrePost": "false"},
                           headers={"User-Agent": "Mozilla/5.0"})
        res = (js.get("chart") or {}).get("result")
        if not res:
            raise ProviderError(f"yahoo: {js.get('chart', {}).get('error')}")
        r = res[0]
        q = r["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(r.get("timestamp") or []):
            vals = [q[k][i] for k in ("open", "high", "low", "close")]
            if None in vals:
                continue
            out.append(self._bar(instrument, interval, t, *vals, q["volume"][i] or 0, now))
        return clean_intraday(out, interval, getattr(self, "session_hint", None) or _session_for(instrument), self.artifacts)

    @property
    def artifacts(self) -> list:
        if not hasattr(self, "_artifacts"):
            self._artifacts = []
        return self._artifacts


def _session_for(instrument: str) -> str:
    from ..instruments import InstrumentMaster
    master = InstrumentMaster()
    return master.get(instrument).session if instrument in master else "24x7"


def clean_intraday(bars: list, interval: str, session: str, artifacts: list | None = None) -> list:
    """Yahoo intraday artifacts.

    1. Synthetic close bar: for US equities Yahoo appends a bar starting at the session close (16:00 ET, or the early
       close) with volume 0 and open == high == low == close. It is not a traded bar, so it is dropped.
    2. :30-offset bars: on hour-aligned sessions (24x7 crypto, FX, futures) Yahoo can return 60m bars starting at :30.
       They are normalised by moving the start FORWARD to the next grid boundary. This never moves a bar earlier, so it
       cannot create lookahead. Each one is recorded in ``artifacts``. Bars that are still off-grid (for example on RTH,
       whose grid anchors at 09:30 ET) are kept unchanged, and quality.assess flags them ``off_grid_bar`` so predict()
       abstains.
    """
    from dataclasses import replace
    from ..core import INTERVALS
    from ..quality import on_grid
    log = artifacts if artifacts is not None else []
    step = INTERVALS[interval]
    if step >= 86400:
        return bars
    out, seen = [], set()
    for b in bars:
        flat = b.open == b.high == b.low == b.close and not b.volume
        if flat and session == "us_equity_rth" and _is_rth_close(b.event_time):
            log.append({"artifact": "synthetic_close_bar", "event_time": b.event_time, "action": "dropped"})
            continue
        if interval == "1h" and session != "us_equity_rth" and b.event_time % step == step // 2:
            t = b.event_time + step // 2
            log.append({"artifact": "half_hour_offset", "event_time": b.event_time, "action": f"normalized_to_{t}"})
            b = replace(b, event_time=t, confirmed=b.confirmed and t + step <= b.receipt_time)
        elif not on_grid(b.event_time, session, interval):
            log.append({"artifact": "off_grid", "event_time": b.event_time, "action": "flagged"})
        if b.event_time in seen:
            log.append({"artifact": "duplicate_after_normalize", "event_time": b.event_time, "action": "dropped"})
            continue
        seen.add(b.event_time)
        out.append(b)
    return out


def _is_rth_close(t: int) -> bool:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    try:
        from atlas.marketdata.pit.calendars import session_close
        d = datetime.fromtimestamp(t, ZoneInfo("America/New_York")).date()
        return int(session_close("XNYS", d).timestamp()) == t
    except Exception:  # calendar unavailable or not a session day
        ny = datetime.fromtimestamp(t, ZoneInfo("America/New_York"))
        return (ny.hour, ny.minute) == (16, 0)
