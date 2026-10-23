export interface Feature100Item {
  featureId: string;
  number: number;
  categoryId: number;
  categoryTitle: string;
  name: string;
  realm: "Open-Market" | "Prop Competition" | "Both";
  subsystem: string;
  description: string;
  /** Implemented / Partial / Planned, from /api/features-100. */
  status: string;
  evidence: string;
}

export interface FeatureCategoryMeta {
  id: number;
  shortLabel: string;
  title: string;
  rangeLabel: string;
  icpTag: string;
}

export const TEN_CATEGORIES_META: FeatureCategoryMeta[] = [
  { id: 1, shortLabel: "Identity", title: "Identity checklist", rangeLabel: "F-001..F-010", icpTag: "Open the checklist" },
  { id: 2, shortLabel: "Chart data", title: "Public candles and the chart", rangeLabel: "F-011..F-020", icpTag: "Open the chart" },
  { id: 3, shortLabel: "Limits", title: "Rulebook and the paper account", rangeLabel: "F-021..F-030", icpTag: "Open the rulebook" },
  { id: 4, shortLabel: "Orders", title: "Order ticket and positions", rangeLabel: "F-031..F-040", icpTag: "Open the ticket" },
  { id: 5, shortLabel: "Desk layout", title: "Chart and desk layout", rangeLabel: "F-041..F-050", icpTag: "Open the chart" },
  { id: 6, shortLabel: "Account", title: "The one paper account", rangeLabel: "F-051..F-060", icpTag: "Open account risk" },
  { id: 7, shortLabel: "Audit", title: "Orders and the audit log", rangeLabel: "F-061..F-070", icpTag: "Open the audit log" },
  { id: 8, shortLabel: "Research", title: "Walk-forward and chart read", rangeLabel: "F-071..F-080", icpTag: "Open the study" },
  { id: 9, shortLabel: "Exposure", title: "Open paper positions", rangeLabel: "F-081..F-090", icpTag: "Open exposure" },
  { id: 10, shortLabel: "Reserve", title: "Reserve sleeve, bars, and connectors", rangeLabel: "F-091..F-100", icpTag: "Open the reserve plan" },
];

// Feature rows come from /api/features-100 (src/atlas/proctoring_and_features100.py); see src/lib/features100.ts.

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
    label: "1. Example: one face, blink on, score 0.97",
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
    label: "2. Example: two faces",
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
    label: "3. Example: virtual camera driver",
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
    label: "4. Example: gaze field set to 6.2 seconds",
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

