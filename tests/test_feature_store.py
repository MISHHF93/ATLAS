"""Unit tests for feature store."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from atlas.features.feature_store import (
    FeatureStore,
    FeatureMetadata,
    FeatureLineage,
    FeatureVersion,
    create_feature_store,
)


@pytest.fixture
def temp_feature_store():
    """Create a temporary feature store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        parquet_dir = Path(tmpdir) / "parquet"
        
        store = create_feature_store(
            store_id="test_store",
            db_path=str(db_path),
            parquet_dir=str(parquet_dir),
        )
        
        yield store
        
        store.close()


def test_create_feature_store(temp_feature_store):
    """Test feature store creation."""
    assert temp_feature_store.store_id == "test_store"
    assert temp_feature_store._conn is not None


def test_store_feature(temp_feature_store):
    """Test storing a feature."""
    # Create sample data
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    data = pd.DataFrame({
        "timestamp": timestamps,
        "value": np.random.randn(100),
    })
    
    metadata = FeatureMetadata(
        feature_name="test_feature",
        feature_type="numeric",
        description="Test feature",
        source="test",
        lineage_ref="test_lineage",
        license_ref="test_license",
        created_at=datetime.now(timezone.utc),
        version=1,
    )
    
    version = temp_feature_store.store_feature(
        feature_name="test_feature",
        data=data,
        metadata=metadata,
    )
    
    assert version.feature_name == "test_feature"
    assert version.version == 1
    assert version.row_count == 100
    assert version.artifact_sha256 is not None


def test_get_feature(temp_feature_store):
    """Test retrieving a feature."""
    # Store a feature first
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    data = pd.DataFrame({
        "timestamp": timestamps,
        "value": np.random.randn(100),
    })
    
    metadata = FeatureMetadata(
        feature_name="test_feature",
        feature_type="numeric",
        description="Test feature",
        source="test",
        lineage_ref="test_lineage",
        license_ref="test_license",
        created_at=datetime.now(timezone.utc),
        version=1,
    )
    
    temp_feature_store.store_feature(
        feature_name="test_feature",
        data=data,
        metadata=metadata,
    )
    
    # Retrieve the feature
    retrieved = temp_feature_store.get_feature("test_feature")
    
    assert len(retrieved) == 100
    assert "timestamp" in retrieved.columns
    assert "value" in retrieved.columns


def test_get_feature_by_version(temp_feature_store):
    """Test retrieving a specific version of a feature."""
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    data = pd.DataFrame({
        "timestamp": timestamps,
        "value": np.random.randn(100),
    })
    
    metadata = FeatureMetadata(
        feature_name="test_feature",
        feature_type="numeric",
        description="Test feature",
        source="test",
        lineage_ref="test_lineage",
        license_ref="test_license",
        created_at=datetime.now(timezone.utc),
        version=1,
    )
    
    # Store two versions
    temp_feature_store.store_feature(
        feature_name="test_feature",
        data=data,
        metadata=metadata,
    )
    
    data2 = data.copy()
    data2["value"] = np.random.randn(100)
    metadata2 = FeatureMetadata(
        feature_name="test_feature",
        feature_type="numeric",
        description="Test feature v2",
        source="test",
        lineage_ref="test_lineage",
        license_ref="test_license",
        created_at=datetime.now(timezone.utc),
        version=2,
    )
    
    temp_feature_store.store_feature(
        feature_name="test_feature",
        data=data2,
        metadata=metadata2,
    )
    
    # Retrieve specific version
    v1 = temp_feature_store.get_feature("test_feature", version=1)
    v2 = temp_feature_store.get_feature("test_feature", version=2)
    
    assert len(v1) == 100
    assert len(v2) == 100


