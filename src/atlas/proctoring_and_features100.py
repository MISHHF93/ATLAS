"""Comprehensive 100-Feature Technical Breakdown & Webcam Proctoring Engine.

Implements:
- Category 1 (Features 1-10): Webcam Proctoring, Biometric KYC, Liveness & Anti-Spoofing,
  Multiple-Face Proxy Detection, Gaze Telemetry, OBS/Virtual Camera Driver Filter,
  SHA-256 Snapshot Watermarking, Hardware Fingerprinting, Dual-Camera Mobile QR Handoff,
  and Proctoring Flag Review Timeline.
- Categories 1-10 (Features 1-100): feature catalogue with a verified per-feature status
  (Implemented / Partial / Planned, see FEATURE_STATUS). Telemetry is not measured.
- Category 1 checks run on caller-supplied values: no camera, biometric or OS driver access.

All analytical and proctoring outputs strictly enforce `execution_permission: "none"`.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BLOCKED_VIRTUAL_CAMERA_DRIVERS: tuple[str, ...] = (
    "obs virtual camera",
    "obs-camera",
    "manycam",
    "splitcam",
    "xsplit",
    "snap camera",
    "v4l2loopback",
    "virtualcam",
)


@dataclass(frozen=True)
class ProctoringFrameEvaluation:
    """Result of evaluating a webcam proctoring frame during onboarding or live trading."""

    frame_id: str
    trader_id: str
    timestamp_utc: str
    concurrent_order_id: str
    biometric_match_score: float
    biometric_kyc_passed: bool
    liveness_passed: bool
    face_count: int
    proxy_trading_flagged: bool
    gaze_off_screen_pct: float
    gaze_deviation_flagged: bool
    camera_driver: str
    virtual_camera_blocked: bool
    hardware_guid: str
    dual_camera_mobile_active: bool
    watermark_sha256: str
    proctoring_status: str
    violations: list[str]
    execution_permission: str = "none"


class WebcamProctoringEngine:
    """Deterministic Webcam Proctoring, Biometric KYC & Trader Integrity Engine (Features 1-10)."""

    def __init__(self) -> None:
        self._review_timeline: list[ProctoringFrameEvaluation] = []
        self._registered_hardware: dict[str, str] = {
            "TRADER-001": "HW-GUID-9921-LOGI-4K",
            "TRADER-002": "HW-GUID-4410-FACEID-PRO",
        }

    def evaluate_frame(
        self,
        *,
        trader_id: str = "TRADER-001",
        biometric_match_score: float = 0.984,
        eye_blink_detected: bool = True,
        head_yaw_degrees: float = 12.5,
        face_count: int = 1,
        gaze_off_screen_pct: float = 0.08,
        camera_driver: str = "USB Video Device (Integrated IR Webcam)",
        concurrent_order_id: str = "ORD-2026-8841",
        hardware_guid: str = "HW-GUID-9921-LOGI-4K",
        dual_camera_mobile_active: bool = True,
        timestamp: datetime | None = None,
    ) -> ProctoringFrameEvaluation:
        now_dt = timestamp or datetime.now(timezone.utc)
        ts_str = now_dt.isoformat()
        violations: list[str] = []

        # Feature 1: Webcam Biometric Face-Match Verification (KYC)
        biometric_kyc_passed = biometric_match_score >= 0.90
        if not biometric_kyc_passed:
            violations.append(f"biometric_face_mismatch:{biometric_match_score:.3f}<0.900")

        # Feature 2: Liveness Detection & Anti-Spoofing
        liveness_passed = bool(eye_blink_detected and abs(head_yaw_degrees) >= 5.0)
        if not liveness_passed:
            violations.append("liveness_challenge_failed:blink_or_head_turn_missing")

        # Feature 3 & 4: Session Continuous Re-Auth & Multiple Face / Proxy-Trading Detection
        proxy_trading_flagged = face_count != 1
        if face_count > 1:
            violations.append(f"proxy_trading_multiple_faces_detected:count={face_count}")
        elif face_count < 1:
            violations.append("trader_absent_from_frame:count=0")

        # Feature 5: Gaze & Screen Tracking Telemetry
        gaze_deviation_flagged = gaze_off_screen_pct > 0.35
        if gaze_deviation_flagged:
            violations.append(f"gaze_deviation_exceeded:{gaze_off_screen_pct:.2f}>0.35")

        # Feature 6: Virtual Camera & OBS Driver Filter
        driver_lower = camera_driver.strip().lower()
        virtual_camera_blocked = any(sig in driver_lower for sig in BLOCKED_VIRTUAL_CAMERA_DRIVERS)
        if virtual_camera_blocked:
            violations.append(f"virtual_camera_driver_blocked:{camera_driver}")

        # Feature 8: Hardware Device & Peripheral Fingerprinting
        expected_guid = self._registered_hardware.get(trader_id)
        if expected_guid and expected_guid != hardware_guid:
            violations.append(f"hardware_guid_mismatch:{hardware_guid}!={expected_guid}")

        # Feature 7: Periodic Identity Snapshot Watermarking
        watermark_payload = (
            f"{trader_id}|{ts_str}|{concurrent_order_id}|{biometric_match_score:.4f}|"
            f"faces={face_count}|{hardware_guid}"
        )
        watermark_sha256 = hashlib.sha256(watermark_payload.encode("utf-8")).hexdigest()

        status = "VERIFIED_COMPLIANT" if not violations else "FLAGGED_FOR_COMPLIANCE"
        frame_eval = ProctoringFrameEvaluation(
            frame_id=f"PROC-{len(self._review_timeline) + 1:04d}",
            trader_id=trader_id,
            timestamp_utc=ts_str,
            concurrent_order_id=concurrent_order_id,
            biometric_match_score=round(biometric_match_score, 4),
            biometric_kyc_passed=biometric_kyc_passed,
            liveness_passed=liveness_passed,
            face_count=face_count,
            proxy_trading_flagged=proxy_trading_flagged,
            gaze_off_screen_pct=round(gaze_off_screen_pct, 4),
            gaze_deviation_flagged=gaze_deviation_flagged,
            camera_driver=camera_driver,
            virtual_camera_blocked=virtual_camera_blocked,
            hardware_guid=hardware_guid,
            dual_camera_mobile_active=dual_camera_mobile_active,
            watermark_sha256=watermark_sha256,
            proctoring_status=status,
            violations=violations,
            execution_permission="none",
        )
        self._review_timeline.append(frame_eval)
        return frame_eval

    def create_dual_camera_mobile_handoff(self, trader_id: str, evaluation_tier: str = "100k_2phase") -> dict[str, Any]:
        """Feature 9: Generates a QR handoff payload for over-the-shoulder smartphone proctoring."""
        token_seed = f"{trader_id}|{evaluation_tier}|mobile_room_cam_v1"
        handoff_token = hashlib.sha256(token_seed.encode("utf-8")).hexdigest()[:24]
        return {
            "trader_id": trader_id,
            "evaluation_tier": evaluation_tier,
            "handoff_token": handoff_token,
            "qr_uri": f"atlas://proctor-mobile?trader={trader_id}&tier={evaluation_tier}&token={handoff_token}",
            "room_view_status": "OVER_SHOULDER_SYNCED",
            "execution_permission": "none",
        }

    def get_review_timeline(self) -> list[dict[str, Any]]:
        """Feature 10: Scrubbable compliance timeline of webcam captures linked to orders."""
        if not self._review_timeline:
            self.evaluate_frame()
        return [asdict(item) for item in self._review_timeline]


# ============================================================================
# COMPREHENSIVE 100-FEATURE TECHNICAL CATALOG (CATEGORIES 1 TO 10)
# ============================================================================

CATEGORY_METADATA: dict[int, dict[str, str]] = {
    1: {
        "name": "Webcam Proctoring, Identity Verification & Trader Integrity",
        "range": "1-10",
        "workspace_route": "/control/proctoring",
        "icp": "ICP-01 / ICP-03",
    },
    2: {
        "name": "Live Market Data, Microstructure & Order Book Feeds",
        "range": "11-20",
        "workspace_route": "/trade/depth-dom",
        "icp": "ICP-02 / ICP-04",
    },
    3: {
        "name": "Deterministic Risk Management System (RMS) & Circuit Breakers",
        "range": "21-30",
        "workspace_route": "/control/rulebook",
        "icp": "ICP-01 / ICP-03",
    },
    4: {
        "name": "Order Management System (OMS) & Execution Tactics",
        "range": "31-40",
        "workspace_route": "/trade/cockpit",
        "icp": "ICP-01 / ICP-02",
    },
    5: {
        "name": "Charting, Workbench & Terminal User Experience",
        "range": "41-50",
        "workspace_route": "/trade/cockpit",
        "icp": "ICP-01 / ICP-02",
    },
    6: {
        "name": "Prop Firm Evaluation & Lifecycle Engine",
        "range": "51-60",
        "workspace_route": "/control/risk-hud",
        "icp": "ICP-01 / ICP-03",
    },
    7: {
        "name": "Anti-Cheating, Surveillance & Sybil Guard",
        "range": "61-70",
        "workspace_route": "/control/surveillance",
        "icp": "ICP-03",
    },
    8: {
        "name": "Quantitative Research, Machine Learning & Analytics",
        "range": "71-80",
        "workspace_route": "/research/walk-forward",
        "icp": "ICP-04",
    },
    9: {
        "name": "Dealing Desk, B-Book Hedging & Liquidity Routing",
        "range": "81-90",
        "workspace_route": "/control/dealing-desk",
        "icp": "ICP-03 / ICP-04",
    },
    10: {
        "name": "Enterprise Architecture, Storage & Compliance",
        "range": "91-100",
        "workspace_route": "/data/governance",
        "icp": "ICP-03 / ICP-04",
    },
}


RAW_100_FEATURES: list[tuple[int, int, str, str, str, str, str]] = [
    # Category 1: Webcam Proctoring, Identity Verification & Trader Integrity (1-10)
    (1, 1, "Webcam Biometric Face-Match Verification (KYC)", "Compares live camera stream against government ID during trader onboarding.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (2, 1, "Liveness Detection & Anti-Spoofing", "Active eye-blinking and head-turning challenges blocking deepfakes and photo loops.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (3, 1, "Session Continuous Facial Re-Authentication", "Periodically captures passive webcam frames during live funded trading sessions.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (4, 1, "Multiple Face / Proxy-Trading Detection", "Flags secondary individuals coaching or executing trades alongside the applicant.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (5, 1, "Gaze & Screen Tracking Telemetry", "Tracks eye-tracking vectors away from the primary terminal screen during evaluations.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (6, 1, "Virtual Camera & OBS Driver Filter", "Scans OS video device drivers to block OBS virtual feeds and video injection.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (7, 1, "Periodic Identity Snapshot Watermarking", "Cryptographically timestamps and SHA-256 hashes webcam captures against trade IDs.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (8, 1, "Hardware Device & Peripheral Fingerprinting", "Cross-correlates webcam hardware GUIDs, monitors, and canvas fingerprints.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (9, 1, "Dual-Camera Mobile Proctoring Handoff", "Prompts secondary smartphone camera via QR code for over-the-shoulder room view.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (10, 1, "Automated Proctoring Flag Review Desk", "Provides compliance officers with a scrubbable video timeline synchronized with orders.", "Prop Competition", "frontend/app/control/proctoring", "Not measured"),

    # Category 2: Live Market Data, Microstructure & Order Book Feeds (11-20)
    (11, 2, "Tick-by-Tick Level 3 Market-by-Order (MBO) Parser", "Ingests granular queue positions and order IDs from ITCH / CME MDP 3.0 protocols.", "Both Realms", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (12, 2, "Aggregated Level 2 Top-of-Book Depth Engine", "Maintains rolling low-latency 10-to-50 level bid/ask price and volume ladder.", "Both Realms", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (13, 2, "Sub-Millisecond WebSocket Market Gateway", "High-throughput async streaming pipeline with automated heartbeat drop recovery.", "Both Realms", "src/atlas/api/ws.py", "Not measured"),
    (14, 2, "Volume-Synchronized Probability of Informed Trading (VPIN)", "Groups market trade prints into equal-volume buckets to measure toxic flow.", "Both Realms", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (15, 2, "Rolling Order Flow Imbalance (OFI) Calculator", "Evaluates microsecond delta changes in top-5 bid/ask queues for directional pressure.", "Both Realms", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (16, 2, "Dynamic Kyle's Lambda Liquidity Estimator", "Continuously calculates price impact coefficient per unit of executed order size.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (17, 2, "Point of Control (POC) & Value Area Engine", "Computes intraday volume profiles displaying Value Area High (VAH) and Low (VAL).", "Both Realms", "frontend/src/components/market/LiveChartEngine.tsx", "Not measured"),
    (18, 2, "Cross-Exchange Perpetual Funding Rate Tracker", "Aggregates continuous and 8-hour funding rates across crypto derivative venues.", "Prop Competition", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (19, 2, "Exchange Auction Imbalance Tracker", "Displays paired shares, unpaired shares, and indicative match prices on NYSE/Nasdaq.", "Open-Market Trading", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (20, 2, "Market Data Freshness Gate (500ms)", "Flags feed staleness if tick updates exceed 500ms to guard against stale quotes.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),

    # Category 3: Deterministic Risk Management System (RMS) & Circuit Breakers (21-30)
    (21, 3, "Hard Daily Loss Limit Circuit Breaker", "Evaluates combined realized and unrealized PnL to liquidate and freeze at 4.0% / 3.0%.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (22, 3, "Trailing High-Water Mark Drawdown Floor", "Tracks peak account equity tick-by-tick and locks an 8.0% trailing loss floor.", "Prop Competition", "src/atlas/control/engine.py", "Not measured"),
    (23, 3, "Intraday Open Equity Drawdown Guard", "Monitors floating open losses in real time prior to candle close.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (24, 3, "Single-Day Profit Consistency Gate (<=35%)", "Flags accounts where a single trading day exceeds 35% of total challenge profit.", "Prop Competition", "src/atlas/control/engine.py", "Not measured"),
    (25, 3, "Per-Trade Equity Risk Cap", "Rejects pre-flight orders whose stop distance implies loss > 0.50%-0.75% equity.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (26, 3, "Mandatory Structural ATR Stop-Loss Validator", "Blocks market or limit orders submitted without an attached stop-loss.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (27, 3, "One-Click Emergency Kill-Switch Desk", "Dispatches immediate order cancellation and position flattening across all brokers.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (28, 3, "Dynamic Remaining-Room Calculator", "Computes exact dollar and percentage buffers remaining before drawdown limits.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (29, 3, "Maximum Notional Leverage Throttling", "Restricts total portfolio notional based on volatility regime and track rules.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (30, 3, "Weekend & Session-Close Auto-Flatten Trigger", "Liquidates open intraday exposures prior to Friday close or maintenance windows.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),

    # Category 4: Order Management System (OMS) & Execution Tactics (31-40)
    (31, 4, "Almgren-Chriss Optimal Trajectory Engine", "Slices block orders along a sinh decay path balancing impact vs volatility risk.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (32, 4, "Time-Weighted Average Price (TWAP) Execution", "Dispatches randomized child orders evenly across specified execution windows.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (33, 4, "Volume-Weighted Average Price (VWAP) Engine", "Dynamically paces child orders against historical and intraday volume curves.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (34, 4, "Iceberg Order Engine", "Displays small visible clip sizes at top of book while replenishing hidden inventory.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (35, 4, "One-Cancels-the-Other (OCO) Bracket Slicing", "Links simultaneous profit-target limit orders and protective stop-market orders.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (36, 4, "Post-Only Maker Validation Engine", "Ensures passive limit orders rest on the book without crossing spread as taker.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (37, 4, "Immediate-or-Cancel (IOC) Sweeper", "Executes available resting volume up to strict slippage boundary and cancels remainder.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (38, 4, "Multi-Leg Spread Execution Router", "Simultaneously executes paired assets for basis/delta arbitrage with auto-unwind.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (39, 4, "Smart Order Routing (SOR) Gateway", "Distributes equity orders across lit exchanges (XNYS, XNAS, ARCA) and ATS pools.", "Open-Market Trading", "src/atlas/whale_saas_az.py", "Not measured"),
    (40, 4, "Sub-Millisecond FIX 4.4 / 5.0 Engine", "Maintains persistent low-latency FIX sessions with prime brokers and LPs.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),

    # Category 5: Charting, Workbench & Terminal User Experience (41-50)
    (41, 5, "60 FPS Hardware-Accelerated Canvas Charting", "Renders continuous tick, minute, hourly, and daily candles with volume histograms.", "Both Realms", "frontend/src/components/market/LiveChartEngine.tsx", "Not measured"),
    (42, 5, "Multi-Horizon Forecast Fan Overlay (t+1h / t+2h)", "Projects statistical uncertainty cones and GBDT trajectories over price candles.", "Both Realms", "frontend/src/components/market/LiveChartEngine.tsx", "Not measured"),
    (43, 5, "Interactive Depth of Market (DOM) Ladder", "Order book ladder displaying resting bid/ask volumes with proportional depth bars.", "Both Realms", "frontend/app/trade/depth-dom", "Not measured"),
    (44, 5, "Intraday Footprint & Cluster Charts", "Displays buy/sell volume deltas and bid-ask imbalance inside price bars.", "Both Realms", "frontend/src/components/market/LiveChartEngine.tsx", "Not measured"),
    (45, 5, "Multi-Monitor Detachable Workspaces", "Supports 4 Core Operational Workspaces and 17 dedicated App Router URLs.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (46, 5, "Real-Time Remaining-Room HUD Bar", "Persistent top header progress bars for daily loss and trailing drawdown buffers.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (47, 5, "Interactive Point of Control (POC) Ray", "Extends horizontal dashed volume-node rays across the chart canvas.", "Both Realms", "frontend/src/components/market/LiveChartEngine.tsx", "Not measured"),
    (48, 5, "Integrated Pre-Trade Order Desk", "Formulates notional, ATR stop bps, and post-trade drawdown room before submission.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (49, 5, "Historical Market Bar Replay Simulator", "Deterministic point-in-time session replay for strategy and rule verification.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (50, 5, "Global Quick Ticker Strip", "1-click symbol switcher displaying live prices and 24h changes across stocks & perps.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),

    # Category 6: Prop Firm Evaluation & Lifecycle Engine (51-60)
    (51, 6, "Automated Multi-Phase Challenge Provisioning", "Provisions $50K Sprint, $100K 2-Phase, and $250K Institutional accounts.", "Prop Competition", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (52, 6, "Minimum Active Trading Days Counter (>=5 Days)", "Tracks qualifying active trading days to enforce challenge completion rules.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (53, 6, "Automated Scaling & Capital Allocation Ladder", "Increases account balance and risk allowances upon hitting sustained profit targets.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (54, 6, "Automated Profit Split Calculator (80/20 & 90/10)", "Computes trader performance payouts based on realized net closed profits.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (55, 6, "Instant Challenge Reset / Retry Checkout", "Allows traders breaching soft thresholds to reset evaluation accounts cleanly.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (56, 6, "Trader Verification Badge Engine", "Generates SHA-256 verifiable digital certificates upon passing evaluation phases.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (57, 6, "Trader Leaderboard & Performance Scorecard", "Ranks competition participants by Sharpe ratio, win rate, and drawdown control.", "Prop Competition", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (58, 6, "Automated Payout Gateway Integration", "Reconciles approved performance payouts via Ledger 6 & Ledger 8 double-entry books.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (59, 6, "Trader Performance Milestone Alerts", "Dispatches real-time alerts when approaching +8% target or 75% drawdown utilization.", "Prop Competition", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (60, 6, "Rule Breach Post-Mortem Generator", "Produces exact timestamp, fill price, and violated rule clause on any breach.", "Prop Competition", "src/atlas/control/engine.py", "Not measured"),

    # Category 7: Anti-Cheating, Surveillance & Sybil Guard (61-70)
    (61, 7, "Copy-Trading Ring Detection Engine", "Flags identical trade timestamps and lot sizes across accounts (ρ > 0.92, Δt < 50ms).", "Prop Competition", "frontend/app/control/surveillance", "Not measured"),
    (62, 7, "Latency Arbitrage Trade Identifier", "Detects scalping fills exploiting momentary broker lag vs primary SIP/MDP3 feeds.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (63, 7, "Tick-to-Trade Behavioral Fingerprinting", "Profiles order entry cadence and mouse/API timing to detect unauthorized bots.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (64, 7, "Hedging / Reverse-Trading Surveillance", "Detects opposing buy/sell orders placed simultaneously across two challenge accounts.", "Prop Competition", "frontend/app/control/surveillance", "Not measured"),
    (65, 7, "News Straddle Order Trap Guard", "Restricts bracket straddle traps ±2 minutes around Tier-1 FOMC/CPI/NFP releases.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (66, 7, "High-Frequency Quote Stuffing Detector", "Blocks rapid order placement/cancellation bursts (>50 msg/sec) degrading venue fills.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (67, 7, "Account Sharing IP & Subnet Scanner", "Flags impossible travel or simultaneous cross-region IP sessions during open trades.", "Prop Competition", "src/atlas/proctoring_and_features100.py", "Not measured"),
    (68, 7, "Off-Market Slippage Anomaly Detector", "Verifies fill prices against underlying exchange L1/L2 prints.", "Both Realms", "src/atlas/marketdata/live_stream.py", "Not measured"),
    (69, 7, "Toxic Flow Scoring Algorithm", "Computes post-fill markout curves and VPIN adverse selection ratios per account.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (70, 7, "Automated Account Disqualification Gate", "Suspends challenge access and freezes orders upon confirmed Sybil or proctoring breach.", "Prop Competition", "frontend/app/control/surveillance", "Not measured"),

    # Category 8: Quantitative Research, Machine Learning & Analytics (71-80)
    (71, 8, "Air-Gapped Research Isolation (execution_permission: none)", "Strict architectural barrier preventing AI/research models from placing orders.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (72, 8, "Causal Regime Classification Engine", "Tags Volatility, Trend, Liquidity, and Auction regimes using strictly backward-looking bars.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (73, 8, "Purged & Embargoed Walk-Forward Evaluator", "Evaluates models across rolling folds with 3-bar purge and 2-bar embargo windows.", "Both Realms", "frontend/app/research/walk-forward", "Not measured"),
    (74, 8, "Triple-Barrier Labeling Engine", "Labels training observations by profit-take, stop-loss, or vertical time barrier touch.", "Both Realms", "src/atlas/experiments", "Not measured"),
    (75, 8, "Point-in-Time (PIT) SEC XBRL Ingestion Engine", "Parses 10-K/10-Q fundamentals strictly enforcing acceptance_time <= as_of.", "Open-Market Trading", "frontend/app/data/lakehouse", "Not measured"),
    (76, 8, "Hawkes Self-Exciting Point Process (WF-07)", "Detects hidden iceberg refills via trade arrival intensity clustering λ(t).", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (77, 8, "Gradient Boosted Decision Tree Spread Predictor (WF-05)", "Predicts short-term spread widening from OFI, VPIN, and L2 book Shannon entropy.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (78, 8, "Probability Calibration Engine (ECE <= 0.035)", "Calibrates raw model scores into empirical hit rates via Platt/isotonic scaling.", "Both Realms", "frontend/app/research/registry", "Not measured"),
    (79, 8, "Feature Ablation & Importance Matrix", "Quantifies out-of-sample return lift and MAE drop across OFI, VPIN, and SEC XBRL.", "Both Realms", "frontend/app/research/walk-forward", "Not measured"),
    (80, 8, "Automated Model Alias Promotion / Rollback Gate", "Requires DSR >= 0.95 and human ScopedLiveApproval before promoting challengers.", "Both Realms", "frontend/app/research/registry", "Not measured"),

    # Category 9: Dealing Desk, B-Book Hedging & Liquidity Routing (81-90)
    (81, 9, "Dynamic A-Book vs. B-Book Smart Router (SAAS-04)", "Routes high-Sharpe or toxic flow externally while internalizing uninformed flow.", "Both Realms", "frontend/app/control/dealing-desk", "Not measured"),
    (82, 9, "Delta Neutral Inventory Balancer", "Aggregates net directional exposure across accounts and executes delta hedges.", "Both Realms", "frontend/app/control/dealing-desk", "Not measured"),
    (83, 9, "Synthetic Copy-Trading Hub", "Replicates top-performing funded trader signals onto firm capital with risk multipliers.", "Prop Competition", "frontend/app/control/dealing-desk", "Not measured"),
    (84, 9, "Liquidity Provider Slippage & Execution Monitor", "Tracks fill ratios, latency, and implementation shortfall across 6 broker gateways.", "Both Realms", "frontend/app/data/pipelines", "Not measured"),
    (85, 9, "Internal Netting & Crossing Engine", "Matches opposing buy and sell flow across internal traders to save spread costs.", "Both Realms", "frontend/app/control/dealing-desk", "Not measured"),
    (86, 9, "Spread Markup & Commission Schedule Engine", "Applies transparent institutional commission and spread tiers per challenge type.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (87, 9, "Overnight Swap & Financing Rate Engine", "Tracks 8-hour perpetual funding and overnight Reg-T carry across open positions.", "Both Realms", "src/atlas/whale_saas_az.py", "Not measured"),
    (88, 9, "Dark Pool Fill Emulation Engine", "Simulates realistic queue position and Kyle's Lambda impact on evaluation fills.", "Prop Competition", "src/atlas/whale_saas_az.py", "Not measured"),
    (89, 9, "Dealing Desk Risk Exposure Matrix (9x9)", "Visualizes cross-asset correlation and enforces cluster correlation cap ρ <= 0.80.", "Both Realms", "frontend/app/control/dealing-desk", "Not measured"),
    (90, 9, "External Broker Margin & Equity Surveillance", "Monitors prime broker and LP margin utilization to prevent clearing bottlenecks.", "Both Realms", "frontend/app/control/risk-hud", "Not measured"),

    # Category 10: Enterprise Architecture, Storage & Compliance (91-100)
    (91, 10, "8 Strictly Separated Non-Custodial Money Ledgers", "Isolates SaaS subscriptions, broker capital, prop rules, and treasury with zero commingling.", "Both Realms", "frontend/app/data/governance", "Not measured"),
    (92, 10, "Immutable Append-Only Audit Trail", "Records all order decisions, kill-switch triggers, and proctoring watermarks with SHA-256.", "Both Realms", "src/atlas/control/engine.py", "Not measured"),
    (93, 10, "Point-in-Time Analytical Lakehouse (DuckDB / Parquet)", "Stores ZSTD Parquet tick and bar series queryable via zero-copy vectorized SQL.", "Both Realms", "frontend/app/data/lakehouse", "Not measured"),
    (94, 10, "BigQuery Enterprise Tick Archive", "Petabyte-scale longitudinal tick and L2 depth archive for multi-year walk-forward studies.", "Both Realms", "frontend/app/data/lakehouse", "Not measured"),
    (95, 10, "Role-Based Access Control (RBAC) Engine", "Enforces strict permissions across Founder/Admin, Quant Researcher, Funded Trader, and Auditor.", "Both Realms", "frontend/src/components/shell/InstitutionalWorkspacesView.tsx", "Not measured"),
    (96, 10, "FRED Data Training Firewall", "Blocks ML model training on restricted third-party FRED macroeconomic series per license terms.", "Both Realms", "frontend/app/data/pipelines", "Not measured"),
    (97, 10, "Quarantined MCP Tool Guard", "Allowlists read-only research MCP servers and blocks mutating servers (irohan0/quant-mcp).", "Both Realms", "frontend/app/data/pipelines", "Not measured"),
    (98, 10, "Automated Daily Trade Confirmation & Statement Dispatch", "Generates post-session trade blotter summaries and risk compliance digests.", "Both Realms", "frontend/app/trade/journal", "Not measured"),
    (99, 10, "Zero-Leak Secret Masking Engine", "Scans research prompts and API payloads to scrub API keys, tokens, or credentials.", "Both Realms", "frontend/app/research/central-node", "Not measured"),
    (100, 10, "ISO/IEC 42001, NIST AI RMF & IOSCO Compliance Exporter", "Exports governance readiness matrices and full 9-sheet Master Roadmap CSVs.", "Both Realms", "frontend/app/data/governance", "Not measured"),
]


# Verified 2026-10-23 against code/tests on main@c87ef50 (see root workbook). Implemented = code + tests;
# Partial = some code, or a rule on caller-supplied/sample inputs; Planned = not implemented. Paper only.
FEATURE_STATUS: dict[int, tuple[str, str]] = {
    1: ('Partial', 'Threshold check on a caller-supplied match score; no camera or biometric model (tests/test_hundred_features.py).'),
    2: ('Partial', 'Checks caller-supplied blink/yaw flags; no liveness model.'),
    3: ('Planned', 'No periodic capture loop.'),
    4: ('Partial', 'Flags a caller-supplied face_count > 1; no face detection.'),
    5: ('Partial', 'Threshold on a caller-supplied off-screen fraction; no eye tracking.'),
    6: ('Partial', 'Driver-name blocklist on a caller-supplied string (BLOCKED_VIRTUAL_CAMERA_DRIVERS); no OS driver scan.'),
    7: ('Implemented', 'SHA-256 over frame fields + order id in evaluate_frame (tested).'),
    8: ('Partial', 'Lookup against two hard-coded GUIDs; no device fingerprinting.'),
    9: ('Partial', 'Returns a QR URI string only; no mobile session.'),
    10: ('Partial', 'In-memory review timeline + typed checklist page /control/proctoring; no video.'),
    11: ('Planned', 'No L3/MBO feed (Databento not configured).'),
    12: ('Planned', 'No depth feed; /trade/depth-dom is an estimated ladder.'),
    13: ('Partial', 'WebSocket bridge exists (api/ws.py, frontend/server.mjs); latency not measured.'),
    14: ('Implemented', 'VPIN implemented and tested (features/toxicity.py, marketdata/microstructure.py); bars are not true volume buckets.'),
    15: ('Implemented', 'OFI implemented and tested (marketdata/microstructure.py); no real depth data.'),
    16: ('Implemented', 'Kyle λ OLS implemented and tested (liquidity/impact.py).'),
    17: ('Partial', 'Bar-volume profile helpers in strategies/chart engine; not tick-based.'),
    18: ('Planned', 'No funding-rate feed; marketdata/crypto.py is a descriptor.'),
    19: ('Partial', 'Auction strategy logic exists (strategies/auction.py); no exchange imbalance feed.'),
    20: ('Implemented', 'Staleness gate in control/engine.py: 500 ms competition / 2000 ms open-market (tested).'),
    21: ('Implemented', 'TradingRuleBook max_daily_loss_fraction: 4% competition, 3% open-market, 2% founder Safe stop (tested).'),
    22: ('Implemented', 'Trailing drawdown 8% competition; static 10% open-market/founder (control/rules.py, tested).'),
    23: ('Implemented', 'Setup autopilot checks realized + floating paper P&L every bar against the founder Safe stop (per bar, not per tick).'),
    24: ('Implemented', 'max_single_day_profit_share 0.35 on the competition rulebook (tested).'),
    25: ('Implemented', 'max_per_trade_risk_fraction 0.75% competition / 0.50% open-market and founder (tested).'),
    26: ('Implemented', 'required_stop_kind and min_stop_distance_bps enforced pre-trade (tested).'),
    27: ('Implemented', 'One unified Safe stop (risk/safe_stop.py) flattens paper positions; paper only.'),
    28: ('Implemented', 'RemainingRoomReport in control/rules.py; shown on Overview/Account risk.'),
    29: ('Implemented', 'Fixed notional/leverage caps per rulebook ($50k/3x competition, $40k/2x open, $40k/1x founder); not regime-based.'),
    30: ('Partial', 'Session allow-list and 1-day forced close (founder); no weekend auto-flatten scheduler.'),
    31: ('Implemented', 'Almgren-Chriss trajectory (execution/tactics/optimal.py, execution/scheduling.py), tested; research/paper only.'),
    32: ('Partial', 'Schedule maths only; no child-order execution.'),
    33: ('Partial', 'POV schedule (execution/scheduling.pov_schedule); no VWAP child-order engine.'),
    34: ('Planned', 'No iceberg order engine.'),
    35: ('Partial', 'Stop/target brackets on paper positions via the control plane; no venue OCO.'),
    36: ('Planned', 'Advisory label only (execution/rl_agent.py).'),
    37: ('Planned', 'No IOC sweeper.'),
    38: ('Partial', 'Research pairs sleeve strategy exists; no multi-leg execution.'),
    39: ('Planned', 'No smart order router; live routing disabled.'),
    40: ('Planned', 'No FIX engine; only paper adapters.'),
    41: ('Implemented', 'Canvas charting via lightweight-charts (LiveChartEngine); frame rate not measured. TradingView rework in progress on atlas-tv-1.'),
    42: ('Partial', 'UDF projected rows only; no validated forecast model (registry empty).'),
    43: ('Partial', 'Estimated ladder from last close + catalog spread; not an exchange book.'),
    44: ('Planned', 'No footprint/cluster chart.'),
    45: ('Implemented', 'Route registry pagesMap.ts with aliases (npm run test:routes).'),
    46: ('Implemented', 'Safe stop pill and room-before-Safe-stop tiles (AppShell/Overview).'),
    47: ('Partial', 'Chart overlay only on bar-volume profile.'),
    48: ('Implemented', 'Paper ticket risk check against the rulebook (/control/rulebook).'),
    49: ('Implemented', 'Deterministic bar replay conservative_ohlc_v1 (features/price_action/replay.py, /api/quant/replay), tested.'),
    50: ('Partial', 'Public quotes/fixture catalog; not a live listing session.'),
    51: ('Planned', 'No challenge provisioning.'),
    52: ('Implemented', 'min_trading_days 5 on the competition rulebook (tested).'),
    53: ('Planned', 'No prop scaling ladder (the founder autonomy ladder is a different, live-locked mechanism).'),
    54: ('Planned', 'No profit-split engine.'),
    55: ('Planned', 'No reset/checkout flow.'),
    56: ('Planned', 'No badge/certificate issuance.'),
    57: ('Planned', 'No leaderboard.'),
    58: ('Partial', 'Non-custodial ledger/wallet payout records (ledgers/); live money movement disabled.'),
    59: ('Partial', 'Limit proximity in RemainingRoomReport and the Inbox; no milestone alert dispatch.'),
    60: ('Implemented', 'Violation reasons and decisions written to the hash-chained audit log.'),
    61: ('Planned', 'No copy-trading ring detector.'),
    62: ('Planned', 'No latency-arbitrage identifier.'),
    63: ('Planned', 'No behavioural fingerprinting.'),
    64: ('Planned', 'No cross-account hedging surveillance.'),
    65: ('Planned', 'No economic calendar feed (price_action/events.py is interface only).'),
    66: ('Partial', 'API-key token-bucket rate limits and risk rate limiter; no venue message-rate detector.'),
    67: ('Planned', 'No IP/geo scanner.'),
    68: ('Planned', 'No fill-vs-print verification (no L1/L2 prints).'),
    69: ('Partial', 'VPIN only; no post-fill markout scoring.'),
    70: ('Planned', 'No disqualification gate.'),
    71: ('Implemented', 'AI/research outputs carry execution_permission none; architecture boundary tests. Not an air-gapped sandbox.'),
    72: ('Partial', 'Rule-based causal regimes (models/regimes.py) + HMM in models/quant/regime.py; not wired into candidates.'),
    73: ('Implemented', 'Purged/embargoed walk-forward (models/quant, models/challengers), tested; used for 2026-10-23 evidence.'),
    74: ('Implemented', 'Triple-barrier labels (models/quant, research/setup_evidence.py), tested.'),
    75: ('Partial', 'As-filed XBRL selector (marketdata/sec_edgar.py); no EDGAR fetcher.'),
    76: ('Partial', 'Hawkes intensity only; no MLE parameter fit.'),
    77: ('Partial', "Four hand-set threshold 'trees' (models/microstructure_gbdt.py); not a trained GBDT."),
    78: ('Implemented', 'Platt/bin calibration in models/predict.py, tested; ECE/Brier not measured on a validated model.'),
    79: ('Implemented', 'Feature-ablation endpoints (research/vertical_slice.py), tested; no current results recorded here.'),
    80: ('Implemented', 'auto_promoted=False with owner sign-off; prediction registry is empty.'),
    81: ('Planned', 'No A/B-book router; live routing disabled.'),
    82: ('Planned', 'Hedge-notional formula only (sync/); no balancer.'),
    83: ('Planned', 'No copy-trading hub.'),
    84: ('Partial', 'Arrival slippage + paper broker slippage model; no LP connections.'),
    85: ('Planned', 'No internal netting engine.'),
    86: ('Partial', 'Cost assumptions in replay/paper broker (bps + per share); no commission schedule engine.'),
    87: ('Planned', 'Funding/repo spread formula only (yield/); no financing engine.'),
    88: ('Planned', 'No dark-pool fill emulation.'),
    89: ('Partial', 'max_correlated_exposure_fraction cap in rulebooks; matrix view on sample data.'),
    90: ('Planned', 'No broker margin surveillance.'),
    91: ('Implemented', 'Non-custodial ledgers/wallet (ledgers/), tested; custody disabled.'),
    92: ('Implemented', 'Hash-chained audit log (governance/audit), tested.'),
    93: ('Partial', 'DuckDB feature store/bar query (features/feature_store.py, api/udf.py); no ZSTD Parquet lakehouse.'),
    94: ('Planned', 'BigQuery not wired.'),
    95: ('Partial', 'Role checks (profile/, api/rbac.py) + API-key scopes; scope audit pending.'),
    96: ('Implemented', 'FRED training block in marketdata data-rights/MCP adapters (tested).'),
    97: ('Implemented', 'Allowlist + quarantine in marketdata/mcp_adapters.py (tested).'),
    98: ('Partial', 'atlas-summary ops command exists; no statement dispatch.'),
    99: ('Partial', 'ai.policy.scrub_secrets used for logs/prompts; redaction covered indirectly (tests/founder/test_audit_logging.py).'),
    100: ('Partial', 'CSV exports + alignment docs (docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md); not a certification.'),
}


def build_100_feature_matrix() -> dict[str, Any]:
    """Builds the complete 100-Feature Technical Matrix across Categories 1-10."""
    proctor_engine = WebcamProctoringEngine()
    sample_frame = proctor_engine.evaluate_frame()
    mobile_handoff = proctor_engine.create_dual_camera_mobile_handoff("TRADER-001", "100k_2phase")

    features: list[dict[str, Any]] = []
    for num, cat_id, title, desc, realm, subsystem, _telemetry in RAW_100_FEATURES:
        cat_meta = CATEGORY_METADATA[cat_id]
        status, evidence = FEATURE_STATUS[num]
        features.append(
            {
                "feature_id": f"F-{num:03d}",
                "feature_number": num,
                "category_number": cat_id,
                "category_name": cat_meta["name"],
                "title": title,
                "description": desc,
                "realm": realm,
                "icp_alignment": cat_meta["icp"],
                "workspace_route": cat_meta["workspace_route"],
                "subsystem": subsystem,
                "live_telemetry": "Not measured",
                "status": status,
                "evidence": evidence,
            }
        )

    categories_summary = [
        {
            "category_number": cat_id,
            "category_name": meta["name"],
            "feature_range": meta["range"],
            "workspace_route": meta["workspace_route"],
            "icp_alignment": meta["icp"],
            "total_features": 10,
            "implemented_features": sum(1 for f in features if f["category_number"] == cat_id and f["status"] == "Implemented"),
            "partial_features": sum(1 for f in features if f["category_number"] == cat_id and f["status"] == "Partial"),
            "planned_features": sum(1 for f in features if f["category_number"] == cat_id and f["status"] == "Planned"),
        }
        for cat_id, meta in CATEGORY_METADATA.items()
    ]

    return {
        "status": "ok",
        "total_features": len(features),
        "categories_count": len(categories_summary),
        "execution_permission": "none",
        "status_counts": {k: sum(1 for f in features if f["status"] == k) for k in ("Implemented", "Partial", "Planned")},
        "status_note": "Statuses verified 2026-10-23 against code/tests; telemetry is not measured. Paper/simulation only.",
        "categories_summary": categories_summary,
        "features": features,
        "proctoring_telemetry": {
            "latest_frame": asdict(sample_frame),
            "mobile_handoff": mobile_handoff,
            "blocked_virtual_drivers": list(BLOCKED_VIRTUAL_CAMERA_DRIVERS),
        },
    }


def export_100_feature_csv(output_dir: str | Path | None = None) -> str:
    """Exports the 100-Feature Technical Matrix to docs/roadmap/tab9_100_feature_matrix.csv."""
    repo_root = Path(__file__).resolve().parents[2]
    target_dir = Path(output_dir) if output_dir else repo_root / "docs" / "roadmap"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / "tab9_100_feature_matrix.csv"

    matrix = build_100_feature_matrix()
    rows = matrix["features"]
    if rows:
        fieldnames = list(rows[0].keys())
        with file_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return str(file_path)

