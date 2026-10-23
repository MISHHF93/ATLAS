from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.proctoring_and_features100 import (
    WebcamProctoringEngine,
    build_100_feature_matrix,
    export_100_feature_csv,
)
from atlas.whale_saas_az import export_master_roadmap_csvs


def test_build_100_feature_matrix_completeness() -> None:
    matrix = build_100_feature_matrix()
    assert matrix["status"] == "ok"
    assert matrix["execution_permission"] == "none"
    assert matrix["total_features"] == 100
    assert len(matrix["categories_summary"]) == 10
    features = matrix["features"]
    assert len(features) == 100

    # Verify F-001 through F-100 and 10 features per category
    for idx in range(1, 101):
        feat = features[idx - 1]
        assert feat["feature_id"] == f"F-{idx:03d}"
        assert feat["feature_number"] == idx
        assert feat["status"] in {"Implemented", "Partial", "Planned"}
        assert feat["live_telemetry"] == "Not measured"
        assert feat["evidence"]

    for cat_id in range(1, 11):
        cat_rows = [f for f in features if f["category_number"] == cat_id]
        assert len(cat_rows) == 10

    counts = matrix["status_counts"]
    assert sum(counts.values()) == 100
    assert counts["Planned"] > 0 and counts["Partial"] > 0
    # F-001 uses a caller-supplied score (no camera) and FIX is not built.
    assert features[0]["status"] == "Partial"
    assert features[39]["status"] == "Planned"


def test_webcam_proctoring_engine_features_1_to_10() -> None:
    engine = WebcamProctoringEngine()

    # 1. Verified single trader frame
    ok_res = engine.evaluate_frame(
        trader_id="TRADER-001",
        biometric_match_score=0.984,
        eye_blink_detected=True,
        head_yaw_degrees=12.5,
        face_count=1,
        gaze_off_screen_pct=0.08,
        camera_driver="USB Video Device (Integrated IR Webcam)",
        concurrent_order_id="ORD-2026-8841",
        hardware_guid="HW-GUID-9921-LOGI-4K",
        dual_camera_mobile_active=True,
    )
    assert ok_res.proctoring_status == "VERIFIED_COMPLIANT"
    assert ok_res.execution_permission == "none"
    assert len(ok_res.watermark_sha256) == 64
    assert len(ok_res.violations) == 0

    # 2. Multiple face / proxy-trading breach (F-004)
    proxy_res = engine.evaluate_frame(
        trader_id="TRADER-001",
        biometric_match_score=0.95,
        eye_blink_detected=True,
        head_yaw_degrees=8.0,
        face_count=2,
        gaze_off_screen_pct=0.10,
        camera_driver="USB Video Device",
        concurrent_order_id="ORD-2026-8842",
        hardware_guid="HW-GUID-9921-LOGI-4K",
        dual_camera_mobile_active=True,
    )
    assert proxy_res.proctoring_status == "FLAGGED_FOR_COMPLIANCE"
    assert proxy_res.proxy_trading_flagged is True
    assert any("proxy_trading_multiple_faces_detected" in v for v in proxy_res.violations)

    # 3. OBS virtual camera driver block (F-006)
    obs_res = engine.evaluate_frame(
        trader_id="TRADER-001",
        biometric_match_score=0.84,
        eye_blink_detected=False,
        head_yaw_degrees=1.0,
        face_count=1,
        gaze_off_screen_pct=0.45,
        camera_driver="OBS Virtual Camera",
        concurrent_order_id="ORD-2026-8843",
        hardware_guid="HW-GUID-0000-VIRTUAL",
        dual_camera_mobile_active=False,
    )
    assert obs_res.proctoring_status == "FLAGGED_FOR_COMPLIANCE"
    assert obs_res.virtual_camera_blocked is True
    assert any("virtual_camera_driver_blocked" in v for v in obs_res.violations)

    # 4. Dual-camera mobile QR handoff (F-009) & timeline (F-010)
    handoff = engine.create_dual_camera_mobile_handoff("TRADER-001")
    assert handoff["qr_uri"].startswith("atlas://proctor-mobile?trader=TRADER-001")
    timeline = engine.get_review_timeline()
    assert len(timeline) == 3


def test_hundred_features_and_proctoring_api_endpoints(tmp_path: Path) -> None:
    client = TestClient(app)

    res = client.get("/api/features-100")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total_features"] == 100
    assert payload["filtered_count"] == 100
    assert payload["execution_permission"] == "none"

    cat1_res = client.get("/api/features-100?category_id=1")
    assert cat1_res.status_code == 200
    assert cat1_res.json()["filtered_count"] == 10

    eval_res = client.post(
        "/api/proctoring/evaluate-frame",
        json={
            "trader_id": "TRADER-001",
            "camera_driver": "Logitech Brio 4K USB Video Device",
            "hardware_guid": "HW-GUID-9921-LOGI-4K",
            "face_count": 1,
            "biometric_match_score": 0.971,
            "eye_blink_detected": True,
            "head_yaw_degrees": 9.2,
            "gaze_off_screen_pct": 0.05,
            "concurrent_order_id": "ORD-COMP-99200",
            "dual_camera_mobile_active": True,
        },
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["evaluation"]["proctoring_status"] == "VERIFIED_COMPLIANT"

    csv_path = export_100_feature_csv(tmp_path)
    assert Path(csv_path).exists()

    exported = export_master_roadmap_csvs(tmp_path)
    assert "tab9_100_feature_matrix.csv" in exported
    with Path(exported["tab9_100_feature_matrix.csv"]).open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 100

