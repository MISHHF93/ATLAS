# ATLAS — MASTER PRODUCT VISION & AUTONOMOUS TRADING INTELLIGENCE OBJECTIVES

## Your Mission

You are responsible for evolving ATLAS — Autonomous Trading, Liquidity, Allocation & Strategy Intelligence — into a world-class, institutional-quality, AI-powered quantitative research and autonomous trading platform.

We already have an existing repository, architecture, machine learning research infrastructure, trading workbenches, market data integrations, and deterministic risk control systems.

Your responsibility is to understand this existing foundation, discover what is missing, research the best available approaches, and develop the platform toward our ultimate vision.

We want to describe **what the platform must accomplish**, not dictate every technical implementation decision.

You are expected to exercise expert engineering judgment, challenge weak assumptions, compare alternatives, and build only what provides measurable value.

Our ambition is to create a proprietary AI trading intelligence ecosystem capable of operating across supported financial markets, participating in permitted proprietary trading evaluations, and eventually managing authorized automated trading strategies for individual users.

We do not expect guaranteed profitability. We expect scientific rigor, intelligent decision-making, measurable performance, strong risk management, and continuous improvement.

---

## OBJECTIVE 1 — Understand Financial Markets in Real Time

We want ATLAS to continuously observe and understand financial markets using reliable, authorized real-time and historical data.

The platform should recognize price movements, trading activity, liquidity conditions, volatility, market structure, momentum, and meaningful changes in supply and demand.

We want it to analyze supported asset classes, including:

- U.S. and international listed stocks and ETFs.
- Cryptocurrencies and eligible digital-asset markets.
- Futures and commodities.
- Foreign exchange.
- Options and other derivatives where appropriate.
- Additional financial instruments as legally and technically supported.

Each asset class should have its own trading calendars, market conventions, data requirements, and risk rules.

ATLAS must distinguish between complete and partial market visibility. Missing or delayed information must not be presented as comprehensive real-time intelligence.

Use independently licensed market data for machine learning and trading decisions. TradingView may provide professional chart visualization only within applicable licensing terms.

### Desired outcome

ATLAS continuously understands what is happening across its supported markets and provides timely, reliable, context-aware market intelligence.

---

## OBJECTIVE 2 — Build Proprietary Machine Learning Intelligence

We want ATLAS to develop sophisticated predictive capabilities using established machine learning technologies combined with our proprietary research.

Investigate and compare suitable approaches, including:

- XGBoost and LightGBM.
- Linear and statistical forecasting models.
- Random forests and other tree ensembles.
- PyTorch-based neural networks.
- Temporal sequence models and transformers.
- Regime-conditioned models.
- Probabilistic forecasting and calibrated classification.
- Reinforcement learning where the problem and evidence justify it.

We do not want to reinvent mature algorithms without a compelling reason.

We want proprietary intelligence built through our features, market understanding, training objectives, datasets, strategy research, model combinations, and evaluation methods.

Preserve and assess the custom models already present in ATLAS.

We want the system to discover which models perform best under different conditions rather than assume one model is universally superior.

### Desired outcome

ATLAS develops measurable predictive intelligence that can identify opportunities, estimate uncertainty, recognize its limitations, and outperform relevant simple benchmarks where evidence supports that conclusion.

---

## OBJECTIVE 3 — Identify Whale Activity and Institutional Market Behavior

One of our central goals is to understand how large market participants influence prices and liquidity.

We want ATLAS to investigate:

- Unusual executed trading volume.
- Significant buying and selling pressure.
- Order-flow imbalance.
- Liquidity absorption and replenishment.
- Order-book changes and depth.
- Institutional accumulation and distribution hypotheses.
- Large-trade clustering.
- Potential liquidity sweeps.
- Market impact and adverse selection.
- Volatility associated with large trading events.

Leverage existing ATLAS market microstructure research, including Kyle's Lambda, VPIN, multi-level OFI, Hawkes processes, and execution impact models.

Recognize that public market data generally does not identify the true owner or intent behind every trade.

