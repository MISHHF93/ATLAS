# ATLAS evolution roadmap (evo-14 to evo-21)

Written 2026-10-29 (Toronto time). Research-only document: paper trading only, ML `execution_permission` stays `none`, `risk_policy.yaml` is not touched,
free official data only, keys stay unset and show "Needs verification". **Nothing here is a profitability claim.** Where a source says something about returns it is
quoted as evidence about methods, not a forecast for ATLAS. Facts marked **(verify)** come from a secondary source or a search summary and must be re-read on the
official page before code depends on them.

## 0. Persona and goals

The primary user is a **Canadian resident who trades any market globally** (US, TSX, Europe, Asia, FX, crypto, metals) and **keeps trading while travelling**.
Goals, each mapped to a roadmap item below:

| # | Goal | Item |
|---|---|---|
| G1 | An ML model that learns from the live data ATLAS already stores, validated strictly (no leakage, no selection bias) | evo-14 |
| G2 | Follow-the-sun: know which markets are open, each in the user's local time and the market's own time (paper only) | evo-15 |
| G3 | The ML understands the broker account and sizes within the unchanged risk policy; small accounts handled honestly | evo-16 |
| G4 | Free, Canada-eligible data for TSX and global markets; CAD base currency with FX costs visible | evo-17 |
| G5 | Observable, reproducible ML (experiments, registry, drift) | evo-18 |
| G6 | Safe remote access (travelling) and a multi-user SaaS that can be launched responsibly in Canada | evo-19, evo-20 |
| G7 | A calm, accessible trading UI | evo-20 |
| G8 | Optional extra signal sources (foundation-model embeddings) | evo-21 |

## 1. What already exists (so the roadmap does not redo it)

Read from `src/atlas/ai/ml/`: triple-barrier meta-labels per detected price-action setup (`dataset.py`), purged + embargoed expanding walk-forward (`cv.py`),
isotonic/Platt calibration and split-conformal abstention (`calibration.py`), Brier/logloss/ECE/AUC, Deflated Sharpe and PBO (`metrics.py`), HGB/logit models with xgb/lgbm challengers
(`train.py`), PSI and ADWIN drift (`drift.py`), a niche archive and evolution search (`niche_archive.py`, `evolution.py`), a model registry with pre-declared gates (`registry.py`),
and chart predictions (`chart_prediction.py`). Gaps this roadmap targets: the training universe is a fixed list, labels exist only for detected setups, no generic volatility-scaled
labelling or forward-return targets, no cross-asset or regime features, no online (adaptive) conformal, no per-market session clocks, no broker-state adapters beyond phase 1.

## 2. Roadmap table (ranked)

Effort: S under 1 day, M 1-3 days, L about a week. Risk is the main way the item can go wrong.

### evo-14: Model spec + all-asset training pipeline (G1) , keys: none
* **Technique.** Generic volatility-scaled triple-barrier labels at CUSUM-sampled events plus forward-return targets; features v2 (multi-timeframe, cross-asset, regime, session/VWAP, read-only account features);
  gradient-boosted baseline (HGB, LightGBM challenger); adaptive conformal intervals; walk-forward with purge + embargo; DSR and PBO gates; failures labelled "research / below gate".
* **Sources.** Lopez de Prado, *Advances in Financial Machine Learning* ch. 3 (labels), 7 (purged CV): https://www.oreilly.com/library/view/advances-in-financial/9781119482086/c03.xhtml ;
  Bailey & Lopez de Prado, Deflated Sharpe: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 ; Bailey et al., PBO: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf (J. Computational Finance 20(4), doi 10.21314/jcf.2016.322) ;
  Gibbs & Candes, ACI: https://arxiv.org/abs/2106.00170 ; Zaffran et al., AgACI: https://proceedings.mlr.press/v162/zaffran22a.html ;
  LightGBM early stopping: https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.early_stopping.html ; full spec in `ATLAS_MODEL_SPEC.md`.
