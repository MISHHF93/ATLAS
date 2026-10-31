# Changelog

## 2026-10-30: leftover venue cleanup, stale data and models deleted
- Remaining Binance / Hyperliquid references removed: `CRYPTO_SOURCES` is Coinbase + Kraken only; the perp catalog rows are labelled COINBASE and seeded with an empty state (price 0.0, shown as "no data") instead of placeholder prices; filler venues are Coinbase / Kraken; Hyperliquid and CCXT Pro labels removed from the live-stream status and the terminal/workbench UI (Kraken replaces Hyperliquid as the second live provider); the default CCXT exchange id is `kraken`. The `excluded_venues` safety records stay.
- Stale data deleted (to save space; nothing from Coinbase/Kraken/Alpaca was touched): 2,720,984 Binance/OKX `bar_revisions` rows, 66 `last_quotes` and 11,606 `ingest_log` rows from the feed store (batched, ingest untouched; free pages are reused, no VACUUM), the 15 `atlas-meta-crypto-*` registry models and the 4 `directional/crypto-*` model dirs trained on Binance-sourced data (about 380 MB on disk). Pre-switch horizon models under `var/ml/horizons` stay for the roll loop to supersede.
- `.env.example`: `EIA_API_KEY` placeholder added (key was read by the EIA adapter but undocumented).

## 2026-10-30: crypto data now Coinbase + Kraken only (Binance, Bybit, OKX, Robinhood Crypto removed)
- Binance, Bybit and OKX are not available to Canadian residents, and Robinhood Crypto is US-only. They are removed from ATLAS: adapters (`feeds/providers/{binance,bybit,okx}.py`), the provider chain, live ingest, universe, instruments, catalog rows, nowcast, ML evidence and scripts, frontend TradingView mapping and labels, `ATLAS_BINANCE_REST_HOSTS`, the `robinhood_crypto` broker and venue blocks (`ROBINHOOD_CRYPTO_*`), and the provider docs. The `excluded_venues` safety records for them stay.
- Crypto now comes from Coinbase (`<BASE>-USD`: REST history, gap fill, ticker) and Kraken (`<BASE>/USD`: 1m ohlc websocket, ticker) through the existing adapters, with the `kraken_ca` blocklist respected (`feeds/crypto_venues.py`). Internal ids (`BTCUSDT` etc.) are kept, the venue is labelled COINBASE and the currency USD. An asset with no listing, or a blocklisted base, shows a labelled empty state, never fake data.
- Known break: stored Binance/OKX history (USDT quote) is no longer read by `feed.bars()`. A Coinbase backfill is needed for depth, and there is a USDT to USD basis break at the switch.
- Research cost assumption for crypto spot raised from 24 bp (a Binance fee schedule) to 124 bp round trip (60 bp taker per side at Kraken Pro tier 2 plus 2 bp slippage per side; Kraken fee schedule read 2026-10-30). This tightens evidence and loosens no gate. Evidence published earlier used 24 bp and stays as a dated record.
- Models need retraining on the new source. Existing models stay as `.prev`; the rolling retrain and challenger gate decide. No gate was changed.
- Alpaca `.env.example` comment reworded (paper is available to Canadians; live accounts and paid data are not). Questrade refresh-token lifetime corrected to 3 days.

## 2026-10-30: Tradier removed
- Tradier requires non-Canadian residency, so it is removed entirely: adapter (`feeds/providers/tradier.py`), default stock chain (now polygon, alphavantage, questrade, alpaca), integrations registry, verify, setup/checklist UI entry, source terms, provider catalog and docs, and `TRADIER_ACCESS_TOKEN` / `TRADIER_ENV` in `.env.example`. No other provider and no safety gate changed. The generic HTTP 400 "Quota Violation" retry in `feeds/core.py` stays (now tested with another adapter).

## 2026-10-29: evo-14, model spec and directional research pipeline
- **`ATLAS_MODEL_SPEC.md`**: full equations for targets (CUSUM, triple barrier, forward return), features (HAR-RV, multi-timeframe, regime, cross-asset, session/VWAP, read-only account context), models, meta-labelling, calibration and adaptive conformal, ensemble and MAP-Elites, purged/embargoed walk-forward, DSR and PBO, costs, and the sizing hand-off. States what exists, what evo-14 adds, and what is deferred.
- **`src/atlas/ai/ml/directional/`**: detector-free direction research pipeline pooled per asset group and interval over every stored series. HGB primary, logit challenger, quantile GBM interval, ACI coverage. The existing `GATES` are inherited unchanged and two are added (ACI coverage, quantile skill). A model that fails any gate is labelled **research / below gate**; none is ever eligible here (the shadow gate cannot pass at training time). `scripts/ml_directional.py --inventory|--run`.
- **Chart**: new `directional_prediction` layer and a line in the Prediction zone card (direction, P(up barrier first), conformal set, p10-p90 band, label, out-of-sample n/AUC/Brier next to the base-rate Brier). `execution_permission` stays `none`.
- **Ten new chart layers (25 total plus layer 26 News & filings, all off by default)**: conformal forecast bands, multi-timeframe confluence, economic events, global market clock (user timezone, `tz` query), cross-asset correlation (DXY/UUP, gold, BTC, SPY where stored), volatility cone, liquidity and spread cost (OHLCV estimate, no quote feed), model disagreement (six fixed rule experts; learned spread display-only), account-aware size (read-only control-plane snapshot) and drift alert. Computed server-side in `/api/ai/chart/overlays` (`api/chart_layers25.py`); each returns `status`, `reason`, `meaning` and its feature values. Chart: bands drawn as two dotted lines, a readout card for the rest. Earnings dates are reported unavailable (no key-free source); exchange holidays are not modelled.
- **Model training features**: the same numbers feed the model (`ai/ml/directional/layers25.py`, leak-free, NaN when uncomputable). Directional feature count 51 -> 103 (+52: news 9 (layer 26), and the 43 layer columns: conformal 3, confluence 4, events 3, clock 4, cross-asset 8, vol cone 5, liquidity 4, disagreement 3, account size 2, drift 3, existing-layer gaps 4). Meta stack 45, vertical-slice 21 and REP_FEATURES 6 are unchanged. `scripts/feature_inventory.py` enumerates all counts from the code; `ATLAS_MODEL_SPEC.md` section 3A has the equations and inventory. 8 of the 25 layers are model outputs or outcomes and are excluded on purpose.
- **Catalog**: ROK, CEG, OKLO, VST, RKLB, SOFI, ENPH added after resolving each on SEC EDGAR (CIKs 1024478, 1868275, 1849056, 1692819, 1819994, 1818874, 1463101). AIWA and IONO were **not** added: EDGAR has no listing under those tickers (IONQ is a different company). Prices show "needs key" until the Massive or Alpha Vantage key is verified.
- **News intelligence (`src/atlas/news/`, `/api/news/*`, Research -> News & AI review, chart layer 26 "News & filings", off by default)**: per-user watchlist and feed from SEC EDGAR, GDELT and official RSS; tier-1 official vs tier-3 unverified; deterministic hype/scam flags; LLM event/sentiment/materiality scores kept only with a verbatim evidence quote and only when Gemini is verified on the paid tier (`llm_other` is never used). Nine leak-free `nw_*` model features.
- **LLM Reviewer**: ML proposal -> LLM review (allow / reduce confidence / veto, reasons, cited sources) -> unchanged control plane. Monotone (can only restrict), fails closed to "no opinion", every review logged with prompt hash and model, **shadow mode by default**, verdict in marker details and the News feed, paper-outcome effect report and gate-eligibility test (>= 100 vs 100 resolved, CI below 0). `execution_permission` stays `none`.
- Tests: hermetic network guard for the keyless context sources in `tests/conftest.py`.
- **Roadmap**: `ATLAS_EVOLUTION_ROADMAP.md` (evo-14..21, Canadian-resident traveller persona).
- Tests: `tests/ml_directional/` (future-perturbation leaves events, labels and features identical; ACI coverage bound; cross-asset alignment is causal; pure noise is labelled research / below gate; persisted-model scoring round trip).

