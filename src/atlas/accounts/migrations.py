"""Versioned, forward-only SQL migrations. Portable DDL (TEXT ids, BIGINT epoch seconds, base64 TEXT for binary), so the
same statements run on Postgres later (swap ``executescript`` for a driver loop). Each migration is applied once, in order,
inside a transaction, and recorded in ``schema_migrations``. Never edit a shipped migration: add a new one."""
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

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "accounts_sessions", M0001_ACCOUNTS),
    (2, "connectors_secrets", M0002_CONNECTORS),
    (3, "audit_log", M0003_AUDIT),
    (4, "billing", M0004_BILLING),
)
