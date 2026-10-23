"""Canadian legally usable alternative-data adapters (research item 19). ALL DISABLED BY DEFAULT.

Each adapter is off unless BOTH ``enabled=True`` is passed AND env ``ATLAS_ALTDATA_<NAME>=1``
is set; and it can only use the network through an explicitly injected Transport (default is
OfflineTransport, which raises). Bulk sources without an open API (SEDAR+, SEDI, CIRO) read files
the owner downloaded manually under the site's terms: no scraping, no login automation.

Compliance guards (PIPEDA / OSC):
* SEDI: insider NAMES are dropped; only role/relationship category and transaction facts are kept.
* Every record carries ``available_at`` (publication/filing time) for point-in-time use; values are
  never back-dated to the event or period date.
* Public, already-disclosed data only. Material non-public information is out of scope.
Outputs are research features / veto inputs, never order instructions.
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas.marketdata.pit.providers.base import OfflineTransport, ProviderDisabled, Transport

UTC = timezone.utc


@dataclass(frozen=True)
class AltRecord:
    source: str
    entity: str                 # ticker / series id / query
    event_ts: datetime          # when the thing happened (trade date, reference period, article time)
    available_at: datetime      # when WE could have known it (filing / publication)
    values: dict = field(default_factory=dict)


class AltAdapter:
    NAME = "base"
    TERMS_URL = ""

    def __init__(self, enabled: bool = False, transport: Transport | None = None):
        self.transport = transport or OfflineTransport()
        env = os.environ.get(f"ATLAS_ALTDATA_{self.NAME.upper()}", "") == "1"
        self.enabled = bool(enabled and env)

    def _check(self):
        if not self.enabled:
            raise ProviderDisabled(f"{self.NAME}: disabled (needs enabled=True and ATLAS_ALTDATA_{self.NAME.upper()}=1)")


def _ts(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) == 15 and s[8] == "T":             # GDELT 20261015T143000Z style
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# ------------------------------------------------------------------ open JSON APIs
class BankOfCanadaValet(AltAdapter):
    """BoC Valet API (open data; FX, policy rate, CORRA, bond yields). Published ~16:30 ET same day."""
    NAME = "boc"
    BASE = "https://www.bankofcanada.ca/valet/observations/"
    TERMS_URL = "https://www.bankofcanada.ca/terms/"
    PUBLISH_LAG = timedelta(hours=21, minutes=30)   # day stamp 00:00 UTC -> ~16:30 ET (20:30/21:30 UTC)

    def observations(self, series: list[str], start: str, end: str) -> list[AltRecord]:
        self._check()
        js = self.transport.get_json(self.BASE + ",".join(series) + "/json", {"start_date": start, "end_date": end})
        return self.parse(js, series)

    @classmethod
    def parse(cls, js: dict, series: list[str]) -> list[AltRecord]:
        out = []
        for ob in js.get("observations", []):
            t = _ts(ob["d"])
            for s in series:
                if s in ob and ob[s].get("v") not in (None, ""):
                    out.append(AltRecord("boc", s, t, t + cls.PUBLISH_LAG, {"value": float(ob[s]["v"])}))
        return out


class StatCanWDS(AltAdapter):
    """Statistics Canada Web Data Service (Open Government Licence - Canada). Uses releaseTime."""
    NAME = "statcan"
    BASE = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
    TERMS_URL = "https://www.statcan.gc.ca/en/reference/licence"

    def vectors(self, vector_ids: list[int], latest_n: int = 12) -> list[AltRecord]:
        self._check()
        js = self.transport.get_json(self.BASE, {"body": [{"vectorId": v, "latestN": latest_n} for v in vector_ids]})
        return self.parse(js)

    @staticmethod
    def parse(js: list) -> list[AltRecord]:
        out = []
        for item in js:
            if item.get("status") != "SUCCESS":
                continue
            obj = item["object"]
            for dp in obj.get("vectorDataPoint", []):
                out.append(AltRecord("statcan", f"v{obj['vectorId']}", _ts(dp["refPer"]), _ts(dp["releaseTime"]),
                                     {"value": float(dp["value"]), "scalar": dp.get("scalarFactorCode")}))
        return out


class GDELTDoc(AltAdapter):
    """GDELT DOC 2.0 article list (open). Only metadata (title, domain, tone); no full-text scraping."""
    NAME = "gdelt"
    BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
    TERMS_URL = "https://www.gdeltproject.org/about.html#termsofuse"
    INGEST_LAG = timedelta(minutes=15)

    def articles(self, query: str, timespan: str = "1d", max_records: int = 75) -> list[AltRecord]:
        self._check()
        js = self.transport.get_json(self.BASE, {"query": query, "mode": "artlist", "format": "json",
                                                 "timespan": timespan, "maxrecords": max_records})
        return self.parse(js, query)

    @classmethod
    def parse(cls, js: dict, query: str) -> list[AltRecord]:
        out = []
        for a in js.get("articles", []):
            t = _ts(a["seendate"])
            out.append(AltRecord("gdelt", query, t, t + cls.INGEST_LAG,
                                 {"title": a.get("title", ""), "domain": a.get("domain", ""), "language": a.get("language", ""),
                                  "tone": float(a["tone"]) if a.get("tone") not in (None, "") else None}))
        return out


# ------------------------------------------------------------------ manual-download file sources
class _FileAdapter(AltAdapter):
    def read(self, path: str | Path) -> list[AltRecord]:
        self._check()
        return self.parse(Path(path).read_text(encoding="utf-8"))


class SEDARPlusFilings(_FileAdapter):
    """SEDAR+ filing index exported manually (CSV: issuer, ticker, filing_type, filed_at, document_date).
    No public API: we never scrape SEDAR+."""
    NAME = "sedarplus"
    TERMS_URL = "https://www.sedarplus.ca/"
    MATERIAL = {"material change report", "news release", "annual information form", "md&a", "financial statements",
                "business acquisition report", "early warning report", "cease trade order"}

    @classmethod
    def parse(cls, text: str) -> list[AltRecord]:
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            ft = r["filing_type"].strip().lower()
            out.append(AltRecord("sedarplus", r["ticker"].strip().upper(), _ts(r.get("document_date") or r["filed_at"]),
                                 _ts(r["filed_at"]), {"filing_type": ft, "material": ft in cls.MATERIAL}))
        return out


class SEDIInsiderTrades(_FileAdapter):
    """SEDI insider transaction export (CSV). Insider names are DROPPED (PIPEDA data minimisation)."""
    NAME = "sedi"
    TERMS_URL = "https://www.sedi.ca/"

    @classmethod
    def parse(cls, text: str) -> list[AltRecord]:
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            qty = float(r["quantity"])
            out.append(AltRecord("sedi", r["ticker"].strip().upper(), _ts(r["transaction_date"]), _ts(r["filing_date"]),
                                 {"relationship": r["relationship"].strip(), "nature_code": r["nature_code"].strip(),
                                  "qty": qty, "price": float(r["price"] or 0), "direction": "buy" if qty > 0 else "sell",
                                  "filing_delay_days": (_ts(r["filing_date"]) - _ts(r["transaction_date"])).days}))
        return out

    @staticmethod
    def net_insider_flow(records: list[AltRecord], ticker: str, as_of: datetime, days: int = 90) -> float:
        lo = as_of - timedelta(days=days)
        return sum(r.values["qty"] * r.values["price"] for r in records
                   if r.entity == ticker and lo <= r.available_at <= as_of)


class CIROShortSales(_FileAdapter):
    """CIRO (formerly IIROC) short-sale trading statistics (CSV: date, ticker, short_volume,
    total_volume, published_at)."""
    NAME = "ciro"
    TERMS_URL = "https://www.ciro.ca/"

    @staticmethod
    def parse(text: str) -> list[AltRecord]:
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            sv, tv = float(r["short_volume"]), float(r["total_volume"])
            out.append(AltRecord("ciro", r["ticker"].strip().upper(), _ts(r["date"]), _ts(r["published_at"]),
                                 {"short_volume": sv, "total_volume": tv, "short_ratio": sv / tv if tv else None}))
        return out


ADAPTERS = {c.NAME: c for c in (BankOfCanadaValet, StatCanWDS, GDELTDoc, SEDARPlusFilings, SEDIInsiderTrades, CIROShortSales)}


def as_of(records: list[AltRecord], when: datetime) -> list[AltRecord]:
    """Point-in-time filter: only records published by `when`."""
    return [r for r in records if r.available_at <= when]


def to_featurestore(fs, records: list[AltRecord], fset: str) -> int:
    for r in records:
        fs.put(r.entity, fset, r.event_ts, r.available_at, {k: v for k, v in r.values.items() if isinstance(v, (int, float, bool))})
    return len(records)
