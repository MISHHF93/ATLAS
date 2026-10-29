# ATLAS master spec

This file is the product boundary. The explanation of the platform is [the README](../README.md). The repository is [github.com/MISHHF93/ATLAS](https://github.com/MISHHF93/ATLAS), checked out at `C:\Users\borah\ATLAS-main`.

## Product

ATLAS (Autonomous Trading, Liquidity, Allocation & Strategy Intelligence) is founder-owned software for market research and paper supervision. The paper control plane in this tree (`ActionableControlPlaneEngine`) can authorize a paper order after an operator deposit, inside free cash.

The first releasable product is software. It researches markets and can later show a read-only view of a venue the customer already uses. Customer custody, deposit addresses, live withdrawals, and changes to live venue orders stay unimplemented until counsel, a licensed partner, and written provider approval all exist. A software subscription is not a trading deposit.

The founder retains proprietary source, algorithms, strategy logic, data models, and model weights. An infrastructure retainer does not transfer that ownership and does not grant discretion over orders or signing keys.

## Two planes

Research and authorization are different.

- A language model may classify observations and draft a research note. In this tree that model is Gemini, on the paid tier, with no tools attached.
- Local research models are stored. The evolution hand has not passed `evo8-strict-1` and cannot order. Naive last-value and zero-return baselines also exist. No model in this tree is eligible to order.
- A research note and a forecast are stored records. Neither is an order.
- Deterministic services alone may authorize, size, and release an order. Those services must run when every model process is down.
- Gemini is absent from the order path, the risk path, and the kill switch.
- `confidence` on a research note is uncalibrated. It does not enter a combiner and it does not size a position.
- Forecast `execution_permission` defaults to `none`. A missing evaluation gate leaves it there.

## Money records

These eight records stay separate. One is not updated by copying another.

1. Software subscription.
2. Broker account.
3. Exchange account.
4. User external wallet.
5. Custodian, only if a later review engages one.
6. Prop-firm rules. The firm account is not an ATLAS customer balance.
7. Founder treasury, outside customer tables.
8. Future customer funds, only as a double-entry ledger reconciled to a regulated provider.

A mutable balance column is forbidden for customer funds. A read-only snapshot carries its source, an as-of timestamp, and a label that it is not the book of record. A broker profit is not an ATLAS wallet balance.

The only wallet shape allowed in a design is the user signing in a wallet they control. That design is not built. ATLAS-operated custody is rejected. An agent wallet that signs while the user is offline is rejected.

## Markets and models

ATLAS is not limited to one symbol or one interval in its design. The running desk reads confirmed bars from the feed store. Version 0.1.0 also shipped invented fixture candles for `BTC-USD` at `1h` so a read-only route could be tested. Those fixtures are not the live chart source.

No model in this tree is a universal predictor. Eligibility is per instrument and per horizon, after a human approval and an evaluation against a naive baseline on a point-in-time, costed sample. Uncontrolled live weight updates are forbidden.

TimesFM 3.0 downloaded weights are non-commercial and are not a dependency. Moirai 2.0 is CC-BY-NC-4.0 and is not a dependency. Chronos-2 may be tried later only after its downloaded license file is confirmed Apache-2.0. OpenAI is not a dependency. xAI may be added later as a second narrator over HTTP. It is not in this tree.

## Venue and prop rules

Live orders stay on the venue’s own adapter. A research connector is not an execution bus. Unknown prop-firm automation stays disabled. ATLAS does not evade firm rules and does not disguise automation. Unknown order status is reconciled before any retry.

## Jurisdiction

The operating entity’s country is unknown. Research notes may discuss Canada, the United States, the European Union, and the United Kingdom. Those notes are not a domicile, a registration, or legal advice. A missing permission row denies the feature. Hiding a button is not the control.

## This repository

Checked out at `C:\Users\borah\ATLAS-main` from `https://github.com/MISHHF93/ATLAS.git`, branch `main`. Decision 44 in [architecture/DECISIONS.md](architecture/DECISIONS.md) records that identity. The 2026-10-19 path `C:\Users\borah\ATLAS` is not present on this machine.

The tree includes a paper control plane, an append-only paper ledger, a research terminal, and stored research genomes. Paper orders, paper closes, and paper withdrawals stay inside that ledger. The research hand cannot buy or sell.

The version 0.1.0 scaffold also includes `GeminiResearchProvider` (mocked tests, paid-tier gate) and read-only health, capability, and research demo routes. The capability route reports only adapters registered in this process.

No module here custodies customer funds, issues a deposit address, or submits an order to a live broker. The Alpaca adapter, when configured, talks only to the paper endpoint.


## Universal AI ecosystem directive — 2026-10-19

ATLAS now also targets universal AI model orchestration, training, evaluation and
forecasting across permitted instruments, sampling resolutions, horizons and
strategy families. Universal means extensible interfaces, not universal accuracy.
The implementation and remaining integrations are specified in
[UNIVERSAL_AI_ECOSYSTEM.md](architecture/UNIVERSAL_AI_ECOSYSTEM.md), with dated
official-source evidence in [AI_ECOSYSTEM.md](research/AI_ECOSYSTEM.md).

This directive allows isolated offline research infrastructure to proceed before
any separate live-broker audit. The checkout path recorded on 2026-10-19 as
`C:\Users\borah\ATLAS` is not present on this machine. The paper control plane
is in this tree. Live broker execution is not.
Earlier milestone sequencing still applies to live connectors and live execution.

Providers advertise only implemented capabilities. Gemini remains the preferred
generative research provider, behind a replaceable protocol. Training, inference,
embedding, retrieval and model registry use separate typed contracts. Hosted
inference support never implies training access or commercial weight rights.

Dataset/feature lineage, model revisions, held-out evaluation and explicit
instrument/horizon approval are required. Unknown prices are unknown, not zero.
Online feature updates do not authorize weight changes. Retraining produces a
challenger, never an automatic production deployment. Whale features need
point-in-time provenance and incremental-value tests. Research signals retain
`execution_permission: none`; deterministic control alone can authorize future
execution. No LLM overrides risk or a kill switch.

## Continuous research and regime awareness

The long-term research target is continuous operation over two distinct
evaluation tracks: a named competition's actual rulebook and an independently
specified open-market instrument/horizon. They do not share score claims. The
research plane may schedule read-only collection, quality monitoring, causal
regime features and offline experiments 24/7; this does not imply autonomous
trading or a running scheduler in this repository.

Regime labels must be versioned, reproducible, and built only from observations
available at the evaluation time. Volatility, session/calendar, liquidity,
macro/event and asset-class differences are candidate dimensions, not evidence
of predictive value. Keep an explicit unknown regime where inputs are
insufficient. The [Research Operating Contract](architecture/RESEARCH_OPERATING_CONTRACT.md)
specifies research gates and the future deterministic policy fields. Numeric
execution limits remain unset until a competition rulebook, venue and audited
execution source supply the required evidence. Unknown policy fields default
deny; this spec does not implement or authorize an order path.

External MCP/data services are read-only research inputs only. Tool annotations
do not establish data rights or enforce safety. See the
[MCP/data integration review](research/MCP_DATA_INTEGRATION.md); no listed MCP is
currently connected or pre-approved for freezing/training.


## Dual-Track Prop Trading, US Stock Desk & Enterprise Data Warehouse — 2026-10-20

ATLAS operates visually and programmatically as a specialized **Dual-Track Proprietary (Prop) Trading & U.S. Stock Trading Platform**:

1. **Open-Market U.S. Stock & ETF Track (`open_market`)**: Covers NYSE Arca & Nasdaq equities and ETFs (`SPY`, `NVDA`, `AAPL`, `MSFT`, `QQQ`, `TSLA`) with regular-session calendars (`09:30–16:00 ET`), SEC EDGAR as-filed XBRL facts (`acceptance_time <= as_of`), and SIP/Polygon/Databento market data feeds.
2. **Prop Competition & Funded Challenge Track (`competition`)**: Covers prop-firm evaluations and 24/7 liquid competition markets (`BTC-USD`, `ETH-USD`, `SOL-USD`) under hard deterministic `TradingRuleBook` constraints (`4.0%` daily loss circuit breaker, `8.0%` trailing drawdown floor, `<= 35%` single-day profit consistency gate, `>= 5` minimum trading days, per-trade fractional risk caps, and mandatory stop-loss distances).
3. **Enterprise API Data Warehouse & Dual-Mode Charts (`/warehouse` & `/market`)**: Pairs **Google Cloud BigQuery & BigQuery Analytics Hub** (Google's institutional financial data warehouse, distinct from website-only Google Analytics GA4), **DuckDB + ZSTD Parquet Local PIT Lakehouse**, **Databento L1/L2/MBO**, **Polygon.io**, **Coinbase Public Exchange Live API**, and **ClickHouse / TimescaleDB** with a **Dual-Mode Institutional Chart Engine** (**ATLAS PIT + Forecast Fan SVG** and **TradingView Live Internet Charts**). All data warehouse and research outputs preserve `execution_permission: none`.
4. **Institutional Microstructure, Optimal Execution & Anti-Gravity Self-Training Engine**:
   - **Microstructure & Whale Order Flow (`src/atlas/marketdata/microstructure.py` & `src/atlas/features/toxicity.py`)**: Implements rolling **Kyle's Lambda ($\lambda$)**, **Volume-Synchronized Probability of Informed Trading (VPIN)**, **Multi-Level Order Flow Imbalance (OFI)**, and causal **Hawkes Self-Exciting Intensity ($\lambda(t)$)** (`execution_permission: none`).
   - **Almgren-Chriss Optimal Execution (`src/atlas/execution/tactics/optimal.py`)**: Computes discrete child-order execution schedules $x_j = X \frac{\sinh(\kappa (T - t_j))}{\sinh(\kappa T)}$ balancing temporary/permanent impact against volatility risk (`execution_permission: none`).
   - **Anti-Gravity Autonomous Self-Training (`src/atlas/ai/models/self_training.py`)**: Implements **Triple-Barrier Labeling** ($\pm k \cdot \text{ATR}$, vertical expiration), **Prop-Aligned Objective Loss** $\mathcal{L}(\theta)$, and **Purged & Embargoed Walk-Forward Out-of-Sample Gating** with zero lookahead leakage (`execution_permission: none`).
   - **VPIN-Aware Deterministic Control Plane (`src/atlas/control/rules.py` & `engine.py`)**: Automatically widens mandatory stop distances when VPIN exceeds `vpin_widening_threshold` (`0.45`) and enforces an adverse-selection quote pause when VPIN reaches `vpin_pause_threshold` (`0.70`).
