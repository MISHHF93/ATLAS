# Target state

ATLAS is aimed at a founder-owned platform that researches markets and may later
supervise venues the customer already uses. The control plane is deterministic.
The research plane may operate continuously and can be offline without stopping
risk checks. Research operates distinct competition and open-market evaluation
tracks; it does not gain order authority. The full definition is in the
[README](../../README.md).

The initial version 0.1.0 was the scaffold; the universal research foundation now extends it. The table below is the destination, not a list of running services.

## Capabilities

Seven product capabilities, built as modules inside one Python process until a measured load requires a split.

| Capability | Responsibility | Authority |
| --- | --- | --- |
| Data Hub | Exchange, broker, macro, and on-chain feeds | Read |
| Quant Lab | Licensed point-in-time features, causal regime analysis, models, walk-forward backtests and experiments on frozen data | Research |
| Gemini Research | Notes from screened context. No tools on the call | Research |
| Prop Intelligence | Firm rules and account eligibility | Policy. Unknown firm denies automation |
| Risk and Portfolio Control | Drawdown, exposure, circuit breakers | Authorize |
| Execution and Reconciliation | The existing venue adapters, orders, fills, positions | Execute, after the live-repo audit |
| ATLAS Terminal | Charts, research panels, portfolio, prop status | Display. Order controls only on a desktop flow with step-up authentication, and only after the gates in the master spec |

Gemini sits only in Gemini Research. Risk and execution do not import a language-model client.

A forecast orchestrator, when it is built, emits a research record. It does not override a hard risk rule. Models are compared with a naive forecast before any of them is eligible. Eligibility is per instrument and per horizon.

Continuous research may collect approved data, assess freshness, compute
versioned regime features and evaluate immutable challengers. Every run must
retain track, instrument, horizon, calendar, dataset, regime and protocol
identity. Regime-based slicing does not imply live regime switching. Missing
source rights, calendar or numeric execution-rule values leave the relevant
capability unavailable; unknown values default deny. See the
[research operating contract](RESEARCH_OPERATING_CONTRACT.md).

## First releasable software

The first release a customer can be offered is research software, plus a read-only view of an account the customer already holds, after the live repository has been audited and the venue allows that read. That release has no custody, no withdrawal, no deposit address, and no change to live orders.

The first customer is the founder. The first outside customer, if any, is an advanced retail trader or a quant developer buying analytics software. Prop participants, desks, funds, and brokerages come later because they pull in further regulatory duties.

## Storage

PostgreSQL for operational records. Parquet and DuckDB for research. Neither is provisioned in version 0.1.0. Customer funds, if ever allowed, use a double-entry ledger in the operational store, reconciled to the provider. The eight money records in the master spec stay in separate books.

## Terminal

The terminal target is Next.js and TypeScript. The current read-only research
terminal displays invented fixture candles, local baseline discovery, a synthetic
approval demo and integration status. Real venue data, account linking and all
order controls remain absent pending their separate gates.

Later visual work uses Lightweight Charts for the terminal chart and ECharts for dashboards. TradingView widgets stay a hosted reference. Advanced Charts waits until a written license allows a private or paid terminal. Tailwind and an accessible component set start with the visual system. The target is WCAG 2.2 AA. Every market number shows its source and its as-of time. A stale panel disables actions. Mobile is status, alerts, and a read-only chart.

## Model tier

Founder compute is a CPU, a naive baseline, then one tree model, plus paid Gemini notes. A local Chronos-2 experiment waits on the license file. Managed cloud training and BigQuery-hosted TimesFM wait on counsel and a measured need. TimesFM 3.0 weights and Moirai 2.0 stay out.

## Explicitly later

Identity, software billing, a user-signed wallet view, payout feasibility, regulated deposits, prop automation for a named firm, and an enterprise API. Each one waits on the audit or on a written legal and vendor gate. Redis, NATS, and Kubernetes wait on a measured need.


## Expanded model ecosystem

The [universal AI architecture](UNIVERSAL_AI_ECOSYSTEM.md) is the current detailed
model-system target and implementation map. It introduces capability discovery,
provider reliability controls, instrument/horizon metadata, research-only forecast
orchestration, evaluation, training manifests and experiment history. This work is
independent of live-engine integration. Provider connectors, actual training,
calendar services, validated ensembles and production deployment are separate
remaining deliverables. See [current state](CURRENT_STATE.md).
