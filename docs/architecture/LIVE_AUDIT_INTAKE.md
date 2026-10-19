# Live-system audit intake

Status: user supplied `C:\Users\borah\ATLAS`. This tree was inspected and
contains no live execution engine. Live-system findings remain unverified. Do not include credentials or secret values in this document.

## Required context

- Repository path supplied: `C:\Users\borah\ATLAS` (scaffold/research source only)
- Broker/exchange names and order interfaces: pending
- Prop account connected (and program name, if applicable): pending
- Secret-storage mechanism name only: pending
- Operating entity country: pending

## Evidence to record during the read-only audit

For every finding, cite the file and function, describe the observed behavior,
and distinguish source inspection from executed tests. Do not execute live order
scripts or tests that connect to trading accounts.

| Area | Evidence required | Status |
| --- | --- | --- |
| Entrypoints | Process startup, configuration flow, dependency versions | Not inspected |
| Venue adapters | Submit, amend, cancel, query, authentication boundaries | Not inspected |
| Order lifecycle | State transitions, unknown status, reconciliation before retry | Not inspected |
| Idempotency | Stable request IDs, duplicate detection, restart recovery | Not inspected |
| Partial fills | Quantity accounting and reconciliation behavior | Not inspected |
| Risk | Exposure and drawdown limits, stale data handling, default-deny cases | Not inspected |
| Kill switch | Enforcement path and independence from model services | Not inspected |
| Secrets | Mechanism and redaction boundaries, without recording values | Not inspected |
| Tests | Offline coverage, test isolation, missing characterization cases | Not inspected |
| Deployment | Process supervision and recovery behavior | Not inspected |

## Compatibility map to produce

Map each existing market reader, risk component, execution adapter, and
reconciler to the corresponding target capability. Identify read-only reuse
points and conflicts with the master spec. Preserve the existing engine.

The audit changes documentation only. Subsequent characterization tests and
small security fixes belong to the next milestone. No audit outcome by itself
enables an order route, customer funds, or a live connector in this scaffold.