## 2026-10-29: evo-13, Canada-eligible stock source, needs-verification keys, keyless context
- **Stock/ETF provider registry (`feeds/stock_providers.py`)**: `ATLAS_STOCK_PROVIDER` (default `polygon` = Massive Stocks Basic: free, email signup, daily bars) with automatic fallbacks alphavantage, questrade, tradier, alpaca. Alpaca is optional (not offered to Canadian residents). Tiingo, Twelve Data and Finnhub free plans stay out of the automatic chain (terms forbid storage/display, or no candles). Plan-aware intervals: free Massive/Alpha Vantage report daily bars only, honestly. Adapter fixes: Massive 5/min limiter, Alpha Vantage `outputsize=compact`, Questrade single-use refresh token kept in memory.
- **Needs verification (`integrations/verify.py`)**: no key is set by ATLAS. Every keyed service reads Needs verification with a Verify button (Settings Setup, Broker & alerts, Data coverage). `POST /api/integrations/verify` makes one read-only call (paper/practice/test endpoints only; Stripe test keys only), throttled, stores a secret-free result tied to a key fingerprint so a changed key resets. New `stripe` service entry.
- **Keyless context (`ext/keyless_context.py`, `/api/context/*`, Research, Macro & news)**: economic calendar from the BLS schedule and US Treasury auctions (FRED only after its key verifies), SEC EDGAR filings, Federal Reserve / SEC / Bank of Canada RSS, GDELT headlines (1 request / 5 s). Failures are reported, nothing is estimated.
- **Docs**: `docs/data/canada-sources.md` (researched sources, licences, per-asset-class result).