ATLAS should distinguish observed evidence from inferred institutional behavior.

We want to know whether whale-related events genuinely help predict future price movements and under what market conditions.

### Desired outcome

ATLAS identifies meaningful liquidity events, estimates their potential consequences, explains the supporting evidence, and learns which patterns have demonstrated predictive value.

---

## OBJECTIVE 4 — Predict the Next Trading Opportunity

We want ATLAS to continuously evaluate whether a meaningful trading opportunity is developing.

It should estimate:

- Whether price is more likely to rise, fall, or remain within a range.
- The probability of relevant outcomes.
- Expected movement magnitude and uncertainty.
- The appropriate forecast horizon.
- Whether momentum is strengthening or weakening.
- Whether a potential reversal or breakout is developing.
- Whether the expected opportunity exceeds transaction costs and risk.
- Whether the market environment is suitable for the proposed strategy.

We want predictions across multiple horizons, including short-term, intraday, and longer-term opportunities where supported by the data.

The model must be able to recommend buying, selling, reducing exposure, holding, or doing nothing.

We do not want ATLAS to manufacture trades simply because it is running continuously.

### Desired outcome

ATLAS can identify a candidate opportunity and explain:

**What could happen, why it might happen, how likely it is, what could invalidate the prediction, and whether a trade is justified.**

---

## OBJECTIVE 5 — Develop a Diverse Quantitative Trading Strategy Ecosystem

We want ATLAS to investigate, implement, and scientifically evaluate established and emerging quantitative trading strategies.

Candidate strategy families include:

- Trend following and time-series momentum.
- Cross-sectional momentum.
- Mean reversion.
- Breakout and volatility expansion.
- Statistical arbitrage and relative-value trading.
- Liquidity and order-flow-based strategies.
- Whale-event continuation and reversal.
- Regime-adaptive trading.
- Market-neutral strategies.
- Event-driven strategies.
- ML-assisted trade selection.
- Execution optimization and transaction-cost reduction.

Research which approaches are appropriate for different markets, instruments, holding periods, and liquidity environments.

We want strategies to complement one another where evidence supports combining them.

A strategy should never be accepted merely because its historical backtest looks profitable.

### Desired outcome

ATLAS maintains a validated library of trading strategies with documented hypotheses, operating conditions, historical performance, risk characteristics, limitations, and deployment eligibility.

---

## OBJECTIVE 6 — Participate in Proprietary Trading Competitions

We want ATLAS to support proprietary trading challenges, funded-account evaluations, and legitimate trading competitions.

The platform should understand the objectives and constraints of each supported program.

These may include:

- Profit targets.
- Daily loss limits.
- Maximum drawdown.
- Trailing drawdown.
- Position limits.
- Leverage limits.
- Minimum trading days.
- Profit consistency requirements.
- Restricted trading periods.
- Permitted instruments.
- Automated trading permissions.
- Holding-period and overnight restrictions.

Rules must be configurable and versioned by provider, account, and program.

ATLAS should continuously monitor progress toward evaluation objectives while prioritizing compliance and capital preservation.

It should evaluate strategies based on their probability of meeting the permitted program objectives without violating the applicable rules.

Do not assume every competition permits AI, automated execution, third-party operation, or the same trading methods.

Do not circumvent competition restrictions, manipulate evaluation conditions, or exploit simulation defects.

### Desired outcome

ATLAS can research and simulate competition strategies, monitor account eligibility and progress, and participate automatically only where the provider expressly permits the intended activity and the account holder has authorized it.

The objective is sustainable, rule-compliant performance, not reckless pursuit of profit targets.

---

## OBJECTIVE 7 — Support Open-Market Autonomous Trading

Beyond competitions, we want ATLAS to support authorized trading through brokerage and exchange integrations.

Users should eventually be able to connect eligible accounts and define objectives such as capital preservation, controlled growth, conservative trading, or more aggressive strategies within permitted risk limits.

ATLAS should evaluate available opportunities, portfolio exposure, account restrictions, execution costs, and market conditions.

Autonomous operation should be bounded by explicit user permissions and independent risk controls.

