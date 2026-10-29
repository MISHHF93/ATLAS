"""Versioned, forward-only SQL migrations. Portable DDL (TEXT ids, BIGINT epoch seconds, base64 TEXT for binary). The only
non-portable statements are the ``payouts_ledger`` immutability triggers; ``migrations_for("postgresql")`` swaps them for a
plpgsql guard (see ``atlas.accounts.dialect``). Each migration is applied once, in order, inside a transaction, and recorded in
``schema_migrations``. Never edit a shipped migration: add a new one."""
from __future__ import annotations

M0001_ACCOUNTS = """
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  email_verified INTEGER NOT NULL DEFAULT 0,
  password_hash TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('owner','admin','user')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  display_name TEXT NOT NULL DEFAULT '',
  timezone TEXT NOT NULL DEFAULT 'America/Toronto',
  referral_code TEXT UNIQUE,
  referred_by_code TEXT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  last_login_at BIGINT,
  password_changed_at BIGINT
);
CREATE TABLE oauth_identities (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  subject TEXT NOT NULL,
  email TEXT,
  created_at BIGINT NOT NULL,
  UNIQUE (provider, subject)
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  last_seen_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  idle_expires_at BIGINT NOT NULL,
  ip_hash TEXT,
  user_agent TEXT,
  revoked_at BIGINT
);
CREATE INDEX idx_sessions_user ON sessions (user_id);
CREATE TABLE login_attempts (
  id TEXT PRIMARY KEY,
  bucket TEXT NOT NULL,
  ts BIGINT NOT NULL,
  success INTEGER NOT NULL
);
CREATE INDEX idx_login_attempts_bucket ON login_attempts (bucket, ts);
"""

M0002_CONNECTORS = """
CREATE TABLE connectors (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  connector_id TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'saved' CHECK (status IN ('saved','ok','failed')),
  mode TEXT NOT NULL DEFAULT 'data_only',
  last_tested_at BIGINT,
  last_test_ok INTEGER,
  last_test_detail TEXT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE (user_id, connector_id)
);
CREATE INDEX idx_connectors_user ON connectors (user_id);
CREATE TABLE connector_secrets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  connector_pk TEXT NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  last4 TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  nonce TEXT NOT NULL,
  wrapped_dek TEXT NOT NULL,
  wrap_nonce TEXT NOT NULL,
  kid TEXT NOT NULL,
  alg TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE (connector_pk, field)
);
CREATE INDEX idx_connector_secrets_user ON connector_secrets (user_id);
"""

M0003_AUDIT = """
CREATE TABLE audit_log (
  id TEXT PRIMARY KEY,
  seq BIGINT NOT NULL UNIQUE,
  ts BIGINT NOT NULL,
  actor_user_id TEXT,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  outcome TEXT NOT NULL DEFAULT 'ok',
  detail_json TEXT NOT NULL DEFAULT '{}',
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX idx_audit_actor ON audit_log (actor_user_id, seq);
"""

M0004_BILLING = """
CREATE TABLE plans (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'usd',
  billing_interval TEXT NOT NULL DEFAULT 'month',
  stripe_price_id TEXT,
  is_placeholder INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL
);
CREATE TABLE plan_entitlements (
  plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('flag','quota')),
  bool_value INTEGER,
  int_value BIGINT,
  period TEXT NOT NULL DEFAULT 'none' CHECK (period IN ('none','day','month')),
  PRIMARY KEY (plan_id, key)
);
CREATE TABLE subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan_id TEXT NOT NULL REFERENCES plans(id),
  status TEXT NOT NULL,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT UNIQUE,
  current_period_start BIGINT,
  current_period_end BIGINT,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX idx_subscriptions_user ON subscriptions (user_id, status);
CREATE TABLE usage_events (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  quantity BIGINT NOT NULL DEFAULT 1,
  ts BIGINT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_usage_user_key_ts ON usage_events (user_id, key, ts);
CREATE TABLE invoices (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  stripe_invoice_id TEXT NOT NULL UNIQUE,
  subscription_id TEXT,
  status TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'usd',
  amount_due BIGINT NOT NULL DEFAULT 0,
  amount_paid BIGINT NOT NULL DEFAULT 0,
  hosted_invoice_url TEXT,
  period_start BIGINT,
  period_end BIGINT,
  created_at BIGINT NOT NULL,
  mirrored_at BIGINT NOT NULL
);
CREATE INDEX idx_invoices_user ON invoices (user_id);
CREATE TABLE partner_referrals (
  id TEXT PRIMARY KEY,
  referrer_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  referred_user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','qualified','rewarded','void')),
  reward_cents BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  qualified_at BIGINT,
  rewarded_at BIGINT
);
CREATE INDEX idx_referrals_referrer ON partner_referrals (referrer_user_id);
CREATE TABLE stripe_events (
  event_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  livemode INTEGER NOT NULL DEFAULT 0,
  received_at BIGINT NOT NULL,
  processed_at BIGINT
);
"""

