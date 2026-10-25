"""THE ATLAS feed: the single authoritative normalized bars/trades/quotes stream + PIT store.

Every consumer (charts/UDF, detectors, predict, training, evidence, replay, autopilot) reads through ``AtlasFeed``;
none calls a provider directly. Behind it sits the provider-adapter library with per-instrument priority + failover.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .aggregate import aggregate
from .core import INTERVALS, FeedBar, ProviderAdapter, ProviderError
from .instruments import Instrument, InstrumentMaster
from .providers import ALL_ADAPTERS
from .free_sources import allowed as free_allowed
from .quality import Quality, assess, find_gaps
from .store import FeedStore

DEFAULT_STORE = os.environ.get("ATLAS_FEED_DB", "var/feeds/atlas_feed.sqlite")


class ProviderRegistry:
    """Registry data model: every plugin, its manifest and live health."""

    def __init__(self, adapters: Sequence[ProviderAdapter] | None = None, env: Mapping[str, str] | None = None, **kw):
        self._a = {a.name: a for a in (adapters if adapters is not None else [cls(env=env, **kw) for cls in ALL_ADAPTERS])}

    def get(self, name) -> ProviderAdapter | None:
        return self._a.get(name)

    def names(self):
        return list(self._a)

    def snapshot(self) -> list[dict]:
        out = []
        for a in self._a.values():
            h = asdict(a.health())
            out.append({"name": a.name, "title": a.caps.title, "status": a.caps.status, "enabled": a.enabled,
                        "unofficial": a.caps.unofficial, "manifest": a.caps.as_dict(), "health": h})
        return out


class AtlasFeed:
    def __init__(self, store: FeedStore | None = None, registry: ProviderRegistry | None = None,
                 instruments: InstrumentMaster | None = None, clock: Callable[[], float] = time.time):
        self.store = store or FeedStore(DEFAULT_STORE)
        self.registry = registry or ProviderRegistry()
        self.instruments = instruments or InstrumentMaster()
        self.clock = clock
        self.events: list[dict] = []

    # ---- provider selection ----
    def candidates(self, instrument: str, interval: str) -> list[ProviderAdapter]:
        inst = self.instruments.get(instrument)
        out = []
        for name in inst.provider_priority:
            a = self.registry.get(name)
            if a and a.enabled and free_allowed(name) and interval in a.caps.intervals and a.health().consecutive_errors < 5:
                out.append(a)
        return out

    def _with_symbol(self, a: ProviderAdapter, inst: Instrument):
        a.symbol_map = {**dict(a.symbol_map), inst.id: inst.provider_symbols.get(a.name, inst.id)}
        return a

    def fetch(self, instrument: str, interval: str, start: int, end: int, providers: Sequence[str] | None = None) -> tuple[str | None, dict]:
        """Fetch from the first healthy provider in priority order, failing over on error/empty. Ingest into store."""
        inst = self.instruments.get(instrument)
        cands = [self.registry.get(p) for p in providers if free_allowed(p)] if providers else self.candidates(instrument, interval)
        errors = {}
        for a in cands:
            if a is None or not a.enabled:
                continue
            try:
                bars = self._with_symbol(a, inst).history(instrument, interval, start, end)
            except ProviderError as e:
                errors[a.name] = str(e)[:200]
                self.events.append({"t": int(self.clock()), "event": "failover", "provider": a.name, "instrument": instrument, "error": str(e)[:200]})
                continue
            if not bars:
                errors[a.name] = "empty"
                continue
            res = self.store.ingest(bars, note=f"fetch {start}-{end}")
            return a.name, {**res, "errors": errors}
        return None, {"errors": errors}

    def backfill(self, instrument: str, interval: str, start: int, end: int | None = None, fill_gaps: bool = True) -> dict:
        end = int(end or self.clock())
        prov, res = self.fetch(instrument, interval, start, end)
        out = {"instrument": instrument, "interval": interval, "provider": prov, **res, "gap_fills": []}
        if fill_gaps and prov:
            out["gap_fills"] = self.fill_gaps(instrument, interval, start, end)
            step = INTERVALS[interval]
            bars = self.bars(instrument, interval, start, end)
            others = [c.name for c in self.candidates(instrument, interval) if c.name != prov]
            if bars and others:
                if bars[0].event_time - start >= step:
                    p2, r2 = self.fetch(instrument, interval, start, bars[0].event_time, providers=others)
                    if p2:
                        out["gap_fills"].append({"gap": [start, bars[0].event_time], "provider": p2, "inserted": r2.get("inserted", 0)})
                if end - bars[-1].bar_end >= 2 * step:
                    p2, r2 = self.fetch(instrument, interval, bars[-1].bar_end, end, providers=others)
                    if p2:
                        out["gap_fills"].append({"gap": [bars[-1].bar_end, end], "provider": p2, "inserted": r2.get("inserted", 0)})
        return out

    def fill_gaps(self, instrument: str, interval: str, start: int, end: int, max_gaps: int = 20) -> list[dict]:
        """Automatic backfill: detect calendar gaps in the authoritative series and refetch each from the provider chain."""
        inst = self.instruments.get(instrument)
        bars = self.bars(instrument, interval, start, end)
        if not bars:
            return []
        gaps = find_gaps(bars, inst.session, interval, max(start, bars[0].event_time), bars[-1].bar_end)
        done = []
        for g0, g1 in gaps[:max_gaps]:
            prov, res = self.fetch(instrument, interval, g0, g1)
            done.append({"gap": [g0, g1], "provider": prov, "inserted": res.get("inserted", 0)})
        return done

    # ---- reads (the authoritative series) ----
    def priority(self, instrument: str) -> list[str]:
        inst = self.instruments.get(instrument)
        return list(inst.provider_priority) + [p for p in inst.sanity_providers if p not in inst.provider_priority]

    def bars(self, instrument: str, interval: str, start: int | None = None, end: int | None = None,
             as_of: int | None = None, confirmed_only: bool = True, provider: str | None = None) -> list[FeedBar]:
        """Authoritative series: per bar, the highest-priority provider's latest confirmed version known at ``as_of``.
        Sanity-only providers (e.g. Coinbase USD for a USDT pair) are never merged into the series."""
        if provider:
            return self.store.bars(instrument, interval, start, end, provider=provider, as_of=as_of, confirmed_only=confirmed_only)
        prio = list(self.instruments.get(instrument).provider_priority)
        merged: dict[int, FeedBar] = {}
        for p in reversed(prio):
            for b in self.store.bars(instrument, interval, start, end, provider=p, as_of=as_of, confirmed_only=confirmed_only):
                merged[b.event_time] = b
        return [merged[k] for k in sorted(merged)]

    def quality(self, instrument: str, interval: str, now: int | None = None, lookback_bars: int = 200,
                max_age_seconds: int | None = None, cross_check: bool = True) -> Quality:
        now = int(now or self.clock())
        inst = self.instruments.get(instrument)
        step = INTERVALS[interval]
        bars = self.bars(instrument, interval, now - lookback_bars * step, now + 1, as_of=now)
        cross = None
        if cross_check and bars:
            primary = bars[-1].provider
            for p in inst.sanity_providers:
                if p != primary:
                    c = self.store.bars(instrument, interval, now - lookback_bars * step, now + 1, provider=p, as_of=now)
                    if c:
                        cross = c
                        break
        return assess(bars, inst.session, interval, now, lookback_bars, max_age_seconds, cross)

    def quality_flags(self, instrument: str, interval: str, now: int | None = None, **kw) -> tuple[str, ...]:
        """What predict() consumes: non-empty -> abstain (see atlas.models.predict.DATA_QUALITY)."""
        return self.quality(instrument, interval, now, **kw).flags

    def cross_check(self, instrument: str, interval: str, start: int, end: int, tolerance_bps: float = 50.0) -> dict:
        """Fetch from sanity providers and compare closes with the authoritative series."""
        inst = self.instruments.get(instrument)
        ser = self.bars(instrument, interval, start, end)
        main = {b.event_time: b.close for b in ser}
        primary = {b.provider for b in ser}
        out = {}
        for p in inst.sanity_providers:
            if p in primary:
                out[p] = {"skipped": "is the primary provider for this series"}
                continue
            a = self.registry.get(p)
            if not a or not a.enabled or interval not in a.caps.intervals:
                continue
            try:
                bars = self._with_symbol(a, inst).history(instrument, interval, start, end)
            except ProviderError as e:
                out[p] = {"error": str(e)[:160]}
                continue
            self.store.ingest(bars, note="sanity")
            d = sorted(abs(b.close / main[b.event_time] - 1) * 1e4 for b in bars if b.event_time in main)
            out[p] = {"overlap": len(d), "median_bps": round(d[len(d) // 2], 2) if d else None,
                      "max_bps": round(d[-1], 2) if d else None, "ok": bool(d) and d[len(d) // 2] <= tolerance_bps}
        return out

    # ---- live ----
    async def run_stream(self, provider: str, instruments: Sequence[str], interval: str, on_item=None, aggregate_to: Sequence[str] = ()):  # pragma: no cover - network
        """Ingest a provider's live stream into the store. 1m streams are aggregated to ``aggregate_to`` timeframes."""
        a = self.registry.get(provider)
        for i in instruments:
            self._with_symbol(a, self.instruments.get(i))
        async for item in a.stream(list(instruments), interval):
            if isinstance(item, FeedBar):
                self.store.ingest([item], note="stream")
                if item.confirmed:
                    for tf in aggregate_to:
                        step = INTERVALS[tf]
                        t0 = item.event_time // step * step
                        mins = self.store.bars(item.instrument, item.interval, t0, t0 + step, provider=provider)
                        self.store.ingest(aggregate(mins, tf, int(self.clock())), note="aggregate")
            if on_item:
                on_item(item)

    # ---- health endpoint payload ----
    def health(self, intervals: Sequence[str] = ("15m", "1h")) -> dict:
        now = int(self.clock())
        series = []
        for s in self.store.summary():
            series.append({**s, "age_seconds": now - (s["last"] + INTERVALS[s["interval"]]) if s["last"] else None})
        q = []
        for inst in self.instruments.all():
            for iv in intervals:
                if any(s["instrument"] == inst.id and s["interval"] == iv for s in series):
                    qq = self.quality(inst.id, iv, now)
                    q.append({"instrument": inst.id, "interval": iv, "flags": list(qq.flags), "age_seconds": qq.age_seconds,
                              "gaps": len(qq.gaps), "disagreement_bps": qq.disagreement_bps})
        return {"as_of": now, "providers": self.registry.snapshot(), "series": series, "quality": q, "events": self.events[-50:]}


_DEFAULT: AtlasFeed | None = None


def get_feed(store_path: str | Path | None = None) -> AtlasFeed:
    """Process-wide default feed (what UDF/charts and scripts should use)."""
    global _DEFAULT
    if _DEFAULT is None or store_path:
        _DEFAULT = AtlasFeed(FeedStore(store_path or DEFAULT_STORE))
    return _DEFAULT