* **Effort / risk.** L / overfitting and leakage. Mitigation: pre-declared gates, trial registry for DSR, leakage tests that perturb the future and assert features and labels are unchanged.
* **Acceptance test.** (1) Replacing all bars after a cut leaves features and labels before the cut bit-identical; (2) purged folds have zero label overlap with test windows;
  (3) every instrument with stored data is trained or listed with an explicit skip reason; (4) a pure-noise series fails the gate (DSR below threshold) in a seeded test;
  (5) no model is shown as eligible unless all gates pass; the rest read "research / below gate".

### evo-15: Global sessions and follow-the-sun clocks (G2) , keys: none
* **Technique.** A market registry (venue, IANA time zone, session segments, holiday calendar). Use `exchange_calendars` (ISO MIC codes such as XTSE, XLON, XTKS; regular sessions and holidays)
  with TSX's own published 2026 holiday list as a cross-check. UI shows the user's local time and each market's time side by side; a "what is open now / next to open" strip; paper-only scheduler
  that runs ML refresh per session.
* **Sources.** exchange_calendars: https://pypi.org/project/exchange_calendars/ , https://github.com/gerrymanoim/exchange_calendars ; TSX hours: https://tsx.com/en/trading/calendars-and-trading-hours/trading-hours ;
  TSX 2026 calendar: https://www.tsx.com/en/trading/calendars-and-trading-hours/calendar (regular 09:30-16:00 ET; closed 2026-01-01, 02-16, 04-03, 05-18, 07-01, 08-03, 09-07, 10-12, 12-25, 12-28; early close 2026-12-24).
* **Effort / risk.** M / holiday and DST edge cases; calendars lag real changes. Mitigation: compare against official calendars in a test; the UI shows the data source and date of the calendar.
* **Acceptance test.** For XTSE, XNYS, XLON, XTKS, 24/7 crypto and 24/5 FX: is_open matches the calendar at fixed instants around DST changes and holidays; local-time display is correct for a user in Toronto and a user travelling (browser zone changes).

### evo-16: Account-aware sizing, phases 2-3 of `ATLAS_ACCOUNT_AWARENESS.md` (G3) , keys: none for tests; Verify for live paper reads
* **Technique.** Broker-state adapters for IBKR paper (Client Portal Web API `summary` and `ledger`), Questrade practice (OAuth, `/v1/accounts`), OANDA practice (already phase 1), each idle until Verify.
  Then a tighten-only sizing module (fractional Kelly cap, volatility target, drawdown governor, feasibility gate) called from the control-plane pre-check. Property tests prove it never exceeds policy.
* **Sources.** IBKR paper accounts and Web API: https://www.interactivebrokers.com/docs/web-api/authentication/paper.md ; IBKR Canada welcome (every new account includes a paper account): https://www.interactivebrokers.ca/en/accounts/welcome-individuals.php ;
  Questrade API authorization (practice login `practicelogin.questrade.com`, manual tokens expire after 7 days **(verify)**): https://www.questrade.com/api/documentation/authorization ;
  OANDA v20: https://developer.oanda.com/rest-live-v20/development-guide/ ; Kelly and drawdown literature as cited in `ATLAS_ACCOUNT_AWARENESS.md`.
* **Effort / risk.** L / mis-mapped fields; a sizing bug could oversize. Mitigation: fixture tests from official response shapes, hypothesis tests (size <= policy cap, <= buying power, never below broker minimum, rounded down), no write methods.
* **Acceptance test.** 10^5 random inputs: size never exceeds `risk_policy.yaml` caps; zero network calls before Verify; live hosts refused.

### evo-17: Canada-eligible data, multi-currency CAD base, FX costs (G4) , keys: Massive/Alpha Vantage optional (Needs verification)
* **Technique.** Provider chain stays: Massive (formerly Polygon.io) Stocks Basic, then Alpha Vantage. Massive free: end-of-day, two years of aggregates, 5 requests/minute **(verify on plan page)**; Alpha Vantage free key: 25 requests/day; Bank of Canada Valet for CAD FX (no key; cache daily data and back off);
  TSX: instruments only where an official free source exists, otherwise labelled "no free official data". Accounts report in CAD with per-currency balances; show FX conversion cost as a separate line.
  Tax reporting helper (data export only, **no tax advice**): CRA says convert each component of a foreign-currency capital gain at the Bank of Canada rate, with listed-stock proceeds at the settlement date.
