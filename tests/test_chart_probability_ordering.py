"""Probability display lines must be strictly ordered without dropping opportunities."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from atlas.api import chart_overlays as co
from atlas.api.app import app
from atlas.features.price_action.bars import Bar


def test_probability_line_sorts_and_keeps_last_valid_candidate_per_bar():
    timestamp = 1792548000  # Exact duplicate timestamp from the reported chart assertion.
    predictions = [
        {"time": timestamp + 900, "p": 0.7, "take": True},
        {"time": timestamp, "p": 0.2, "take": False},
        {"time": timestamp, "p": 0.9, "take": True},
        {"time": timestamp, "p": float("nan"), "take": False},
    ]
    original = copy.copy(predictions)

    layer = co._probability_layer(predictions)

    assert layer["status"] == "ok"
    assert layer["points"] == [
        {"time": timestamp, "value": 0.9, "take": True},
        {"time": timestamp + 900, "value": 0.7, "take": True},
    ]
    assert layer["selection"] == "last_valid_prediction_per_timestamp"
    assert "candidate" in layer["note"]
    assert predictions == original


@pytest.mark.parametrize(
    ("timestamp", "probability"),
    [
        (float("nan"), 0.5),
        (float("inf"), 0.5),
        (1792548000.5, 0.5),
        (2**53, 0.5),
        (True, 0.5),
        ("1792548000", 0.5),
        (1792548000, float("nan")),
        (1792548000, float("inf")),
        (1792548000, -0.1),
        (1792548000, 1.1),
        (1792548000, True),
        (1792548000, None),
    ],
)
def test_invalid_probability_display_point_is_not_drawn(timestamp, probability):
    layer = co._probability_layer([{"time": timestamp, "p": probability, "take": False}])
    assert layer["status"] == "unavailable"
    assert layer["points"] == []


def test_probability_display_accepts_zero_and_one():
    assert co._probability_layer([
        {"time": 1792548000, "p": 0, "take": False},
        {"time": 1792548900, "p": 1, "take": True},
    ])["points"] == [
        {"time": 1792548000, "value": 0.0, "take": False},
        {"time": 1792548900, "value": 1.0, "take": True},
    ]


def test_overlay_collapses_display_only_and_preserves_markers_and_calibration(monkeypatch):
    timestamp, duration = 1792548000, 900
    bars = [Bar(timestamp + i * duration, duration, 100, 101, 99, 100, 10) for i in range(3)]
    markers = [
        {"id": "later", "time": timestamp + duration, "probability": 0.7, "class": "ml_suggested", "r": 1.0},
        {"id": "long", "time": timestamp, "probability": 0.2, "class": "ml_skip", "r": -1.0},
        {"id": "short", "time": timestamp, "probability": 0.9, "class": "ml_suggested", "r": 1.0},
    ]
    for marker in markers:
        marker.update(source="evolution_oos", outcome="target" if marker["r"] > 0 else "stop")

    monkeypatch.setattr(co, "load", lambda *args: (bars, [], "regression fixture"))
    monkeypatch.setattr(co, "_feed", lambda: None)
    monkeypatch.setattr(co, "_markers", lambda *args: (markers, {}, None))
    monkeypatch.setattr(co, "_enrich_and_forward", lambda *args: ({"status": "ok"}, {"status": "unavailable"}))
    monkeypatch.setattr(co, "_ml_panel", lambda *args: {"execution_permission": "none", "evolution": None})
    for name in ("_zones", "_regimes", "_conviction"):
        monkeypatch.setattr(co, name, lambda *args: {"status": "unavailable"})

    response = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=15m&limit=50")
    assert response.status_code == 200
    payload = response.json()
    layers = payload["layers"]
    points = layers["ml_probability"]["points"]
    assert points == [
        {"time": timestamp, "value": 0.9, "take": True},
        {"time": timestamp + duration, "value": 0.7, "take": True},
    ]
    assert all(a["time"] < b["time"] for a, b in zip(points, points[1:]))
    assert len(layers["ml_markers"]["items"]) == 3
    assert [p["id"] for p in layers["predictions"]["items"]] == ["later", "long", "short"]
    assert layers["predictions"]["running_calibration"]["n"] == 3
    assert layers["predictions"]["running_calibration"]["brier"] == 0.0467
    assert payload["execution_permission"] == "none"
