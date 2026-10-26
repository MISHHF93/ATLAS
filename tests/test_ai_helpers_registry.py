"""Pin the behaviour of each same-named helper variant and check old names still resolve."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from atlas.ai import helpers_registry as hr


def test_registry_shape_and_aliases_resolve():
    fams = hr.families()
    assert set(fams) == {"bars_frame", "purged_walk_forward", "FeatureStore", "compute_hawkes_intensity", "symbol_info"}
    assert all(len(v) == 2 for v in fams.values())
    assert len({h.id for h in hr.HELPERS}) == len(hr.HELPERS)
    for h in hr.HELPERS:
        impl = hr.resolve(h.id)
        assert hr._load(h.legacy) is impl, h.id
        if h.renamed_in_place:
            assert impl.__name__ == h.id
        # every documented parameter name appears in the real signature
        params = inspect.signature(impl).parameters
        for name in params:
            if name != "self":
                assert name in h.signature, (h.id, name)


def test_registry_components_exist_and_node_reports_helpers():
    from atlas.ai.node import NODE, REGISTRY

    names = {c.name for c in REGISTRY}
    assert all(c in names for h in hr.HELPERS for c in h.used_by_components)
    by = {c["name"]: c["helpers"] for c in NODE.components()}
    assert by["quant_models"] == ["bars_frame_close_volume_time_index", "purged_walk_forward_splits_by_time"]
    assert by["vertical_slice"] == ["purged_walk_forward_model_selection_by_rows"]
    assert "compute_hawkes_intensity_from_deltas_summary" in by["challengers"]


def test_helpers_endpoint_lists_and_filters():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.ai.http import router

    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    body = c.get("/api/ai/helpers").json()
    assert len(body["helpers"]) == len(hr.HELPERS) and body["execution_permission"] == "none"
    one = c.get("/api/ai/helpers", params={"family": "FeatureStore"}).json()["helpers"]
    assert [h["id"] for h in one] == ["PointInTimeFeatureStoreSQLite", "VersionedFeatureStoreDuckDBParquet"]
    q = c.get("/api/ai/helpers", params={"component": "quant_models"}).json()["helpers"]
    assert {h["id"] for h in q} == {"bars_frame_close_volume_time_index", "purged_walk_forward_splits_by_time"}
    comp = c.get("/api/ai/components/vertical_slice").json()
    assert comp["helpers"] == ["purged_walk_forward_model_selection_by_rows"]


def _bars(n=3):
    return [SimpleNamespace(start=i * 60, end=(i + 1) * 60, open=1.0 + i, high=2.0 + i, low=0.5 + i, close=1.5 + i,
                            volume=10.0 * (i + 1), ts=pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=i))
            for i in range(n)]


def test_bars_frame_variants_differ():
    ohlcv = hr.resolve("bars_frame_ohlcv_range_index")(_bars())
    cv = hr.resolve("bars_frame_close_volume_time_index")(_bars())
    assert list(ohlcv.columns) == ["start", "end", "open", "high", "low", "close", "volume"]
    assert isinstance(ohlcv.index, pd.RangeIndex)
    assert list(cv.columns) == ["close", "volume"] and isinstance(cv.index, pd.DatetimeIndex)
    assert cv["close"].tolist() == ohlcv["close"].tolist() == [1.5, 2.5, 3.5]


def test_purged_walk_forward_splits_by_time_purges_and_applies_embargo():
    split = hr.resolve("purged_walk_forward_splits_by_time")
    t = np.arange(100)
    folds = list(split(t, n_splits=4, horizon=5))
    assert len(folds) == 4
    for train, test in folds:
        assert train.max() + 5 < test.min()  # label ends purged before the test window
    embargoed = list(split(t, n_splits=4, horizon=5, embargo=10))
    assert len(embargoed) == 4
    for (tr0, te0), (tr_emb, te_emb) in zip(folds, embargoed):
        assert (te0 == te_emb).all()
        assert tr_emb.max() + 5 + 10 < te_emb.min()
        assert tr_emb.max() == tr0.max() - 10


def test_purged_walk_forward_model_selection_is_a_model_report():
    impl = hr.resolve("purged_walk_forward_model_selection_by_rows")
    params = inspect.signature(impl).parameters
    assert list(params)[:2] == ["rows", "symbol"] and params["config"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(impl).return_annotation in ("dict[str, Any]", dict)


def test_point_in_time_store_hides_future_and_revisions():
    store = hr.resolve("PointInTimeFeatureStoreSQLite")()
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.put("AAPL", "f", t0, t0 + timedelta(hours=1), {"x": 1.0})
    store.put("AAPL", "f", t0, t0 + timedelta(hours=3), {"x": 2.0})  # later revision
    assert store.get("AAPL", "f", t0) is None
    assert store.get("AAPL", "f", t0 + timedelta(hours=2))["x"] == 1.0
    assert store.get("AAPL", "f", t0 + timedelta(hours=4))["x"] == 2.0


def test_versioned_store_is_a_different_class():
    from atlas.features.feature_store import FeatureStore as Versioned
    from atlas.marketdata.pit.featurestore import FeatureStore as PIT

    assert Versioned is not PIT
    assert not hasattr(Versioned, "frame") and hasattr(PIT, "frame")


def test_hawkes_variants_agree_and_differ_in_shape():
    causal = hr.resolve("compute_hawkes_intensity_causal_report")
    summary = hr.resolve("compute_hawkes_intensity_from_deltas_summary")
    deltas = [0.1, 0.5, 1.0]
    rep = causal([100.0 - d for d in deltas], eval_time_sec=100.0, alpha=0.85)
    out = summary(deltas)
    assert isinstance(out, dict) and out["execution_permission"] == "none"
    assert out["current_intensity_lambda"] == round(float(rep.intensity_lambda_t), 4)
    assert out["iceberg_clustering_detected"] is (float(rep.intensity_lambda_t) >= 1.85)


def test_symbol_info_variants():
    desk = hr.resolve("symbol_info_desk_catalog")
    assert desk("NOT_A_REAL_SYMBOL_XYZ") == {"s": "error", "errmsg": "unknown_symbol"}
    feed_variant = hr.resolve("symbol_info_feed_instrument")
    fake = SimpleNamespace(instruments={"X": SimpleNamespace(id="X", description="d", asset_class="crypto", venue="V",
                                                             session="24x7", timezone="UTC", tick_size=0.01, currency="USD")})
    info = feed_variant("X", fake)
    assert info["timezone"] == "Etc/UTC" and info["pricescale"] == 100 and info["supported_resolutions"] == ["15", "60", "1D"]
    with pytest.raises(AttributeError):
        feed_variant("missing", fake)
