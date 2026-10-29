# Monetization (evo-11): schema and rules

> **Status: placeholder. Not live.** Plans, prices and limits below are examples. A legal review is required before real billing is switched on (see "Before going live").

## Verdict: no per-trade fee, no performance fee

The owner asked how to fund the platform without taking a commission on pro trading, and for market-reasonable prices. The research (`docs-research/monetization_plan.md`, sections 1.2 and 3) found that mainstream US stock/ETF commissions are already $0, so a per-trade fee is neither competitive nor safe. ATLAS therefore:

- charges **$0 per trade** and takes **no performance fee**, rebate, spread or payment-for-order-flow. `GET /api/billing/plans` reports `fees: {per_trade_fee_cents: 0, performance_fee: false}` and a test asserts no table has a commission, per-trade, performance or take-rate column;
- earns only from **flat subscriptions** (and seats), plus an optional **fixed-bounty broker referral** that is switched off until counsel approves it;
- never moves user money: ATLAS is paper/practice only, the control plane stays deterministic, ML `execution_permission` stays `none`, and `live_order_routing` is false on every plan and is the one entitlement that owner/admin cannot bypass.

## Plans (placeholders, configurable)

All prices are **ex-tax** (`tax_behavior=exclusive`), in minor units, seeded with `is_placeholder=1`. The seeder never overwrites a row an operator edited (`POST /api/admin/plans/update`, bounded and audit-logged, or SQL).

| Plan | Monthly USD | Monthly CAD | Yearly USD | Yearly CAD | Seats |
|---|---|---|---|---|---|
| Free | 0 | 0 | | | 1 |
| Pro | 29 | 39 | 290 | 390 | 1 |
| Team | 99 | 135 | 990 | 1,350 | 5 included; extra seat USD 15 / CAD 20 per month (yearly 10x) |

Plan codes are `{tier}_{interval}_{currency}` (e.g. `team_year_cad`); the old bare `pro` / `team` codes were renamed by M0005 (ids kept, so existing subscriptions follow). Checkout takes `{plan: "team", interval, currency, seats}`; extra seats become a second inline price line and the seat count travels in the metadata. Quotas (connectors, AI queries, backtests, history days, alerts, webhooks, API access, audit export) are `plan_entitlements` rows. `seats` and `feature.team_workspace` are seeded but **not enforced**, because team workspaces are not built. Planned add-ons are listed by the plans API but are not purchasable.

## Tables (`src/atlas/accounts/migrations.py`)

M0004 `billing`: `plans`, `plan_entitlements`, `subscriptions`, `usage_events`, `invoices` (read-only Stripe mirror), `partner_referrals`, `stripe_events`.

M0005 `billing_v2_tax_brokers_ledger` (forward-only, applies cleanly to a DB with M0004 data):

| Table / change | Purpose |
|---|---|
| `plans` + | `tier`, `stripe_product_id`, `trial_days`, `tax_behavior`, `seats_included`, `extra_seat_cents` |
| `subscriptions` + | `currency`, `seats`, `trial_end`, `canceled_at`, `dunning_state` (none/retrying/read_only/downgraded), `grace_until`, `tax_country`, `tax_region` |
| `usage_events` + | `idempotency_key` (unique), `subscription_id`, `unit_cost_micros` (variable cost per use, feeds unit economics) |
| `invoices` + | `amount_subtotal`, `amount_tax`, `amount_refunded`, `stripe_fee_cents`, `stripe_charge_id`, `number`, `paid_at` |
| `tax_records` | per invoice and tax line: country, region, `tax_type`, `rate_bps`, taxable/tax amounts, location evidence JSON, `reverse_charge`, `filing_period` (e.g. `2026Q4`), status collected/refunded/remitted |
| `broker_partners` | seeded **`not_approved`, inactive**; code, name, programme type, terms URL |
| `broker_referrals` | user, partner, status (clicked/account_opened/qualified/paid/void), fixed `cpa_cents`, `disclosure_shown_at` |
| `payouts_ledger` | append-only, hash-chained company cash ledger (below) |

## Cash flows

```
Customer card --(subscription + tax)--> Stripe --(fees deducted)--> payout --> ATLAS business bank
                                           |                                      |
                                  tax collected (Stripe Tax)                tax remitted to CRA/IRS/EU by ATLAS
Broker partner (if approved) --(fixed bounty per funded account)--> ATLAS business bank
```

| Event | Source | Ledger entry |
|---|---|---|
| Stripe payout lands | webhook `payout.paid` | `stripe_payout` in |
| Refund | webhook `charge.refunded` (delta vs `invoices.amount_refunded`) | `refund` out |
| Dispute opened | webhook `charge.dispute.created` | `chargeback` out + `dispute_fee` out (default 1500, `ATLAS_DISPUTE_FEE_CENTS`) |
| Partner bounty received | admin marks referral `paid` | `partner_cpa` in (fixed amount) |
| Tax paid to authority | admin manual entry | `tax_remittance` out |
| Stripe fee reconciliation, credit, correction | admin manual entry | `stripe_fee` / `user_credit` / `adjustment` |

