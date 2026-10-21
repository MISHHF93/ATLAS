export interface Feature100Item {
  featureId: string;
  number: number;
  categoryId: number;
  categoryTitle: string;
  name: string;
  realm: "Open-Market" | "Prop Competition" | "Both";
  subsystem: string;
  metric: string;
  description: string;
}

export interface FeatureCategoryMeta {
  id: number;
  shortLabel: string;
  title: string;
  rangeLabel: string;
  icpTag: string;
}

export const TEN_CATEGORIES_META: FeatureCategoryMeta[] = [
  { id: 1, shortLabel: "Cat 1 · Webcam & KYC", title: "Webcam Proctoring, Identity Verification & Trader Integrity", rangeLabel: "F-001..F-010", icpTag: "ICP-01 / ICP-03" },
  { id: 2, shortLabel: "Cat 2 · Market Data & L2/L3", title: "Live Market Data, Microstructure & Order Book Feeds", rangeLabel: "F-011..F-020", icpTag: "ICP-01 / ICP-02" },
  { id: 3, shortLabel: "Cat 3 · Deterministic RMS", title: "Deterministic Risk Management System (RMS) & Circuit Breakers", rangeLabel: "F-021..F-030", icpTag: "ICP-01 / ICP-03" },
  { id: 4, shortLabel: "Cat 4 · OMS & Execution", title: "Order Management System (OMS) & Execution Tactics", rangeLabel: "F-031..F-040", icpTag: "ICP-01 / ICP-02" },
  { id: 5, shortLabel: "Cat 5 · Charting & UX", title: "Charting, Workbench & Terminal User Experience", rangeLabel: "F-041..F-050", icpTag: "All ICPs" },
  { id: 6, shortLabel: "Cat 6 · Prop Lifecycle", title: "Prop Firm Evaluation & Lifecycle Engine", rangeLabel: "F-051..F-060", icpTag: "ICP-01 / ICP-03" },
  { id: 7, shortLabel: "Cat 7 · Sybil & Anti-Cheat", title: "Anti-Cheating, Surveillance & Sybil Guard", rangeLabel: "F-061..F-070", icpTag: "ICP-03 / ICP-04" },
  { id: 8, shortLabel: "Cat 8 · Quant & Whale ML", title: "Quantitative Research, Machine Learning & Analytics", rangeLabel: "F-071..F-080", icpTag: "ICP-02 / ICP-04" },
  { id: 9, shortLabel: "Cat 9 · Dealing Desk & A/B", title: "Dealing Desk, B-Book Hedging & Liquidity Routing", rangeLabel: "F-081..F-090", icpTag: "ICP-03 / ICP-04" },
  { id: 10, shortLabel: "Cat 10 · Lakehouse & Ledgers", title: "Enterprise Architecture, Storage & Compliance", rangeLabel: "F-091..F-100", icpTag: "All ICPs" },
];