def test_query_features(temp_feature_store):
    """Test querying multiple features with time range."""
    # Store two features
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    
    for i in range(2):
        data = pd.DataFrame({
            "timestamp": timestamps,
            f"value{i}": np.random.randn(100),
        })
        
        metadata = FeatureMetadata(
            feature_name=f"feature{i}",
            feature_type="numeric",
            description=f"Test feature {i}",
            source="test",
            lineage_ref="test_lineage",
            license_ref="test_license",
            created_at=datetime.now(timezone.utc),
            version=1,
        )
        
        temp_feature_store.store_feature(
            feature_name=f"feature{i}",
            data=data,
            metadata=metadata,
        )
    
    # Query with time range
    start_time = timestamps[20]
    end_time = timestamps[50]
    
    result = temp_feature_store.query_features(
        feature_names=["feature0", "feature1"],
        start_time=start_time,
        end_time=end_time,
    )
    
    assert len(result) > 0
    assert "timestamp" in result.columns
    assert "value0" in result.columns
    assert "value1" in result.columns


def test_register_feature_importance(temp_feature_store):
    """Test registering feature importance."""
    importance = {
        "feature1": 0.8,
        "feature2": 0.6,
        "feature3": 0.4,
    }
    
    temp_feature_store.register_feature_importance(
        model_id="test_model",
        feature_importance=importance,
        importance_type="shap",
    )
    
    # Retrieve importance
    records = temp_feature_store.get_feature_importance("test_model", "shap")
    
    assert len(records) == 3
    assert records[0].importance_score == 0.8  # Should be sorted descending


def test_list_features(temp_feature_store):
    """Test listing all features."""
    # Store some features
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    
    for i in range(3):
        data = pd.DataFrame({
            "timestamp": timestamps,
            "value": np.random.randn(100),
        })
        
        metadata = FeatureMetadata(
            feature_name=f"feature{i}",
            feature_type="numeric",
            description=f"Test feature {i}",
            source="test",
            lineage_ref="test_lineage",
            license_ref="test_license",
            created_at=datetime.now(timezone.utc),
            version=1,
        )
        
        temp_feature_store.store_feature(
            feature_name=f"feature{i}",
            data=data,
            metadata=metadata,
        )
    
    # List features
    features = temp_feature_store.list_features()
    
    assert len(features) == 3
    assert "feature0" in features
    assert "feature1" in features
    assert "feature2" in features


def test_get_feature_versions(temp_feature_store):
    """Test getting all versions of a feature."""
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    data = pd.DataFrame({
        "timestamp": timestamps,
        "value": np.random.randn(100),
    })
    
    # Store multiple versions
    for i in range(3):
        metadata = FeatureMetadata(
            feature_name="test_feature",
            feature_type="numeric",
            description=f"Test feature v{i+1}",
            source="test",
            lineage_ref="test_lineage",
            license_ref="test_license",
            created_at=datetime.now(timezone.utc),
            version=1,
        )
        
        temp_feature_store.store_feature(
            feature_name="test_feature",
            data=data,
            metadata=metadata,
        )
    
    # Get all versions
    versions = temp_feature_store.get_feature_versions("test_feature")
    
    assert len(versions) == 3
    assert all(v.feature_name == "test_feature" for v in versions)


def test_feature_lineage(temp_feature_store):
    """Test feature lineage tracking."""
    timestamps = pd.date_range(
        start="2024-01-01",
        periods=100,
        freq="h",
    )
    data = pd.DataFrame({
        "timestamp": timestamps,
        "value": np.random.randn(100),
    })
    
    metadata = FeatureMetadata(
        feature_name="test_feature",
        feature_type="numeric",
        description="Test feature",
        source="test",
        lineage_ref="test_lineage",
        license_ref="test_license",
        created_at=datetime.now(timezone.utc),
        version=1,
    )
    
    lineage = FeatureLineage(
        lineage_id="test_lineage",
        feature_name="test_feature",
        transformation_steps=(
            {"step": "normalize", "params": "{}"},
            {"step": "smooth", "params": "{}"},
        ),
        source_features=("raw_feature1", "raw_feature2"),
        created_at=datetime.now(timezone.utc),
    )
    
    temp_feature_store.store_feature(
        feature_name="test_feature",
        data=data,
        metadata=metadata,
        lineage=lineage,
    )
    
    # Retrieve lineage
    retrieved_lineage = temp_feature_store.get_lineage("test_feature")
    
    assert retrieved_lineage is not None
    assert retrieved_lineage.feature_name == "test_feature"
    assert len(retrieved_lineage.transformation_steps) == 2
    assert len(retrieved_lineage.source_features) == 2