Every automatic entry carries a `dedupe_key` derived from the Stripe event id, so a replayed webhook books nothing twice. `stripe_fee` entries are **not** created automatically: the fee is only known from a balance transaction and that reconciliation is not implemented.

### Ledger integrity

Each row stores `prev_hash` and `hash = sha256(prev | canonical row)`. SQLite triggers refuse `DELETE` and any `UPDATE` except filling `flooos_batch` once (that column is outside the hash). `ledger.verify_chain` detects tampering even if someone drops the triggers. The triggers are SQLite syntax and need a Postgres port. Amounts are positive integer minor units; direction is `in`/`out`.

### Flooos export

`GET /api/admin/flooos/export?from=&to=&format=json|csv` (admin only) returns format `atlas-flooos-v1`: ledger rows with a Flooos-style category (cash, payment_processing_cost, refunds_disputes, referral_income, tax_remitted, ...), plus a summary of cash by category/currency, subscription revenue (subtotal, ex-tax) by month/plan/currency, tax collected by period/country/region/type, and variable cost. It contains no user ids or emails; CSV neutralises formula injection. `POST /api/admin/flooos/mark` labels exported rows with a batch id once. **This format is ours, not a verified Flooos import schema**; adjust the mapper once Flooos's real import format is known.

## Tax approach

Prices are tax-exclusive. Stripe Tax hooks are **off by default**; set `ATLAS_STRIPE_TAX=1` (and optionally `ATLAS_STRIPE_TAX_CODE`) and checkout adds `automatic_tax`, required billing address, and tax-id collection. ATLAS mirrors the tax lines of each paid invoice into `tax_records` (best-effort parsing of `total_taxes` / `total_tax_amounts` plus the customer address) so filings can be prepared; this must be verified against a Stripe test-mode invoice with Stripe Tax enabled. Registration thresholds, GST/HST/QST/PST and US nexus are for the accountant (see the research doc, section 5). Deleting an account that owns tax records or broker referrals **anonymises** it (personal data, sessions, secrets destroyed; opaque row kept) instead of deleting it, to respect statutory retention.

## Broker referrals (off until counsel approves)

Fixed bounty per qualified account only; no revenue share, no volume-based pay, no ranking by payout. A user can start a referral only if the partner is `approved` **and** `active` **and** the user was shown the disclosure; `set_partner` refuses to activate an unapproved partner; all changes are audit-logged. Unknown and not-approved partners give the same 404.

## Entitlement checks

`atlas.accounts.entitlements` is the single gate. A request is allowed only if the user's plan has the flag or quota headroom; an unknown key is **denied** (fail closed) with HTTP 402 `not_in_plan` / `quota_exceeded`. Owner and admin roles bypass quotas, except `NEVER_BYPASS` keys (`live_order_routing`). A subscription that is not `active` or `trialing` falls back to Free. `ROUTE_FEATURES` in `middleware.py` gates whole routes (today `/api/intel/lab` needs `feature.research_lab`). Usage events can carry an idempotency key.

## Stripe (test mode only)

- Env: `STRIPE_SECRET_KEY` (must start `sk_test_`; a live key is refused), `STRIPE_WEBHOOK_SECRET` (`whsec_...`), optional `ATLAS_STRIPE_TAX`, `ATLAS_STRIPE_TAX_CODE`, `ATLAS_DISPUTE_FEE_CENTS`. Never committed.
- `POST /api/billing/checkout` creates a hosted Checkout session (no SDK, plain HTTPS to `api.stripe.com`).
- `POST /api/billing/webhook` verifies the `Stripe-Signature` header (HMAC-SHA256 over `timestamp.payload`, 300 s tolerance, constant-time compare), rejects `livemode` events, and de-duplicates by event id. Without `STRIPE_WEBHOOK_SECRET` it answers 503.

## Before going live (not done)

- [ ] **Legal review**: terms of service, privacy policy, refund policy, sales tax / VAT, and consumer-protection rules in every target market.
- [ ] **Regulatory review**: confirm that a paid research/software subscription, with no commission and no custody, stays outside investment-advice, broker or money-transmission rules in each jurisdiction. Referral payments to partners need their own review (disclosure and licensing rules).
- [ ] Decide real plans and prices (replace placeholders).
- [ ] Add live-mode keys through a deliberate code change; today live keys are refused on purpose.
- [ ] Counsel sign-off per broker partner before any `legal_status='approved'`; implement automatic Stripe fee reconciliation (balance transactions); port the ledger triggers to Postgres if the DB moves.
- [ ] Enforce `seats` / team workspace once those features exist.
- [ ] Email verification and receipts.