We want to support manual trading, AI-assisted trading, simulated autonomous trading, and eventually authorized live autonomous trading.

Real-money autonomy must never be activated by default.

### Desired outcome

ATLAS becomes capable of operating approved trading strategies for eligible users, subject to verified regulatory, licensing, broker, security, and operational requirements.

---

## OBJECTIVE 8 — Build a Continuous Learning and Improvement System

We want ATLAS to learn from its observations, predictions, simulated trades, and realized outcomes.

The system should recognize when predictions succeed, when they fail, and what market conditions contributed to those results.

It should identify model drift, changing market regimes, unstable relationships, and deteriorating strategy performance.

We want an automated research lifecycle that can:

- Generate testable hypotheses.
- Build and validate datasets.
- Train challenger models.
- Compare competing strategies.
- Evaluate predictions against realized outcomes.
- Detect degradation.
- Recommend improvements.
- Maintain reproducible experiment histories.

Use strict point-in-time correctness, chronological out-of-sample evaluation, appropriate purging and embargoes, and realistic cost assumptions.

Continuous learning must not mean uncontrolled production self-modification.

Models must pass independent evaluation and approval requirements before deployment.

### Desired outcome

ATLAS becomes more capable through disciplined, evidence-based research while maintaining reproducibility, safety, and operational stability.

---

## OBJECTIVE 9 — Build a Realistic Market Simulation and Backtesting Laboratory

We want ATLAS to test trading hypotheses under conditions that resemble real markets as closely as the available data allows.

Historical simulations should account for relevant costs and constraints, including spreads, fees, slippage, latency, liquidity, market impact, partial fills, order types, and market sessions.

We want market replay capabilities that allow researchers to inspect how a strategy would have behaved during historical events.

The platform must distinguish hypothetical backtests, broker paper-trading results, and actual live execution performance.

It should record failed experiments as well as successful ones.

We want statistical safeguards against overfitting, data leakage, survivorship bias, and repeated strategy selection.

### Desired outcome

ATLAS can demonstrate whether a proposed strategy has credible out-of-sample value before risking real capital.

---

## OBJECTIVE 10 — Develop Portfolio-Level Intelligence

We do not want ATLAS to evaluate every trade in isolation.

It should understand how multiple positions, strategies, and markets interact.

We want intelligent analysis of:

- Correlated exposures.
- Portfolio concentration.
- Volatility and drawdown.
- Capital allocation.
- Leverage and margin.
- Liquidity constraints.
- Strategy diversification.
- Tail-risk scenarios.
- Portfolio rebalancing.
- Capacity and transaction-cost sensitivity.

ATLAS should recognize when individually attractive opportunities create unacceptable combined risk.

### Desired outcome

The platform makes decisions based on total portfolio health, not simply the confidence of an individual prediction.

---

## OBJECTIVE 11 — Preserve Independent Risk and Execution Authority

This is a non-negotiable architectural principle.

Preserve ATLAS's separation between AI research and deterministic trading authorization.

Machine learning models and LLMs may analyze markets, explain predictions, and propose candidate actions.

They must not independently bypass risk controls, access unauthorized accounts, or directly override execution permissions.

Preserve the ActionableControlPlaneEngine as the authoritative decision boundary.

We want strict controls for account exposure, losses, leverage, position sizing, market-data freshness, broker state, and emergency shutdown.

Unexpected failures should cause safe suspension of new risk-taking rather than uncontrolled execution.

### Desired outcome

ATLAS can operate autonomously within approved boundaries without granting unrestricted financial authority to AI models.

---

## OBJECTIVE 12 — Explain Every Important Decision

We want ATLAS to be understandable.

For every significant prediction or proposed trade, users should be able to inspect:

- The market conditions observed.
- The strategy generating the opportunity.
- The relevant model and version.
- The strongest supporting and contradicting evidence.
- Estimated probabilities and uncertainty.
- Expected trading costs.
- Applicable account and portfolio risks.
- The reason a trade was accepted, rejected, or skipped.
- The realized outcome when it becomes available.

