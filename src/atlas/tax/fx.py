"""Bank of Canada daily exchange rates (Valet API format), OFFLINE.

Loads Valet JSON (e.g. a downloaded /valet/observations/FXUSDCAD,FXEURCAD/json file
or a test fixture). No network calls. For non-business days, the most recent prior
business-day rate is used (max 7 days back); otherwise fail closed. The source string
is stored on every converted fill."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


class FxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class FxQuote:
    rate: Decimal          # CAD per 1 unit of currency
    source: str
    rate_date: date


class BocFxProvider:
    MAX_LOOKBACK_DAYS = 7

    def __init__(self, observations: dict[str, dict[date, Decimal]]):
        self.obs = observations

    @classmethod
    def from_valet_json(cls, payload: str | dict | Path) -> "BocFxProvider":
        if isinstance(payload, Path):
            payload = payload.read_text()
        data = json.loads(payload) if isinstance(payload, str) else payload
        obs: dict[str, dict[date, Decimal]] = {}
        for row in data.get("observations", []):
            d = date.fromisoformat(row["d"])
            for k, v in row.items():
                if k.startswith("FX") and k.endswith("CAD") and isinstance(v, dict) and v.get("v"):
                    obs.setdefault(k[2:-3], {})[d] = Decimal(str(v["v"]))
        return cls(obs)

    def quote(self, ccy: str, on: date) -> FxQuote:
        if ccy == "CAD":
            return FxQuote(Decimal(1), "identity (CAD)", on)
        series = self.obs.get(ccy)
        if not series:
            raise FxUnavailable(f"no Bank of Canada series for {ccy}")
        for back in range(self.MAX_LOOKBACK_DAYS + 1):
            d = on - timedelta(days=back)
            if d in series:
                return FxQuote(series[d], f"Bank of Canada Valet FX{ccy}CAD {d.isoformat()}", d)
        raise FxUnavailable(f"no Bank of Canada FX{ccy}CAD rate within {self.MAX_LOOKBACK_DAYS} days before {on}")
