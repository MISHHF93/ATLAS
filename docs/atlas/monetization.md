# Monetization (evo-11): schema and rules

> **Status: placeholder. Not live.** Plans, prices and limits below are examples. A legal review is required before real billing is switched on (see "Before going live").

## What ATLAS does not do

- **No per-trade commissions.** ATLAS never takes a fee, spread, rebate or share of any trade or of any user's profit. No table, column or code path records one. The owner's question was how to fund the platform without taking a commission on pro trading; the answer here is subscriptions plus (later) partner referrals.
- **No live money movement.** ATLAS is paper/practice only. The control plane stays deterministic and ML `execution_permission` stays `none`. Billing never touches execution.

## Revenue model (schema only)

1. **Subscriptions** (Free / Pro / Team): a flat recurring fee that gates features and quotas.
2. **Partner referrals**: a referral code per user and a ledger of sign-ups. Payout logic is **not implemented** (`reward_cents` is 0; TODO).

## Tables (`src/atlas/accounts/migrations.py`, migration 4 `billing`)

| Table | Purpose |
|---|---|
| `plans` | code, name, description, `price_cents`, currency, interval, `is_placeholder`, active, sort |
| `plan_entitlements` | per plan: key, kind (`flag` or `quota`), `bool_value` / `int_value`, `period` (`none`, `day`, `month`) |
| `subscriptions` | per user: plan, status, Stripe customer and subscription ids, period end, cancel flag. Created only from a verified webhook |
| `usage_events` | metered use (for example `connector_tests.daily`), per user, per key, timestamped |
| `invoices` | read-only mirror of Stripe invoices (hosted URL, amounts, status) |
| `partner_referrals` | referrer, referred user, code, status, `reward_cents` (0), timestamps |
| `stripe_events` | processed event ids, so a replayed webhook is a no-op |

Seeded placeholder plans (TODO(pricing): replace through a new migration or an admin edit; the seeder never overwrites existing rows):

| Plan | Example price | Notes |
|---|---|---|
| Free | $0 | 4 connectors, 1 alert channel, 20 connector tests/day, no research lab |
| Pro | $19/month | more connectors and channels, research lab |
| Team | $49/month | team workspace flag reserved, not built |

## Entitlement checks

`atlas.accounts.entitlements` is the single gate. A request is allowed only if the user's plan has the flag or quota headroom; an unknown key is **denied** (fail closed) with HTTP 402 `not_in_plan` / `quota_exceeded`. Owner and admin roles bypass quotas. A subscription that is not `active` or `trialing` falls back to Free. `ROUTE_FEATURES` in `middleware.py` gates whole routes (today `/api/intel/lab` needs `feature.research_lab`).

## Stripe (test mode only)

- Env: `STRIPE_SECRET_KEY` (must start `sk_test_`; a live key is refused) and `STRIPE_WEBHOOK_SECRET` (`whsec_...`). Never committed.
- `POST /api/billing/checkout` creates a hosted Checkout session (no SDK, plain HTTPS to `api.stripe.com`).
- `POST /api/billing/webhook` verifies the `Stripe-Signature` header (HMAC-SHA256 over `timestamp.payload`, 300 s tolerance, constant-time compare), rejects `livemode` events, and de-duplicates by event id. Without `STRIPE_WEBHOOK_SECRET` it answers 503.

## Before going live (not done)

- [ ] **Legal review**: terms of service, privacy policy, refund policy, sales tax / VAT, and consumer-protection rules in every target market.
- [ ] **Regulatory review**: confirm that a paid research/software subscription, with no commission and no custody, stays outside investment-advice, broker or money-transmission rules in each jurisdiction. Referral payments to partners need their own review (disclosure and licensing rules).
- [ ] Decide real plans and prices (replace placeholders).
- [ ] Add live-mode keys through a deliberate code change; today live keys are refused on purpose.
- [ ] Implement referral payouts (currently reward 0).
- [ ] Email verification and receipts.
