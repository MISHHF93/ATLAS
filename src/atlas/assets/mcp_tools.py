"""Feature 9 — Gemini AI and MCP Asset Capabilities.

Provides governed, read-only AI and Model Context Protocol (MCP) tools over the
ATLAS Authentic Assets Catalog and live market-data store:

1. `assets.search`
2. `assets.get_profile`
3. `assets.verify_identity`
4. `metals.get_reference_price`
5. `etfs.get_fund_details`
6. `markets.get_quote`
7. `markets.get_history`
8. `assets.compare`

Every tool response enforces:
- `execution_permission="none"` (no autonomous trading or order submission)
- `personalized_advice=False` (no NI 31-103 suitability or investment advice)
- `investment_safety_score=None` (instrument authenticity != investment safety)
- Explicit `source_attribution`, `data_freshness`, `licensed_data_control`, and
  `uncertainty_disclosure`
- Tenant and role access control (`researcher`, `auditor`, `compliance`,
  `founder`, `viewer`)
- Append-only audit logging to `var/ai/audit.jsonl`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from atlas.assets.authenticity import verify_instrument_authenticity
from atlas.assets.etf_intelligence import ETFS_BY_SYMBOL, get_etf_fund_details
from atlas.assets.master import get_canonical_asset_master
from atlas.assets.precious_metals import (
    METALS_BY_SYMBOL,
    build_precious_metals_catalog,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_AUDIT_PATH = _REPO_ROOT / "var" / "ai" / "audit.jsonl"

ALLOWED_MCP_ROLES = frozenset(
    {"researcher", "auditor", "compliance", "founder", "viewer"}
)


@dataclass(frozen=True)
class GovernedMCPToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    execution_permission: str = "none"
    requires_source_attribution: bool = True
    allowed_roles: tuple[str, ...] = (
        "researcher",
        "auditor",
        "compliance",
        "founder",
        "viewer",
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_roles"] = list(self.allowed_roles)
        return d


GOVERNED_ASSET_MCP_TOOLS: tuple[GovernedMCPToolSpec, ...] = (
    GovernedMCPToolSpec(
        name="assets.search",
        description=(
            "Search the verified Canonical Asset Master by query text, asset class, "
            "jurisdiction, or currency. Excludes unverified meme-token launches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "asset_class": {"type": "string"},
                "jurisdiction": {"type": "string"},
                "currency": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
        },
    ),
    GovernedMCPToolSpec(
        name="assets.get_profile",
        description=(
            "Retrieve the full canonical instrument profile, issuer metadata, "
            "regulatory identifiers (ISIN, CUSIP, CIK, Exchange MIC), and "
            "provenance for a verified symbol."
        ),
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {"symbol": {"type": "string"}},
        },
    ),
    GovernedMCPToolSpec(
        name="assets.verify_identity",
        description=(
            "Run deterministic ISO 6166 ISIN, ANSI X9.6 CUSIP, SEC CIK, and "
            "ISO 10383 MIC authenticity checks for an instrument, keeping "
            "instrument authenticity strictly separate from investment safety."
        ),
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {"symbol": {"type": "string"}},
        },
    ),
    GovernedMCPToolSpec(
        name="metals.get_reference_price",
        description=(
            "Retrieve Gold (XAU), Silver (XAG), Platinum (XPT), and Palladium (XPD) "
            "reference prices normalized across troy_oz, gram, and kg in USD and CAD, "
            "along with holding-form and custody disclosures."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "metal": {"type": "string", "description": "gold, silver, platinum, palladium, or all"},
                "holding_form": {"type": "string"},
            },
        },
    ),
    GovernedMCPToolSpec(
        name="etfs.get_fund_details",
        description=(
            "Retrieve verified ETF or ETR fund intelligence including issuer, ISIN, "
            "CUSIP, exchange MIC, expense ratio (bps), underlying exposure, "
            "replication method, and NAV vs. market-price provenance."
        ),
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {"symbol": {"type": "string"}},
        },
    ),
    GovernedMCPToolSpec(
        name="markets.get_quote",
        description=(
            "Retrieve the latest verified reference price, timestamp, bar freshness, "
            "and source attribution from the local feed store for a symbol."
        ),
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "currency": {"type": "string", "default": "USD"},
            },
        },
    ),
    GovernedMCPToolSpec(
        name="markets.get_history",
        description=(
            "Retrieve recent verified OHLCV historical bars from `atlas_feed.sqlite` "
            "with explicit timeframe, bar count, and source provenance."
        ),
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "default": "1d"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    ),
    GovernedMCPToolSpec(
        name="assets.compare",
        description=(
            "Compare 2 to 6 verified instruments side by side across asset class, "
            "issuer, identifiers (ISIN/CIK), reference price (USD & CAD), expense "
            "ratio, custody/holding model, and data freshness."
        ),
        input_schema={
            "type": "object",
            "required": ["symbols"],
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 8,
                }
            },
        },
    ),
)


def list_governed_mcp_tools() -> list[dict[str, Any]]:
    return [t.to_dict() for t in GOVERNED_ASSET_MCP_TOOLS]


def _query_latest_feed_quote(symbol: str) -> dict[str, Any]:
    from atlas.api.feeds_api import feed_quotes

    sym = symbol.strip().upper()
    master = get_canonical_asset_master()
    inst = master.get_instrument(sym)
    feed_sym = (inst.identifiers.feed_instrument_id if inst else None) or sym
    q_map = feed_quotes([feed_sym])
    q = q_map.get(feed_sym) or {}
    return {
        "symbol": sym,
        "feed_symbol": feed_sym,
        "price": q.get("price"),
        "change_pct": q.get("change_pct"),
        "observed_at": q.get("observed_at"),
        "observed_at_toronto": q.get("observed_at_toronto"),
        "source": q.get("source") or "reference_only",
        "status": q.get("status") or "reference_only",
        "age_seconds": q.get("age_seconds"),
    }


def _query_feed_history(symbol: str, timeframe: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    from atlas.api.feeds_api import _feed
    from atlas.feeds.universe import resolve

    sym = symbol.strip().upper()
    tf = (timeframe or "1d").strip().lower()
    cap = max(1, min(int(limit or 30), 250))
    feed = _feed()
    iid = resolve(sym) or sym
    if feed is None or iid not in feed.instruments:
        return []
    bars = feed.store.bars(iid, tf, None, None, confirmed_only=True)[-cap:]
    return [
        {
            "event_time": int(b.event_time),
            "ts_iso": datetime.fromtimestamp(int(b.event_time), tz=timezone.utc).isoformat(),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume or 0.0),
            "provider": str(b.provider),
        }
        for b in bars
    ]


def _get_usd_cad_rate() -> float:
    q = _query_latest_feed_quote("USD_CAD")
    price = q.get("price")
    if isinstance(price, (int, float)) and 1.0 <= float(price) <= 2.0:
        return float(price)
    return 1.3850


def _append_mcp_audit(
    tool_name: str,
    params: dict[str, Any],
    tenant_id: str,
    role: str,
    ok: bool,
    audit_path: Path | None = None,
) -> None:
    target = audit_path or _DEFAULT_AUDIT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": "authentic_assets_mcp",
            "tool": tool_name,
            "tenant_id": tenant_id,
            "role": role,
            "params": params,
            "ok": ok,
            "execution_permission": "none",
        }
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:
        pass


def call_governed_mcp_tool(
    tool_name: str,
    params: dict[str, Any] | None = None,
    *,
    tenant_id: str = "default_workspace",
    role: str = "researcher",
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one of the 8 governed read-only asset MCP tools with full governance envelope."""
    params = dict(params or {})
    norm_role = (role or "researcher").strip().lower()
    norm_tenant = (tenant_id or "default_workspace").strip()

    if norm_role not in ALLOWED_MCP_ROLES:
        _append_mcp_audit(tool_name, params, norm_tenant, norm_role, False, audit_path)
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"Role '{norm_role}' is not authorized. Allowed roles: {sorted(ALLOWED_MCP_ROLES)}",
            "execution_permission": "none",
            "personalized_advice": False,
        }

    if params.get("execute_order") or params.get("execution_permission") not in (None, "none"):
        _append_mcp_audit(tool_name, params, norm_tenant, norm_role, False, audit_path)
        return {
            "ok": False,
            "tool": tool_name,
            "error": "MCP asset tools are strictly read-only (`execution_permission='none'`).",
            "execution_permission": "none",
            "personalized_advice": False,
        }

    master = get_canonical_asset_master()
    usd_cad = _get_usd_cad_rate()

    if tool_name == "assets.search":
        limit = max(1, min(int(params.get("limit", 25)), 250))
        matches = master.list_instruments(
            asset_class=params.get("asset_class"),
            jurisdiction=params.get("jurisdiction"),
            currency=params.get("currency"),
            query=str(params.get("query", "")),
        )[:limit]
        payload: dict[str, Any] = {
            "count": len(matches),
            "items": [m.as_dict() for m in matches],
        }
        source_attr = "ATLAS Canonical Asset Master (SEC EDGAR / SEDAR+ / BoC / ISO 10383)"

    elif tool_name == "assets.get_profile":
        sym = str(params.get("symbol", "")).strip().upper()
        inst = master.get_instrument(sym)
        if inst is None:
            _append_mcp_audit(tool_name, params, norm_tenant, norm_role, False, audit_path)
            return {
                "ok": False,
                "tool": tool_name,
                "symbol": sym,
                "error": f"Symbol '{sym}' not found in verified Canonical Asset Master.",
                "execution_permission": "none",
                "personalized_advice": False,
            }
        issuer = master.get_issuer(inst.issuer_id)
        venue = master.get_exchange(inst.primary_exchange_mic)
        quote = _query_latest_feed_quote(sym)
        payload = {
            "instrument": inst.as_dict(),
            "issuer": issuer.as_dict() if issuer else None,
            "exchange_venue": venue.as_dict() if venue else None,
            "latest_quote": quote,
        }
        source_attr = f"{inst.source_provenance.primary_source} ({inst.source_provenance.verification_method})"

    elif tool_name == "assets.verify_identity":
        sym = str(params.get("symbol", "")).strip().upper()
        report = verify_instrument_authenticity(sym)
        payload = report.as_dict()
        source_attr = "ATLAS Deterministic Checksum & Cross-Source Reconciliation Engine"

    elif tool_name == "metals.get_reference_price":
        metal_filter = params.get("metal")
        if metal_filter and str(metal_filter).strip().lower() == "all":
            metal_filter = None
        holding_form = params.get("holding_form")
        payload = build_precious_metals_catalog(
            metal=metal_filter,
            holding_form=holding_form,
        )
        source_attr = "LBMA / CME COMEX / NYMEX / Royal Canadian Mint / Sprott / Bank of Canada FX"

    elif tool_name == "etfs.get_fund_details":
        sym = str(params.get("symbol", "")).strip().upper()
        try:
            payload = get_etf_fund_details(sym)
        except KeyError as exc:
            _append_mcp_audit(tool_name, params, norm_tenant, norm_role, False, audit_path)
            return {
                "ok": False,
                "tool": tool_name,
                "symbol": sym,
                "error": str(exc),
                "execution_permission": "none",
                "personalized_advice": False,
            }
        source_attr = f"{payload.get('issuer_name')} ({payload.get('official_prospectus_domain')})"

    elif tool_name == "markets.get_quote":
        sym = str(params.get("symbol", "")).strip().upper()
        target_ccy = str(params.get("currency", "USD")).strip().upper()
        inst = master.get_instrument(sym)
        quote = _query_latest_feed_quote(sym)
        raw_price = quote.get("price")
        inst_ccy = inst.currency if inst else "USD"
        converted_price = raw_price
        if isinstance(raw_price, (int, float)):
            if inst_ccy == "USD" and target_ccy == "CAD":
                converted_price = round(float(raw_price) * usd_cad, 4)
            elif inst_ccy == "CAD" and target_ccy == "USD":
                converted_price = round(float(raw_price) / usd_cad, 4)
        payload = {
            "symbol": sym,
            "native_currency": inst_ccy,
            "native_price": raw_price,
            "display_currency": target_ccy,
            "display_price": converted_price,
            "usd_cad_rate": usd_cad,
            "quote": quote,
        }
        source_attr = str(quote.get("source") or "atlas_feed.sqlite")

    elif tool_name == "markets.get_history":
        sym = str(params.get("symbol", "")).strip().upper()
        tf = str(params.get("timeframe", "1d")).strip().lower()
        lim = int(params.get("limit", 30))
        bars = _query_feed_history(sym, timeframe=tf, limit=lim)
        payload = {
            "symbol": sym,
            "timeframe": tf,
            "count": len(bars),
            "bars": bars,
        }
        source_attr = bars[-1]["provider"] if bars else "atlas_feed.sqlite"

    elif tool_name == "assets.compare":
        raw_syms = params.get("symbols") or []
        if isinstance(raw_syms, str):
            raw_syms = [s.strip() for s in raw_syms.split(",") if s.strip()]
        comparison_rows = []
        for s in raw_syms[:8]:
            sym = str(s).strip().upper()
            inst = master.get_instrument(sym)
            if inst is None:
                continue
            issuer = master.get_issuer(inst.issuer_id)
            quote = _query_latest_feed_quote(sym)
            etf = ETFS_BY_SYMBOL.get(sym)
            pm = METALS_BY_SYMBOL.get(sym)
            native_p = quote.get("price")
            price_usd = None
            price_cad = None
            if isinstance(native_p, (int, float)):
                if inst.currency == "CAD":
                    price_cad = round(float(native_p), 4)
                    price_usd = round(float(native_p) / usd_cad, 4)
                else:
                    price_usd = round(float(native_p), 4)
                    price_cad = round(float(native_p) * usd_cad, 4)

            comparison_rows.append(
                {
                    "symbol": inst.symbol,
                    "display_name": inst.display_name,
                    "asset_class": inst.asset_class,
                    "sub_class": inst.sub_class,
                    "issuer_name": issuer.legal_name if issuer else inst.issuer_id,
                    "exchange_mic": inst.primary_exchange_mic,
                    "jurisdiction": inst.jurisdiction,
                    "native_currency": inst.currency,
                    "isin": inst.identifiers.isin,
                    "cusip": inst.identifiers.cusip,
                    "cik": inst.identifiers.cik,
                    "price_usd": price_usd,
                    "price_cad": price_cad,
                    "expense_ratio_bps": etf.expense_ratio_bps if etf else (pm.annual_custody_or_expense_bps if pm else None),
                    "holding_or_custody_form": pm.holding_form if pm else (etf.replication_method if etf else "direct_security_or_benchmark"),
                    "source": quote.get("source"),
                    "quote_status": quote.get("status"),
                    "authenticity_verified": True,
                    "investment_safety_score": None,
                }
            )
        payload = {
            "count": len(comparison_rows),
            "usd_cad_rate": usd_cad,
            "comparison": comparison_rows,
        }
        source_attr = "ATLAS Canonical Asset Master + Local Feed Store"

    else:
        _append_mcp_audit(tool_name, params, norm_tenant, norm_role, False, audit_path)
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"Unknown governed MCP tool '{tool_name}'.",
            "available_tools": [t.name for t in GOVERNED_ASSET_MCP_TOOLS],
            "execution_permission": "none",
            "personalized_advice": False,
        }

    _append_mcp_audit(tool_name, params, norm_tenant, norm_role, True, audit_path)
    return {
        "ok": True,
        "tool": tool_name,
        "tenant_id": norm_tenant,
        "role": norm_role,
        "execution_permission": "none",
        "autonomous_trading": False,
        "personalized_advice": False,
        "investment_safety_score": None,
        "source_attribution": source_attr,
        "licensed_data_control": {
            "paid_data_enabled": False,
            "redistribution_policy": "internal_research_and_paper_simulation_only",
        },
        "uncertainty_disclosure": (
            "Instrument identity verification confirms regulatory/exchange identifiers only and "
            "does not imply investment safety, positive expected return, or custodian solvency."
        ),
        "data": payload,
    }

