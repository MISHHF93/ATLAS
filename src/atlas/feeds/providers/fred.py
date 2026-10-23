from __future__ import annotations

from ..core import Capabilities, FeedObservation, ProviderAdapter


class FREDAdapter(ProviderAdapter):
    caps = Capabilities(
        name="fred", title="FRED / ALFRED (St. Louis Fed)", status="interface_fixture_tested",
        asset_classes=("macro",), schemas=("series",), intervals=("1d",),
        history_depth="Full series history; vintages via realtime_start/realtime_end (ALFRED)",
        live_stream="none (polling; series release schedules)",
        rate_limits="120 requests/min per API key",
        auth_env=("FRED_API_KEY",),
        official_docs=("https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
                       "https://fred.stlouisfed.org/docs/api/api_key.html",
                       "https://fred.stlouisfed.org/docs/api/fred/realtime_period.html"),
        terms_url="https://fred.stlouisfed.org/docs/api/terms_of_use.html",
        notes="Free key required (the keyless request returns 400 'api_key is not set'). Use output_type=2/vintages for point-in-time.")

    def observations(self, series_id: str, start: str | None = None, realtime_start: str | None = None) -> list[FeedObservation]:
        js = self.get_json("https://api.stlouisfed.org/fred/series/observations",
                           {"series_id": series_id, "api_key": self.env.get("FRED_API_KEY"), "file_type": "json",
                            "observation_start": start, "realtime_start": realtime_start})
        now = int(self.clock())
        out = []
        for o in js.get("observations", []):
            v = None if o["value"] in (".", "") else float(o["value"])
            out.append(FeedObservation(series_id, o["date"], v, o["realtime_start"], self.name, now))
        return out

    def _history(self, *a, **k):
        return []
