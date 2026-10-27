/**
 * ContrainerMaster / ATLAS — Feature 1: Canonical Investment Portfolio & Transaction Ledger
 * PostgreSQL / Drizzle ORM Schema Definition (`investmentIntelligenceSchema.ts`).
 *
 * Separately permissioned, tenant-scoped financial domain tables supporting:
 * - `cm_investment_accounts`
 * - `cm_investment_transactions` (append-only with SHA-256 deduplication & correction chains)
 * - `cm_daily_brief_archive` (point-in-time reproducible daily briefs)
 * - `cm_user_brief_preferences` (CASL/PIPEDA notification opt-in, currency, watchlists)
 */

export type EpistemicCategory =
  | "VERIFIED_TRANSACTION"
  | "IMPORTED_UNRECONCILED"
  | "USER_ENTERED"
  | "MARKET_OBSERVATION"
  | "RESEARCH_RATING"
  | "MODEL_FORECAST"
  | "AI_COMMENTARY";

export type InvestmentTransactionType =
  | "BUY"
  | "SELL"
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "DIVIDEND"
  | "DISTRIBUTION"
  | "INTEREST"
  | "FEE"
  | "SPLIT"
  | "CORPORATE_ACTION";

export interface CmInvestmentAccountRow {
  accountId: string;
  tenantId: string;
  accountName: string;
  accountType: string;
  baseCurrency: "USD" | "CAD";
  custodianSource: string;
  verificationStatus: "VERIFIED_TRANSACTION" | "IMPORTED_UNRECONCILED" | "USER_ENTERED";
  createdAt: string;
}

export interface CmInvestmentTransactionRow {
  txId: string;
  tenantId: string;
  accountId: string;
  symbol: string | null;
  txType: InvestmentTransactionType;
  tradeDate: string;
  settlementDate: string;
  quantity: number;
  price: number;
  grossAmount: number;
  fee: number;
  netCashImpact: number;
  currency: "USD" | "CAD";
  fxRateToUsd: number;
  verificationStatus: "VERIFIED_TRANSACTION" | "IMPORTED_UNRECONCILED" | "USER_ENTERED" | "CORPORATE_ACTION_ADJUSTED";
  settlementStatus: "SETTLED" | "PENDING_SETTLEMENT" | "CANCELLED_OR_SUPERSEDED";
  sourceProvenance: string;
  dedupHash: string;
  correctionOfTxId: string | null;
  supersededByTxId: string | null;
  notes: string;
  recordedAt: string;
}

export interface CmDailyBriefArchiveRow {
  briefId: string;
  tenantId: string;
  reportingDate: string;
  asOfCutoffTs: number;
  timezone: string;
  ratingMethodologyVersion: string;
  modelVersion: string;
  payloadJson: Record<string, unknown>;
  createdAt: string;
}

export interface CmUserBriefPreferencesRow {
  tenantId: string;
  preferredCurrency: "USD" | "CAD";
  timezone: string;
  watchlistSymbols: string[];
  researchInterests: string[];
  scheduleCron: string;
  deliveryChannel: "in_app" | "email_digest";
  notificationOptIn: boolean;
  consentTimestamp: string | null;
  updatedAt: string;
}

export const POSTGRES_INVESTMENT_INTELLIGENCE_DDL = `
CREATE TABLE IF NOT EXISTS cm_investment_accounts (
    account_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD',
    custodian_source TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'VERIFIED_TRANSACTION',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cm_investment_transactions (
    tx_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES cm_investment_accounts(account_id),
    symbol TEXT,
    tx_type TEXT NOT NULL,
    trade_date DATE NOT NULL,
    settlement_date DATE NOT NULL,
    quantity NUMERIC(20, 8) NOT NULL DEFAULT 0,
    price NUMERIC(20, 8) NOT NULL DEFAULT 0,
    gross_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    fee NUMERIC(20, 4) NOT NULL DEFAULT 0,
    net_cash_impact NUMERIC(20, 4) NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    fx_rate_to_usd NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    verification_status TEXT NOT NULL,
    settlement_status TEXT NOT NULL DEFAULT 'SETTLED',
    source_provenance TEXT NOT NULL,
    dedup_hash TEXT NOT NULL,
    correction_of_tx_id TEXT,
    superseded_by_tx_id TEXT,
    notes TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cm_daily_brief_archive (
    brief_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    reporting_date DATE NOT NULL,
    as_of_cutoff_ts BIGINT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
    rating_methodology_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cm_user_brief_preferences (
    tenant_id TEXT PRIMARY KEY,
    preferred_currency TEXT NOT NULL DEFAULT 'USD',
    timezone TEXT NOT NULL DEFAULT 'America/Toronto',
    watchlist_symbols_json JSONB NOT NULL DEFAULT '["GC","GLD","SPY","AAPL","MSFT","BIL"]',
    research_interests_json JSONB NOT NULL DEFAULT '["precious_metals","etfs","equities","macro_rates"]',
    schedule_cron TEXT NOT NULL DEFAULT '30 7 * * 1-5',
    delivery_channel TEXT NOT NULL DEFAULT 'in_app',
    notification_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    consent_timestamp TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
`.trim();