* **Sources.** Massive: https://massive.com/stocks , https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have ; Alpha Vantage: https://www.alphavantage.co/support/#api-key , terms https://www.alphavantage.co/terms_of_service/ ;
  Bank of Canada Valet: https://www.bankofcanada.ca/valet-api-how-to/ ; CRA: https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/completing-a-tax-return/personal-income/line-12700-capital-gains/calculating-reporting-your-capital-gains-losses.html ,
  https://www.canada.ca/en/revenue-agency/services/tax/technical-information/income-tax/income-tax-folios-index/series-5-international-residency/series-5-international-residency-folio-4-foreign-currency/income-tax-folio-s5-f4-c1-income-tax-reporting-currency.html
* **Effort / risk.** M / free-tier limits and licence terms (Alpha Vantage free use is for private individual use; a multi-user SaaS needs a commercial plan or another source). Mitigation: each provider's licence stated in the UI, SaaS use blocked until reviewed.
* **Acceptance test.** With no keys: every card says "Needs verification", nothing fabricated; with a recorded fixture, bars load and rate limits are respected (a test asserts at most 5 calls per minute for Massive); CAD-converted P&L matches a hand-computed example using the dated Bank of Canada rate.

### evo-18: MLOps: experiments, registry, drift (G5) , keys: none
* **Technique.** Log every run (params, data hash, code SHA, metrics, gates) to the existing registry and optionally to MLflow tracking / Model Registry (open source); Evidently-style drift reports for feature distributions and prediction/label drift
  alongside the existing PSI and ADWIN; scheduled retrain with model cards; rollback to the previous eligible version.
* **Sources.** MLflow tracking and registry: https://mlflow.org/docs/latest/ml/tracking/ , https://mlflow.org/docs/latest/ml/model-registry/ ; Evidently: https://github.com/evidentlyai/evidently .
* **Effort / risk.** M / tool sprawl. Mitigation: local-first, MLflow optional, no cloud dependency.
* **Acceptance test.** A run is reproducible from its stored manifest (same data hash and seed gives identical metrics); an injected shifted feature raises drift status; rollback restores the earlier version.

### evo-19: Secure remote access while travelling (G6) , keys: none
* **Technique.** Hosted deployment option vs laptop-only; session and device management per OWASP ASVS 5.0 and the Session Management cheat sheet (idle timeout, absolute lifetime, list and revoke active sessions and devices, terminate other sessions after credential change);
  re-authentication before sensitive actions; broker 2FA guidance in-app: activate a non-SMS second factor before travelling (IBKR: IBKR Mobile Authentication, passkeys; Questrade: Push Approval works over Wi-Fi without a local SIM, plus SMS, voice and authenticator apps).
  Broker keys stay read-only paper keys held in the vault; no live trading.
* **Sources.** OWASP ASVS V7: https://asvs.dev/v5.0.0/V7-Session-Management/ ; cheat sheet: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html ;
  IBKR Canada secure login: https://www.interactivebrokers.ca/en/general/secure-login.php ; Questrade sign-in approval and push approval: https://invest.questrade.com/learning/questrade-basics/account-profile-and-security/sign-in-approval-a-secure-and-convenient-way-to-protect-your-account ,
  https://www.questrade.com/learning/using-questrade/push-approval-a-secure-and-convenient-way-to-protect-your-account ; whether each broker restricts logins from abroad must be confirmed from the broker's own terms **(verify)**; a Questrade staff reply (2023) reportedly confirms travel access (community thread only).
