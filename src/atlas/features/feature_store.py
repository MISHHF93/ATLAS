"""Centralized feature store with DuckDB and Parquet compression.

Implements:
- DuckDB-based feature storage and querying
- Parquet compression with ZSTD
- Feature versioning and lineage tracking
- Feature importance tracking
- Point-in-time (PIT) queries
- High-performance feature retrieval

All outputs retain execution_permission: none.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np
import pandas as pd
from pydantic import AwareDatetime, Field

from atlas.models.schemas import Record, Text


@dataclass(frozen=True)
class FeatureMetadata:
    """Metadata for a feature in the store."""
    
    feature_name: str
    feature_type: Literal["numeric", "categorical", "binary"]
    description: str
    source: str
    lineage_ref: str
    license_ref: str
    created_at: datetime
    version: int
    compression: str = "zstd"
    compression_level: int = 3


class FeatureVersion(Record):
    """Version information for a feature."""
    
    feature_name: Text
    version: int
    created_at: AwareDatetime
    artifact_path: Text
    artifact_sha256: Text
    row_count: int
    size_bytes: int
    lineage_ref: Text
    execution_permission: Literal["none"] = "none"


class FeatureLineage(Record):
    """Lineage tracking for feature transformations."""
    
    lineage_id: Text
    feature_name: Text
    transformation_steps: tuple[dict[str, str], ...]
    source_features: tuple[Text, ...]
    created_at: AwareDatetime
    execution_permission: Literal["none"] = "none"


class FeatureImportanceRecord(Record):
    """Record of feature importance for a model."""
    
    model_id: Text
    feature_name: Text
    importance_score: float
    importance_type: Literal["shap", "permutation", "gain", "weight"]
    computed_at: AwareDatetime
    execution_permission: Literal["none"] = "none"


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to an aware UTC value.

    DuckDB returns timezone-naive ``TIMESTAMP`` values even when an aware
    datetime was inserted. Persisted research timestamps are treated as UTC.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_storage_timestamp(value: datetime) -> datetime:
    """Convert to the UTC-naive representation used by DuckDB TIMESTAMP."""
    return _as_utc(value).replace(tzinfo=None)


class VersionedFeatureStoreDuckDBParquet:
    """Centralized feature store using DuckDB and Parquet."""

    def __init__(self, store_id: str, db_path: str, parquet_dir: str) -> None:
        self.store_id = store_id
        self.db_path = db_path
        self.parquet_dir = parquet_dir
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self.db_path))
        self._init_schema()
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_versions (
                    feature_name VARCHAR NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    artifact_path VARCHAR NOT NULL,
                    artifact_sha256 VARCHAR NOT NULL,
                    row_count INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    lineage_ref VARCHAR NOT NULL,
                    PRIMARY KEY (feature_name, version)
                )
            """)
            
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feature_name 
                ON feature_versions(feature_name)
            """)
            
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_lineage (
                    lineage_id VARCHAR PRIMARY KEY,
                    feature_name VARCHAR NOT NULL,
                    transformation_steps JSON NOT NULL,
                    source_features JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_importance (
                    model_id VARCHAR NOT NULL,
                    feature_name VARCHAR NOT NULL,
                    importance_score DOUBLE NOT NULL,
                    importance_type VARCHAR NOT NULL,
                    computed_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (model_id, feature_name, importance_type)
                )
            """)
            
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_importance_model 
                ON feature_importance(model_id)
            """)
    
    def store_feature(
        self,
        feature_name: str,
        data: pd.DataFrame,
        metadata: FeatureMetadata,
        lineage: FeatureLineage | None = None,
    ) -> FeatureVersion:
        """Store a feature as compressed Parquet file.
        
        Args:
            feature_name: Name of the feature
            data: DataFrame with feature data (must include timestamp column)
            metadata: Feature metadata
            lineage: Optional lineage information
        
        Returns:
            FeatureVersion record
        """
        with self._lock:
            # Ensure timestamp column exists
            if "timestamp" not in data.columns:
                raise ValueError("DataFrame must include 'timestamp' column")
            
            # Get next version
            version = self._get_next_version(feature_name)
            
            # Create artifact path
            artifact_path = Path(self.parquet_dir) / f"{feature_name}_v{version}.parquet"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to Parquet with ZSTD compression
            data.to_parquet(
                artifact_path,
                engine="pyarrow",
                compression="zstd",
                compression_level=metadata.compression_level,
            )
            
            # Compute SHA256
            artifact_sha256 = self._compute_sha256(artifact_path)
            
            # Get file size
            size_bytes = artifact_path.stat().st_size
            row_count = len(data)
            
            # Store lineage if provided
            if lineage:
                self._conn.execute("""
                    INSERT INTO feature_lineage 
                    (lineage_id, feature_name, transformation_steps, source_features, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    lineage.lineage_id,
                    lineage.feature_name,
                    json.dumps(lineage.transformation_steps),
                    json.dumps(lineage.source_features),
                    _to_storage_timestamp(lineage.created_at),
                ))
            
            # Register version
            self._conn.execute("""
                INSERT INTO feature_versions 
                (feature_name, version, created_at, artifact_path, artifact_sha256, 
                 row_count, size_bytes, lineage_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feature_name,
                version,
                _to_storage_timestamp(metadata.created_at),
                str(artifact_path),
                artifact_sha256,
                row_count,
                size_bytes,
                metadata.lineage_ref,
            ))
            
            return FeatureVersion(
                feature_name=feature_name,
                version=version,
                created_at=metadata.created_at,
                artifact_path=str(artifact_path),
                artifact_sha256=artifact_sha256,
                row_count=row_count,
                size_bytes=size_bytes,
                lineage_ref=metadata.lineage_ref,
            )
    
    def _get_next_version(self, feature_name: str) -> int:
        """Get next version number for a feature."""
        result = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM feature_versions WHERE feature_name = ?",
            (feature_name,)
        ).fetchone()
        return (result[0] if result else 0) + 1
    
    def _compute_sha256(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def get_feature(
        self,
        feature_name: str,
        version: int | None = None,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        """Retrieve a feature by name and version or point-in-time.
        
        Args:
            feature_name: Name of the feature
            version: Specific version (if None, uses latest)
            as_of: Point-in-time timestamp (if provided, uses version <= as_of)
        
        Returns:
            DataFrame with feature data
        """
        with self._lock:
            if version is not None:
                # Get specific version
                result = self._conn.execute(
                    "SELECT artifact_path FROM feature_versions "
                    "WHERE feature_name = ? AND version = ?",
                    (feature_name, version)
                ).fetchone()
            elif as_of is not None:
                # Get version as of timestamp
                result = self._conn.execute(
                    "SELECT artifact_path FROM feature_versions "
                    "WHERE feature_name = ? AND created_at <= ? "
                    "ORDER BY version DESC LIMIT 1",
                    (feature_name, _to_storage_timestamp(as_of))
                ).fetchone()
            else:
                # Get latest version
                result = self._conn.execute(
                    "SELECT artifact_path FROM feature_versions "
                    "WHERE feature_name = ? ORDER BY version DESC LIMIT 1",
                    (feature_name,)
                ).fetchone()
            
            if not result:
                raise ValueError(f"Feature {feature_name} not found")
            
            artifact_path = result[0]
            return pd.read_parquet(artifact_path)
    
    def query_features(
        self,
        feature_names: list[str],
        start_time: datetime,
        end_time: datetime,
        version: int | None = None,
    ) -> pd.DataFrame:
        """Query multiple features with time range filter.
        
        Args:
            feature_names: List of feature names to retrieve
            start_time: Start of time range
            end_time: End of time range
            version: Version to use (if None, uses latest)
        
        Returns:
            DataFrame with all features merged on timestamp
        """
        with self._lock:
            # Retrieve each feature
            dfs = []
            for feature_name in feature_names:
                df = self.get_feature(feature_name, version)
                df = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= end_time)]
                dfs.append(df)
            
            # Merge on timestamp
            if not dfs:
                return pd.DataFrame()
            
            result = dfs[0]
            for df in dfs[1:]:
                result = pd.merge(result, df, on="timestamp", how="outer")
            
            return result.sort_values("timestamp")
    
    def register_feature_importance(
        self,
        model_id: str,
        feature_importance: dict[str, float],
        importance_type: Literal["shap", "permutation", "gain", "weight"],
    ) -> None:
        """Register feature importance scores for a model.
        
        Args:
            model_id: Model identifier
            feature_importance: Dictionary mapping feature names to importance scores
            importance_type: Type of importance metric
        """
        with self._lock:
            computed_at = datetime.now(timezone.utc)
            
            for feature_name, score in feature_importance.items():
                self._conn.execute("""
                    INSERT OR REPLACE INTO feature_importance 
                    (model_id, feature_name, importance_score, importance_type, computed_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    model_id,
                    feature_name,
                    float(score),
                    importance_type,
                    _to_storage_timestamp(computed_at),
                ))
    
    def get_feature_importance(
        self,
        model_id: str,
        importance_type: Literal["shap", "permutation", "gain", "weight"] | None = None,
    ) -> list[FeatureImportanceRecord]:
        """Retrieve feature importance for a model.
        
        Args:
            model_id: Model identifier
            importance_type: Filter by importance type (if None, returns all)
        
        Returns:
            List of feature importance records
        """
        with self._lock:
            if importance_type:
                results = self._conn.execute(
                    "SELECT * FROM feature_importance "
                    "WHERE model_id = ? AND importance_type = ? "
                    "ORDER BY importance_score DESC",
                    (model_id, importance_type)
                ).fetchall()
            else:
                results = self._conn.execute(
                    "SELECT * FROM feature_importance "
                    "WHERE model_id = ? ORDER BY importance_score DESC",
                    (model_id,)
                ).fetchall()
            
            return [
                FeatureImportanceRecord(
                    model_id=row[0],
                    feature_name=row[1],
                    importance_score=float(row[2]),
                    importance_type=row[3],
                    computed_at=_as_utc(row[4]),
                )
                for row in results
            ]
    
    def list_features(self) -> list[str]:
        """List all available features."""
        with self._lock:
            results = self._conn.execute(
                "SELECT DISTINCT feature_name FROM feature_versions"
            ).fetchall()
            return [row[0] for row in results]
    
    def get_feature_versions(self, feature_name: str) -> list[FeatureVersion]:
        """Get all versions of a feature.
        
        Args:
            feature_name: Name of the feature
        
        Returns:
            List of feature versions
        """
        with self._lock:
            results = self._conn.execute(
                "SELECT * FROM feature_versions WHERE feature_name = ? "
                "ORDER BY version DESC",
                (feature_name,)
            ).fetchall()
            
            return [
                FeatureVersion(
                    feature_name=row[0],
                    version=row[1],
                    created_at=_as_utc(row[2]),
                    artifact_path=row[3],
                    artifact_sha256=row[4],
                    row_count=row[5],
                    size_bytes=row[6],
                    lineage_ref=row[7],
                )
                for row in results
            ]
    
    def get_lineage(self, feature_name: str) -> FeatureLineage | None:
        """Get lineage information for a feature.
        
        Args:
            feature_name: Name of the feature
        
        Returns:
            FeatureLineage record or None
        """
        with self._lock:
            result = self._conn.execute(
                "SELECT * FROM feature_lineage WHERE feature_name = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (feature_name,)
            ).fetchone()
            
            if not result:
                return None
            
            return FeatureLineage(
                lineage_id=result[0],
                feature_name=result[1],
                transformation_steps=tuple(json.loads(result[2])),
                source_features=tuple(json.loads(result[3])),
                created_at=_as_utc(result[4]),
            )
    
    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


# Deprecated name; use ``VersionedFeatureStoreDuckDBParquet``. Not the same as atlas.marketdata.pit.featurestore.FeatureStore.
FeatureStore = VersionedFeatureStoreDuckDBParquet


def create_feature_store(
    store_id: str,
    db_path: str = "data/feature_store.db",
    parquet_dir: str = "data/parquet_features",
) -> FeatureStore:
    """Create a new feature store.
    
    Args:
        store_id: Store identifier
        db_path: Path to DuckDB database file
        parquet_dir: Directory for Parquet files
    
    Returns:
        Configured FeatureStore
    """
    # Ensure directories exist
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(parquet_dir).mkdir(parents=True, exist_ok=True)
    
    return FeatureStore(
        store_id=store_id,
        db_path=db_path,
        parquet_dir=parquet_dir,
    )
