# Security review (evo-11): accounts, secrets, billing

Scope: `src/atlas/accounts/`, `src/atlas/api/account_api.py`, the settings UI, `frontend/server.mjs` IP header. Method: a pass against OWASP ASVS 4.0 level 1 basics, backed by tests in `tests/accounts/` (178 passing with the legacy connector tests).

## ASVS pass

| ASVS area | Result | How |
|---|---|---|
| V2 Authentication | Pass | argon2id (OWASP parameters), 12-character minimum, dummy hash for unknown emails (no timing oracle), per-email (5) and per-IP (30) login throttle per 15 min, register throttle 10/IP/h, rehash on parameter change, password change revokes other sessions |
| V3 Session | Pass | random 256-bit token, only sha256 stored, `HttpOnly`, `SameSite=Lax`, `Secure` when HTTPS configured, idle and absolute expiry, server-side revoke and logout, session list in the profile |
| V4 Access control | Pass | every query scoped by `user_id` from the session, never from the request; cross-user reads return 404; admin routes need owner/admin; unknown entitlement keys denied |
| V5 Validation | Pass | manual JSON parsing with size caps (32 KB) on secret-bearing routes, field allow-lists per connector, SSRF guard (`assert_public_https`, no redirects, fixed vendor hosts) |
| V6 Cryptography | Pass | AES-256-GCM, fresh 96-bit nonce per secret, per-secret data key wrapped by `ATLAS_MASTER_KEY`; AAD binds user, connector, field and version, so a copied or edited ciphertext fails; rotation via `ATLAS_MASTER_KEY_PREVIOUS` + `rewrap`; fails closed when the key is missing or malformed |
| V7 Errors and logging | Pass | hash-chained audit log, secret-shaped keys redacted, values never logged; validation errors never echo bodies on secret routes |
| V8 Data protection | Pass | secrets write-only (last 4 only), `Cache-Control: no-store` on account, billing and admin responses |
| V9 Communication | Partial | TLS is the deployer's job; cookie `Secure` is automatic with an https `ATLAS_PUBLIC_URL` |
| V10 Malicious code | Pass | no new third-party service SDKs; one new dependency, `argon2-cffi` |
| V13 API | Pass | CSRF token header plus same-host Origin check on every state change; mutations are POST only (the app CORS allows GET/POST/OPTIONS) |
| V14 Configuration | Pass | `.env.example` has blanks only; no secret in git |

## Trading-safety controls

- Catalog refuses live endpoints (Alpaca live host, OANDA live host, IBKR live ports) and keys that show live or withdraw/transfer permission. No catalog connector asks for a withdraw-capable key.
- `execution_permission` stays `none`; nothing in the accounts package places orders.

## Known limits (honest list)

1. `ATLAS_REQUIRE_AUTH` defaults **off**, so existing single-owner use keeps working. Turn it on for any shared deployment.
2. Registration defaults **open** (`ATLAS_REGISTRATION=open`). Set `closed` to invite-only.
3. Register returns 409 `email_unavailable`, which allows email enumeration. This is a deliberate trade-off while there is no email verification. There is no email sending at all.
4. The shared ingest daemon runs with the host environment (owner credentials). Only per-request API paths resolve credentials per user.
5. Behind a reverse proxy the client IP is the proxy's unless the proxy forwards it; `server.mjs` overwrites `x-atlas-client-ip` and the app trusts it only from loopback.
6. OAuth is a hook only (501). Referral payouts are not implemented.
7. The Sentry test checks DSN format only. The IBKR test is owner-only because it talks to a local gateway.
8. Rate-limit state is in SQLite; it is per instance.
9. Master key compromise exposes all secrets: keep it out of git and backups, rotate with `python -m atlas.accounts.cli rewrap`.

## M0005 additions (billing v2, tax, ledger, brokers)

- **Ledger tamper-evidence**: hash-chained `payouts_ledger`, UPDATE/DELETE blocked by triggers (SQLite syntax; Postgres port needed), chain verifiable at any time; tested including a dropped trigger.
- **Admin surface**: plan edits, broker status, manual ledger entries, Flooos export and batch marking are admin-only, bounded (integer ranges, enums, `price_`/`prod_` id prefixes), CSRF-protected POSTs, and audit-logged without values. Manual ledger kinds are restricted so cash kinds cannot be forged.
- **No user data in exports**: the Flooos export carries no user ids or emails; CSV cells beginning with `= + - @` are prefixed.
- **Webhook money paths**: refunds, disputes and payouts are idempotent by event id; livemode events are rejected before any booking. Seat counts come only from metadata written by our own checkout and are range-checked.
- **Retention vs erasure**: accounts with tax or referral records are anonymised, not deleted; secrets and sessions are always destroyed.
- **Broker referrals** are inert until an admin approves and activates a partner; disclosure is mandatory; same 404 for unknown and unapproved partners.
- **Stripe fee ledger entries** need balance-transaction reconciliation (not implemented). Tax record parsing is best-effort and unverified against a live Stripe Tax invoice.