const RAW_100_ROWS: Array<[number, number, string, "Open-Market" | "Prop Competition" | "Both", string, string, string]> = [
  // Category 1 (1-10)
  [1, 1, "Webcam Biometric Face-Match Verification (KYC)", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Cosine Sim >= 0.92", "Compares live camera stream against government-issued ID documents during trader onboarding."],
  [2, 1, "Liveness Detection & Anti-Spoofing", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Blink + Head Yaw <= 28 deg", "Enforces active eye-blinking and head-turning challenges to detect deepfakes, printed photos, or loopers."],
  [3, 1, "Session Continuous Facial Re-Authentication", "Prop Competition", "src/atlas/proctoring_and_features100.py", "60s Passive Cadence", "Periodically captures passive webcam frames during live funded trading sessions to verify trader identity."],
  [4, 1, "Multiple Face / Proxy-Trading Detection", "Prop Competition", "src/atlas/proctoring_and_features100.py", "face_count == 1 Gate", "Analyzes background video frames to flag secondary individuals coaching or executing trades alongside the user."],
  [5, 1, "Gaze & Screen Tracking Telemetry", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Off-Screen <= 4.0s", "Tracks eye-tracking vectors away from the primary terminal screen during formal funded evaluation tests."],
  [6, 1, "Virtual Camera & OBS Driver Filter", "Prop Competition", "src/atlas/proctoring_and_features100.py", "OBS / ManyCam Blocked", "Scans OS video device drivers to block virtual cameras, OBS virtual feeds, and pre-recorded video injection."],
  [7, 1, "Periodic Identity Snapshot Watermarking", "Prop Competition", "src/atlas/proctoring_and_features100.py", "SHA-256 Order Link", "Cryptographically timestamps and hashes webcam captures against concurrent trade execution IDs for audit defense."],
  [8, 1, "Hardware Device & Peripheral Fingerprinting", "Prop Competition", "src/atlas/proctoring_and_features100.py", "USB Hardware GUID Match", "Cross-correlates webcam hardware GUIDs, monitor setups, and browser canvas fingerprints to block sharing rings."],
  [9, 1, "Dual-Camera Mobile Proctoring Handoff", "Prop Competition", "src/atlas/proctoring_and_features100.py", "QR 360 Room Scan", "Prompts a smartphone QR scan for secondary room-angle verification during high-stakes payout reviews."],
  [10, 1, "Proctoring Audit Log & Compliance Review Queue", "Prop Competition", "frontend/app/control/proctoring", "Scrubbable Event Timeline", "Provides risk officers with a scrubbable timeline of flagged video/identity anomalies linked to trade blotters."],

  // Category 2 (11-20)
  [11, 2, "Sub-Millisecond WebSocket Tick Broadcaster", "Both", "src/atlas/api/ws.py", "9ms RTT · 60 FPS", "Streams real-time L1/L2 market data from backend gateways to browser clients."],
  [12, 2, "Multi-Venue Crypto Aggregation", "Prop Competition", "src/atlas/marketdata/live_stream.py", "CCXT Pro Unified Book", "Normalizes live spot and perpetual futures feeds across Binance, Coinbase, and Kraken via CCXT Pro."],
  [13, 2, "US Equities SIP & Direct Feed Integration", "Open-Market", "src/atlas/marketdata/live_stream.py", "Polygon SIP + Databento", "Connects Polygon.io and Databento for real-time NYSE/Nasdaq equity quotes and trades."],
  [14, 2, "CME / Futures Market-By-Order (MBO) Reconstruction", "Both", "src/atlas/marketdata/live_stream.py", "L3 Queue Priority", "Tracks individual order queue priority and resting depth via Databento L3 feeds."],
  [15, 2, "Zero-Allocation In-Memory Ring Buffers", "Both", "src/atlas/marketdata/live_stream.py", "maxlen=5,000 Deque", "Maintains rolling 5,000-tick windows per symbol in RAM for instant indicator computation."],
  [16, 2, "Real-Time Order Flow Imbalance (OFI)", "Both", "src/atlas/whale_saas_az.py", "Top-5 Level OFI", "Calculates net aggressive buying vs. selling pressure across the top 5 order book levels."],
  [17, 2, "Volume-Synchronized Probability of Informed Trading (VPIN)", "Both", "src/atlas/whale_saas_az.py", "50-Bucket Toxicity CDF", "Measures order flow toxicity in real time to detect institutional whale activity."],
  [18, 2, "Kyle's Lambda Price Impact Estimator", "Both", "src/atlas/whale_saas_az.py", "dP / dOFI Slope", "Computes the instantaneous cost of liquidity and market depth resilience per asset."],
  [19, 2, "Automated Feed Failover & Redundancy", "Both", "src/atlas/marketdata/live_stream.py", "<50ms Hot Failover", "Switches seamlessly between primary and backup market data providers upon packet loss."],
  [20, 2, "Dual-Timestamp Causal Tagging", "Both", "src/atlas/marketdata/live_stream.py", "exchange_ts <= receipt_ts", "Stamps every incoming tick with both exchange_timestamp and system_receipt_timestamp."],

  // Category 3 (21-30)
  [21, 3, "500ms Data Staleness Circuit Breaker", "Prop Competition", "src/atlas/control", "500ms Hard Halt", "Halts order entry automatically if market data feed latency exceeds 500 milliseconds."],
  [22, 3, "Real-Time High-Water-Mark (HWM) Trailing Drawdown", "Prop Competition", "src/atlas/control", "8.0% HWM Floor (0.8ms)", "Tracks tick-by-tick unrealized + realized equity against dynamic trailing drawdown floors."],
  [23, 3, "Hard Daily Loss Limit Enforcement", "Both", "src/atlas/control", "3.0% Open / 4.0% Prop", "Automatically flattens open positions and locks the account until the next session if daily loss is breached."],
  [24, 3, "VPIN Toxicity Dynamic Stop-Widening", "Both", "src/atlas/control", "1.35x ATR Widening", "Adjusts mandatory stop-loss distances automatically when order book toxicity spikes."],
  [25, 3, "Pre-Trade Margin & Buying Power Gate", "Both", "src/atlas/control", "Reg-T & Prop Leverage", "Validates leverage, initial margin, and notional exposure in <1ms before routing any order."],
  [26, 3, "Mandatory ATR / Structure Stop-Loss Validator", "Both", "src/atlas/control", "0.50%-0.75% Risk Cap", "Rejects naked orders that lack a protective stop-loss within the allowed per-trade risk cap."],
  [27, 3, "Macro Economic News Blackout Filter", "Prop Competition", "src/atlas/control", "T-2m to T+2m FOMC/CPI", "Blocks new market order execution 2 minutes before and after Tier-1 macro releases."],
  [28, 3, "Cross-Asset Correlation Exposure Cap", "Both", "src/atlas/control", "rho <= 0.80 · Cap 50%", "Prevents traders from stacking correlated directional risk across identical beta clusters."],
  [29, 3, "Global Sub-Millisecond Emergency Kill Switch", "Both", "src/atlas/control", "<1ms Global Flatten", "Provides 1-click firm-wide or account-level position liquidation and order cancellation."],
  [30, 3, "Strict AI Air-Gap Enforcement", "Both", "src/atlas/control", "execution_permission: none", "Guarantees that machine learning and LLM nodes carry execution_permission: none."],

  // Category 4 (31-40)
  [31, 4, "Almgren-Chriss Optimal Execution Slicer", "Both", "src/atlas/whale_saas_az.py", "6-Slice Sinh Trajectory", "Breaks large parent orders into child slices to minimize market impact and timing risk."],
  [32, 4, "TWAP & VWAP Algorithmic Execution Engines", "Both", "src/atlas/oms", "Volume-Curve Slicing", "Executes orders systematically along historical or real-time volume profiles."],
  [33, 4, "Interactive Depth-of-Market (DOM) Price Ladder", "Both", "frontend/app/trade/depth-dom", "10-Level Click-to-Trade", "Enables 1-click limit and stop order placement directly on the live L2 price ladder."],
  [34, 4, "Bracket Order & OCO (One-Cancels-Other) Engine", "Both", "src/atlas/oms", "Entry + TP + SL Linked", "Attaches synchronized take-profit and stop-loss orders to every entry."],
  [35, 4, "Dynamic Trailing Stop & Breakeven Automation", "Both", "src/atlas/oms", "+1R Auto-Breakeven", "Moves stop-losses to breakeven automatically once a trade reaches +1R unrealized profit."],
  [36, 4, "Slippage & Realistic Fill Simulator", "Prop Competition", "src/atlas/oms", "L2 Sweep VWAP Fill", "Models queue position, bid-ask spread, and partial fills accurately for paper/eval accounts."],
  [37, 4, "Multi-Broker FIX & REST Gateway Router", "Both", "src/atlas/oms", "Alpaca / IBKR / FIX 4.4", "Connects to Interactive Brokers, Alpaca, Coinbase, cTrader, and Rithmic."],
  [38, 4, "1-Click Reverse & Partial Scale-Out Controls", "Both", "frontend/app/trade/blotter", "25% / 50% / 100% Flatten", "Allows traders to trim 25%, 50%, or 75% of an active position or flip direction instantly."],
  [39, 4, "Pre-Trade Remaining-Risk-Room Calculator", "Both", "frontend/app/trade/cockpit", "Live Post-Trade Sim", "Displays exact post-trade daily and trailing drawdown impact on the order ticket before submission."],
  [40, 4, "Idempotent Order State Machine", "Both", "src/atlas/oms", "Zero Duplicate Fills", "Prevents duplicate order submissions during network retries via unique client-order UUIDs."],

  // Category 5 (41-50)
  [41, 5, "60fps HTML5 Canvas Candlestick Engine", "Both", "frontend/src/components/market/LiveChartEngine.tsx", "TradingView Canvas Engine", "Renders smooth multi-timeframe charts powered by lightweight-charts."],
  [42, 5, "Volume Profile (VPVR) & POC/VAH/VAL Overlay", "Both", "frontend/src/components/market/LiveChartEngine.tsx", "24-Bin VPVR + POC Line", "Displays horizontal volume distribution and Point of Control directly on the price chart."],
  [43, 5, "Calibrated Uncertainty Forecast Fan Overlay", "Both", "frontend/src/components/market/LiveChartEngine.tsx", "P10 / P50 / P90 Cone", "Projects P10/P50/P90 quantitative price cones onto the live chart (execution_permission: none)."],
  [44, 5, "Visual On-Chart Trade Entry/Stop/Target Lines", "Both", "frontend/src/components/market/LiveChartEngine.tsx", "Entry / SL / TP Lines", "Renders active orders and protective stops directly on the candlestick canvas."],
  [45, 5, "Multi-Workspace Command Shell", "Both", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "4 Core Workspaces", "Organizes the terminal into 4 clean workspaces (Trading Desk, Risk & Surveillance, Quant Lab, Data & Governance)."],
  [46, 5, "Command Palette & Keyboard Hotkey Engine", "Both", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "1-Click Workspace Jump", "Supports rapid keyboard navigation across symbols, workspaces, and order actions."],
  [47, 5, "Dual-Realm Context Switcher", "Both", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Open-Market vs Prop Realm", "Switches seamlessly between Open-Market Stock Trading and Prop Trading Competitions."],
  [48, 5, "Role-Based ICP Workspace Lenses", "Both", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "ICP-01..04 Persona Views", "Tailors the interface for Prop Challengers, Open-Market Traders, Firm Founders, and Quant Researchers."],
  [49, 5, "Low-Noise Institutional Dark Theme", "Both", "frontend/app/globals.css", "WCAG AAA #070A0F + Mono", "Uses high-contrast typography and tabular-nums alignment to eliminate eye strain."],
  [50, 5, "Collapsible Quick-Jump Navigation Sidebar", "Both", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "17 Sub-Routes Synced", "Provides instant 1-click access to all sub-pages while maximizing screen real estate."],

  // Category 6 (51-60)
  [51, 6, "Multi-Phase Challenge State Machine", "Prop Competition", "src/atlas/whale_saas_az.py", "Phase 1 (+8%) -> Phase 2 (+5%)", "Automates transitions from Phase 1 (+8%) to Phase 2 (+5%) to Funded Live status."],
  [52, 6, "35% Single-Day Profit Consistency Gate", "Prop Competition", "src/atlas/control", "Max Day <= 35% Total", "Enforces balanced profit distribution so no single lucky day exceeds 35% of total challenge profit."],
  [53, 6, "Minimum Active Trading Days Tracker", "Prop Competition", "src/atlas/control", ">= 5 Qualifying Days", "Verifies that challengers meet minimum active session requirements (>= 5 days) before graduation."],
  [54, 6, "Automated Funded Account Provisioning", "Prop Competition", "src/atlas/whale_saas_az.py", "Instant Funded Credentials", "Generates funded credentials and resets drawdown baselines upon challenge completion."],
  [55, 6, "Trader Profit-Split & Payout Waterfall Calculator", "Prop Competition", "src/atlas/whale_saas_az.py", "80/20 -> 90/10 Split", "Computes 80/20 or 90/10 profit splits, performance bonuses, and challenge fee refunds."],
  [56, 6, "Competition Leaderboard & Live Equity Ranking", "Prop Competition", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Risk-Adjusted Rank", "Ranks tournament participants by risk-adjusted return, drawdown discipline, and Sharpe ratio."],
  [57, 6, "Custom Challenge Rulebook Builder", "Prop Competition", "frontend/app/control/rulebook", "$50k / $100k / $250k Presets", "Allows prop firm operators to configure custom account sizes, targets, and drawdown types."],
  [58, 6, "Automated Certificate & Funded Badge Generator", "Prop Competition", "src/atlas/whale_saas_az.py", "SHA-256 Verified Badge", "Issues cryptographically verifiable payout and graduation certificates for traders."],
  [59, 6, "Account Reset, Top-Up & Extension Billing Flow", "Prop Competition", "frontend/app/data/governance", "Ledger 1 Non-Custodial", "Handles challenge retries and subscription renewals cleanly in the non-custodial billing ledger."],
  [60, 6, "Behavioral Coaching & Revenge-Trading Guard", "Both", "frontend/app/trade/journal", "15m Cool-Down Trigger", "Detects rapid lot-size escalation after consecutive losses and triggers a cool-down warning."],

  // Category 7 (61-70)
  [61, 7, "Cross-Account Sybil & Copy-Bot Graph Clustering", "Prop Competition", "frontend/app/control/surveillance", "rho > 0.92 & dt < 50ms", "Flags synchronized order entry (dt < 50ms, rho > 0.92) across separate accounts."],
  [62, 7, "Reverse-Hedging & Group Arbitrage Detector", "Prop Competition", "frontend/app/control/surveillance", "Opposite-Leg Match", "Identifies coordinated accounts taking opposite sides of high-volatility events to game challenge fees."],
  [63, 7, "Latency Arbitrage & Stale-Tick Exploitation Guard", "Prop Competition", "frontend/app/control/surveillance", "Sub-5ms Stale Fill Reject", "Detects and nullifies trades attempting to pick off delayed broker quotes."],
  [64, 7, "IP, ASN, Geolocation & VPN/Proxy Telemetry", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Datacenter Proxy Block", "Alerts compliance when an account logs in from conflicting jurisdictions or residential proxies."],
  [65, 7, "Order-to-Cancel Ratio & Spoofing Monitor", "Both", "frontend/app/control/surveillance", "OTR <= 15:1 Gate", "Flags accounts that flood the order book with fake liquidity to manipulate simulated fills."],
  [66, 7, "Martingale & Grid-Bot Pattern Classifier", "Prop Competition", "frontend/app/control/surveillance", "2.0x Geometric Lot Flag", "Detects prohibited geometric position-doubling strategies in funded accounts."],
  [67, 7, "Expert Advisor (EA) & Script Signature Fingerprinting", "Prop Competition", "frontend/app/control/surveillance", "Order Timing Entropy", "Identifies mass-distributed commercial bots violating unique-strategy prop rules."],
  [68, 7, "1-Click Account Quarantine & Payout Hold", "Prop Competition", "frontend/app/control/surveillance", "Instant Compliance Freeze", "Freezes suspicious accounts and routes full audit packets to the compliance officer."],
  [69, 7, " Wash-Trading & Self-Match Prevention (SMP)", "Both", "src/atlas/oms", "SMP Cancel-Newest", "Blocks crossing buy and sell orders originating from the same beneficial owner."],
  [70, 7, "Immutable Surveillance Evidence Packet Exporter", "Both", "src/atlas/control", "Signed Audit JSON/CSV", "Compiles trade logs, IP traces, and webcam snapshots into a single dispute-defense report."],

  // Category 8 (71-80)
  [71, 8, "Purged & Embargoed Walk-Forward Cross-Validation", "Both", "frontend/app/research/walk-forward", "5-Fold Purged + Embargo", "Trains and evaluates models without forward-looking data leakage."],
  [72, 8, "Deflated Sharpe Ratio (DSR) Multiple-Testing Gate", "Both", "frontend/app/research/walk-forward", "DSR >= 0.95 Gate", "Penalizes backtest overfitting across challenger model tournaments (DSR >= 0.95)."],
  [73, 8, "Probability Calibration & Brier/ECE Scorer", "Both", "frontend/app/research/registry", "ECE <= 0.035 Gate", "Ensures model confidence scores match empirical realized hit rates (ECE <= 0.035)."],
  [74, 8, "Challenger vs. Champion Model Tournament (CB-01..06)", "Both", "frontend/app/research/walk-forward", "6 Model Families", "Benchmarks Ridge, GBDT, Temporal Transformers, and Regime Ensembles side by side."],
  [75, 8, "Hawkes Process Self-Exciting Order Arrival Model", "Both", "src/atlas/whale_saas_az.py", "alpha/beta < 1.0", "Forecasts short-term volatility clustering and liquidation cascades."],
  [76, 8, "Hidden Iceberg & Institutional Whale Classifier", "Both", "frontend/app/research/microstructure", "WF-01..WF-08 Signals", "Detects large resting institutional orders replenishing at identical price levels."],
  [77, 8, "Market Regime State Classifier", "Both", "frontend/app/research/central-node", "4 Causal Regime States", "Labels market conditions into Compression, Expansion, Mean-Reversion, or Toxic Flow."],
  [78, 8, "Feature Ablation & Drift Attribution Engine", "Both", "frontend/app/research/walk-forward", "Shapley / IC Decay", "Monitors feature importance decay and alerts researchers when alpha signals degrade."],
  [79, 8, "Point-in-Time SEC EDGAR XBRL Fundamental Parser", "Open-Market", "frontend/app/data/lakehouse", "acceptance_time <= as_of", "Extracts balance sheet and earnings metrics strictly stamped by SEC filing acceptance time."],
  [80, 8, "Human-in-the-Loop Scoped Model Promotion Gate", "Both", "frontend/app/research/registry", "Dual-Signoff Required", "Requires explicit human sign-off (ScopedLiveApproval) before any challenger model is promoted."],

  // Category 9 (81-90)
  [81, 9, "Real-Time Trader Toxicity & Alpha Scorer", "Prop Competition", "frontend/app/control/dealing-desk", "Sharpe + VPIN Routing", "Segments funded traders into profitable sharp flow vs. noise flow in real time."],
  [82, 9, "Dynamic A-Book / B-Book / Hybrid Auto-Router", "Prop Competition", "frontend/app/control/dealing-desk", "100% A / 60% H / 100% B", "Routes sharp trader flow to external liquidity providers while internalizing noise flow."],
  [83, 9, "Firm-Wide Cross-Account Net Exposure Aggregator", "Both", "frontend/app/control/dealing-desk", "Real-Time Delta Netting", "Calculates the prop firm's net directional delta across all active traders per symbol."],
  [84, 9, "Automated Tail-Risk Hedge Execution", "Both", "frontend/app/control/dealing-desk", "Auto-DMA Offset Order", "Fires offsetting DMA hedge orders when net firm B-Book exposure exceeds risk thresholds."],
  [85, 9, "Liquidity Provider (LP) Spread & Fill Quality Monitor", "Both", "frontend/app/control/dealing-desk", "LP Reject & Markout", "Tracks execution latency, reject rates, and markouts across connected institutional LPs."],
  [86, 9, "9x9 Cross-Asset Portfolio Beta & VaR Matrix", "Both", "frontend/app/control/dealing-desk", "9x9 Correlation Grid", "Computes real-time Value-at-Risk and correlation heatmaps across equities and crypto."],
  [87, 9, "Internal Crossing Engine", "Both", "frontend/app/control/dealing-desk", "Spread Savings Capture", "Matches opposing buy and sell flow across internal accounts to save external spread costs."],
  [88, 9, "Funding Rate & Overnight Carry Cost Tracker", "Both", "frontend/app/control/dealing-desk", "8h Perp Funding & Borrow", "Monitors perpetual swap funding rates and equity borrow fees across open positions."],
  [89, 9, "Stress-Test & Flash-Crash Scenario Simulator", "Both", "frontend/app/control/dealing-desk", "-10% Shock Sim", "Simulates -5% to -15% instantaneous market shocks on the dealing desk's net book."],
  [90, 9, "B2B SaaS Dealing Desk Revenue & Hedge Cost Attribution", "Prop Competition", "frontend/app/data/governance", "SAAS-12 Volume Billing", "Tracks net dealing desk P&L, LP commissions, and platform volume fees."],

  // Category 10 (91-100)
  [91, 10, "DuckDB + Apache Parquet Point-in-Time Lakehouse", "Both", "frontend/app/data/lakehouse", "Zero-Copy PIT Queries", "Stores and queries millions of historical ticks and candles with zero-copy efficiency."],
  [92, 10, "Causal SQL Query Studio (acceptance_time <= as_of)", "Both", "frontend/app/data/lakehouse", "Zero Lookahead SQL", "Enforces point-in-time temporal joins so backtest queries never leak future data."],
  [93, 10, "8 Strictly Separated Non-Custodial Financial Ledgers", "Both", "frontend/app/data/governance", "8 Books · 0 Commingling", "Isolates SaaS subscription billing from broker capital, prop evaluation books, and treasury."],
  [94, 10, "Allowlisted Read-Only MCP Connector Guard", "Both", "frontend/app/data/pipelines", "Mutating MCP Quarantined", "Permits vetted read-only data connectors while blocking external mutating MCP servers."],
  [95, 10, "Cryptographic SHA-256 Audit Trail & Dataset Manifests", "Both", "frontend/app/data/pipelines", "SHA-256 Chain of Custody", "Hashes every risk decision, model training dataset, and configuration change."],
  [96, 10, "Secret-Screened Prompt & Log Sanitizer", "Both", "src/atlas/control", "API Keys Redacted", "Strips API keys, credentials, and PII automatically before any payload reaches logs or LLMs."],
  [97, 10, "ISO/IEC 42001, NIST AI RMF & IOSCO Compliance Matrix", "Both", "frontend/app/data/governance", "100% Readiness Verified", "Maps every platform control directly to international algorithmic and AI governance standards."],
  [98, 10, "Multi-Tenant B2B White-Label & Seat Billing Engine", "Prop Competition", "frontend/app/data/governance", "$2.5k Base + Tiered Seats", "Calculates tiered seat pricing and hedged volume fees for institutional prop firm clients."],
  [99, 10, "Role-Based Access Control (RBAC) & IP Ownership Guard", "Both", "src/atlas/api/app.py", "4 Roles · 100% Founder IP", "Separates permissions across Founder Admin, Quant Researcher, Funded Trader, and Auditor."],
  [100, 10, "Master Roadmap CSV & Markdown Export Engine", "Both", "src/atlas/whale_saas_az.py", "9 Exported CSV Sheets", "Synchronizes all platform specifications, ICP pipelines, and 100-feature matrices to local CSVs."],
];

export const HUNDRED_FEATURES_LIST: Feature100Item[] = RAW_100_ROWS.map(
  ([num, catId, name, realm, subsystem, metric, description]) => {
    const catMeta = TEN_CATEGORIES_META.find((c) => c.id === catId)!;
    return {
      featureId: `F-${String(num).padStart(3, "0")}`,
      number: num,
      categoryId: catId,
      categoryTitle: catMeta.title,
      name,
      realm,
      subsystem,
      metric,
      description,
    };
  }
);

export interface ProctoringScenarioPreset {
  id: "verified" | "proxy_coaching" | "obs_virtual" | "gaze_deviation";
  label: string;
  traderId: string;
  cameraDriver: string;
  hardwareGuid: string;
  registeredGuid: string;
  faceCount: number;
  biometricSimilarity: number;
  blinkPassed: boolean;
  headYawDeg: number;
  gazeOffScreenSec: number;
  concurrentOrderId: string;
  mobileRoomScan: boolean;
  status: "VERIFIED_PASS" | "WARNING_REVIEW" | "CRITICAL_BREACH";
  controlAction: string;
  watermarkSha256: string;
  anomalies: string[];
}

export const PROCTORING_SCENARIO_PRESETS: ProctoringScenarioPreset[] = [
  {
    id: "verified",
    label: "1. Verified Single Trader (Logitech Brio 4K · 96.8% Match)",
    traderId: "TRD-0412 (A. Vance · $100K Phase 2)",
    cameraDriver: "Logitech Brio 4K USB Video Device",
    hardwareGuid: "HW-GUID-9921-BRIO-4K",
    registeredGuid: "HW-GUID-9921-BRIO-4K",
    faceCount: 1,
    biometricSimilarity: 0.968,
    blinkPassed: true,
    headYawDeg: 3.8,
    gazeOffScreenSec: 0.35,
    concurrentOrderId: "ORD-COMP-99041",
    mobileRoomScan: true,
    status: "VERIFIED_PASS",
    controlAction: "ALLOW_EXECUTION",
    watermarkSha256: "9f84c2e10b7a4f38d16e5290a8c3b1e744f9201d8a3c6b5e0192f4a7c8d3e112",
    anomalies: [],
  },
  {
    id: "proxy_coaching",
    label: "2. Proxy Coaching / Multiple Faces Detected (2 Faces in Frame)",
    traderId: "TRD-0819 (K. Patel · $100K Funded)",
    cameraDriver: "Sony Alpha USB Capture UVC",
    hardwareGuid: "HW-GUID-4410-UVC",
    registeredGuid: "HW-GUID-4410-UVC",
    faceCount: 2,
    biometricSimilarity: 0.941,
    blinkPassed: true,
    headYawDeg: 6.2,
    gazeOffScreenSec: 1.8,
    concurrentOrderId: "ORD-COMP-99088",
    mobileRoomScan: true,
    status: "CRITICAL_BREACH",
    controlAction: "QUARANTINE_ACCOUNT_AND_HOLD_PAYOUT",
    watermarkSha256: "3e11b7a94c02d8f56a12e904c7b3d1f882a04e6c9d1b3f7a5e20c4d8b9a1f304",
    anomalies: ["PROXY_TRADING_MULTIPLE_FACES (2 faces detected in active funded session)"],
  },
  {
    id: "obs_virtual",
    label: "3. Virtual Camera / OBS Video Injection Attempt",
    traderId: "TRD-1104 (M. Volkov · $250K Eval)",
    cameraDriver: "OBS Virtual Camera (DirectShow Loopback)",
    hardwareGuid: "HW-GUID-0000-VIRTUAL",
    registeredGuid: "HW-GUID-7731-WEBCAM",
    faceCount: 1,
    biometricSimilarity: 0.84,
    blinkPassed: false,
    headYawDeg: 0.2,
    gazeOffScreenSec: 0.0,
    concurrentOrderId: "ORD-COMP-99105",
    mobileRoomScan: false,
    status: "CRITICAL_BREACH",
    controlAction: "BLOCK_ORDER_ENTRY_AND_LOCK_TERMINAL",
    watermarkSha256: "7c49d1a08e3f5b2291c6a4d0e8b7f31950a2c4e6d8b1f903a7c5e2d4b6f8a019",
    anomalies: [
      "VIRTUAL_CAMERA_DRIVER_BLOCKED (OBS Virtual Camera)",
      "BIOMETRIC_FACE_MISMATCH (0.840 < 0.92)",
      "LIVENESS_CHALLENGE_FAILED (blink=False, yaw=0.2 deg)",
      "HARDWARE_GUID_MISMATCH (HW-GUID-0000-VIRTUAL != HW-GUID-7731-WEBCAM)",
      "DUAL_CAMERA_MOBILE_HANDOFF_PENDING",
    ],
  },
  {
    id: "gaze_deviation",
    label: "4. Off-Screen Gaze Vector Warning (6.2s External Screen Glance)",
    traderId: "TRD-0551 (J. Chen · $50K Sprint)",
    cameraDriver: "Elgato Facecam Pro USB 3.0",
    hardwareGuid: "HW-GUID-6120-ELGATO",
    registeredGuid: "HW-GUID-6120-ELGATO",
    faceCount: 1,
    biometricSimilarity: 0.954,
    blinkPassed: true,
    headYawDeg: 18.4,
    gazeOffScreenSec: 6.2,
    concurrentOrderId: "ORD-COMP-99129",
    mobileRoomScan: true,
    status: "WARNING_REVIEW",
    controlAction: "FLAG_COMPLIANCE_REVIEW_QUEUE",
    watermarkSha256: "5a20f8c31d9b4e7602a8c5f1d3b9e40761c2a9f4e8d0b3c7a5f1e9d2b4c6a821",
    anomalies: ["GAZE_OFF_SCREEN_EXCEEDED (6.2s > 4.0s threshold)"],
  },
];