# M0005 aligns billing with docs-research/monetization_plan.md section 7. Forward-only: M0004 is never edited.
# Portable SQL (TEXT ids, BIGINT epoch seconds, INTEGER 0/1, money in integer minor units). The two payouts_ledger triggers are
# SQLite syntax and live in M0005_SQLITE_LEDGER_TRIGGERS; the Postgres equivalent is generated in dialect.py (M0005 is split in two
# constants whose concatenation is byte-identical to the shipped text).
M0005_BILLING_V2_BASE = """
ALTER TABLE plans ADD COLUMN tier TEXT NOT NULL DEFAULT 'free';
ALTER TABLE plans ADD COLUMN stripe_product_id TEXT;
ALTER TABLE plans ADD COLUMN trial_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plans ADD COLUMN tax_behavior TEXT NOT NULL DEFAULT 'exclusive' CHECK (tax_behavior IN ('exclusive','inclusive'));
ALTER TABLE plans ADD COLUMN seats_included INTEGER NOT NULL DEFAULT 1;
ALTER TABLE plans ADD COLUMN extra_seat_cents INTEGER NOT NULL DEFAULT 0;
UPDATE plans SET tier='pro', code='pro_month_usd', seats_included=1 WHERE code='pro';
UPDATE plans SET tier='team', code='team_month_usd', seats_included=5 WHERE code='team';
UPDATE plans SET price_cents=2900, extra_seat_cents=0 WHERE code='pro_month_usd' AND is_placeholder=1;
UPDATE plans SET price_cents=9900, extra_seat_cents=1500 WHERE code='team_month_usd' AND is_placeholder=1;

ALTER TABLE subscriptions ADD COLUMN currency TEXT NOT NULL DEFAULT 'usd';
ALTER TABLE subscriptions ADD COLUMN seats INTEGER NOT NULL DEFAULT 1;
ALTER TABLE subscriptions ADD COLUMN trial_end BIGINT;
ALTER TABLE subscriptions ADD COLUMN canceled_at BIGINT;
ALTER TABLE subscriptions ADD COLUMN dunning_state TEXT NOT NULL DEFAULT 'none' CHECK (dunning_state IN ('none','retrying','read_only','downgraded'));
ALTER TABLE subscriptions ADD COLUMN grace_until BIGINT;
ALTER TABLE subscriptions ADD COLUMN tax_country TEXT;
ALTER TABLE subscriptions ADD COLUMN tax_region TEXT;

ALTER TABLE usage_events ADD COLUMN idempotency_key TEXT;
ALTER TABLE usage_events ADD COLUMN subscription_id TEXT;
ALTER TABLE usage_events ADD COLUMN unit_cost_micros BIGINT NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX idx_usage_idem ON usage_events (idempotency_key);

ALTER TABLE invoices ADD COLUMN amount_subtotal BIGINT NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN amount_tax BIGINT NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN amount_refunded BIGINT NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN stripe_fee_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN stripe_charge_id TEXT;
ALTER TABLE invoices ADD COLUMN number TEXT;
ALTER TABLE invoices ADD COLUMN paid_at BIGINT;

CREATE TABLE tax_records (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  invoice_id TEXT NOT NULL REFERENCES invoices(id),
  stripe_tax_calculation_id TEXT,
  country TEXT NOT NULL,
  region TEXT NOT NULL DEFAULT '',
  tax_type TEXT NOT NULL CHECK (tax_type IN ('gst','hst','qst','pst','rst','sales','vat','other')),
  rate_bps INTEGER NOT NULL,
  taxable_amount BIGINT NOT NULL,
  tax_amount BIGINT NOT NULL,
  currency TEXT NOT NULL,
  location_evidence_json TEXT NOT NULL DEFAULT '{}',
  customer_tax_id TEXT,
  reverse_charge INTEGER NOT NULL DEFAULT 0,
  filing_period TEXT,
  status TEXT NOT NULL DEFAULT 'collected' CHECK (status IN ('collected','refunded','filed','remitted')),
  created_at BIGINT NOT NULL,
  remitted_at BIGINT
);
CREATE INDEX idx_tax_period ON tax_records (filing_period, tax_type, region);
CREATE INDEX idx_tax_invoice ON tax_records (invoice_id);

CREATE TABLE broker_partners (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  program_type TEXT NOT NULL CHECK (program_type IN ('cpa','rebate','pfof_share')),
  legal_status TEXT NOT NULL DEFAULT 'not_approved' CHECK (legal_status IN ('not_approved','approved')),
  terms_url TEXT,
  active INTEGER NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL
);
CREATE TABLE broker_referrals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  partner_id TEXT NOT NULL REFERENCES broker_partners(id),
  external_ref TEXT,
  status TEXT NOT NULL DEFAULT 'clicked' CHECK (status IN ('clicked','account_opened','qualified','paid','void')),
  cpa_cents BIGINT NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'usd',
  disclosure_shown_at BIGINT,
  created_at BIGINT NOT NULL,
  qualified_at BIGINT,
  paid_at BIGINT,
  UNIQUE (user_id, partner_id)
);

CREATE TABLE payouts_ledger (
  id TEXT PRIMARY KEY,
  seq BIGINT NOT NULL UNIQUE,
  ts BIGINT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('stripe_payout','stripe_fee','refund','chargeback','dispute_fee','partner_cpa','user_credit','tax_remittance','adjustment')),
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
  currency TEXT NOT NULL,
  fx_rate_micros BIGINT,
  counterparty TEXT NOT NULL,
  stripe_payout_id TEXT,
  invoice_id TEXT REFERENCES invoices(id),
  broker_referral_id TEXT REFERENCES broker_referrals(id),
  tax_record_id TEXT REFERENCES tax_records(id),
  bank_ref TEXT,
  dedupe_key TEXT UNIQUE,
  flooos_batch TEXT,
  memo TEXT NOT NULL DEFAULT '',
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX idx_ledger_kind_ts ON payouts_ledger (kind, ts);
"""