## 2026-10-29: evo-12, public-launch hardening, ops integrations, data coverage
- **Launch hardening (`src/atlas/accounts/`)**: `ATLAS_REQUIRE_AUTH` defaults on for any non-localhost deployment; registration modes `open|invite|closed` (default invite, hashed single-use invite codes, optionally bound to an email); email verification and password reset with an SMTP-agnostic mailer (`ATLAS_MAIL_BACKEND=console|smtp|file|memory`, console by default, nothing is sent); generic register/reset/resend responses (no account enumeration); `ATLAS_TRUSTED_PROXIES`-aware client IP for the rate limiter; Team seats enforced (plan seats, pending invites hold a seat); dialect-aware migrations with a Postgres version of the ledger immutability triggers (tested on a real Postgres when one is available).
- **Security headers**: per-request nonce CSP, `frame-ancestors 'none'`, nosniff, Referrer-Policy, Permissions-Policy and HSTS on https, on both the Next server and FastAPI.
- **UI**: sign-in gate, register, forgot / reset, verify-email pages; admin invitations; Team card in Settings, Account.
- **Ops integrations (all no-ops unless their env vars are set)**: Healthchecks.io dead-man ping, Sentry (Python, PII scrubbed), ntfy alert backend. Alerts stay off (`ATLAS_ALERTS_ENABLED`).
- **Env drift**: `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` are canonical; `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `APCA_*` are accepted.
- **Data coverage**: `GET /api/feeds/catalog-health` and Settings, Connectors, "Data coverage" show, for every catalog asset, the provider chain, the env var each needs, why it is empty, the last bar in Toronto time, and the labelled free stand-ins for gold spot and indices. Providers re-read their keys on every use, so a key saved in Settings works without a restart. A test asserts every catalog asset resolves to a provider chain. The free-data policy gate is unchanged: Yahoo (unofficial) and Databento (paid) stay off.
- **Fixes**: `/control?tab=portfolio` crashed on an empty book (full-shape empty book plus null-safe view); `/api/account/me` and `/api/account/config` are reachable signed out so the gate can render.

## 2026-10-29: evo-11, multi-user accounts, encrypted connectors, setup wizard, billing schema
- **Accounts (`src/atlas/accounts/`, `/api/account/*`)**: email + password (argon2id), HttpOnly sessions, CSRF, throttled login, roles owner/admin/user, profile page, per-user isolation, hash-chained audit log, OAuth hook (501).
- **Encrypted credentials**: AES-256-GCM envelope encryption keyed by `ATLAS_MASTER_KEY` (fails closed), write-only secrets (last 4), rotate/delete, rewrap CLI (`python -m atlas.accounts.cli`).
- **Connector library + wizard (`/settings?tab=setup`)**: 18 connectors from the integration-loop research, status lights, per-connector tests, paper/practice only. Feeds and integrations resolve credentials per user with the owner `.env` as fallback. API lives under `/api/account/connectors` (the legacy `/api/connectors` stays as is).
- **Billing schema, no commissions**: plans, plan_entitlements, subscriptions, usage_events, invoices, partner_referrals; Stripe test mode checkout and verified webhook; entitlement gate. See `docs/atlas/monetization.md` and `docs/atlas/security-review.md`.
- **UI fixes**: three nested-scroller tabs now scroll as one page; an empty chart no longer shows the old volume profile.

- **Billing v2 (M0005, aligned with `docs-research/monetization_plan.md`)**: Free / Pro (USD 29 / CAD 39 month, USD 290 / CAD 390 year) / Team (USD 99 / CAD 135, 5 seats, extra seats USD 15 / CAD 20) as configurable placeholders; **$0 per-trade fees and no performance fee**; seats in checkout; Stripe Tax hooks (`ATLAS_STRIPE_TAX`); `tax_records`; `broker_partners` / `broker_referrals` (off until counsel approval); hash-chained `payouts_ledger` with a Flooos-style JSON/CSV export; admin plan/broker/ledger endpoints; anonymise-on-delete for retained financial records; `live_order_routing` never bypassed. Stripe stays test-mode only.

## 2026-10-26: ATLAS Internet Research, Protocol Manifest, Extended Institutional Strategies & 14-Stage Unified Intelligence Loop
- **Version-Pinned Protocol & Adapter Manifest (`src/atlas/integrations/protocol_manifest.py`, `GET /api/ai/protocol-manifest`)**:
  - Codifies verified upstream protocol specifications, binary account discriminators, rate limits, licensing, and security invariants across `Databento GLBX.MDP3`, `Massive.com (formerly Polygon.io)`, `Alpaca Markets Paper & Crypto`, `Coinbase Exchange`, `Bank of Canada Valet & ECB SDMX 2.1`, `TradingView UDF / Pine v5`, `Solana JSON-RPC 2.0 & WebSocket`, `Pump.fun Bonding Curve (@pump-fun/pump-sdk@^4.1.0)`, `PumpSwap AMM (@pump-fun/pump-swap-sdk@^2.1.0)`, and the `ATLAS Point-in-Time ML & Analytics Stack`.
  - Adds `verify_protocol_compatibility()` and `detect_protocol_drift()` to catch smart-contract discriminator changes, unknown program owners, or forbidden live endpoints.
- **Massive.com & Solana JSON-RPC Adapter Enhancements (`src/atlas/feeds/providers/polygon.py`, `src/atlas/integrations/registry.py`, `src/atlas/pump/indexing/__init__.py`)**:
  - `PolygonAdapter` and `integrations.registry` now accept both `POLYGON_API_KEY` and `MASSIVE_API_KEY` (and `POLYGON_BASE_URL` / `MASSIVE_BASE_URL`, defaulting to `https://api.massive.com`).
  - Added `solana_rpc` to `SERVICES` and `PROBES` in `src/atlas/integrations/registry.py`.
  - Added `fetch_recent_prioritization_fees`, `simulate_transaction_rpc`, `fetch_account_info`, and `build_ws_subscription_payloads` (`logsSubscribe` and `accountSubscribe`) to `SolanaRPCIndexer`.
- **Extended Institutional Strategy Detectors & Prop-Firm Risk Pacing (`src/atlas/features/price_action/extended_strategies.py`, `src/atlas/features/price_action/strategies.py`, `src/atlas/ai/intel/fourbox.py`)**:
  - Implemented causal bar-by-bar detectors with `execution_permission="none"`:
    - `FailedBreakoutReversalDetector` (`failed_breakout_reversal`)
    - `NasdaqOpeningSessionDetector` (`nasdaq_opening_drive`, strictly scoped to `NQ`, `MNQ`, `QQQ`, `TQQQ`, `NDX`, 09:30–10:00 `America/New_York` IB-30)
    - `FairPriceSessionAnchorDetector` (`fair_price_session_anchor`, causal session VWAP and volume-weighted dispersion bands)
    - `ScheduledNewsPostReleaseDetector` (`scheduled_news_post_release`, strictly causal via `EconomicEvent.as_of(bar.end)` post-release volatility box)
    - `WhaleOrderFlowDetector` (`whale_orderflow_research`, causal rolling volume z-score, CLV, and effort-vs-result absorption)
    - `PropFirmCompetitionAdvisor` (`prop_firm_competition_intel`, deterministic risk-reducing `size_scalar <= 1.0` for trailing drawdown buffer, daily loss pacing, and consistency rule; never loosens `config/founder/risk_policy.yaml`).
  - Enhanced `fourbox.scan` (`src/atlas/ai/intel/fourbox.py`) to activate the 4th `Event` box causally when verified `EconomicEvent` objects are provided while remaining `disabled` by default when no events are supplied.
- **14-Stage ATLAS Unified Intelligence Loop (`src/atlas/ai/intel/unified_loop.py`, `GET/POST /api/ai/intelligence-loop`)**:
  - Connects multi-asset confirmed bars (`GC`, `NQ`, `QQQ`, `SPY`, `BTCUSDT`) and Solana/Pump.fun/PumpSwap tokens across all 14 stages (`AUTHORIZED_INTERNET_AND_MARKET_DATA` through `MODEL_EVALUATION_AND_RESEARCH`), registered as `unified_intelligence_loop` in `src/atlas/ai/node.py`.

## 2026-10-26: ATLAS Pump Intelligence — Solana Token Discovery, Risk, ML & Paper Execution (`atlas.pump`)
- **Pump.fun & Solana Trading Subsystem (`src/atlas/pump/*`, `/api/pump/*`, `/trade?tab=pump`)**:
  - **Discovery & Lifecycle (`atlas.pump.tokens`, `atlas.pump.discovery`, `atlas.pump.migrations`)**: Mint-address primary identity (`assert_mint_identifier`, rejecting bare symbols and disambiguating ticker collisions), `create`/`create_v2` custom quote-mint hierarchy validation (`MAX_QUOTE_DEPTH = 3`), and causal lifecycle state machine (`DISCOVERED -> CURVE_ACTIVE -> MIGRATION_PENDING -> PUMPSWAP_ACTIVE`, plus `UNSUPPORTED`, `SUSPENDED`, `DATA_UNAVAILABLE`, `RISK_REJECTED`).
  - **Bonding Curve & PumpSwap AMM (`atlas.pump.bonding_curve`, `atlas.pump.pumpswap`)**: Binary and JSON decoding for Pump.fun bonding curves (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) and PumpSwap pools (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`), v3 17-account trade instructions (`buy_v3`, `sell_v3`, `buy_exact_quote_in_v3`), unswept protocol/creator fee accounting, signed negative `Pool::virtual_quote_reserves` (`effective_quote_reserves = quote_vault_amount + virtual_quote_reserves`), synthetic migration crossover (`CompleteEvent` + `PostCompleteBuyEvent`), and `multi_hop_swap` routing.
  - **Real-Time Solana Indexer (`atlas.pump.indexing`)**: Authorized RPC/WebSocket event ingestion with deduplication, `(slot, tx_index, instruction_index)` ordering, confirmation progression (`processed -> confirmed -> finalized`), slot-fork chain-reorg rollback, rate limiting, and freshness monitoring.
  - **Token Safety & Wallet Intelligence (`atlas.pump.token_risk`, `atlas.pump.wallet_intelligence`, `atlas.pump.liquidity`)**: Evaluates mint/freeze authorities, restricted Token-2022 extensions (`PermanentDelegate`, `TransferHook`, etc.), creator/holder concentration, heuristic funding/slot clusters, sell simulation, price impact, and Solana base + priority fees (`5000 * signatures + ceil(CU * micro_lamports / 1e6)`). Strictly separates verified on-chain facts from heuristic risk scores (`safe_guaranteed = False`, `cluster_coordination_proven = False`).
  - **Strategies, Point-in-Time ML & Net EV Ranking (`atlas.pump.features`, `atlas.pump.strategies`, `atlas.pump.models`)**: Causal feature builder with `LookaheadBiasError` guard; all 8 strategy detectors (`launch_momentum`, `launch_pullback_continuation`, `bonding_curve_momentum`, `post_graduation_momentum`, `liquidity_sweep_reversal`, `whale_flow_research`, `momentum_exhaustion`, `creator_risk_avoidance`); calibrated 9-target ML forecasts with abstention and survivorship-bias-free baseline evaluation (`evaluate_models_vs_baselines`); and net EV ranking after round-trip fees, price impact, and Solana network costs. Registered in `atlas.ai.node` (`pump_intelligence`, `execution_permission: none`).
  - **Deterministic Risk, Wallet Guard, Paper Execution & Replay (`atlas.pump.portfolio`, `atlas.pump.execution`, `atlas.pump.replay`, `atlas.pump.monitoring`)**: 14-check `PumpDeterministicRiskEngine` integrated with `shared_safe_stop` and paper-only enforcement; `DedicatedTradingWalletGuard` blocking LLM/AI signing access and scrubbing secret keys; liquidation-marked `PumpPortfolioBook` (unrealized P&L marked at net exit quote after sell impact and fees, never at last trade price); and event-driven historical replay (`run_event_driven_replay`).
  - **Next.js Workbench (`frontend/src/ui/pages/PumpIntelligenceView.tsx`)**: Mounted on `/trade?tab=pump` (with `/pump` and `/solana` permanent redirects).

## 2026-10-25: repo consolidation (`unify-3b..6`), 2y feed backfill, and `atlas-evo-9`
- **Unified AI package layout (`src/atlas/ai/`)**:
  - `atlas.models`, `atlas.intel`, and `atlas.ml` now live under `src/atlas/ai/{models,intel,ml}` with backward-compatible import/pickle aliases in `src/atlas/_aliases.py` (`atlas.models.*`, `atlas.intel.*`, `atlas.ml.*` resolve to the exact same module objects). Shared schemas live at neutral `atlas.schemas` so `atlas.control` never loads `atlas.ai`.
  - Disambiguated same-named ML helpers in `src/atlas/ai/helpers_registry.py`, `docs/architecture/ML_HELPERS.md`, and `GET /api/ai/helpers`.
- **Module splits & changelog merge**:
  - Split `src/atlas/api/app.py` platform/operator routes into `src/atlas/api/routes_platform.py`.
  - Split `src/atlas/research/vertical_slice.py` (4,008 lines) into `vertical_slice_features.py`, `vertical_slice_models.py`, `vertical_slice_ledger.py`, `vertical_slice_scheduler.py`, and `vertical_slice.py` (`VerticalSliceService` + facade exports).
  - Merged `CHANGELOG.md` and `docs/CHANGELOG.md` into this single canonical `CHANGELOG.md` (with `docs/CHANGELOG.md` synced).
- **2-year free crypto history backfill (`dfb9cb5`)**:
  - Backfilled 730 days (`2024-10-25..2026-10-25`) of `15m` (`~70,080` bars/symbol) and `1h` (`~17,519` bars/symbol) plus 1,095 days of `1d` bars across all 34 crypto symbols via keyless `alpaca_crypto` and prefix/suffix exchange failover (`binance`, `okx`, `kraken`).
- **Evolution round 9 (`f3710d2`, `docs/research/evo9-longer-history-and-variants.{md,json}`)**:
  - Fixed causal `htf_frame` bar-end alignment and `add_macro` timestamps in `atlas.ai.ml.evolution`.
  - Added wider-stop, tighter cost-filter variants (`atr2.5_rr2_cf10`, `atr3_rr2_cf08`, `atr2_rr1.5_cf12`) and the `trend_conditioned` regime gene (`reg_trend_with`, `reg_trend_counter`, `{s}_x_trend`).
  - Over the full 2-year 34-symbol history, `model=hgb|features=full|regime=trend_conditioned|bar_type=time|context=none` achieves positive fitness (`+0.0012`) and `3/5` positive folds on `4h` `atr2.5_rr2_cf10`, while `evo7_1h` on the full 2-year history is negative (`-0.2817 R` take-all, `-0.0026 R` EV/opp), confirming `evo8`'s demotion of `432dba69a77e`.
  - 0 models pass all 6 checks of `evo8-strict-1`; `champion()` remains `None`, and all evolution chart markers are explicitly labelled `research-only`.
- **Purged walk-forward embargo fix (`203b8f1`)**:
  - `atlas.ai.models.quant.cv.purged_walk_forward_splits_by_time` now enforces `embargo` on the unique timestamp grid (`emb_lo = uniq[max(0, edges[k] - max(0, int(embargo)))]`, requiring `t < emb_lo` and `end < emb_lo`), with updated docs and pinned unit test in `tests/test_ai_helpers_registry.py`.
- **Keyless central-bank FX feeds (`boc_valet` & `ecb_fx`)**:
  - Wired `USD_CAD` into `DEFAULT_INSTRUMENTS` (`src/atlas/feeds/instruments.py`), `FX_ALIASES` (`src/atlas/feeds/universe.py`), and `FEED_ALIASES` (`src/atlas/api/udf.py`) with `boc_valet` (`FXUSDCAD`) and `ecb_fx` as keyless daily reference providers and sanity cross-checks.
  - Built `ECBFXAdapter` (`src/atlas/feeds/providers/ecb.py`) against the official ECB Data Portal SDMX-JSON API (`data-api.ecb.europa.eu/service/data/EXR`) with `certifi` TLS fallback (`ecb_transport`) and static `eurofxref-hist-90d.xml` failover, supporting direct `EUR_*` pairs (`EUR_USD`, `EUR_CAD`, `EUR_GBP`, `EUR_JPY`, `EUR_CHF`) and cross-rates (`USD_CAD`, `CAD_USD`).

## 2026-10-24: branch `atlas-evo-8` (strict evolution gate)
- (a) `ml/evolution.strict_gate` (gate_version evo8-strict-1, stricter only): beats_baseline + all folds evaluated + >=20 taken trades per fold + positive in a majority of folds + DSR >= 0.95 and Bonferroni p x n_trials < 0.05 over all genomes tried. Champions are crowned only from strict passes.
  - `scripts/regate_evolution.py`: 432dba69a77e reproduced exactly and was DEMOTED to research-only (failed min_trades_per_fold 2<20, DSR 0.0015, Bonferroni p 1.0). No research champion now.
- (b) Chart overlays: 1h resampled from complete 15m hours when no stored 1h exists, labelled "1h resampled".
- (c) Robustness (`research/champion_robustness.py`): block-bootstrap CIs span 0; edge is concentrated in the last fold (115% of taken R) and in alts. No more history exists in the feed. See `docs/research/evo8-champion-robustness.md`.
  - New evolve run d0e147849051 (evo7_1h, 5 gens, 42 genomes incl. bar types and context genes): 0/42 pass the strict gate. execution_permission none.

## 2026-10-24: branch `atlas-evo-7` (PDR reversal probe)
- `research/reversal_probe.py` + `scripts/run_reversal_probe.py`:
  - limit entries, partial targets, time stops, and closed-bar HTF/volatility filters;
  - a labelled `maker_assumed` cost model;
  - 540 trials over BTC/ETH, 28 alts and SPY/QQQ/IWM, with CIs, DSR, PBO and purged walk-forward.
- Result: 0/540 pass, PBO 0.109. Core 4h OOS net +0.039 R, CI spans 0. Alts and 1h are negative. See `docs/research/evo7-reversal-probe.md`.
- `ml/dataset.resample_buckets`: crypto 1h derived from complete 15m hours when no feed bars exist.
- ML: `--universe evo7|evo7_1h` (30 crypto).
  - 4h run 489861863694: no challenger beats baseline.
  - 1h run 432dba69a77e: research champion, EV +0.019 R vs take-all -0.170 R, Brier skill +0.0009. Fragile: the edge comes from the last fold.
  - execution_permission none. Markers come from 432dba69a77e. See `docs/ml/evo7-reversal-probe.md`.

## 2026-10-24: branch `atlas-unify-1` (streamline pass 1, AI as one node)
- AI node: `atlas.ai.node` (one registry of 14 AI/ML/LLM components, uniform statuses, audit trail) + `atlas.ai.http` (`/api/ai/*`; `/api/ai/{ml,research,intel,advanced-ml,agent}/*` alias the legacy paths). One middleware forces `execution_permission: none` on every AI JSON response (old and new paths); the control plane stays the sole authorizer. Docs: `docs/architecture/AI_NODE.md` and `docs/audit/2026-10-24-repo-streamline.md`.
- Fixed 5 scripts failing `--help`; fixed RecursionError in `setup_evidence.load_datasets` legacy JSON branch.
- Removed dead `research/warmup.py`, `marketdata/drift_integration.py`, `frontend/build_output.txt`; moved `frontend/ATLAS_AUDIT.md` to `docs/audit/`. One `brier` implementation. Dropped unused deps databento, polygon-api-client, ccxt, polars, aiohttp.
- UI: ML models page uses `/api/ai/ml/*` and shows the AI node card.

## 2026-10-24: branch `atlas-ext-1`
- Seven-repo gap audit: `docs/audit/2026-10-24-seven-repo-gap.md`.
- `atlas.ext`: Black-Scholes greeks/IV, parametric/historical/component VaR+ES, DCF (FCFF/FCFE), SEC EDGAR point-in-time fundamentals, VWAP/volume profile/S-R/scan, Pine v5 export, conviction dossier, rule-based investor personas, a deterministic analyst-debate-trader-risk-PM pipeline (never submits), an Alpaca PAPER broker (live refused, control plane first), alerts (off by default), and a read-only MCP tool server (`scripts/atlas_mcp_stdio.py`). `/api/ext/*`.
- Control plane: `preview_order` (no booking) shares `_evaluate_request` with `submit_order`. Rules are unchanged.
- UI tabs: Research Lab gets Valuation / Dossier & agents / Options; Research gets Scan & Pine; Settings gets Broker & alerts.
- Blocked: live option chains, news/sentiment, maritime. Deferred to evo-5: yield curve/macro.

## 2026-10-24: branch `atlas-evo-6` (from main 8cea007)
- Setup redesign research (new, toggleable; legacy setups unchanged):
  - `ReplayConfig.stop_atr_mult / target_rr / max_cost_r` (default None): ATR(14) stops on closed bars, R-multiple targets, and a cost filter that skips setups whose round-trip cost exceeds a fraction of risk (`cost_skipped`).
  - `research/setup_variants.py` + `scripts/run_setup_variants.py`: 5 variants x 15m/1h/4h (4h = complete UTC buckets of 1h bars, crypto only) x BTCUSDT/ETHUSDT/SPY/QQQ/IWM with paper realism, gross and net R, bootstrap CIs, DSR across 230 trials, PBO (CSCV) and purged walk-forward selection. Output `docs/research/evo6-setup-variants.{md,json}`.
  - 16 `research` strategy specs `<detector>__<variant>` (off by default; excluded from the live suite).
  - `orb_retest` 15m research-retired with a documented reason, reversible (`Registry.set_retired`, `POST /api/quant/strategies/{sid}/retired/{interval}`).
- Findings: 0/230 configs pass the gates. Costs drop from ~0.3-0.7 R to ~0.04-0.12 R with wider stops, but gross R stays negative for orb_retest, dual_band_breakout and wick_reversal on every timeframe. Only prior_day_range_reversal 4h crypto is positive before costs (+0.05 to +0.07 R; CI spans 0) and about break-even after costs. See `docs/ml/evo6-setup-redesign.md`.
- ML: `--universe evo6` (PDR 4h atr2_rr2 labels, 457 rows). AUC 0.485, shuffled 0.481. Evolution de86779da75c: no challenger beats baseline (best EV +0.058 R but Brier skill -0.031). Extended run f8e7de55c108 (15,157 rows) refreshes the 15m/1h chart markers: no challenger beats baseline. Nothing promoted; execution_permission none.
- `ml/dataset.py`, `intel/markers.py`: 4h interval support (crypto only).

## 2026-10-24: branch `atlas-evo-5` (from main 771863a)
- §22 macro data: `feeds/providers/fred_public.py` reads keyless FRED `fredgraph.csv` (DGS10, DGS2, VIXCLS, DTWEXBGS, CPIAUCNS, chosen because they are rarely or never revised). Every value gets a conservative availability date as `realtime_start`:
  - daily series: next business day + 1 day
  - H.10 dollar index: + 10 days
  - CPI: first day of M+2
  Values are stored through `FeedStore.ingest_observations` (`scripts/fetch_fred_public.py`).
- `ml/context.py`:
  - HTF features come from closed UTC-day and 4h buckets of the series itself: d1 returns, trend in ATR, daily ATR, position in the prior-day range, 4h return and trend, and risk relative to the daily ATR.
  - Macro features (10y level and 20d change, 2s10s, VIX level and z-score, 20d USD return, CPI YoY) are joined only from 00:00 UTC of the availability date. With no observations they are NaN, and the genome is gated as unavailable.
- Evolution adds the gene `context` (none|htf|macro|htf_macro) with 4 seeds. Old genomes default to `context=none`. `--universe extended` adds 1h bars for the same 5 symbols.
- `scripts/ml_diagnose.py` and `docs/ml/evo5-diagnosis.md`: why nothing beats baseline.
  - The primary setups lose before costs (gross −0.24 R), costs are about 0.48 R median, and the meta-label AUC is about 0.53.
  - The shuffled-label check shows no leakage.
  - Fixed the biased permutation importance from the scratch analysis (calibrated base vs raw permuted score).
- Evolution:
  - 44f40efd9e65 (default, 9,531 rows) and 30721a3ccb32 (extended, 15,157 rows): **no challenger beats baseline**.
  - On extended data, HTF context improves hgb fitness from −0.027 to −0.008, but EV stays negative.
  - Nothing promoted; execution_permission none. Chart markers now come from 30721a3ccb32.
- `ml/features.py`: `dt.dayofweek` → `dt.day_of_week` (pandas deprecation).

## 2026-10-24: branch `atlas-evo-4` (from main b299511)
- Control plane reduce-only partial close: `close_position(position_id, exit_price, fraction=…)`. 0 < fraction ≤ 1 only (else `invalid_fraction_reduce_only`); books P&L on the closed slice, frees gross and correlated exposure, keeps the remainder open; audited `position_reduced` / `position_closed` with closed and remaining notional. No risk check changed.
- Setup autopilot: a volume-capped partial entry now cancels the unfilled remainder through that partial close at the booked entry price (zero P&L, audit `setup_autopilot.partial_fill`), so exits book the real filled quantity. The evo3 fill-ratio exit-price approximation is removed.
- `research/backtester.py` (`StrategyBacktester`) uses the same paper realism as replay by default (1-bar latency, trade-through entry/target limits, 10% participation, zero volume no fill, fill-weighted net P&L, `fill_ratio` on `TradeOutcome`); `realism=None` keeps the legacy model. `scripts/backtester_realism_compare.py` prints before/after.
- Fixed `strategies/snapback.py`: `SnapbackSetup` subclassed the frozen pydantic `Record`, so the detector raised on its first bar and the backtester/coordinator snapback path could never run.
- §6: `feeds/universe.py` FUTURES and `feeds/instruments.py` ES read tick/multiplier from `feeds/contracts.CONTRACT_TERMS` (the duplicates were there, not in `marketdata/futures.py`/`models/quant/multi.py`).
- Before/after on real feed bars (3,000 bars each, cost_bps 0): BTCUSDT 15m 8→8 trades, +35.2 bps expectancy both; ETHUSDT 15m 6→6, +30.8 both; ES 1m 20→19 trades (1 unfilled), net +1,161→+1,101 bps; GC 1m 9→9 (1 unfilled signal that legacy had expired). Samples are tiny and say nothing about edge; on these liquid markets realism removes little.
- ML not re-run: dataset labels come from PA replay, which did not change in this pass.

## 2026-10-24: branch `atlas-evo-3` (from main 62bf221)
- §13 cumulative-loss cap for re-entry. `ReentryConfig` adds `max_loss_r_per_family_day`, `max_loss_r_per_day` and `max_consecutive_losses`. They load from the new tighten-only overlay `config/risk_overlays/reentry_tighten.yaml` (2.0 R, 3.0 R, 2) via `load_reentry_config`. A looser, null, unknown or non-positive overlay value is ignored and listed in `overlay_notes`. `config/founder/risk_policy.yaml` is unchanged.
  - Feedback: replay feeds each exit's after-cost, fill-weighted R to `PriceActionEngine.record_outcome` before the bar reaches the detectors (causal). The setup autopilot feeds realized paper exits to an OMS-level governor and refuses new proposals with the audited decision `reentry_loss_cap`. `risk_view` shows the governor state.
- §6 one contract-spec source. `feeds/contracts.py` is the source. `intel.data.SPEC` futures rows and `scripts/run_level_research.py` now derive from it. The new `risk.sizing.contracts_for_risk` sizes from it. Where two duplicates disagreed, the more conservative cost was kept: MGC $3.5 RT (was 2.5 in contracts), ES $30 (was 25), SI price-unit cost 0.025 (was 0.015 in intel). Every spec is still flagged `verified: false`.
- §25 paper realism by default. `PAPER_REALISM` / `paper_replay_config` (1-bar latency, trade-through limits, 10% participation; zero or unknown volume does not fill) is now used by the intel lab, `/api/intel` replays, the ML dataset and the setup autopilot. The autopilot sets the real order quantity per trade. A partial fill is booked as the exit price that gives fill_ratio × full P&L, because the control plane closes whole positions only (documented limitation).
  - `PaperBroker` gains opt-in `ExecRealism` (latency in price updates, trade-through, volume-capped partials with the remainder left working). The default is unchanged.
- API `/api/intel/contracts` and `/api/intel/reentry`. Risk → Track rules now shows "Re-entry loss caps" and "Contract specs" cards.
- ML labels changed (realism in the dataset), so evolution was re-run: run acfd9abb65cc, **no challenger beats baseline** (details in the checkpoint, pass 9). Nothing promoted; execution_permission none.

## 2026-10-24: branch `atlas-evo-2` (from main 727975f)
- Chart opportunity markers: categories are now accurate per class.
  - Rule-only markers no longer say "rejected"; their risk status reads "gate abstained, no validated model (not a risk rejection)".
  - `/api/intel/markers` returns `classes` with count, `applicable` and a note per category. The legend shows "n/a" (disabled, with the reason on hover) for categories that cannot occur on that chart, e.g. ML take/skip where there are no out-of-sample predictions.
  - "Gate rejected (geometry/costs)" now states that its count is out of N rule candidates checked, and that the edge check needs a validated model.
  - Labels: ML take / ML skip (out-of-sample), Rule setup with no model verdict, Gate rejected (geometry/costs).
- New causal bar types `kagi_atr` and `pnf_atr` (3-box reversal, ATR box frozen per column) in `features/representations`. Only completed lines/columns are emitted. Prefix-invariance (no-lookahead) tests and fixed-size worked examples were added.
- Both are in the evolution `bar_type` gene and seeds, and in the chart bar-type switcher (Levels chart, desk chart).
- Evolution run 3bdaaf38ba24 (same data snapshot and seed as d6a35224ceef): **no challenger beats baseline**. Best kagi genome fitness -0.053, best P&F -0.065; both are below renko (-0.034) and time bars (-0.039). Nothing was promoted, and execution_permission stays none.
- Removed the dead pathname-to-workspace map in `InstitutionalWorkspacesView.tsx`. Legacy paths 308 before render. On canonical hub paths it overrode the tab's workspace view (e.g. `/settings` → rulebook, `/data?tab=reserve` → lakehouse).
- Gap matrix re-audited (pass 8).

## 2026-10-24: branch `atlas-routes-1` (from main 8cabd13)
- Consolidated pages that did the same job under different names. Audit: `docs/audit/2026-10-24-route-consolidation.md`.
  - Risk & positions: the "Positions" tab (former `/trade/blotter`, `/control/dealing-desk`) is merged into "Account & positions". It keeps the exposure, recorded-decision and stop-protection figures and the full positions table, with one Flatten button.
  - Research lab "Microstructure" moved into Research → Chart read, next to the candle measurements.
  - Research lab "Four-Box" moved into Research → Price zones, next to the opening-range and wick-zone detectors.
  - Overview and Money → Summary now share one P&L strip (`src/ui/PnlTiles.tsx`) instead of two copies.
- Old addresses are now permanent (308) redirects generated from `pagesMap.ts` in `next.config.ts`. The 40 stub `redirect()` page files and `scripts/gen-redirects.mjs` are gone. Retired tabs (`/control?tab=positions`, `/research/lab?tab=microstructure`, `/research/lab?tab=fourbox`) redirect to the tab that took them over.
- No backend, API or risk-rule changes.

## 2026-10-24: branch `atlas-evo-1` (from atlas-full-2 97bf58f)
- Added alternative bar builders in `features/representations`: Heikin-Ashi (features and display only), Renko (ATR), range (ATR), volume and dollar bars. They are causal and indexed by completion time. Tick bars are gated as unavailable because the feed stores bars only.
- Added a governed model-evolution loop in `ml/evolution.py`, run with `scripts/evolve_models.py`:
  - Genes: model (hgb/ridge/xgb/lgbm), regime conditioning, feature ablations and bar type.
  - Evaluation uses shared purged/embargoed walk-forward folds.
  - Fitness = OOS EV after costs + Brier skill + stability.
  - Lineage and the champion are recorded in the ML registry. There is no auto-promotion, and execution_permission is none.
- New API routes: `/api/intel/evolution`, `/evolution/run`, `/markers` and `/bars_alt`.
- Research lab now has a "Model evolution" tab. It shows "No model beats baseline" when that is the case, which it is for run d6a35224ceef.
- Opportunity markers now appear on the Levels & sweeps chart and on the desk "Model opportunities" chart:
  - Classes: ML-suggested, rule-only, risk-rejected and ML-skip.
  - Each tooltip shows probability or "uncalibrated/LOW_CONFIDENCE", EV, model, risk status and outcome.
  - Markers can be toggled, and they carry the label "research signal, paper only, not advice".
- Both charts can switch the display bar type between candles, HA, Renko, range and volume, on the real time axis.
- Lab variants now report `zero_trade_reason`. Gold snapback/ORB on 15m give `timeframe_mismatch`, because the 08:20–08:50 box is not tiled by 15m bars.
- Fixed: daily data no longer shows as "live" on weekends. "Live" now requires the last bar to be at most min(2×bucket, 1h) old.
- Merged `intel/memory.py` into `research/memory.py`.

## 2026-10-24: branch `atlas-sfp-1`
- Added a price-level suite: CME/COMEX calendar, liquidity level registry, shared level interaction engine, SFP, gold opening box ORB and snapback (GC/MGC only), HTF bias, re-entry governor, unified candidate contracts with resolve.
- Added a strategy registry with per-technique toggles (`/api/quant/strategies`). New techniques default to off.
- Added a strategy selector (`ml/selector.py`): context features plus per-family calibrated meta-labels, purged walk-forward, and baselines. Added xgb/lgbm challengers.
- Added `/api/quant/levels` and the Research → "Levels & sweeps" tab.
- Added the NO_TRADE reason `COST_TOO_HIGH` (cost/risk > 0.5).
- Fixed: the re-entry per-level limit never applied (wrong key).
- Research: no technique or selector beats NO_TRADE on the available data (`docs/research/levels-2026-10-24.md`).

## 2026-10-24: `atlas-full-2` pass 5
- `atlas.intel`: research lab (DSR, PBO, bootstrap, cost sensitivity, reproducible report IDs), causal regimes + strategy-by-regime, portfolio exposure/correlation/VaR/CVaR/stress, track rulebook diff + enforcement probes, grounded evidence-ID assistant (LLM never used), market memory/attribution/governance view, microstructure tier gating, Four-Box scan. `/api/intel/*`.
- UI: `/research/lab` hub (6 tabs) and Risk tabs Portfolio risk / Track rules, with freshness chips.
- Exchange holidays via `exchange_calendars` (COMEX/CMES) for futures last-trade/roll dates.

## 2026-10-24: `atlas-full-1` pass 4
- Control plane: lot-sized orders now report whole-contract `quantity` (0 on a zero-lot rejection; previously a fractional value derived from the 0.01 placeholder notional). Tests: `tests/test_control_futures_sizing.py` (GC/MGC/SI/ES whole contracts, notional = qty x entry x multiplier, 1 GC > open-track cap rejected, unknown symbol -> lot metadata unavailable).
- Levels: dynamic `ma<N>` (shared `indicators.EMA`) and `vwap` (shared `indicators.BarVWAP`, session reset, absent without volume) zone types; one live level per type, valid one bar; `priority_of()`. Off by default (`RegistryConfig.ma_periods=()`, `session_vwap=False`).
- `vertical-text.check.mjs`: pages and tabs read from `pagesMap.ts` (30 pages x 4 widths = 120 combos); load failures / near-empty pages are counted and exit 2. Rerun: 120/120 checked, 0 instances, 0 load failures.
- UI: curtain merged into 4 sections (Home & trading, Research & models, Money & compliance, Settings, help & tools incl. advanced); `Card fresh=` prop renders the shared freshness badge on Levels, Gold sessions, Candidates, Inspect, No-trade, Setup candidates, Zones and Paper replay cards; market AssetCard shows only symbol/name/price/change/quote status (fixture microstructure details removed).
- Research `scripts/run_mgc_sizing_eval.py` -> `shots/full1/e2e/mgc_sizing_eval.json`: MGC does not make the E2E candidates pass. All 6 have stops of 2.4-12.1 bps vs the 30 bps open-track minimum, and one MGC (~$41.2k-42.3k) already exceeds the $40k open-track position cap. GC and MGC: 0/6 authorized. No rule changed.
- Exchange holidays: `last_trade_date` remains weekday-only prior to pass 5.

## 2026-10-24: `atlas-full-1` pass 3
- `models/serving.py`: one serving path over the ml / quant / serving registries; statuses TRADE_CANDIDATE, LOW_CONFIDENCE, CONFLICTING_EVIDENCE, INSUFFICIENT_DATA, UNFAVORABLE_COSTS, NO_TRADE; PSI+ADWIN DriftGuard; `GET /api/ml/serving`. Only TRADE_CANDIDATE reaches the deterministic control plane.
- Correlation id (`ops.correlation.bind`) on control-plane decisions/intake reports, PaperConnector receipts, signal telemetry, autopilot audit decisions and paper exits.
- Fix: opportunity geometry is now directional (a long with stop above entry was accepted).
- Fix: gold `range_atr` uses the causal pre-Asian 15m ATR(14) (`atr_basis`); 1m basis rejected.
- `scripts/run_e2e_journey.py`: GC 15m replay → detection → logistic+Platt (research only) → serving → control plane → paper → exits → SVG chart, evidence in `/workspace/shots/full1/e2e/`.
- `feeds/contracts.py`: ContractSpec for GC/MGC/SI/ES on top of InstrumentMaster (expiry, roll before first notice for metals, hours, cost assumptions, `verified=False`). Control plane sizes futures by contracts × multiplier.
- Levels: confluence_ids, rejection/breakout/sweep/acceptance counts, last_event_ts, optional round-number levels.
- Replay: `latency_bars`, `limit_fill="trade_through"`, volume-capped partial fills (`fill_ratio`, weighted R); `scripts/run_replay_realism.py`.
- `GET /api/feeds/freshness` + shared `FreshBadge` / `DataFreshnessChip` in the header and curtain menu.

## 2026-10-24: `atlas-full-1`
- Added `features/price_action/library.py` (indicator + quant math library), `structure.py` (causal market-structure events), `gold_models.py` (gold-only Early Bird / range-bound / ORB alignment / Asian context).
- Added gap matrix, indicator catalog, checkpoint, `scripts/run_structure_evidence.py`, tests `tests/price_action/test_mandate_full1.py`.
- `gold_models.window_range` gap tolerance (Asian ≤10% missing 1m bars, early ≤5%, 08:00/08:20 boxes strict); every window reports `n/expected/coverage`. Gaps are never filled.
- `/api/quant/levels` now returns `overlays` (indicator series, structure events, gold-only session ranges from ATLAS feed 1m only, `freshness` label). Levels & sweeps chart gains SMA / trend band / Donchian / structure toggles, freshness badges and a Gold session ranges card.
- `atlas.ops.correlation`: `x-correlation-id` request/response header and JSON-line `atlas.request` logs.
