/**
 * Feature 1 — Canonical Asset Master (PostgreSQL / Drizzle ORM Schema & Types).
 *
 * Provides normalized relational table specifications and TypeScript interfaces
 * for:
 *   1. `canonical_asset_classes`
 *   2. `canonical_issuers`
 *   3. `canonical_exchange_venues`
 *   4. `canonical_currencies`
 *   5. `canonical_instruments`
 *   6. `canonical_precious_metals`
 *   7. `canonical_etf_profiles`
 */

export interface CanonicalAssetClassRow {
  classId: string;
  label: string;
  regulatoryTreatment: string;
  custodyBoundary: string;
  allowedInPaperTrading: boolean;
  liveExecutionPermitted: boolean;
}

export interface CanonicalIssuerRow {
  issuerId: string;
  legalName: string;
  jurisdiction: string;
  lei: string | null;
  secCik: string | null;
  sedarProfileNumber: string | null;
  regulator: string;
  issuerType:
    | "sovereign"
    | "crown_corporation"
    | "fund_sponsor"
    | "public_corporation"
    | "exchange"
    | "decentralized_network";
  verified: boolean;
}

export interface CanonicalExchangeVenueRow {
  mic: string;
  operatingMic: string;
  name: string;
  countryCode: string;
  timezone: string;
  regulator: string;
  marketDataDelayMinutesFreeTier: number;
}

export interface CanonicalInstrumentRow {
  symbol: string;
  name: string;
  assetClass: string;
  subCategory: string;
  issuerId: string;
  issuerName: string;
  exchangeMic: string;
  currency: string;
  jurisdiction: string;
  isin: string | null;
  cusip: string | null;
  figi: string | null;
  secCik: string | null;
  sedarNumber: string | null;
  lei: string | null;
  tradingStatus: "active" | "reference_only" | "halted" | "delisted";
  authenticityStatus: "verified" | "flagged" | "rejected";
  primaryAuthority: string;
  feedConnectorId: string;
  regulatoryRegime: string;
  delaySeconds: number;
  redistributionAllowed: boolean;
  executionPermission: "none";
  investmentSafetyScore: null;
  riskDisclosure: string;
  extraMetadataJson: Record<string, unknown>;
}

export const DRIZZLE_CANONICAL_ASSET_TABLES = {
  canonical_asset_classes: {
    tableName: "canonical_asset_classes",
    primaryKey: "class_id",
    columns: [
      "class_id",
      "label",
      "regulatory_treatment",
      "custody_boundary",
      "allowed_in_paper_trading",
      "live_execution_permitted",
    ],
  },
  canonical_issuers: {
    tableName: "canonical_issuers",
    primaryKey: "issuer_id",
    columns: [
      "issuer_id",
      "legal_name",
      "jurisdiction",
      "lei",
      "sec_cik",
      "sedar_profile_number",
      "regulator",
      "issuer_type",
      "verified",
    ],
  },
  canonical_exchange_venues: {
    tableName: "canonical_exchange_venues",
    primaryKey: "mic",
    columns: [
      "mic",
      "operating_mic",
      "name",
      "country_code",
      "timezone",
      "regulator",
      "market_data_delay_minutes_free_tier",
    ],
  },
  canonical_currencies: {
    tableName: "canonical_currencies",
    primaryKey: "code",
    columns: ["code", "numeric_code", "name", "symbol", "minor_unit", "central_bank"],
  },
  canonical_instruments: {
    tableName: "canonical_instruments",
    primaryKey: "symbol",
    columns: [
      "symbol",
      "name",
      "asset_class",
      "sub_category",
      "issuer_id",
      "issuer_name",
      "exchange_mic",
      "currency",
      "jurisdiction",
      "isin",
      "cusip",
      "figi",
      "sec_cik",
      "sedar_number",
      "lei",
      "trading_status",
      "authenticity_status",
      "primary_authority",
      "feed_connector_id",
      "regulatory_regime",
      "delay_seconds",
      "redistribution_allowed",
      "execution_permission",
      "investment_safety_score",
      "risk_disclosure",
      "extra_metadata_json",
    ],
  },
} as const;

