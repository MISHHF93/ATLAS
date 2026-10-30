"""Reference-series catalog (evo-19): rates and energy benchmarks from official, free, Canada-reachable sources.

These are SERIES (yields in percent, spot prices), not tradable instruments: they never enter bar stores, trade series or
the execution path (``execution_permission`` stays none). They are for display, risk context and research features.
Metadata only: no vendor is called here. FRED is deliberately NOT part of this catalog (its terms bar ML use)."""
from __future__ import annotations

from typing import Any, Mapping

from .free_sources import allowed, describe
from .providers.rates import BOC_YIELDS, EIA_SERIES, UST_TAGS

_UST_LABEL = {"1M": "1-month", "3M": "3-month", "6M": "6-month", "1Y": "1-year", "2Y": "2-year", "5Y": "5-year", "10Y": "10-year", "20Y": "20-year", "30Y": "30-year"}
_CAN_LABEL = {"2Y": "2-year", "3Y": "3-year", "5Y": "5-year", "7Y": "7-year", "10Y": "10-year", "LONG": "long-term"}
_EIA_LABEL = {"EIA_WTI_SPOT": "WTI Cushing spot", "EIA_BRENT_SPOT": "Brent Europe spot", "EIA_HENRYHUB_SPOT": "Henry Hub natural gas spot"}


def reference_series() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sid in UST_TAGS:
        out[sid] = {"id": sid, "label": f"US Treasury par yield, {_UST_LABEL[sid[4:]]}", "provider": "us_treasury", "unit": "percent", "kind": "rate",
                    "currency": "USD", "provider_series": UST_TAGS[sid], "frequency": "daily"}
    for sid, vs in BOC_YIELDS.items():
        out[sid] = {"id": sid, "label": f"Government of Canada benchmark bond yield, {_CAN_LABEL[sid[4:]]}", "provider": "boc_rates", "unit": "percent",
                    "kind": "rate", "currency": "CAD", "provider_series": vs, "frequency": "daily"}
    for sid, (route, code) in EIA_SERIES.items():
        out[sid] = {"id": sid, "label": _EIA_LABEL[sid] + " (daily benchmark, not a futures price)", "provider": "eia",
                    "unit": "USD per barrel" if "HENRY" not in sid else "USD per MMBtu", "kind": "energy_spot", "currency": "USD",
                    "provider_series": f"{route}:{code}", "frequency": "daily"}
    for r in out.values():
        r.update(trade_series=False, ml_training="research_features_only", execution_permission="none")
    return out


def catalog_status(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Each series with its source terms and whether it can be fetched right now (key present, free-only gate)."""
    from .providers import ALL_ADAPTERS
    caps = {c.caps.name: c.caps for c in ALL_ADAPTERS}
    rows = []
    for r in reference_series().values():
        c = caps[r["provider"]]
        missing = [k for k in c.auth_env if not (env or {}).get(k)] if env is not None else None
        d = describe(r["provider"])
        rows.append({**r, "needs_key": list(c.auth_env), "key_missing": missing, "terms_url": c.terms_url, "allowed": allowed(r["provider"], env),
                     "cost": d.get("cost"), "status": "needs_verification" if c.auth_env else c.status})
    return rows
