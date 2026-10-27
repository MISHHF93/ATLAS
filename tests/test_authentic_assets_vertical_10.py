"""Comprehensive test suite for the 10-Vertical Authentic Assets Catalog."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.assets import (
    ASSET_CLASSES,
    AUTHORIZED_MARKET_DATA_CONNECTORS,
    BONDS_AND_FIXED_INCOME_CATALOG,
    CANADIAN_REGULATORY_GATES,
    CASH_EQUIVALENTS_CATALOG,
    ETF_INTELLIGENCE_CATALOG,
    FLAGSHIP_PUBLIC_EQUITIES,
    GOVERNED_ASSET_MCP_TOOLS,
    POSTGRES_CANONICAL_ASSET_MASTER_DDL,
    PRECIOUS_METAL_INSTRUMENTS,
    VALID_ISO10383_MICS,
    VALID_ISO4217_CODES,
    audit_market_data_connectors,
    build_canadian_compliance_report,
    build_precious_metals_catalog,
    call_governed_mcp_tool,
    detect_corporate_action_or_split_flags,
    evaluate_canadian_regulatory_gate,
    get_canonical_asset_master,
    normalize_metal_price,
    reconcile_instrument_sources,
    validate_cusip,
    validate_isin,
    validate_lei,
    validate_sec_cik,
    verify_instrument_authenticity,
)
from atlas.integrations.registry import SERVICES


def test_pump_fun_decommissioned_from_active_roadmap() -> None:
    """Verify Pump.fun & speculative token launches are disabled on the active roadmap with neutral rationale."""
    by_id = {s.id: s for s in SERVICES}
    assert by_id["solana_rpc"].default_on is False
    assert "pump_fun" not in by_id or by_id["pump_fun"].default_on is False

    client = TestClient(app)
    r = client.get("/api/pump/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["product_roadmap_status"] == "disabled_by_product_policy"
    assert body["execution_permission"] == "none"
    assert body["replacement_catalog"] == "/trade?tab=markets"


def test_feature_1_canonical_asset_master_and_ddl(tmp_path: Path) -> None:
    """Verify Feature 1 Canonical Asset Master normalization and SQLite/PostgreSQL DDL."""
    master = get_canonical_asset_master()
    summary = master.summary_counts()
    assert summary["execution_permission"] == "none"
    assert summary["total_canonical_instruments"] >= 200
    assert summary["speculative_launchpads_active"] == 0
    assert len(ASSET_CLASSES) >= 8
    assert "CREATE TABLE IF NOT EXISTS canonical_instruments" in POSTGRES_CANONICAL_ASSET_MASTER_DDL

    db_file = tmp_path / "canonical_master.sqlite"
    counts = master.materialize_sqlite_schema(str(db_file))
    assert counts["canonical_instruments"] == summary["total_canonical_instruments"]
    assert counts["canonical_issuers"] >= 10
    assert counts["canonical_exchanges"] >= 8

    # Search for Royal Canadian Mint ETR
    mnt = master.get_instrument("MNT.TO")
    assert mnt is not None
    assert mnt.currency == "CAD"
    assert mnt.jurisdiction == "CA"
    assert validate_isin(mnt.identifiers.isin) is True
    assert mnt.execution_permission == "none"


def test_feature_2_precious_metals_catalog_and_conversions() -> None:
    """Verify Feature 2 Gold, Silver, Platinum, Palladium across all 7 holding forms and unit/FX conversions."""
    metals_present = {m.metal for m in PRECIOUS_METAL_INSTRUMENTS}
    assert metals_present == {"gold", "silver", "platinum", "palladium"}

    holding_forms = {m.holding_form for m in PRECIOUS_METAL_INSTRUMENTS}
    assert {
        "spot_reference",
        "physical_bullion",
        "allocated_holding",
        "unallocated_holding",
        "certificate_etr",
        "futures_contract",
        "exchange_traded_product",
    }.issubset(holding_forms)

    norm = normalize_metal_price(2700.0, usd_cad_rate=1.40, premium_bps=100.0)
    assert norm["usd_per_troy_oz"] == 2700.0
    assert norm["cad_per_troy_oz"] == 3780.0
    assert 86.0 <= float(norm["usd_per_gram"] or 0.0) <= 87.0
    assert float(norm["cad_per_kilogram"] or 0.0) > float(norm["usd_per_kilogram"] or 0.0)

    cat = build_precious_metals_catalog(metal="gold")
    assert cat["execution_permission"] == "none"
    assert cat["count"] >= 6


def test_feature_3_etf_and_fund_intelligence() -> None:
    """Verify Feature 3 ETF catalog has valid ISINs, CUSIPs, expense ratios, and NAV provenance."""
    assert len(ETF_INTELLIGENCE_CATALOG) >= 45
    symbols = {e.symbol for e in ETF_INTELLIGENCE_CATALOG}
    for required in ("SPY", "QQQ", "TLT", "BIL", "SGOV", "GLD", "SLV", "XIU.TO", "ZAG.TO", "CBIL.TO"):
        assert required in symbols

    for etf in ETF_INTELLIGENCE_CATALOG:
        assert validate_isin(etf.isin) is True, f"Invalid ISIN for {etf.symbol}: {etf.isin}"
        assert validate_cusip(etf.cusip) is True, f"Invalid CUSIP for {etf.symbol}: {etf.cusip}"
        assert etf.expense_ratio_bps >= 0
        assert etf.execution_permission == "none"


def test_feature_4_equities_bonds_and_cash_equivalents() -> None:
    """Verify Feature 4 public equities, government/corporate bonds, and cash equivalents."""
    assert len(FLAGSHIP_PUBLIC_EQUITIES) >= 28
    assert len(BONDS_AND_FIXED_INCOME_CATALOG) >= 12
    assert len(CASH_EQUIVALENTS_CATALOG) >= 8

    for eq in FLAGSHIP_PUBLIC_EQUITIES:
        assert validate_isin(eq.isin) is True, f"Invalid equity ISIN {eq.symbol}: {eq.isin}"
        assert validate_cusip(eq.cusip) is True, f"Invalid equity CUSIP {eq.symbol}: {eq.cusip}"

    cash_syms = {c.symbol for c in CASH_EQUIVALENTS_CATALOG}
    assert {"US-TBILL-1M", "US-TBILL-3M", "CA-TBILL-3M", "CA-CORRA", "BIL", "SGOV", "CBIL.TO"}.issubset(
        cash_syms
    )


def test_feature_5_authorized_market_data_connectors() -> None:
    """Verify Feature 5 market-data connectors contract and live SQLite store audit."""
    assert len(AUTHORIZED_MARKET_DATA_CONNECTORS) >= 9
    audit = audit_market_data_connectors()
    by_id = {c["connector_id"]: c for c in audit["connectors"]}
    assert by_id["bank_of_canada_valet"]["enabled_on_active_roadmap"] is True
    assert by_id["sec_edgar_xbrl"]["enabled_on_active_roadmap"] is True
    assert by_id["pump_fun_pumpswap_decommissioned"]["enabled_on_active_roadmap"] is False


def test_feature_6_instrument_authenticity_and_data_quality() -> None:
    """Verify Feature 6 mathematical checksums, cross-source reconciliation, and unlisted/meme guards."""
    assert validate_isin("US0378331005") is True
    assert validate_isin("US0378331009") is False
    assert validate_cusip("037833100") is True
    assert validate_cusip("037833109") is False
    assert validate_sec_cik("0000320193") is True
    assert validate_lei("5493006MHB84DD0ZWV18") is True
    assert "XTSE" in VALID_ISO10383_MICS
    assert "CAD" in VALID_ISO4217_CODES

    # Unlisted private entity must be rejected
    spacex = verify_instrument_authenticity("SPACEX")
    assert spacex.identity_verified is False
    assert spacex.verification_status == "unlisted_private_entity"
    assert spacex.investment_safety_score is None

    # Speculative bonding-curve Solana mint must be rejected from Authentic Assets Catalog
    pump_mint = verify_instrument_authenticity("So11111111111111111111111111111111111111112")
    assert pump_mint.identity_verified is False
    assert pump_mint.verification_status == "unvetted_speculative_token"

    # Verified Equity / ETF must pass
    aapl = verify_instrument_authenticity("AAPL")
    assert aapl.identity_verified is True
    assert aapl.verification_status == "verified_authentic"
    assert aapl.investment_safety_score is None

    rec = reconcile_instrument_sources("EUR_USD")
    assert "status" in rec

    flags = detect_corporate_action_or_split_flags("NVDA")
    assert isinstance(flags, tuple)


def test_feature_7_canadian_regulatory_and_commercial_gates() -> None:
    """Verify Feature 7 Canadian regulatory gates enforce NI 31-103, NI 81-102, NI 93-101, and FINTRAC boundaries."""
    assert len(CANADIAN_REGULATORY_GATES) >= 9
    report = build_canadian_compliance_report()
    assert report["execution_permission"] == "none"
    assert report["paid_data_enabled"] is False
    assert report["speculative_token_launches_active"] is False

    allowed = evaluate_canadian_regulatory_gate("catalog_lookup")
    assert allowed["allowed"] is True
    assert allowed["execution_permission"] == "none"

    for blocked_action in (
        "live_order_execution",
        "personalized_investment_advice",
        "client_asset_custody",
        "public_quote_redistribution",
        "pump_fun_live_trading",
    ):
        res = evaluate_canadian_regulatory_gate(blocked_action)
        assert res["allowed"] is False, f"Expected {blocked_action} to be blocked"
        assert res["execution_permission"] == "none"


def test_feature_9_governed_mcp_tools(tmp_path: Path) -> None:
    """Verify Feature 9 all 8 governed read-only MCP asset tools and audit trail."""
    tool_names = [t.name for t in GOVERNED_ASSET_MCP_TOOLS]
    assert tool_names == [
        "assets.search",
        "assets.get_profile",
        "assets.verify_identity",
        "metals.get_reference_price",
        "etfs.get_fund_details",
        "markets.get_quote",
        "markets.get_history",
        "assets.compare",
    ]
    audit_file = tmp_path / "audit.jsonl"

    r1 = call_governed_mcp_tool("assets.search", {"query": "Gold"}, audit_path=audit_file)
    assert r1["ok"] is True
    assert r1["execution_permission"] == "none"
    assert r1["investment_safety_score"] is None
    assert r1["data"]["count"] >= 2

    r2 = call_governed_mcp_tool("assets.get_profile", {"symbol": "MNT.TO"}, audit_path=audit_file)
    assert r2["ok"] is True
    assert r2["data"]["instrument"]["currency"] == "CAD"

    r3 = call_governed_mcp_tool("assets.verify_identity", {"symbol": "AAPL"}, audit_path=audit_file)
    assert r3["ok"] is True
    assert r3["data"]["identity_verified"] is True

    r4 = call_governed_mcp_tool("metals.get_reference_price", {"metal": "gold"}, audit_path=audit_file)
    assert r4["ok"] is True
    assert r4["data"]["count"] >= 6

    r5 = call_governed_mcp_tool("etfs.get_fund_details", {"symbol": "SPY"}, audit_path=audit_file)
    assert r5["ok"] is True
    assert r5["data"]["isin"] == "US78462F1030"

    r6 = call_governed_mcp_tool("markets.get_quote", {"symbol": "GC", "currency": "CAD"}, audit_path=audit_file)
    assert r6["ok"] is True
    assert r6["data"]["display_currency"] == "CAD"

    r7 = call_governed_mcp_tool("markets.get_history", {"symbol": "SPY", "timeframe": "1d", "limit": 5}, audit_path=audit_file)
    assert r7["ok"] is True

    r8 = call_governed_mcp_tool("assets.compare", {"symbols": ["GC", "GLD", "MNT.TO", "TLT"]}, audit_path=audit_file)
    assert r8["ok"] is True
    assert r8["data"]["count"] == 4

    bad_role = call_governed_mcp_tool("assets.search", {}, role="autonomous_trader_bot", audit_path=audit_file)
    assert bad_role["ok"] is False

    bad_exec = call_governed_mcp_tool("assets.search", {"execute_order": True}, audit_path=audit_file)
    assert bad_exec["ok"] is False

    assert audit_file.exists()
    assert len(audit_file.read_text(encoding="utf-8").strip().splitlines()) == 10


def test_feature_8_and_10_fastapi_endpoints() -> None:
    """Verify all `/api/assets/*` endpoints respond with 200 and `execution_permission: none`."""
    client = TestClient(app)

    for path in (
        "/api/assets/master?q=Gold&include_ddl=true",
        "/api/assets/profile/MNT.TO",
        "/api/assets/metals?metal=gold",
        "/api/assets/etfs?jurisdiction=CA",
        "/api/assets/etfs/XIU.TO",
        "/api/assets/equities-bonds-cash",
        "/api/assets/connectors",
        "/api/assets/verify/SPY",
        "/api/assets/canadian-compliance",
        "/api/assets/compare?symbols=GC,GLD,MNT.TO,TLT",
        "/api/assets/mcp/tools",
        "/api/assets/readiness-report",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} failed with {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["execution_permission"] == "none"
