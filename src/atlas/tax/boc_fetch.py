"""Bank of Canada Valet FX fetcher. DISABLED BY DEFAULT (offline build).

When enabled (tax.yaml boc_fetch.enabled: true) it GETs the public, unauthenticated
Valet endpoint and writes the JSON to a cache file that BocFxProvider reads. No
secrets. Tests inject `http_get`; the suite never touches the network."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable

from atlas.tax.fx import BocFxProvider

VALET = "https://www.bankofcanada.ca/valet/observations/{series}/json?start_date={start}&end_date={end}"


class FetchDisabled(RuntimeError):
    pass


def _urllib_get(url: str) -> str:  # pragma: no cover - network path, only when explicitly enabled
    from urllib.request import urlopen
    if not url.startswith("https://www.bankofcanada.ca/valet/"):
        raise ValueError("BoC fetcher only talks to the Valet API")
    with urlopen(url, timeout=15) as r:  # noqa: S310
        return r.read().decode()


class BocFetcher:
    def __init__(self, enabled: bool = False, series: list[str] | None = None,
                 http_get: Callable[[str], str] | None = None):
        self.enabled = enabled
        self.series = series or ["FXUSDCAD"]
        self.http_get = http_get or _urllib_get

    def url(self, start: date, end: date) -> str:
        if not all(s.startswith("FX") and s.endswith("CAD") and s.isalnum() for s in self.series):
            raise ValueError("series must look like FXxxxCAD")
        return VALET.format(series=",".join(self.series), start=start.isoformat(), end=end.isoformat())

    def fetch(self, start: date, end: date, cache_file: str | Path | None = None) -> BocFxProvider:
        if not self.enabled:
            raise FetchDisabled("BoC fetch disabled (tax.yaml boc_fetch.enabled=false); load a downloaded Valet file instead")
        if end < start:
            raise ValueError("end before start")
        payload = json.loads(self.http_get(self.url(start, end)))
        if "observations" not in payload:
            raise ValueError("unexpected Valet response (no observations)")
        prov = BocFxProvider.from_valet_json(payload)
        if cache_file:
            p = Path(cache_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, indent=1))
        return prov