We want clear explanations without pretending that feature attribution establishes causation.

### Desired outcome

Users can understand what ATLAS is doing, why it is doing it, and how well its decisions have performed.

---

## OBJECTIVE 13 — Create a Professional, Unified Trading Experience

We want ATLAS to feel like a sophisticated institutional trading terminal while remaining intuitive.

We want professional live charts, market intelligence, model forecasts, whale-event markers, strategy analytics, portfolio monitoring, execution status, and risk information presented coherently.

Do not overwhelm users with every available indicator or dataset.

Show the most decision-relevant information first, with deeper research available when needed.

We want a natural-language interface where users can describe objectives such as:

"Analyze the strongest momentum opportunities in U.S. stocks."

"Find potential institutional accumulation in liquid assets."

"Show me why the model expects a reversal."

"Evaluate whether this strategy could satisfy my prop evaluation rules."

"Simulate this strategy using conservative risk limits."

Translate these requests into validated, transparent operations.

Natural language must not bypass account permissions or risk policies.

### Desired outcome

A user can understand market conditions, investigate opportunities, and manage approved strategies without navigating disconnected technical systems.

---

## OBJECTIVE 14 — Build an Autonomous Research Assistant

We want an AI research assistant capable of helping develop and improve ATLAS.

It should be able to investigate relevant academic research, official technical documentation, established quantitative methods, and new machine learning approaches.

It should compare alternatives and identify potentially valuable improvements.

We want it to assist with research planning, experiment design, model evaluation, strategy documentation, and technical analysis.

The research assistant should distinguish established findings from unverified hypotheses.

It must not autonomously deploy unreviewed production code, promote live trading models, or change financial risk limits.

### Desired outcome

ATLAS has a research intelligence layer that accelerates innovation without sacrificing scientific rigor or operational control.

---

## OBJECTIVE 15 — Support Multiple Users and Accounts

We eventually want ATLAS to become a commercial-grade platform serving eligible individual traders and organizations.

We want secure account connections, user-specific strategies, isolated data, configurable permissions, audit trails, and appropriate subscription or licensing models.

The platform should distinguish between providing research software, providing trading signals, executing customer instructions, and managing investments.

These activities may have different regulatory requirements.

Do not assume that being non-custodial eliminates investment-adviser, broker-dealer, or other financial-services obligations.

### Desired outcome

ATLAS can scale into a secure, compliant, maintainable multi-user platform without compromising account separation, privacy, or founder-owned intellectual property.

---

## OBJECTIVE 16 — Build Operational Reliability and Security

We want ATLAS to operate reliably during normal and abnormal market conditions.

The system should handle:

- Market-data interruptions.
- Incomplete or stale data.
- Exchange and broker outages.
- Duplicate messages and order requests.
- Partial fills and rejected orders.
- Unexpected account-state changes.
- Model-serving failures.
- Excessive latency.
- Infrastructure restarts.
- Abnormal market volatility.
- Security incidents.

We want secure credential handling, least-privilege access, audit logging, monitoring, disaster recovery, and tested emergency controls.

### Desired outcome

ATLAS behaves predictably under failure and never relies on an AI model to improvise critical financial safety decisions.

---

## OBJECTIVE 17 — Measure Genuine Success

We want every major capability to be evaluated against measurable evidence.

Machine learning success should include predictive accuracy, probability calibration, robustness, and stability.

Strategy success should include net-of-cost performance, risk-adjusted returns, drawdown, turnover, and consistency across unseen periods.

Execution success should include fill quality, slippage, reconciliation accuracy, and operational reliability.

Competition success should include rule compliance, evaluation completion rates, and account survival across sufficiently representative simulations and permitted live evaluations.

Product success should include usability, reliability, security, and the ability of users to understand and control the system.

No single metric should be treated as proof of success.

### Desired outcome

ATLAS can demonstrate what works, what does not, and where improvement is required.

---

## OBJECTIVE 18 — Define What We Do Not Want

We do not want:

