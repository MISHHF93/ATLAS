# Research Operating Contract v1

Status: documented research rules, not a production scheduler, deterministic
execution controller, or live trading authorization. The current repository has
no live execution engine. All research forecasts, model records and signals keep
`execution_permission: none`.

## Purpose and tracks

ATLAS may run read-only collection, validation, regime analysis, forecasting and
evaluation jobs continuously, including while no person is present. This means
research operations only. It does not authorize orders, account access, custody,
or unattended broker/exchange activity.

Maintain two separately versioned research tracks:

| Track | Objective | Required evaluation identity |
| --- | --- | --- |
| Competition | Evaluate against one named competition's published instruments, session, rules, costs and score | Competition ID/rulebook revision + instrument + horizon + data manifest + protocol revision |
| Open market | Assess forecasts on a separately chosen instrument/horizon scope and point-in-time tradable-session targets | Venue/instrument + horizon + calendar revision + data manifest + protocol revision |

Do not pool scores across tracks or present a competition score as evidence of
open-market performance. Neither evaluation proves profitability or future wins.

## Deterministic research gates

1. **Source and license.** Every dataset/feature has a provider, source reference,
   license reference and allowed-use record for retrieval, retention, transforms,
   internal training, competition participation and any redistribution. Any
   missing or disallowed use makes the input ineligible. MCP tool annotations do
   not establish rights.
2. **Point-in-time availability.** Store event time, published/available time,
   retrieved time, timezone, instrument, venue, upstream ID and adjustment
   method. A feature is usable at `as_of` only if its information was available
   by `as_of`. Use SEC filing acceptance/availability, not just the fiscal period;
   exclude later amendments and revisions unless a vintage-aware replay proves
   they were available then.
3. **Calendar and horizon.** Every instrument pins a versioned calendar or an
   explicit continuous-market schedule, and every horizon pins sampling,
   resolution, clock, target convention and steps. Build targets from the
   selected source's authoritative schedule. Unknown timezone/session/holiday,
   market closure, maintenance or venue-specific funding schedule means no
   target generation for that scope.
4. **Quality and freshness.** Validate numeric finiteness/ranges, ordering,
   duplicate identity, missing intervals, symbol mapping, currency/units,
   adjustment lineage, freshness and expected publication delay. Only a
   reproducible report with no blocking issue may mark quality `verified`.
   Missing metadata is `unknown`, never silently zero or fresh.
5. **Regimes.** Regime labels are versioned deterministic features derived only
   from data available at the observation time. Initial candidate dimensions:
   realized volatility, trend/breadth, liquidity/spread/volume, session state,
   macro/event state, and asset-class/venue schedule. Keep `unknown` when the
   window or source is insufficient. Record label time, inputs, thresholds,
   transform version and availability. Regime labels organize comparisons; they
   do not authorize model switching or execution.
6. **Forecast and approval.** Forecast eligibility remains scoped to immutable
   model revision, instrument, horizon, target and unit, plus license, freshness,
   quality, liquidity/cost scope and human research approval. Expired or absent
   approval denies forecast selection. Approval never changes execution
   permission.
7. **Evaluation and improvement.** Freeze data, code, environment, seed, cost
   assumptions, split boundaries, baselines, regime definition and metrics before
   evaluation. Use chronological walk-forward splits; purge/embargo overlapping
   labels. Report overall and per-regime coverage, missingness, drift, availability,
   and costed performance against naive and no-trade baselines. A challenger is
   immutable. Outcomes may initiate a new experiment, not mutate weights or
   promote a model automatically. Ensembles remain disabled without independent
   evidence.
8. **Authority.** MCP and LLM outputs are untrusted research inputs. They cannot
   mutate policy, approvals, risk settings, kill-switch state, orders, balances or
   model artifacts. The data plane exposes no write tools to the LLM. Every
   `Forecast`, `ModelRecord` and `ResearchSignal` retains
   `execution_permission: none`.

## Future execution policy fields

The following are mandatory fields for a future deterministic control-plane rule
set, but there are no configured numeric values or active rules in this
repository:

| Rule family | Values that must be specified from evidence | Current effect |
| --- | --- | --- |
| Exposure | Max position/notional, gross/net exposure, concentration and correlated exposure | Unconfigured; no orders possible |
| Leverage | Maximum leverage/margin and instrument-specific liquidation buffer | Unconfigured; no orders possible |
| Loss | Intraday/daily loss, peak-to-trough drawdown and recovery/reset rules | Unconfigured; no orders possible |
| Sessions | Allowed venues, instrument sessions, competition restrictions, holidays, early closes and crypto maintenance/funding windows | No authoritative calendar integration |
| Data | Max age, missingness, quality status, source/license validity, clock skew and fallback policy | Research validators only; no execution controller |
| Circuit breakers | Thresholds, order-state reconciliation, kill-switch location, operator reset and independent enforcement | Not implemented or audited |
| Model | Approved immutable revision, feature/calibrator/data revisions, per-scope expiry and rollback | Research approvals/aliases only |

Do not fill these values with generic defaults. First identify the competition
rulebook and actual venue, gather provider/counsel requirements, and verify the
existing engine's behavior. Until then, all future execution-policy fields are
unset and default-deny; this document itself is not an execution control.

## Continuous research behavior

Permitted future 24/7 jobs may poll approved read-only sources, record
availability/health, validate and freeze authorized data, compute causal regime
features, run scheduled offline experiments, and emit audit events. They must
stop or mark the affected scope unavailable on license expiry, provider errors,
rate-limit exhaustion, stale/malformed inputs, calendar mismatch, or integrity
hash change. They may not fall back silently to a source with different rights,
market coverage, adjustment, venue or timestamp semantics.

This contract is a testable specification for research code. It does not create
a live execution path or grant an LLM authority.