* **Effort / risk.** L / credential exposure when hosted. Mitigation: threat model before hosting; CSP nonce stays; secrets only in env/vault; audit log.
* **Acceptance test.** Active-session list shows device and last use; revoking a session invalidates it within one request; password change kills other sessions; idle and absolute timeouts enforced by test with a fake clock.

### evo-20: SaaS launch readiness (Canada) and trading-UI polish (G6, G7) , keys: Stripe stays test-only
* **Technique.** (a) Regulatory screen **before charging**: a paid subscription that delivers trading signals or advice may trigger adviser or dealer registration in Canada if carried on as a business (regularity, compensation, solicitation, holding out); general non-tailored advice may qualify for an exemption with disclosure;
  facilitating or copying users' trades is trading activity. Keep ATLAS as software and research tools, no personalised recommendations, no copy-trading, and get legal advice before launch. (b) GST/HST: Canadian businesses use the small-supplier test (registration once taxable revenue exceeds CA$30,000 over four consecutive calendar quarters);
  non-residents selling digital products to Canadian consumers have a CA$30,000 threshold under the simplified regime. (c) PIPEDA: safeguards proportionate to sensitivity; mandatory breach reporting and 24-month breach records. (d) UI: calm default view, up/down not by colour alone, WCAG 2.2 AA contrast, pause on live feeds, announce only threshold alerts.
* **Sources.** CSA/CIRO Staff Notice 31-369: https://www.securities-administrators.ca/wp-content/uploads/2025/12/CSA-Finfluencer-Staff-Notice_ENG.pdf ; ASC registration overview: https://www.asc.ca/en/registrant-and-market-regulation/registrant-toolkit/getting-registered ;
  CRA GST/HST digital: https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/digital-economy-gsthst/find-out-need-register/cross-border-threshold-amounts.html , https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/when-register-charge.html ;
  PIPEDA: https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/principles/p_safeguards , https://laws-lois.justice.gc.ca/eng/acts/p-8.6/section-10.1.html ;
  accessible financial charts: https://www.accessible-data-interfaces.com/virtualization-charts-dynamic-data-displays/chart-type-specific-patterns/accessible-candlestick-and-financial-charts/ , https://design.morningstar.com/systems/data-visualization/guidelines/accessibility .
* **Effort / risk.** L / regulatory misjudgement; this document is not legal or tax advice. Mitigation: written legal review gate in the launch checklist; disclaimers; no live-trading features.
* **Acceptance test.** Launch checklist file with each item owner-signed; automated UI checks (axe or similar) report no AA contrast failures on main pages; every up/down indicator has a non-colour cue.

### evo-21: Optional foundation-model embeddings and quality-diversity search (G8) , keys: none (free weights)
* **Technique.** Frozen embeddings or zero-shot quantile forecasts from open-weight time-series foundation models as extra features, never as a stand-alone signal; compare against a random-walk and the evo-14 baseline in the same purged folds.
  A recent benchmark on five liquid US equities reports that pretrained models rank well but gains over a random walk are small and sparse, so inclusion must be earned by the gates.
  Extend the existing niche archive toward MAP-Elites (archive of high-performing, behaviourally different strategies).
* **Sources.** Chronos-2 (open weights): https://huggingface.co/amazon/chronos-2 ; TimesFM 2.5 (Apache-2.0 card): https://huggingface.co/google/timesfm-2.5-200m-pytorch ; check each model card's licence before use (Moirai weights are reported as non-commercial **(verify)**);
  benchmark: https://huggingface.co/papers/2606.27100 ; MAP-Elites: https://arxiv.org/abs/1504.04909 ; regime detection, Markov-switching: https://www.statsmodels.org/stable/generated/statsmodels.tsa.regime_switching.markov_regression.MarkovRegression.html .
* **Effort / risk.** L / compute on the laptop, licence, no real lift. Mitigation: optional dependency, skipped cleanly when weights absent, kept only if it improves OOS net-of-cost metrics through the gates.
* **Acceptance test.** With weights absent the pipeline runs unchanged; with weights present the embedding model is a trial counted in DSR; it is promoted only if all gates pass.