- Guaranteed-profit claims or unrealistic accuracy promises.
- An AI that trades continuously without sufficient evidence.
- A black-box model with unrestricted brokerage authority.
- Overfitted strategies optimized only for historical results.
- Training datasets contaminated by future information.
- Unauthorized scraping or use of restricted market data.
- Competition-rule circumvention.
- Uncontrolled self-learning or unreviewed model promotion.
- Unnecessary duplication of existing repository functionality.
- Excessive dashboards, indicators, and disconnected tools.
- Dozens of installed ML frameworks without demonstrated value.
- Unreliable signals presented with artificial certainty.
- Live-money trading activated without explicit approval.
- Security shortcuts or exposure of customer credentials.
- Unverified claims that software tests prove profitability.
- Complexity added without a measurable product benefit.

We want simplicity at the user level, sophistication behind the scenes, and evidence throughout the system.

---

## OBJECTIVE 19 — Research and Select the Best Technical Approaches

You have permission to research and recommend technologies, algorithms, architectures, and engineering methods.

Do not assume that any particular framework must be used.

Evaluate mature open-source and commercial solutions against the needs of ATLAS.

Prefer technologies with strong documentation, maintainability, security, appropriate licenses, and demonstrated suitability.

Investigate whether existing ATLAS capabilities should be extended before introducing new systems.

Explain important trade-offs between accuracy, latency, cost, complexity, reliability, and maintainability.

Avoid building a proprietary replacement for a mature foundational technology unless there is a clear technical or strategic advantage.

### Desired outcome

ATLAS uses an appropriate combination of established technology and proprietary intelligence, selected through evidence rather than popularity.

---

## OBJECTIVE 20 — Evolve the Existing Repository Into the Finished Platform

Begin by understanding the existing ATLAS codebase.

Verify which features are functional, partially implemented, experimental, simulated, or documented only.

Do not assume that the existence of an endpoint, model, chart, or test proves production readiness.

Identify the most important gaps between the current repository and the objectives above.

Create a prioritized development roadmap.

Implement improvements incrementally, preserving working functionality and architectural boundaries.

Each increment should have measurable acceptance criteria, appropriate automated tests, reproducible results, and clear documentation.

Avoid unnecessary rewrites.

Keep the system coherent as it grows.

---

# ULTIMATE PRODUCT OUTCOME

We want a user to open ATLAS and encounter an intelligent trading environment that understands live markets, identifies meaningful opportunities, evaluates the likelihood of different outcomes, explains its analysis, and supports safe, authorized trading decisions.

We want ATLAS to research and learn from financial markets, continuously improve its validated predictive capabilities, and operate suitable strategies across supported asset classes.

We want it to support legitimate prop trading competitions and open-market brokerage accounts, recognizing that these environments have different rules, permissions, and risk objectives.

We want it to become capable of bounded autonomous trading while preserving deterministic risk authority and human control over deployment permissions.

We want the platform to become more intelligent without becoming unnecessarily complicated.

We want proprietary value to emerge from our market research, data quality, feature engineering, strategy combinations, execution intelligence, and disciplined learning system.

We want a product that is reliable, explainable, scalable, secure, and genuinely useful.

# YOUR FIRST RESPONSIBILITY

Before implementing major changes:

1. Study the actual ATLAS repository.
2. Verify its current capabilities and limitations.
3. Research relevant technologies and quantitative methods.
4. Identify missing capabilities and unnecessary complexity.
5. Compare candidate machine learning and trading strategy approaches.
6. Propose a coherent target architecture.
7. Prioritize improvements by measurable value and technical dependencies.
8. Establish testable acceptance criteria.
9. Recommend the first valuable implementation milestone.
10. Implement and verify the first safe, reversible increment.

Separate verified findings, research-backed recommendations, hypotheses, and assumptions.

Do not claim success without evidence.

Do not enable live-money trading without explicit approval.

**The mission is to build ATLAS into a continuously improving, evidence-driven trading intelligence platform that knows when to act, when not to act, and how to operate safely within its authority.**

**Build the intelligence. Validate the strategies. Protect the capital. Simplify the experience. Prove the outcomes.**