"""Founder workbench API (ported from the Lola trading platform; see docs/lola-port-plan.md).

Read-mostly, paper-only endpoints for the owner's own-capital track: Safe stop, approval queue,
Action-needed inbox, Canadian venues, tax (ACB / superficial loss / BoC FX / T5008 / T1135),
the 8 non-custodial money ledgers and compliance. Every response carries
``execution_permission: "none"`` and ``trading: "paper_only"``. Nothing here can place, approve or
size an order. The one write (engage Safe stop) can only *halt*; reset and approvals require the
owner CLI with step-up auth (``atlas-owner``) and are deliberately not exposed over HTTP.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.control.founder_track import build_founder_rulebook, founder_policy_dir
from atlas.governance import EIGHT_NON_CUSTODIAL_LEDGERS, LEDGER_IMPLEMENTATIONS
from atlas.governance.audit import AuditLog
from atlas.risk.approvals import ApprovalQueue
from atlas.risk.killswitch import KillSwitch
from atlas.risk.state_store import StateStore

router = APIRouter(prefix="/api/founder", tags=["founder"])

ENVELOPE = {"execution_permission": "none", "trading": "paper_only", "track": "founder_capital"}


def _env(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, **ENVELOPE}


class _Svc:
    """Shares the SQLite state with the core/watchdog processes when ATLAS_STATE_DB / ATLAS_AUDIT_DB are set."""

    def __init__(self) -> None:
        self.store = StateStore(os.environ.get("ATLAS_STATE_DB", ":memory:"))
        self.audit = AuditLog(os.environ.get("ATLAS_AUDIT_DB", ":memory:"))
        from atlas.risk.safe_stop import shared_safe_stop

        self.ks = shared_safe_stop()  # the same Safe stop the control plane uses
        cfg = _config()
        ttl = float(cfg.risk.autonomy.approval_ttl_seconds) if cfg else 120.0
        owner = cfg.risk.owner if cfg else "owner"
        self.approvals = ApprovalQueue(ttl, owner, self.audit, store=self.store)


@lru_cache(maxsize=1)
def _config():
    try:
        from atlas.control.policy import load_all

        return load_all(founder_policy_dir())
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def service() -> _Svc:
    return _Svc()


def _safe_stop(svc: _Svc) -> dict[str, Any]:
    return {"engaged": svc.ks.engaged, "reason": svc.ks.reason, "engaged_at": svc.ks.engaged_at,
            "reset": "owner CLI only: `atlas-owner reset-kill-switch` (step-up auth)"}


class SafeStopPayload(BaseModel):
    reason: str = Field(default="owner_safe_stop_button", min_length=1, max_length=200)


@router.get("/state")
def founder_state() -> dict[str, Any]:
    book = build_founder_rulebook()
    svc = service()
    return _env({
        "rulebook_id": book.rulebook_id,
        "max_daily_loss_fraction": str(book.max_daily_loss_fraction),
        "max_drawdown_fraction": str(book.max_drawdown_fraction),
        "policy_loaded": _config() is not None,
        "safe_stop": _safe_stop(svc),
        "pending_approvals": len(svc.approvals.pending()),
        "ai_authority": "shrink_or_veto_only",
        "live_trading": "locked",
    })


def _engine():
    from atlas.api.app import control_engine  # lazy: app includes this router

    return control_engine


@router.get("/pnl")
def founder_pnl() -> dict[str, Any]:
    return _env(_engine().founder_pnl())


@router.get("/remaining-room")
def founder_remaining_room() -> dict[str, Any]:
    return _env(_engine().get_remaining_room_hud(track="founder_capital"))


@router.get("/safe-stop")
def safe_stop_status() -> dict[str, Any]:
    return _env(_safe_stop(service()))


@router.post("/safe-stop")
def safe_stop_engage(payload: SafeStopPayload) -> dict[str, Any]:
    """Halt only. Engaging never needs step-up (reducing risk is always allowed); resetting does."""
    res = service().ks.engage(payload.reason, channel="atlas_frontend")
    return _env({"result": res, **_safe_stop(service())})


@router.post("/safe-stop/reset")
def safe_stop_reset() -> dict[str, Any]:
    raise HTTPException(status_code=403, detail="Safe stop reset requires the owner CLI with step-up auth (atlas-owner).")


@router.get("/approvals")
def approvals() -> dict[str, Any]:
    items = [{"approval_id": p.approval_id, "symbol": p.intent.symbol, "side": p.intent.side, "qty": p.intent.qty,
              "status": p.status} for p in service().approvals.pending()]
    return _env({"pending": items, "decide_with": "atlas-owner approve|reject <id> (step-up auth)"})


@router.get("/inbox")
def action_inbox() -> dict[str, Any]:
    svc = service()
    items: list[dict[str, Any]] = []
    if svc.ks.engaged:
        items.append({"area": "trading", "kind": "safe_stop", "severity": "critical", "title": "Trading is halted",
                      "detail": f"Safe stop: {svc.ks.reason or 'no reason'}. Reset needs step-up.", "href": "/control"})
    pend = svc.approvals.pending()
    if pend:
        items.append({"area": "trading", "kind": "approval", "severity": "high",
                      "title": f"{len(pend)} proposed paper trade(s) to approve or reject", "detail": "Expires if you do nothing.",
                      "href": "/inbox", "count": len(pend)})
    if _config() is None:
        items.append({"area": "trading", "kind": "policy", "severity": "high", "title": "Founder risk policy did not load",
                      "detail": "Built-in 2% daily-loss defaults are in force (fail closed).", "href": "/compliance"})
    for name, problem in _venue_problems():
        items.append({"area": "compliance", "kind": "venue", "severity": "normal", "title": f"Venue {name}: re-verify",
                      "detail": problem, "href": "/compliance"})
    return _env({"items": items, "count": len(items)})


def _venue_problems() -> list[tuple[str, str]]:
    cfg = _config()
    if not cfg or not cfg.venues:
        return []
    from atlas.control.policy.venues import as_of_date, registration_problem

    out = []
    for name, v in cfg.venues.venues.items():
        p = registration_problem(v, cfg.venues, as_of_date())
        if p:
            out.append((name, p))
    return out


@router.get("/venues")
def venues() -> dict[str, Any]:
    cfg = _config()
    if not cfg or not cfg.venues:
        return _env({"available": False, "venues": []})
    vc = cfg.venues
    rows = [{"venue": k, "legal_entity": v.legal_entity, "regulator": v.registration.regulator,
             "registration": v.registration.status, "last_verified": v.registration.last_verified.isoformat(),
             "paper_only": v.paper_only, "asset_classes": v.asset_classes, "spot_only": v.flags.spot_only,
             "margin": v.flags.margin, "derivatives": v.flags.derivatives} for k, v in vc.venues.items()]
    return _env({"available": True, "operating_entity": vc.operating_entity.model_dump(mode="json"),
                 "venues": rows, "excluded_venues": vc.excluded_venues, "problems": dict(_venue_problems())})


@router.get("/tax")
def tax_summary() -> dict[str, Any]:
    cfg = _config()
    tax = cfg.tax if cfg else None
    return _env({
        "jurisdiction": "CA",
        "method": "adjusted cost base (ACB, average cost per CRA)",
        "superficial_loss_guard": getattr(tax, "superficial_loss_guard", "warn"),
        "fx_source": "Bank of Canada daily rates (atlas.tax.boc_fetch)",
        "reports": ["T5008-style dispositions CSV", "T1135 foreign property check", "Schedule 3 capital gains"],
        "foreign_currencies": list(getattr(tax, "foreign_currencies", ["USD", "EUR", "GBP"])),
        "notice": "Records for your accountant; not tax advice and nothing is filed.",
    })


@router.get("/ledgers")
def ledgers() -> dict[str, Any]:
    rows = [{"ledger": k, **LEDGER_IMPLEMENTATIONS[k]} for k in EIGHT_NON_CUSTODIAL_LEDGERS]
    balances: dict[str, Any] = {"available": False}
    db = os.environ.get("ATLAS_PAYMENTS_DB")
    if db and os.path.exists(db):
        from atlas.ledgers.readonly import BalanceView

        try:
            balances = {"available": True, **BalanceView(db).summary()}
        except Exception as exc:  # noqa: BLE001
            balances = {"available": False, "error": type(exc).__name__}
    return _env({"custody": "non_custodial", "ledgers": rows, "payments": balances})


@router.get("/compliance")
def compliance() -> dict[str, Any]:
    from atlas.compliance.fintrac import KINDS, RETENTION_YEARS, THRESHOLD, TRAVEL_RULE_MIN

    return _env({
        "fintrac": {"mode": "records_only_simulation", "record_kinds": KINDS, "threshold_cad": str(THRESHOLD),
                    "travel_rule_min_cad": str(TRAVEL_RULE_MIN), "retention_years": RETENTION_YEARS},
        "sanctions": {"lists": ["SEMA (Canada)", "UN", "OFAC SDN"], "refresh": "python tools/fetch_sanctions_lists.py"},
        "privacy": "PIPEDA & Quebec Law 25: minimum data, purpose-bound consent (p_consents), 30-day DSAR access, 24-month RROSH breach register, retention + purge with legal hold (atlas.compliance.privacy)",
        "privacy_details": _privacy_details(),
        "iso_standards": _iso_standards(),
        "regulatory_links": _regulatory_links(),
        "third_party_links": _third_party_links(),
        "venue_problems": dict(_venue_problems()),
        "notice": "Not legal advice. Nothing is filed or transmitted.",
    })


def _privacy_details() -> dict[str, Any]:
    from atlas.compliance.privacy import ACCESS_DAYS, PURPOSES, RETAIN_INCIDENT_DAYS, WITHHELD

    return {
        "frameworks": [
            {
                "id": "PIPEDA",
                "name": "Personal Information Protection and Electronic Documents Act (Canada)",
                "authority": "Office of the Privacy Commissioner of Canada (OPC)",
                "scope": "Federal private-sector privacy law governing consent, data minimization, 30-day DSAR access requests, and s.10.3 24-month RROSH breach register.",
                "module": "atlas.compliance.privacy",
                "official_url": "https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/",
            },
            {
                "id": "QUEBEC_LAW_25",
                "name": "Quebec Law 25 (Act to modernize legislative provisions as regards the protection of personal information)",
                "authority": "Commission d'accès à l'information du Québec (CAI)",
                "scope": "Privacy by default, explicit purpose-bound consent ledger (p_consents), confidentiality incident register, and data portability.",
                "module": "atlas.compliance.privacy",
                "official_url": "https://www.cai.gouv.qc.ca/",
            },
            {
                "id": "PCMLTFA_S8_PRIVACY_INTERLOCK",
                "name": "PCMLTFA s.8 Statutory Withholding Interlock",
                "authority": "FINTRAC / Department of Finance Canada",
                "scope": "Subject access exports (DSAR) automatically withhold STR/sanctions tipping-off indicators as required by PCMLTFA s.8.",
                "module": "atlas.compliance.privacy",
                "official_url": "https://fintrac-canafe.canada.ca/guidance-directives/overview-apercu/Guide1/1-eng",
            },
        ],
        "consent_purposes": list(PURPOSES),
        "breach_register_retention_days": RETAIN_INCIDENT_DAYS,
        "dsar_response_sla_days": ACCESS_DAYS,
        "withheld_fields_on_export": list(WITHHELD),
        "append_only_tables": ["p_consents", "p_incidents", "p_access_requests", "p_retention"],
    }


def _iso_standards() -> list[dict[str, str]]:
    return [
        {
            "standard": "ISO 10383",
            "title": "Codes for exchanges and market identification (MIC)",
            "category": "Financial Markets",
            "atlas_implementation": "Canonical MIC routing across XNYS, XNAS, ARCX, XTSE, XCME, XCEC, XNYM (atlas.market.sessions, atlas.assets.service).",
            "official_url": "https://www.iso20022.org/market-identifier-codes",
        },
        {
            "standard": "ISO 6166",
            "title": "International Securities Identification Number (ISIN)",
            "category": "Financial Instruments",
            "atlas_implementation": "12-character alphanumeric ISIN & Luhn check-digit verification for equities, ETFs, sovereign bonds, and ETRs (atlas.assets.service).",
            "official_url": "https://www.anna-web.org/standards/isin-iso-6166/",
        },
        {
            "standard": "ISO 10962",
            "title": "Classification of Financial Instruments (CFI)",
            "category": "Financial Instruments",
            "atlas_implementation": "Normalized taxonomy distinguishing equities, ETFs, allocated/unallocated bullion, futures, and sovereign debt (atlas.assets.service).",
            "official_url": "https://www.iso.org/standard/81140.html",
        },
        {
            "standard": "ISO 4217",
            "title": "Codes for the representation of currencies (Currency & Precious Metals)",
            "category": "Currency & FX",
            "atlas_implementation": "Currency and bullion unit codes (CAD, USD, EUR, GBP, XAU, XAG, XPT, XPD) with Bank of Canada daily FX conversion (atlas.tax.boc_fetch).",
            "official_url": "https://www.iso.org/iso-4217-currency-codes.html",
        },
        {
            "standard": "ISO 20022",
            "title": "Universal financial industry message scheme",
            "category": "Financial Messaging & Audit",
            "atlas_implementation": "Structured financial transaction, settlement, and FINTRAC LCTR/EFTR/LVCTR audit record schemas (atlas.compliance.fintrac).",
            "official_url": "https://www.iso20022.org/",
        },
        {
            "standard": "ISO/IEC 27001:2022",
            "title": "Information security, cybersecurity and privacy protection — ISMS",
            "category": "Information Security",
            "atlas_implementation": "RBAC enforcement, step-up authentication for owner mutations, correlation IDs, and immutable audit trails (atlas.api.rbac, atlas.ops.correlation).",
            "official_url": "https://www.iso.org/standard/27001",
        },
        {
            "standard": "ISO/IEC 27701:2019",
            "title": "Security techniques — Privacy Information Management System (PIMS)",
            "category": "Privacy & Data Governance",
            "atlas_implementation": "Purpose-bound consent tracking, retention schedules, legal-hold interlocks, and DSAR export redaction (atlas.compliance.privacy).",
            "official_url": "https://www.iso.org/standard/71670.html",
        },
        {
            "standard": "ISO/IEC 42001:2023",
            "title": "Information technology — Artificial intelligence — Management system (AIMS)",
            "category": "AI & ML Governance",
            "atlas_implementation": "Enforces execution_permission='none' via AINodeMiddleware, walk-forward OOS gates, Brier/ECE calibration monitoring, and Champion/Challenger lineage (atlas.ai.http, atlas.ai.ml.live_intelligence).",
            "official_url": "https://www.iso.org/standard/81230.html",
        },
        {
            "standard": "ISO 31000:2018",
            "title": "Risk management — Guidelines",
            "category": "Risk Management",
            "atlas_implementation": "Deterministic 2% daily-loss Safe Stop kill-switch, fractional Kelly sizing caps, and venue/session restriction gates (atlas.risk.safe_stop, atlas.control.engine).",
            "official_url": "https://www.iso.org/iso-31000-risk-management.html",
        },
    ]


def _regulatory_links() -> list[dict[str, str]]:
    return [
        {
            "id": "CIRO",
            "name": "Canadian Investment Regulatory Organization (CIRO)",
            "jurisdiction": "Canada",
            "role": "National self-regulatory organization overseeing investment dealers, crypto-asset trading platforms, and marketplace surveillance (UMIR).",
            "official_url": "https://www.ciro.ca/",
        },
        {
            "id": "CSA_OSC",
            "name": "Canadian Securities Administrators (CSA) & Ontario Securities Commission (OSC)",
            "jurisdiction": "Canada (Ontario)",
            "role": "National Instrument 31-103 (Registration), NI 81-102 (Investment Funds / ETFs), and registered CTP directory.",
            "official_url": "https://www.osc.ca/",
        },
        {
            "id": "FINTRAC",
            "name": "Financial Transactions and Reports Analysis Centre of Canada (FINTRAC)",
            "jurisdiction": "Canada",
            "role": "PCMLTFA anti-money laundering recordkeeping (LVCTR >= 10,000 CAD, EFTR, Travel Rule >= 1,000 CAD, 5-year retention).",
            "official_url": "https://fintrac-canafe.canada.ca/",
        },
        {
            "id": "SEMA_CANADA",
            "name": "Consolidated Canadian Autonomous Sanctions List (SEMA / JVCFOA)",
            "jurisdiction": "Canada",
            "role": "Global Affairs Canada consolidated sanctions screening source.",
            "official_url": "https://www.international.gc.ca/world-monde/international_relations-relations_internationales/sanctions/consolidated-consolide.aspx",
        },
        {
            "id": "OFAC_SDN",
            "name": "US Treasury OFAC Specially Designated Nationals (SDN) List",
            "jurisdiction": "United States",
            "role": "Cross-border USD/equities sanctions screening reference.",
            "official_url": "https://sanctionssearch.ofac.treas.gov/",
        },
        {
            "id": "UN_SC",
            "name": "United Nations Security Council Consolidated List",
            "jurisdiction": "International",
            "role": "Multilateral sanctions screening list.",
            "official_url": "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
        },
        {
            "id": "SEC_EDGAR",
            "name": "U.S. Securities and Exchange Commission (SEC) EDGAR",
            "jurisdiction": "United States",
            "role": "Authoritative as-filed XBRL corporate disclosures, 10-K/10-Q/N-PORT filings, and CIK registry.",
            "official_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        },
    ]


def _third_party_links() -> list[dict[str, str]]:
    from atlas.integrations.protocol_manifest import PROTOCOL_SPECS

    return [
        *[
            {
                "id": spec.adapter_id.upper(),
                "name": spec.title,
                "category": "Market Data & Protocol Integration",
                "auth_or_license": f"{spec.auth_mechanism} · {spec.licensing}",
                "scope": f"Rate limits: {spec.rate_limits} · Ops: {', '.join(spec.supported_operations)}",
                "official_url": spec.official_docs[0] if spec.official_docs else "",
            }
            for spec in PROTOCOL_SPECS
        ],
        {
            "id": "BANK_OF_CANADA",
            "name": "Bank of Canada Valet API (FX & Sovereign Yields)",
            "category": "Central Bank & Macro Reference",
            "auth_or_license": "Public Open Data (No Key Required)",
            "scope": "Daily FX conversion rates (USDCAD, EURCAD, GBPCAD) for CRA ACB tax pools and Government of Canada bond yields.",
            "official_url": "https://www.bankofcanada.ca/valet/docs",
        },
        {
            "id": "ECB_DATA_PORTAL",
            "name": "European Central Bank (ECB) Data Portal SDMX API",
            "category": "Central Bank & Macro Reference",
            "auth_or_license": "Public Open Data",
            "scope": "Euro reference exchange rates and sovereign yield curve series.",
            "official_url": "https://data.ecb.europa.eu/help/api/data",
        },
        {
            "id": "NASDAQ_CALENDAR",
            "name": "Nasdaq Stock Market Official Hours & Holiday Schedule (XNAS)",
            "category": "Exchange Calendar & Microstructure",
            "auth_or_license": "Public Exchange Rulebook",
            "scope": "Pre-market 04:00 ET, Regular 09:30–16:00 ET, After-hours 16:00–20:00 ET, Early closes 13:00 ET, and 23/5 overnight roadmap.",
            "official_url": "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule",
        },
        {
            "id": "NYSE_CALENDAR",
            "name": "New York Stock Exchange & NYSE Arca Hours & Calendars (XNYS / ARCX)",
            "category": "Exchange Calendar & Microstructure",
            "auth_or_license": "Public Exchange Rulebook",
            "scope": "Core trading session 09:30–16:00 ET, extended hours, and US market holidays.",
            "official_url": "https://www.nyse.com/markets/hours-calendars",
        },
        {
            "id": "TMX_TSX_CALENDAR",
            "name": "Toronto Stock Exchange (TSX / XTSE) Trading Hours & Holidays",
            "category": "Exchange Calendar & Microstructure",
            "auth_or_license": "Public Exchange Rulebook",
            "scope": "Canadian equities, ETFs, and Royal Canadian Mint ETRs (09:30–16:00 ET, Family Day, Victoria Day, Civic Holiday, Boxing Day).",
            "official_url": "https://www.tsx.com/trading/calendars-and-trading-hours",
        },
        {
            "id": "CME_GLOBEX",
            "name": "CME Group / COMEX / NYMEX Globex Trading Hours (XCME / XCEC / XNYM)",
            "category": "Exchange Calendar & Microstructure",
            "auth_or_license": "Public Exchange Rulebook",
            "scope": "Sunday 18:00 ET – Friday 17:00 ET continuous futures/metals sessions with daily 17:00–18:00 ET maintenance break.",
            "official_url": "https://www.cmegroup.com/trading-hours.html",
        },
        {
            "id": "LBMA_BULLION",
            "name": "London Bullion Market Association (LBMA) Precious Metals & Good Delivery",
            "category": "Precious Metals Benchmark",
            "auth_or_license": "Public Benchmark Reference",
            "scope": "Good Delivery purity standards (995.0+ Au, 999.0+ Ag, 999.5+ Pt/Pd) and London spot benchmark references.",
            "official_url": "https://www.lbma.org.uk/",
        },
        {
            "id": "ROYAL_CANADIAN_MINT",
            "name": "Royal Canadian Mint — Canadian Gold & Silver Reserves ETRs (MNT.TO / SVR.TO)",
            "category": "Precious Metals Custody",
            "auth_or_license": "Official Issuer Disclosures",
            "scope": "Direct sovereign Crown Corporation physical bullion custody in Ottawa vaults.",
            "official_url": "https://www.reserves.mint.ca/",
        },
        {
            "id": "COINBASE_EXCHANGE",
            "name": "Coinbase Exchange Public Market Data API",
            "category": "Market Data & Protocol Integration",
            "auth_or_license": "Public REST / WebSocket",
            "scope": "24/7 spot crypto reference quotes and candles (BTC-USD, ETH-USD, SOL-USD).",
            "official_url": "https://docs.cdp.coinbase.com/exchange/docs/welcome",
        },
        {
            "id": "TRADINGVIEW_LWC",
            "name": "TradingView Lightweight Charts (v5) & UDF Specification",
            "category": "Open-Source Visualization Attribution",
            "auth_or_license": "Apache License 2.0",
            "scope": "Primary canvas charting engine for ATLAS Live Desk (AtlasChart.tsx) and /api/udf/* history feed.",
            "official_url": "https://www.tradingview.com/lightweight-charts/",
        },
    ]


@router.get("/standards-and-links")
def standards_and_links() -> dict[str, Any]:
    return _env({
        "privacy_details": _privacy_details(),
        "iso_standards": _iso_standards(),
        "regulatory_links": _regulatory_links(),
        "third_party_links": _third_party_links(),
    })