## 3. Persona facts to build around (Canada, global, travelling)

| Topic | What the official pages say | Use in ATLAS |
|---|---|---|
| IBKR Canada | Every new account includes a Paper Trading account (simulated capital, real market data); paper has its own username; Web API users authenticate with the paper username. Non-SMS 2FA: IBKR Mobile Authentication, passkeys. | evo-16 adapter; evo-19 guidance |
| Questrade | Practice account and practice OAuth login; manual tokens expire after seven days **(verify)**; MFA options include Push Approval over Wi-Fi. | evo-16 adapter (practice only); evo-19 guidance |
| OANDA Canada | OANDA (Canada) Corporation ULC is CIRO-regulated; v20 practice host `api-fxpractice.oanda.com`; eligibility by province/residency must be read from OANDA's division page before relying on it **(verify)**. | evo-16 adapter exists (phase 1) |
| TSX | Regular 09:30-16:00 ET; pre-open 07:00; extended 16:15-17:00 ET; 2026 closures listed above. | evo-15 calendar |
| CRA | Report in CAD; Bank of Canada rate on the relevant date; listed-stock proceeds arise on settlement date. | evo-17 export helper only |

Sources: https://www.interactivebrokers.ca/en/accounts/welcome-individuals.php ; https://www.interactivebrokers.com/docs/web-api/authentication/paper.md ; https://www.questrade.com/api/documentation/authorization ;
https://www.ciro.ca/investors/choosing-investment-advisor/dealers-we-regulate/oanda-canada-corporation-ulc ; https://help.oanda.com/ca/en/faqs/oanda-division.htm ; https://tsx.com/en/trading/calendars-and-trading-hours/trading-hours .

## 4. Ranking rationale

1. evo-14 first: it needs no keys, uses data already stored, and the strict gates stop us from believing a noisy result.
2. evo-15 next: the user's central workflow (global, travelling) depends on knowing what is open, in which time zone.
3. evo-16 third: the ML must see the account; tighten-only sizing is the safest place to put risk logic.
4. evo-17 then evo-18: better inputs and better measurement of the model.
5. evo-19 and evo-20 before any external users; evo-21 last because published evidence on foundation models for returns is mixed.

## 5. Standing rules for every item

Paper only; `execution_permission` none; `risk_policy.yaml` unchanged; no secrets committed; free official data only; keys unset, shown as Needs verification; no force-push; kill by exact PID only; report out-of-sample, net-of-cost metrics only and never claim profitability.

## 6. Source list (returned by search or opened on 2026-10-29; Corsi cited from memory)

AFML ch.3: https://www.oreilly.com/library/view/advances-in-financial/9781119482086/c03.xhtml ; DSR: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 ; PBO: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf ; ACI: https://arxiv.org/abs/2106.00170 ; AgACI: https://proceedings.mlr.press/v162/zaffran22a.html ;
multi-step ACI: https://arxiv.org/abs/2409.14792 ; MAP-Elites: https://arxiv.org/abs/1504.04909 ; Chronos-2: https://huggingface.co/amazon/chronos-2 ; TimesFM: https://huggingface.co/collections/google/timesfm-release ;
TSFM finance benchmark: https://huggingface.co/papers/2606.27100 ; statsmodels Markov switching: https://www.statsmodels.org/stable/generated/statsmodels.tsa.regime_switching.markov_regression.MarkovRegression.html ;
Corsi (2009), A simple approximate long-memory model of realized volatility, J. Financial Econometrics 7(2), 174-196 (cited from memory; HAR-RV); MLflow: https://mlflow.org/docs/latest/ml/model-registry/ ; Evidently: https://github.com/evidentlyai/evidently ;
exchange_calendars: https://pypi.org/project/exchange_calendars/ ; Massive: https://massive.com/stocks ; Bank of Canada Valet: https://www.bankofcanada.ca/valet-api-how-to/ ; OWASP: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html .