M0005_SQLITE_LEDGER_TRIGGERS = """CREATE TRIGGER payouts_ledger_no_delete BEFORE DELETE ON payouts_ledger
BEGIN SELECT RAISE(ABORT, 'payouts_ledger is append-only'); END;
CREATE TRIGGER payouts_ledger_no_update BEFORE UPDATE ON payouts_ledger
WHEN OLD.flooos_batch IS NOT NULL OR NEW.id IS NOT OLD.id OR NEW.seq IS NOT OLD.seq OR NEW.ts IS NOT OLD.ts OR NEW.kind IS NOT OLD.kind
  OR NEW.direction IS NOT OLD.direction OR NEW.amount_cents IS NOT OLD.amount_cents OR NEW.currency IS NOT OLD.currency
  OR NEW.fx_rate_micros IS NOT OLD.fx_rate_micros OR NEW.counterparty IS NOT OLD.counterparty OR NEW.stripe_payout_id IS NOT OLD.stripe_payout_id
  OR NEW.invoice_id IS NOT OLD.invoice_id OR NEW.broker_referral_id IS NOT OLD.broker_referral_id OR NEW.tax_record_id IS NOT OLD.tax_record_id
  OR NEW.bank_ref IS NOT OLD.bank_ref OR NEW.dedupe_key IS NOT OLD.dedupe_key OR NEW.memo IS NOT OLD.memo
  OR NEW.prev_hash IS NOT OLD.prev_hash OR NEW.hash IS NOT OLD.hash
BEGIN SELECT RAISE(ABORT, 'payouts_ledger is append-only (only flooos_batch may be set, once)'); END;
"""
M0005_BILLING_V2 = M0005_BILLING_V2_BASE + M0005_SQLITE_LEDGER_TRIGGERS

# M0006 (evo-12, public-launch hardening): email verification + reset tokens, invites (registration + team), team membership.
# Existing users are grandfathered as verified (they predate verification). Tokens and invite codes are stored only as sha256.
M0006_LAUNCH = """
ALTER TABLE users ADD COLUMN email_verified_at BIGINT;
UPDATE users SET email_verified=1, email_verified_at=created_at WHERE email_verified=0;
CREATE TABLE email_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
  token_hash TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  used_at BIGINT
);
CREATE INDEX idx_email_tokens_user ON email_tokens (user_id, purpose);
CREATE TABLE invites (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('registration','team')),
  email TEXT,
  team_owner_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  created_by TEXT,
  note TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  max_uses INTEGER NOT NULL DEFAULT 1,
  uses INTEGER NOT NULL DEFAULT 0,
  used_by TEXT,
  used_at BIGINT,
  revoked_at BIGINT
);
CREATE INDEX idx_invites_owner ON invites (team_owner_id, kind);
CREATE TABLE team_members (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  joined_at BIGINT NOT NULL
);
CREATE INDEX idx_team_owner ON team_members (owner_id, joined_at);
"""

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "accounts_sessions", M0001_ACCOUNTS),
    (2, "connectors_secrets", M0002_CONNECTORS),
    (3, "audit_log", M0003_AUDIT),
    (4, "billing", M0004_BILLING),
    (5, "billing_v2_tax_brokers_ledger", M0005_BILLING_V2),
    (6, "launch_hardening", M0006_LAUNCH),
)
