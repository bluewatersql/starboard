"""Pure domain logic for UC analysis.

This module contains pure functions for schema analysis, classification,
and anomaly detection without any I/O dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import mean, stdev

from starboard_core.domain.models.databricks import TableReference
from starboard_core.domain.models.uc import (
    ColumnDiff,
    ColumnInfo,
    ImpactEstimate,
    JoinPrediction,
    PolicyGap,
    SchemaAnomaly,
    StorageRecommendation,
    StorageState,
    TableDiscoveryResult,
)

logger = logging.getLogger(__name__)


@dataclass
class AnomalyThresholds:
    """Configurable thresholds for anomaly detection."""

    max_columns: int = 100
    max_string_width_chars: int = 10000
    min_id_columns_for_consistency_check: int = 2


class UCAnalyzer:
    """Pure functions for UC analysis.

    All methods are stateless and can be called independently.
    No I/O operations - only computation on provided data.

    Example:
        >>> columns = [
        ...     ColumnInfo(name="id", data_type="BIGINT", position=0, nullable=False),
        ...     ColumnInfo(name="data", data_type="STRING", position=1, nullable=True),
        ... ]
        >>> anomalies = UCAnalyzer.detect_schema_anomalies(columns)
        >>> len(anomalies) >= 0
        True
    """

    @staticmethod
    def detect_schema_anomalies(
        columns: list[ColumnInfo],
        thresholds: AnomalyThresholds | None = None,
    ) -> list[SchemaAnomaly]:
        """
        Detect schema anomalies using heuristics.

        Args:
            columns: List of column info objects
            thresholds: Optional custom thresholds

        Returns:
            List of detected anomalies
        """
        thresholds = thresholds or AnomalyThresholds()
        anomalies: list[SchemaAnomaly] = []

        # Excessive columns
        if len(columns) > thresholds.max_columns:
            anomalies.append(
                SchemaAnomaly(
                    anomaly_type="excessive_columns",
                    severity="medium",
                    description=(
                        f"Table has {len(columns)} columns "
                        f"(threshold: {thresholds.max_columns})"
                    ),
                    affected_columns=(),
                    recommendation=(
                        "Consider normalizing or partitioning wide tables. "
                        "Use nested structs for related columns."
                    ),
                )
            )

        # JSON blob anti-pattern detection
        json_blob_patterns = ["json", "data", "payload", "raw", "blob", "content"]
        json_columns = [
            c
            for c in columns
            if c.data_type.upper() in ("STRING", "BINARY", "VARIANT")
            and any(pattern in c.name.lower() for pattern in json_blob_patterns)
        ]
        if json_columns and len(json_columns) <= 5:
            anomalies.append(
                SchemaAnomaly(
                    anomaly_type="json_blob_antipattern",
                    severity="high",
                    description=(
                        f"Potential JSON blob columns detected: "
                        f"{', '.join(c.name for c in json_columns)}"
                    ),
                    affected_columns=tuple(c.name for c in json_columns),
                    recommendation=(
                        "Extract frequently-queried JSON fields into typed columns. "
                        "Consider using generated columns or materialized views."
                    ),
                )
            )

        # Type mismatches (IDs stored as different types)
        id_columns = [c for c in columns if c.name.lower().endswith("_id")]
        if len(id_columns) >= thresholds.min_id_columns_for_consistency_check:
            id_types = {c.data_type.upper() for c in id_columns}
            # Normalize numeric types
            normalized_types = set()
            for t in id_types:
                if t in ("INT", "INTEGER", "BIGINT", "LONG", "SMALLINT", "TINYINT"):
                    normalized_types.add("INTEGER_TYPE")
                elif t in ("STRING", "VARCHAR", "CHAR"):
                    normalized_types.add("STRING_TYPE")
                else:
                    normalized_types.add(t)
            if len(normalized_types) > 1:
                anomalies.append(
                    SchemaAnomaly(
                        anomaly_type="type_mismatch",
                        severity="medium",
                        description=(
                            f"ID columns have inconsistent types: {id_types}. "
                            f"Found in: {', '.join(c.name for c in id_columns)}"
                        ),
                        affected_columns=tuple(c.name for c in id_columns),
                        recommendation=(
                            "Standardize ID column types across the table. "
                            "String IDs and integer IDs may cause join issues."
                        ),
                    )
                )

        # Naming inconsistency (mixed naming conventions)
        snake_case_count = sum(1 for c in columns if "_" in c.name and c.name.islower())
        camel_case_count = sum(
            1 for c in columns if "_" not in c.name and not c.name.isupper()
        )
        if snake_case_count > 0 and camel_case_count > 0:
            # Mixed conventions - only flag if significant
            total = len(columns)
            if snake_case_count > 0.2 * total and camel_case_count > 0.2 * total:
                anomalies.append(
                    SchemaAnomaly(
                        anomaly_type="naming_inconsistency",
                        severity="low",
                        description=(
                            f"Mixed naming conventions detected: "
                            f"{snake_case_count} snake_case, {camel_case_count} camelCase"
                        ),
                        affected_columns=(),
                        recommendation=(
                            "Consider standardizing column naming conventions "
                            "for consistency and maintainability."
                        ),
                    )
                )

        return anomalies

    @staticmethod
    def classify_table_type_heuristic(
        table_name: str,
        columns: list[ColumnInfo],
    ) -> tuple[str, float]:
        """
        Classify table type using heuristics.

        Args:
            table_name: Full table name
            columns: List of column info objects

        Returns:
            Tuple of (classification, confidence)
        """
        column_names = [c.name.lower() for c in columns]
        table_lower = table_name.lower().split(".")[
            -1
        ]  # Get table name without catalog/schema

        # Snapshot indicators
        snapshot_patterns = [
            "snapshot",
            "effective_date",
            "valid_from",
            "valid_to",
            "as_of",
        ]
        if "snapshot" in table_lower or any(
            pattern in col for pattern in snapshot_patterns for col in column_names
        ):
            return "snapshot", 0.8

        # DLT output indicators
        dlt_patterns = ["__apply_changes", "__stream", "_dlt_", "dlt_"]
        if any(pattern in table_lower for pattern in dlt_patterns):
            return "dlt_output", 0.9

        # Dimension indicators
        dim_score = 0.0
        if any(
            pattern in table_lower for pattern in ["dim", "dimension", "lookup", "ref"]
        ):
            dim_score += 0.5
        if any(
            n.endswith("_name") or n.endswith("_desc") or n.endswith("_description")
            for n in column_names
        ):
            dim_score += 0.2
        # Dimensions typically have fewer columns
        if len(columns) < 30:
            dim_score += 0.1

        # Fact indicators
        fact_score = 0.0
        if any(
            pattern in table_lower
            for pattern in ["fact", "fct", "event", "transaction"]
        ):
            fact_score += 0.5
        measure_patterns = [
            "amount",
            "quantity",
            "count",
            "total",
            "sum",
            "value",
            "price",
        ]
        if any(pattern in col for pattern in measure_patterns for col in column_names):
            fact_score += 0.2
        # Facts typically have many rows and timestamp columns
        timestamp_cols = [
            c
            for c in columns
            if c.data_type.upper() in ("TIMESTAMP", "DATE", "DATETIME")
        ]
        if timestamp_cols:
            fact_score += 0.15

        # Incremental indicators
        incremental_patterns = ["watermark", "checkpoint", "offset", "incremental"]
        if any(
            pattern in col for pattern in incremental_patterns for col in column_names
        ):
            return "incremental", 0.7

        # Return best match
        if dim_score > fact_score and dim_score > 0.3:
            return "dimension", min(dim_score, 0.9)
        if fact_score > 0.3:
            return "fact", min(fact_score, 0.9)

        return "unknown", 0.3

    @staticmethod
    def classify_data_layer_heuristic(
        table_name: str,
    ) -> tuple[str, float]:
        """
        Classify data layer (medallion architecture) using heuristics.

        Args:
            table_name: Full table name (catalog.schema.table)

        Returns:
            Tuple of (layer, confidence)
        """
        # Check all parts of the name
        full_name_lower = table_name.lower()

        # Bronze indicators
        bronze_patterns = [
            "bronze",
            "raw",
            "landing",
            "ingest",
            "staging",
            "source",
            "_raw",
            "_landing",
            "_source",
        ]
        if any(pattern in full_name_lower for pattern in bronze_patterns):
            return "bronze", 0.85

        # Silver indicators
        silver_patterns = [
            "silver",
            "clean",
            "cleansed",
            "normalized",
            "curated",
            "_clean",
            "_normalized",
            "_curated",
        ]
        if any(pattern in full_name_lower for pattern in silver_patterns):
            return "silver", 0.85

        # Gold indicators
        gold_patterns = [
            "gold",
            "agg",
            "aggregated",
            "summary",
            "report",
            "analytics",
            "mart",
            "datamart",
            "_agg",
            "_summary",
            "_report",
        ]
        if any(pattern in full_name_lower for pattern in gold_patterns):
            return "gold", 0.85

        # Sandbox/dev indicators
        sandbox_patterns = [
            "sandbox",
            "dev",
            "test",
            "tmp",
            "temp",
            "scratch",
            "_dev",
            "_test",
            "_tmp",
        ]
        if any(pattern in full_name_lower for pattern in sandbox_patterns):
            return "sandbox", 0.8

        # Operational indicators
        operational_patterns = ["operational", "ops", "transactional", "oltp"]
        if any(pattern in full_name_lower for pattern in operational_patterns):
            return "operational", 0.7

        return "unknown", 0.3

    @staticmethod
    def calculate_schema_health(
        column_count: int,
        anomaly_count: int,
        has_partitioning: bool,
        has_clustering: bool,
        stats_age_days: int | None,
    ) -> float:
        """
        Calculate schema health score (0.0-1.0).

        Args:
            column_count: Number of columns
            anomaly_count: Number of detected anomalies
            has_partitioning: Whether table has partitioning
            has_clustering: Whether table has clustering
            stats_age_days: Age of statistics in days (None if unknown)

        Returns:
            Health score between 0.0 and 1.0
        """
        score = 1.0

        # Penalize excessive columns
        if column_count > 100:
            score -= 0.2
        elif column_count > 50:
            score -= 0.1

        # Penalize anomalies
        score -= min(anomaly_count * 0.1, 0.3)

        # Bonus for good practices
        if has_partitioning:
            score += 0.05
        if has_clustering:
            score += 0.05

        # Penalize stale stats
        if stats_age_days is not None:
            if stats_age_days > 30:
                score -= 0.15
            elif stats_age_days > 7:
                score -= 0.05

        return max(0.0, min(1.0, score))

    @staticmethod
    def detect_semantic_patterns(
        columns: list[ColumnInfo],
    ) -> dict[str, list[str]]:
        """
        Detect semantic patterns in column names.

        Args:
            columns: List of column info objects

        Returns:
            Dictionary of pattern types to matching column names
        """
        patterns: dict[str, list[str]] = {
            "id_columns": [],
            "timestamp_columns": [],
            "amount_columns": [],
            "flag_columns": [],
            "foreign_key_columns": [],
        }

        for col in columns:
            name_lower = col.name.lower()
            type_upper = col.data_type.upper()

            # ID columns
            if name_lower.endswith("_id") or name_lower == "id":
                patterns["id_columns"].append(col.name)
                # Also check for FK pattern (other_table_id)
                if name_lower.endswith("_id") and name_lower != "id":
                    patterns["foreign_key_columns"].append(col.name)

            # Timestamp columns
            if type_upper in ("TIMESTAMP", "DATE", "DATETIME") or any(
                pattern in name_lower
                for pattern in [
                    "_at",
                    "_date",
                    "_time",
                    "timestamp",
                    "created",
                    "updated",
                ]
            ):
                patterns["timestamp_columns"].append(col.name)

            # Amount/value columns
            if any(
                pattern in name_lower
                for pattern in [
                    "amount",
                    "price",
                    "cost",
                    "value",
                    "total",
                    "sum",
                    "qty",
                    "quantity",
                ]
            ):
                patterns["amount_columns"].append(col.name)

            # Boolean/flag columns
            if type_upper == "BOOLEAN" or any(
                pattern in name_lower
                for pattern in ["is_", "has_", "flag", "_enabled", "_active"]
            ):
                patterns["flag_columns"].append(col.name)

        return patterns

    # =========================================================================
    # Storage Optimization Analysis
    # =========================================================================

    @staticmethod
    def analyze_storage_health(
        num_files: int,
        total_size_bytes: int,
        min_file_size_bytes: int | None = None,
        max_file_size_bytes: int | None = None,
    ) -> tuple[str, str]:
        """
        Analyze storage health based on file statistics.

        Args:
            num_files: Number of files in table
            total_size_bytes: Total size in bytes
            min_file_size_bytes: Minimum file size
            max_file_size_bytes: Maximum file size

        Returns:
            Tuple of (health_status, description)
        """
        if num_files == 0 or total_size_bytes == 0:
            return "unknown", "No file statistics available"

        avg_file_size = total_size_bytes / num_files
        avg_file_size_mb = avg_file_size / (1024 * 1024)

        # Ideal file size is 128MB-1GB for Delta
        if avg_file_size_mb < 32:
            return (
                "small_files",
                f"Average file size {avg_file_size_mb:.1f}MB is too small. Consider OPTIMIZE.",
            )
        if avg_file_size_mb > 2048:
            return (
                "large_files",
                f"Average file size {avg_file_size_mb:.1f}MB is very large. May impact read performance.",
            )
        if min_file_size_bytes and max_file_size_bytes:
            min_mb = min_file_size_bytes / (1024 * 1024)
            max_mb = max_file_size_bytes / (1024 * 1024)
            if max_mb > 10 * min_mb and min_mb < 32:
                return (
                    "mixed",
                    f"High variance in file sizes ({min_mb:.1f}MB - {max_mb:.1f}MB). Consider OPTIMIZE.",
                )

        return (
            "healthy",
            f"File size distribution is healthy (avg: {avg_file_size_mb:.1f}MB)",
        )

    @staticmethod
    def generate_storage_recommendations(
        storage_state: StorageState,
        access_pattern: str,
        has_liquid_clustering: bool = False,
    ) -> list[StorageRecommendation]:
        """
        Generate storage optimization recommendations.

        Args:
            storage_state: Current storage state
            access_pattern: Access pattern classification
            has_liquid_clustering: Whether liquid clustering is enabled

        Returns:
            List of prioritized recommendations
        """
        recommendations: list[StorageRecommendation] = []

        # Small files → OPTIMIZE
        if storage_state.file_size_health == "small_files":
            recommendations.append(
                StorageRecommendation(
                    recommendation_type="OPTIMIZE",
                    priority=1,
                    title="Compact small files",
                    description=(
                        f"Table has {storage_state.num_files} files with average size "
                        f"{storage_state.avg_file_size_mb:.1f}MB. Small files hurt query performance."
                    ),
                    sql_command="OPTIMIZE catalog.schema.table_name",
                    estimated_improvement="20-50% query performance improvement",
                    effort="low",
                    risks=("May temporarily increase CPU usage during compaction",),
                )
            )

        # No recent VACUUM
        if storage_state.last_vacuum is None:
            recommendations.append(
                StorageRecommendation(
                    recommendation_type="VACUUM",
                    priority=2,
                    title="Run VACUUM to reclaim storage",
                    description=(
                        "No recent VACUUM detected. Old files may be consuming unnecessary storage."
                    ),
                    sql_command="VACUUM catalog.schema.table_name RETAIN 168 HOURS",
                    estimated_improvement="10-30% storage reduction",
                    effort="low",
                    risks=(
                        "Ensure no queries need time travel beyond retention period",
                    ),
                )
            )

        # High-read table without clustering
        if (
            access_pattern in ("high_read_low_write", "balanced")
            and not storage_state.clustering_columns
            and not has_liquid_clustering
        ):
            recommendations.append(
                StorageRecommendation(
                    recommendation_type="LIQUID_CLUSTERING",
                    priority=2,
                    title="Enable liquid clustering",
                    description=(
                        "High-read table without clustering. Liquid clustering can "
                        "significantly improve query performance for filtered queries."
                    ),
                    sql_command="ALTER TABLE catalog.schema.table_name CLUSTER BY (column1, column2)",
                    estimated_improvement="30-70% improvement for filtered queries",
                    effort="medium",
                    risks=(
                        "Requires initial clustering pass",
                        "Choose clustering columns based on common query filters",
                    ),
                )
            )

        # Partition skew
        if storage_state.partition_skew in ("medium", "high"):
            recommendations.append(
                StorageRecommendation(
                    recommendation_type="PARTITION",
                    priority=3,
                    title="Address partition skew",
                    description=(
                        f"Partition skew detected ({storage_state.partition_skew}). "
                        "Some partitions may be significantly larger than others."
                    ),
                    sql_command="-- Review partition sizes and consider repartitioning",
                    estimated_improvement="Improved parallelism and query distribution",
                    effort="high",
                    risks=(
                        "Repartitioning requires data rewrite",
                        "May need to update downstream queries",
                    ),
                )
            )

        # Statistics refresh
        recommendations.append(
            StorageRecommendation(
                recommendation_type="STATISTICS_REFRESH",
                priority=4,
                title="Refresh table statistics",
                description=(
                    "Ensure statistics are up-to-date for optimal query planning."
                ),
                sql_command="ANALYZE TABLE catalog.schema.table_name COMPUTE STATISTICS FOR ALL COLUMNS",
                estimated_improvement="Better query plan selection",
                effort="low",
                risks=(),
            )
        )

        return recommendations

    @staticmethod
    def estimate_optimization_impact(
        current_avg_file_size_mb: float,
        current_num_files: int,
        has_clustering: bool,
        workload_type: str,
    ) -> ImpactEstimate:
        """
        Estimate impact of applying optimizations.

        Args:
            current_avg_file_size_mb: Current average file size
            current_num_files: Current file count
            has_clustering: Whether clustering is enabled
            workload_type: Type of workload

        Returns:
            Impact estimate
        """
        query_improvement = 0.0
        storage_improvement = 0.0
        cost_improvement = 0.0
        confidence = "medium"

        # Small files optimization impact
        if current_avg_file_size_mb < 32:
            query_improvement += 30.0
            storage_improvement += 5.0
            cost_improvement += 15.0

        # Clustering impact for analytical workloads
        if not has_clustering and workload_type in ("analytical", "hybrid"):
            query_improvement += 40.0
            cost_improvement += 20.0

        # High file count
        if current_num_files > 10000:
            query_improvement += 15.0
            storage_improvement += 10.0

        # Adjust confidence based on data availability
        if current_num_files > 100:
            confidence = "high"
        elif current_num_files < 10:
            confidence = "low"

        return ImpactEstimate(
            query_time_reduction_pct=min(query_improvement, 70.0),
            storage_reduction_pct=min(storage_improvement, 30.0),
            cost_reduction_pct=min(cost_improvement, 40.0),
            confidence=confidence,
        )

    # =========================================================================
    # Query Impact Analysis
    # =========================================================================

    @staticmethod
    def predict_join_behavior(
        left_table_rows: int,  # noqa: ARG004
        left_table_size_gb: float,
        right_table_rows: int,  # noqa: ARG004
        right_table_size_gb: float,
        broadcast_threshold_gb: float = 0.01,  # 10MB default
    ) -> JoinPrediction:
        """
        Predict join behavior between two tables.

        Args:
            left_table_rows: Row count of left table
            left_table_size_gb: Size of left table in GB
            right_table_rows: Row count of right table
            right_table_size_gb: Size of right table in GB
            broadcast_threshold_gb: Threshold for broadcast join

        Returns:
            Join prediction
        """
        smaller_size = min(left_table_size_gb, right_table_size_gb)
        larger_size = max(left_table_size_gb, right_table_size_gb)

        # Determine join type
        if smaller_size <= broadcast_threshold_gb:
            join_type = "broadcast"
            risk_level = "low"
            shuffle_gb = 0.0
            recommendation = None
        elif smaller_size <= 1.0:
            # May broadcast or shuffle depending on config
            join_type = "broadcast"
            risk_level = "medium"
            shuffle_gb = 0.0
            recommendation = "Consider explicitly broadcasting the smaller table if query performance is critical"
        elif larger_size > 100:
            # Large tables need sort-merge
            join_type = "sort_merge"
            risk_level = "high" if larger_size > 500 else "medium"
            shuffle_gb = left_table_size_gb + right_table_size_gb
            recommendation = (
                "Consider pre-bucketing tables on join key for better performance"
            )
        else:
            join_type = "shuffle_hash"
            risk_level = "medium"
            shuffle_gb = left_table_size_gb + right_table_size_gb
            recommendation = None

        return JoinPrediction(
            left_table="",  # Filled in by caller
            right_table="",  # Filled in by caller
            join_type=join_type,
            estimated_shuffle_gb=shuffle_gb,
            risk_level=risk_level,
            recommendation=recommendation,
        )

    @staticmethod
    def detect_query_risks(
        table_sizes_gb: list[float],
        table_row_counts: list[int],
        query_pattern: str | None = None,  # noqa: ARG004
    ) -> tuple[bool, bool, bool]:
        """
        Detect potential query performance risks.

        Args:
            table_sizes_gb: List of table sizes
            table_row_counts: List of row counts
            query_pattern: Optional query pattern hint

        Returns:
            Tuple of (broadcast_risk, shuffle_explosion_risk, skew_risk)
        """
        # Broadcast risk: tables too large for broadcast
        broadcast_risk = 0.01 < min(table_sizes_gb) < 1.0 if table_sizes_gb else False

        # Shuffle explosion: large tables being shuffled
        shuffle_explosion_risk = sum(table_sizes_gb) > 500 if table_sizes_gb else False

        # Skew risk: coefficient of variation (CV) indicates high relative spread
        # CV > 1.0 means stdev exceeds mean, indicating significant dispersion
        skew_risk = False
        if len(table_row_counts) >= 2:
            mu = mean(table_row_counts)
            if mu > 0:
                cv = stdev(table_row_counts) / mu
                skew_risk = cv > 1.0

        return broadcast_risk, shuffle_explosion_risk, skew_risk

    # =========================================================================
    # Schema Diff Analysis
    # =========================================================================

    @staticmethod
    def compute_schema_diff(
        old_columns: list[ColumnInfo],
        new_columns: list[ColumnInfo],
    ) -> tuple[list[ColumnDiff], list[ColumnDiff], list[ColumnDiff], bool, str | None]:
        """
        Compute schema differences between two versions.

        Args:
            old_columns: Columns from older version
            new_columns: Columns from newer version

        Returns:
            Tuple of (added, removed, modified, is_breaking, breaking_reason)
        """
        old_by_name = {c.name: c for c in old_columns}
        new_by_name = {c.name: c for c in new_columns}

        added: list[ColumnDiff] = []
        removed: list[ColumnDiff] = []
        modified: list[ColumnDiff] = []
        is_breaking = False
        breaking_reason = None

        # Find added columns
        for name, col in new_by_name.items():
            if name not in old_by_name:
                added.append(
                    ColumnDiff(
                        column_name=name,
                        change_type="added",
                        new_type=col.data_type,
                        new_nullable=col.nullable,
                    )
                )
                # Adding non-nullable column is breaking
                if not col.nullable:
                    is_breaking = True
                    breaking_reason = f"Added non-nullable column: {name}"

        # Find removed columns
        for name, col in old_by_name.items():
            if name not in new_by_name:
                removed.append(
                    ColumnDiff(
                        column_name=name,
                        change_type="removed",
                        old_type=col.data_type,
                        old_nullable=col.nullable,
                    )
                )
                # Removing column is breaking
                is_breaking = True
                breaking_reason = f"Removed column: {name}"

        # Find modified columns
        for name, new_col in new_by_name.items():
            if name in old_by_name:
                old_col = old_by_name[name]
                if (
                    old_col.data_type != new_col.data_type
                    or old_col.nullable != new_col.nullable
                ):
                    modified.append(
                        ColumnDiff(
                            column_name=name,
                            change_type="modified",
                            old_type=old_col.data_type,
                            new_type=new_col.data_type,
                            old_nullable=old_col.nullable,
                            new_nullable=new_col.nullable,
                        )
                    )
                    # Type change is breaking
                    if old_col.data_type != new_col.data_type:
                        is_breaking = True
                        breaking_reason = f"Type changed for column {name}: {old_col.data_type} -> {new_col.data_type}"
                    # Making nullable -> non-nullable is breaking
                    elif old_col.nullable and not new_col.nullable:
                        is_breaking = True
                        breaking_reason = (
                            f"Column {name} changed from nullable to non-nullable"
                        )

        return added, removed, modified, is_breaking, breaking_reason

    # =========================================================================
    # Policy Coverage Analysis
    # =========================================================================

    @staticmethod
    def analyze_policy_gaps(
        assets_count: int,
        assets_with_owner: int,
        assets_with_grants: int,
        assets_with_row_filters: int,
        has_pii_columns: bool = False,
        has_public_access: bool = False,
    ) -> list[PolicyGap]:
        """
        Identify policy coverage gaps.

        Args:
            assets_count: Total number of assets
            assets_with_owner: Assets with assigned owner
            assets_with_grants: Assets with explicit grants
            assets_with_row_filters: Assets with row-level security
            has_pii_columns: Whether PII columns are detected
            has_public_access: Whether public access is enabled

        Returns:
            List of identified policy gaps
        """
        gaps: list[PolicyGap] = []

        # No owner
        if assets_with_owner < assets_count:
            unowned = assets_count - assets_with_owner
            gaps.append(
                PolicyGap(
                    gap_type="no_owner",
                    severity="medium" if unowned < assets_count * 0.2 else "high",
                    description=f"{unowned} assets have no assigned owner",
                    affected_assets=(),  # Would need to be filled by caller
                    recommendation="Assign owners to all assets for accountability",
                )
            )

        # No grants
        if assets_with_grants == 0:
            gaps.append(
                PolicyGap(
                    gap_type="no_grants",
                    severity="high",
                    description="No explicit grants configured - may rely on inherited permissions",
                    affected_assets=(),
                    recommendation="Review and configure explicit access grants",
                )
            )

        # PII without protection
        if has_pii_columns and assets_with_row_filters == 0:
            gaps.append(
                PolicyGap(
                    gap_type="missing_pii_protection",
                    severity="critical",
                    description="PII columns detected but no row-level or column-level security",
                    affected_assets=(),
                    recommendation="Implement column masking or row-level security for PII data",
                )
            )

        # Public access
        if has_public_access:
            gaps.append(
                PolicyGap(
                    gap_type="public_access",
                    severity="critical",
                    description="Public access enabled - data accessible to all users",
                    affected_assets=(),
                    recommendation="Review and restrict public access unless explicitly required",
                )
            )

        return gaps

    @staticmethod
    def calculate_security_score(
        ownership_coverage: float,
        access_control_coverage: float,
        data_protection_coverage: float,
        gap_count: int,
        critical_gap_count: int,
    ) -> float:
        """
        Calculate overall security score.

        Args:
            ownership_coverage: Percentage of assets with owners
            access_control_coverage: Percentage with explicit grants
            data_protection_coverage: Percentage with data protection
            gap_count: Total policy gaps
            critical_gap_count: Number of critical gaps

        Returns:
            Security score 0.0-1.0
        """
        # Base score from coverage
        score = (
            ownership_coverage + access_control_coverage + data_protection_coverage
        ) / 3

        # Penalize gaps
        score -= gap_count * 0.05
        score -= critical_gap_count * 0.15

        return max(0.0, min(1.0, score))


# =============================================================================
# Table Discovery Analyzer
# =============================================================================


class TableAnalyzer:
    """Pure functions for analyzing and categorizing discovered tables.

    Provides table discovery, deduplication, and categorization logic.
    All methods are stateless and can be called independently.

    Example:
        >>> refs = [
        ...     TableReference(resolved_3part="catalog.schema.table1", ...),
        ...     TableReference(resolved_3part="catalog.schema.table1", ...)
        ... ]
        >>> result = TableAnalyzer.deduplicate_tables(refs)
        >>> len(result)
        1
    """

    @staticmethod
    def deduplicate_tables(
        all_tables: list[TableReference],
    ) -> list[TableReference]:
        """
        Deduplicate tables by resolved 3-part name.

        Args:
            all_tables: List of table references to deduplicate

        Returns:
            Deduplicated list of table references
        """
        unique_tables = {}
        for table in all_tables:
            table_name = table.resolved_3part
            if table_name not in unique_tables:
                unique_tables[table_name] = table

        return list(unique_tables.values())

    @staticmethod
    def categorize_tables(
        table_refs: list[TableReference],
    ) -> TableDiscoveryResult:
        """
        Categorize table references into different types.

        Categorizes tables into:
        - All tables (all references)
        - Source tables (read from)
        - Target tables (written to)
        - Tables and views only (excludes temp tables, CTEs, system tables)

        Args:
            table_refs: List of deduplicated table references

        Returns:
            TableDiscoveryResult with categorized tables
        """
        # Extract lists for convenience
        all_tables = [t.resolved_3part for t in table_refs]
        source_tables = [t.resolved_3part for t in table_refs if t.is_source]
        target_tables = [t.resolved_3part for t in table_refs if t.is_destination]

        # Filter tables/views only (exclude temp tables, temp views, CTEs, system tables)
        tables_and_views_only = [
            t.resolved_3part for t in table_refs if t.type in ("table", "view")
        ]

        logger.debug(
            "Categorized %d unique references (%d tables/views, %d temp/CTE/system)",
            len(all_tables),
            len(tables_and_views_only),
            len(all_tables) - len(tables_and_views_only),
        )

        return TableDiscoveryResult(
            all_tables=all_tables,
            source_tables=source_tables,
            target_tables=target_tables,
            tables_and_views=tables_and_views_only,
            table_references=table_refs,
        )

    @staticmethod
    def convert_table_reference_dicts(
        table_references_data: list[dict | TableReference],
    ) -> list[TableReference]:
        """
        Convert dict representations to TableReference objects.

        Args:
            table_references_data: List of dicts or TableReference objects

        Returns:
            List of TableReference objects
        """
        table_references: list[TableReference] = []
        for t in table_references_data:
            if isinstance(t, dict):
                # Reconstruct TableReference from dict
                table_references.append(
                    TableReference(
                        raw=t.get("raw", ""),
                        table=t.get("table", ""),
                        resolved_3part=t.get("resolved_3part", ""),
                        catalog=t.get("catalog"),
                        schema=t.get("schema"),
                        type=t.get("type", "table"),
                        is_source=t.get("is_source", False),
                        is_destination=t.get("is_destination", False),
                    )
                )
            else:
                table_references.append(t)

        logger.debug("Converted %d table reference dicts", len(table_references))
        return table_references
