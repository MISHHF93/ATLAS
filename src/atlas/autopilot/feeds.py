"""Data feeds for the autopilot, each with a staleness budget. Network feeds are listed but DISABLED (no keys, network
off); the demo uses a deterministic REPLAY feed (synthetic daily bars plus an intraday random-walk tick) that is
labelled as such everywhere. Third-party text (news) is untrusted data: it can only feed veto/downsize screens."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from atlas.autopilot.config import AutopilotCfg, UniverseItem

HEALTH = "feeds.health"
CACHE_FILES = {"news.cache": "news.json", "fundamentals.cache": "fundamentals.json"}


@dataclass
class Feed:
    name: str
    kind: str                     # bars | quotes | news | fundamentals | macro
    source: str
    enabled: bool
    network: bool = False
    env: list[str] = field(default_factory=list)   # env var NAMES only (never values)
    mcp: str | None = None        # third-party MCP server that could supply it (see mcp_server/external.py)
    note: str = ""


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


class ReplayBars:
    """Deterministic synthetic daily bars up to yesterday + a live intraday price for today (5-minute random walk)."""

    def __init__(self, days: int = 400):
        self.days = days
        self._cache: dict[tuple, pd.DataFrame] = {}

    def history(self, u: UniverseItem, today) -> pd.DataFrame:
        key = (u.symbol, str(today))
        if key not in self._cache:
            freq = "D" if u.venue == "crypto" else "B"
            idx = pd.date_range(end=pd.Timestamp(today) - pd.Timedelta(days=1), periods=self.days, freq=freq)
            rng = random.Random(_seed("replay", u.symbol))
            dt = 1 / (365 if u.venue == "crypto" else 252)
            px, rows = u.s0 * 0.8, []
            for _ in idx:
                o = px
                c = o * math.exp((0.06 - 0.5 * u.vol ** 2) * dt + u.vol * math.sqrt(dt) * rng.gauss(0, 1))
                rows.append((o, max(o, c) * 1.002, min(o, c) * 0.998, c, 1e6))
                px = c
            df = pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])
            df[["open", "high", "low", "close"]] *= u.s0 / df["close"].iloc[-1]   # end near the configured price
            self._cache = {k: v for k, v in self._cache.items() if k[1] == str(today)}
            self._cache[key] = df
        return self._cache[key]

    def live_price(self, u: UniverseItem, now: datetime, last_close: float) -> float:
        day = now.astimezone(timezone.utc).date()
        steps = (now.astimezone(timezone.utc).hour * 60 + now.astimezone(timezone.utc).minute) // 5
        rng = random.Random(_seed("tick", u.symbol, day))
        sd = u.vol * math.sqrt(5 / (365 * 24 * 60))
        z = sum(rng.gauss(0, 1) for _ in range(steps + 1))
        return last_close * math.exp(sd * z)

    def frame(self, u: UniverseItem, now: datetime) -> pd.DataFrame:
        today = now.astimezone(timezone.utc).date()
        h = self.history(u, today)
        p = self.live_price(u, now, float(h["close"].iloc[-1]))
        o = float(h["close"].iloc[-1])
        live = pd.DataFrame([(o, max(o, p), min(o, p), p, 5e5)], index=[pd.Timestamp(today)], columns=h.columns)
        return pd.concat([h, live])


class FeedRegistry:
    def __init__(self, cfg: AutopilotCfg, store, var_dir: str | Path = "var", parquet_dir: str | None = None, clock=time.time):
        self.cfg, self.store, self.var, self.clock = cfg, store, Path(var_dir), clock
        self.parquet_dir = Path(parquet_dir or os.environ.get("ATLAS_ML_PARQUET_DIR", "") or "/nonexistent")
        self.replay = ReplayBars()
        use_parquet = self.parquet_dir.is_dir()
        fdir = self.var / "feeds"
        self.feeds = [
            Feed("bars.parquet", "bars", f"local Parquet ({self.parquet_dir})", use_parquet, note="point-in-time daily bars"),
            Feed("bars.replay", "bars", "REPLAY: deterministic synthetic bars + intraday tick (demo/simulation)", not use_parquet,
                 note="not market data; used when no local Parquet bars exist"),
            Feed("quotes.paper_book", "quotes", "paper broker marks (last price per position)", True),
            Feed("news.cache", "news", f"local cache {fdir / 'news.json'}", (fdir / "news.json").exists(), note="untrusted text: veto/downsize only"),
            Feed("fundamentals.cache", "fundamentals", f"local cache {fdir / 'fundamentals.json'}", (fdir / "fundamentals.json").exists()),
            Feed("bars.massive", "bars", "Massive (ex-Polygon) REST / MCP", False, True, ["MASSIVE_API_KEY"], "massive"),
            Feed("bars.eodhd", "bars", "EODHD (TSX/TSXV end-of-day) MCP", False, True, ["EODHD_API_KEY"], "eodhd"),
            Feed("crypto.kraken", "quotes", "Kraken CLI MCP `-s market` (public)", False, True, [], "kraken"),
            Feed("news.finnhub", "news", "Finnhub news & sentiment MCP", False, True, ["FINNHUB_API_KEY"], "finnhub"),
            Feed("fundamentals.fmp", "fundamentals", "Financial Modeling Prep MCP", False, True, ["FMP_API_KEY"], "fmp"),
            Feed("macro.boc_valet", "macro", "Bank of Canada Valet (our adapter)", False, True, []),
            Feed("macro.fred", "macro", "FRED (our adapter; FinanceAPIs MCP optional)", False, True, ["FRED_API_KEY"]),
            Feed("news.gdelt", "news", "GDELT DOC API (our adapter)", False, True, []),
            Feed("screener.tradingview", "screener", "TradingView screener MCP", False, True, [], "tradingview"),
        ]

    # ---------------------------------------------------------------- health
    def mark(self, name: str, n: int = 1, error: str | None = None) -> None:
        now = self.clock()
        def upd(h):
            h = h or {}
            h[name] = {"last_update": now if not error else (h.get(name) or {}).get("last_update"), "n": n, "error": error}
            return h
        self.store.update(HEALTH, upd, {})

    def health(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or self.clock()
        hs = self.store.get(HEALTH) or {}
        out = []
        for f in self.feeds:
            h = hs.get(f.name) or {}
            if f.name in CACHE_FILES and f.enabled and not h.get("last_update"):
                fp = self.var / "feeds" / CACHE_FILES[f.name]
                h = {"last_update": fp.stat().st_mtime, "n": None} if fp.exists() else h
            age = (now - h["last_update"]) if h.get("last_update") else None
            max_age = self.cfg.feed_max_age_s.get(f.kind, 86400)
            status = ("disabled" if not f.enabled else "error" if h.get("error") else "idle" if age is None
                      else "stale" if age > max_age else "ok")
            out.append(asdict(f) | {"status": status, "age_s": age, "max_age_s": max_age, "last_update": h.get("last_update"),
                                    "items": h.get("n"), "error": h.get("error")})
        return out

    def stale_bars(self, now: float | None = None) -> list[str]:
        return [f["name"] for f in self.health(now) if f["kind"] == "bars" and f["enabled"] and f["status"] in ("stale", "error")]

    # ---------------------------------------------------------------- data
    def frames(self, now: datetime, items: list[UniverseItem]) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        try:
            if self.parquet_dir.is_dir():
                for u in items:
                    p = self.parquet_dir / f"{u.symbol}.parquet"
                    if p.exists():
                        out[u.symbol] = pd.read_parquet(p)
                self.mark("bars.parquet", len(out))
            else:
                for u in items:
                    out[u.symbol] = self.replay.frame(u, now)
                self.mark("bars.replay", len(out))
        except Exception as e:  # noqa: BLE001  a broken feed pauses the autopilot (fail closed)
            self.mark("bars.parquet" if self.parquet_dir.is_dir() else "bars.replay", 0, repr(e)[:200])
            return {}
        return out

    def _json(self, name: str) -> Any:
        p = self.var / "feeds" / name
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (OSError, ValueError):
            return None

    def news(self, symbol: str | None = None, limit: int = 20) -> list[dict]:
        rows = self._json("news.json") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or []
        rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        if symbol:
            rows = [r for r in rows if r.get("symbol") in (symbol, None, "*")]
        return rows[-limit:][::-1]

    def fundamentals(self, symbol: str) -> dict | None:
        return (self._json("fundamentals.json") or {}).get(symbol)
