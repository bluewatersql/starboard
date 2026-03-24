"""Unity Catalog domain models.

These models define the data structures used throughout the UC domain,
following the project's conventions of frozen dataclasses for immutability.

Example:
    >>> from starboard_core.domain.models.uc import UCTableMetadata, TableLineage
    >>> metadata = UCTableMetadata(
    ...     full_name="catalog.schema.table",
    ...     catalog="catalog",
    ...     schema="schema",
    ...     table="table",
    ...     table_type="MANAGED",
    ...     data_format="DELTA",
    ...     columns=(),
    ...     column_count=0,
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# =============================================================================
# Asset Models
# =============================================================================


@dataclass(frozen=True)
class UCAssetInfo:
    """Basic asset information for UC objects."""

    name: str
    full_name: str
    asset_type: str  # "catalog", "schema", "table", "volume", "function", "view"
    owner: str | None = None
    created_at: datetime | None = None
    comment: str | None = None


@dataclass(frozen=True)
class UCAssetList:
    """Result of UC asset enumeration."""

    catalog: str | None
    schema: str | None
    asset_type: str
    assets: tuple[UCAssetInfo, ...]
    total_count: int
    truncated: bool


@dataclass(frozen=True)
class ColumnInfo:
    """Column metadata."""

    name: str
    data_type: str
    position: int
    nullable: bool = True
    comment: str | None = None
    is_partition: bool = False
    is_clustering: bool = False


@dataclass(frozen=True)
class UCTableMetadata:
    """Comprehensive table metadata."""

    full_name: str
    catalog: str
    schema: str
    table: str
    table_type: Literal["MANAGED", "EXTERNAL", "VIEW"]
    data_format: str  # DELTA, PARQUET, etc.

    # Schema info
    columns: tuple[ColumnInfo, ...]
    column_count: int

    # Storage info (from DESCRIBE DETAIL)
    location: str | None = None
    num_files: int | None = None
    size_bytes: int | None = None
    partition_columns: tuple[str, ...] | None = None
    clustering_columns: tuple[str, ...] | None = None

    # Statistics
    row_count: int | None = None
    last_modified: datetime | None = None
    statistics_freshness: datetime | None = None

    # Properties
    properties: dict[str, str] | None = None

    # Ownership
    owner: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


# =============================================================================
# Lineage Models
# =============================================================================


@dataclass(frozen=True)
class LineageNode:
    """Single node in lineage graph.

    Represents a table in the lineage graph with its connections
    to jobs and notebooks that access it.

    Note: The REST API only returns direct (1-hop) dependencies.
    For transitive lineage, query system.access.table_lineage.
    """

    table_name: str
    catalog: str
    schema: str
    table_type: str = "UNKNOWN"
    job_count: int = 0
    notebook_count: int = 0
    job_ids: tuple[int, ...] = ()
    notebook_ids: tuple[int, ...] = ()
    last_updated: str | None = None


@dataclass(frozen=True)
class TableLineage:
    """Table lineage information.

    Contains upstream (dependencies) and downstream (consumers) tables
    for a given target table.
    """

    table_name: str
    upstream: tuple[LineageNode, ...]
    downstream: tuple[LineageNode, ...]
    truncated: bool = False


# =============================================================================
# Grants Models
# =============================================================================


@dataclass(frozen=True)
class Grant:
    """Single grant assignment."""

    principal: str  # User, group, or service principal
    principal_type: str  # "USER", "GROUP", "SERVICE_PRINCIPAL"
    privileges: tuple[str, ...]  # SELECT, MODIFY, etc.
    inherited_from: str | None = None  # catalog or schema if inherited


@dataclass(frozen=True)
class EffectivePermission:
    """Resolved effective permission."""

    principal: str
    privilege: str
    source: str  # Where this permission comes from


@dataclass(frozen=True)
class TableGrants:
    """Table access control information."""

    table_name: str
    owner: str
    direct_grants: tuple[Grant, ...]
    inherited_grants: tuple[Grant, ...]
    effective_permissions: tuple[EffectivePermission, ...]


# =============================================================================
# Schema Analysis Models
# =============================================================================


@dataclass(frozen=True)
class SchemaAnomaly:
    """Detected schema anomaly."""

    anomaly_type: Literal[
        "excessive_columns",
        "json_blob_antipattern",
        "type_mismatch",
        "naming_inconsistency",
        "missing_partition",
        "wide_string_columns",
    ]
    severity: Literal["low", "medium", "high"]
    description: str
    affected_columns: tuple[str, ...]
    recommendation: str


@dataclass(frozen=True)
class SchemaAnalysis:
    """Schema analysis results."""

    table_name: str
    column_count: int

    # Classification
    table_classification: (
        str  # "fact", "dimension", "snapshot", "incremental", "dlt_output", "unknown"
    )
    data_layer: str  # "bronze", "silver", "gold", "operational", "sandbox", "unknown"
    classification_confidence: float

    # Patterns detected
    id_columns: tuple[str, ...]
    timestamp_columns: tuple[str, ...]
    partition_columns: tuple[str, ...]
    clustering_columns: tuple[str, ...]

    # Anomalies
    anomalies: tuple[SchemaAnomaly, ...]
    health_score: float  # 0.0-1.0


@dataclass(frozen=True)
class SchemaChange:
    """Individual schema change."""

    version: int
    timestamp: datetime
    change_type: str  # "ADD_COLUMN", "DROP_COLUMN", "TYPE_CHANGE", "RENAME", "NULLABLE_CHANGE", "MODIFY_COLUMN"
    column_name: str
    old_value: str | None
    new_value: str | None
    user: str


@dataclass(frozen=True)
class SchemaDriftAnalysis:
    """Schema drift analysis results."""

    table_name: str
    current_version: int
    versions_analyzed: int

    # Drift summary
    drift_detected: bool
    drift_severity: str  # "none", "low", "medium", "high"

    # Changes
    schema_changes: tuple[SchemaChange, ...]

    # Stats
    columns_added: int
    columns_removed: int
    columns_modified: int
    type_changes: int

    # Last stable schema
    last_stable_version: int
    last_stable_date: datetime


# =============================================================================
# Delta History Models
# =============================================================================


@dataclass(frozen=True)
class DeltaHistoryEntry:
    """Single history entry."""

    version: int
    timestamp: datetime
    user: str
    operation: str
    operation_parameters: dict[str, str] | None = None
    metrics: dict[str, int] | None = None
    is_schema_change: bool = False


@dataclass(frozen=True)
class DeltaHistory:
    """Delta table history."""

    table_name: str
    current_version: int
    entries: tuple[DeltaHistoryEntry, ...]
    total_versions: int

    # Summary stats
    operations_summary: dict[str, int] | None = None  # {MERGE: 45, WRITE: 12, ...}
    last_optimize: datetime | None = None
    last_vacuum: datetime | None = None
    schema_changes_count: int = 0


# =============================================================================
# Access Pattern Models
# =============================================================================


@dataclass(frozen=True)
class UserAccess:
    """User access summary."""

    user: str
    access_count: int
    total_bytes: int = 0  # Total bytes read/written by user
    last_access: datetime | None = None


@dataclass(frozen=True)
class DailyAccess:
    """Daily access count."""

    date: str  # ISO date string
    count: int


@dataclass(frozen=True)
class AccessPatterns:
    """Table access pattern analysis."""

    table_name: str
    window_days: int

    # Read patterns
    read_query_count: int
    total_read_bytes: int
    avg_read_gb: float
    p95_read_gb: float
    distinct_readers: int
    last_read: datetime | None

    # Write patterns
    write_operation_count: int
    total_written_bytes: int
    last_write: datetime | None

    # Users
    top_readers: tuple[UserAccess, ...] | None = None

    # Trends
    daily_trend: tuple[DailyAccess, ...] | None = None
    peak_hour: int | None = None

    # Classification
    access_pattern: str = "unknown"  # "high_read_low_write", "high_write_low_read", "balanced", "inactive", "burst_access"


# =============================================================================
# Storage Optimization Models
# =============================================================================


@dataclass(frozen=True)
class StorageState:
    """Current storage state."""

    num_files: int
    total_size_gb: float
    avg_file_size_mb: float
    min_file_size_mb: float
    max_file_size_mb: float
    partition_count: int | None = None
    clustering_columns: tuple[str, ...] | None = None
    last_optimize: datetime | None = None
    last_vacuum: datetime | None = None
    file_size_health: str = (  # "healthy", "small_files", "large_files", "mixed"
        "healthy"
    )
    partition_skew: Literal["none", "low", "medium", "high"] | None = None


@dataclass(frozen=True)
class StorageRecommendation:
    """Single storage recommendation."""

    recommendation_type: Literal[
        "OPTIMIZE",
        "VACUUM",
        "CLUSTER",
        "PARTITION",
        "Z_ORDER",
        "LIQUID_CLUSTERING",
        "FILE_COMPACTION",
        "STATISTICS_REFRESH",
    ]
    priority: int  # 1-5, 1 = highest
    title: str
    description: str
    sql_command: str
    estimated_improvement: str
    effort: Literal["low", "medium", "high"]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class ImpactEstimate:
    """Estimated impact of recommendations."""

    query_time_reduction_pct: float
    storage_reduction_pct: float
    cost_reduction_pct: float
    confidence: str  # "low", "medium", "high"


@dataclass(frozen=True)
class StorageOptimizationReport:
    """Storage optimization recommendations."""

    table_name: str
    current_state: StorageState
    recommendations: tuple[StorageRecommendation, ...]
    estimated_impact: ImpactEstimate | None


# =============================================================================
# Query Impact Models
# =============================================================================


@dataclass(frozen=True)
class JoinPrediction:
    """Predicted join behavior."""

    left_table: str
    right_table: str
    join_type: str  # "broadcast", "shuffle_hash", "sort_merge", "nested_loop"
    estimated_shuffle_gb: float
    risk_level: str  # "low", "medium", "high"
    recommendation: str | None = None


@dataclass(frozen=True)
class QueryImpactAnalysis:
    """Query performance impact analysis."""

    tables: tuple[str, ...]
    total_rows_estimate: int
    total_size_gb: float

    # Join analysis
    join_predictions: tuple[JoinPrediction, ...]
    broadcast_risk: bool
    shuffle_explosion_risk: bool
    skew_risk: bool

    # Recommendations
    join_hints: tuple[str, ...]
    clustering_recommendations: tuple[str, ...]
    filter_recommendations: tuple[str, ...]


# =============================================================================
# Optimization Simulation Models
# =============================================================================


@dataclass(frozen=True)
class OptimizationScenario:
    """Optimization scenario to simulate."""

    add_clustering: tuple[str, ...] | None = None
    change_partitioning: tuple[str, ...] | None = None
    enable_optimize: bool = False
    enable_vacuum: bool = False


@dataclass(frozen=True)
class SimulationResult:
    """Result of optimization simulation."""

    scenario: OptimizationScenario
    current_metrics: dict[str, float]
    projected_metrics: dict[str, float]
    improvement_summary: str
    implementation_steps: tuple[str, ...]
    estimated_duration: str
    risks: tuple[str, ...]
    confidence: str  # "low", "medium", "high"


# =============================================================================
# Table Fingerprint Models
# =============================================================================


@dataclass(frozen=True)
class ReadWorkloadMetrics:
    """Read workload metrics from system tables."""

    query_count: int
    total_read_gb: float
    avg_read_gb: float
    p95_read_gb: float
    total_runtime_sec: float
    avg_runtime_sec: float
    p95_runtime_sec: float
    distinct_readers: int
    last_read_time: datetime | None

    # Query pattern analysis
    peak_queries_per_hour: int
    common_filters: tuple[str, ...]  # Most frequent WHERE clause columns
    common_aggregations: tuple[str, ...]  # COUNT, SUM, AVG, etc.
    pct_queries_with_groupby: float  # % of queries with GROUP BY


@dataclass(frozen=True)
class WriteWorkloadMetrics:
    """Write workload metrics from system tables."""

    write_op_count: int
    merge_op_count: int
    insert_op_count: int
    update_op_count: int
    delete_op_count: int
    total_written_gb: float
    p95_write_runtime_sec: float

    # Write pattern
    dominant_write_operation: str  # "INSERT", "MERGE", "UPDATE", "DELETE", "NONE"


@dataclass(frozen=True)
class CostMetrics:
    """Cost metrics from billing system tables."""

    total_dbus: float
    avg_dbus_per_day: float


@dataclass(frozen=True)
class WorkloadProfile:
    """Comprehensive workload fingerprint."""

    table_name: str
    window_days: int

    # Read characteristics
    read_heavy: bool
    avg_queries_per_day: float
    peak_queries_per_hour: int
    common_filters: tuple[str, ...]
    common_aggregations: tuple[str, ...]

    # Write characteristics
    write_heavy: bool
    avg_writes_per_day: float
    dominant_write_operation: Literal[
        "INSERT", "MERGE", "UPDATE", "DELETE", "OVERWRITE"
    ]
    batch_vs_streaming: Literal["batch", "streaming", "mixed"]

    # Usage classification
    workload_type: Literal[
        "analytical",
        "operational",
        "hybrid",
        "archive",
        "staging",
    ]
    recommended_tier: Literal["hot", "warm", "cold"]


@dataclass(frozen=True)
class TableFingerprint:
    """Complete table fingerprint from system tables.

    Combines structural metadata, read/write workload analysis,
    query patterns, and cost attribution into a single view.
    """

    table_name: str
    window_days: int

    # Structural metadata
    table_type: str | None
    storage_format: str | None
    storage_path: str | None
    created: datetime | None
    last_altered: datetime | None
    comment: str | None

    # Read workload
    read_metrics: ReadWorkloadMetrics | None

    # Write workload
    write_metrics: WriteWorkloadMetrics | None

    # Cost metrics
    cost_metrics: CostMetrics | None

    # Derived classifications
    workload_type: str  # "analytical", "operational", "hybrid", "archive", "staging"
    recommended_tier: str  # "hot", "warm", "cold"

    # For backward compatibility with legacy fingerprint structure
    metadata: UCTableMetadata | None = None
    access_patterns: AccessPatterns | None = None
    workload: WorkloadProfile | None = None
    storage_state: StorageState | None = None


# =============================================================================
# Cost Attribution Models
# =============================================================================


@dataclass(frozen=True)
class CostBreakdown:
    """Cost breakdown for a table."""

    table_name: str
    window_days: int

    # Storage costs
    storage_cost_usd: float
    storage_gb: float

    # Compute costs (queries reading this table)
    compute_cost_usd: float
    total_dbu_consumed: float
    query_count: int

    # Write costs
    write_cost_usd: float
    write_dbu_consumed: float

    # Totals
    total_cost_usd: float
    cost_per_gb: float
    cost_per_query: float

    # Trend
    cost_trend: str  # "increasing", "decreasing", "stable"
    cost_change_pct: float


# =============================================================================
# Schema Diff Models
# =============================================================================


@dataclass(frozen=True)
class ColumnDiff:
    """Difference in a single column between versions."""

    column_name: str
    change_type: str  # "added", "removed", "modified"
    old_type: str | None = None
    new_type: str | None = None
    old_nullable: bool | None = None
    new_nullable: bool | None = None


@dataclass(frozen=True)
class SchemaDiff:
    """Schema comparison between two versions."""

    table_name: str
    version_from: int
    version_to: int
    timestamp_from: datetime | None
    timestamp_to: datetime | None

    columns_added: tuple[ColumnDiff, ...]
    columns_removed: tuple[ColumnDiff, ...]
    columns_modified: tuple[ColumnDiff, ...]

    is_breaking_change: bool
    breaking_reason: str | None = None
    migration_sql: str | None = None


# =============================================================================
# Policy Coverage Models
# =============================================================================


@dataclass(frozen=True)
class PolicyGap:
    """Identified policy gap."""

    gap_type: Literal[
        "no_owner",
        "no_grants",
        "overly_permissive",
        "missing_pii_protection",
        "public_access",
        "stale_permissions",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    affected_assets: tuple[str, ...]
    recommendation: str


@dataclass(frozen=True)
class PolicyCoverageReport:
    """Security policy completeness analysis."""

    scope: str  # catalog, schema, or table
    assets_analyzed: int

    # Coverage metrics
    assets_with_owner: int
    assets_with_grants: int
    assets_with_row_filters: int
    assets_with_column_masks: int

    # Coverage percentages
    ownership_coverage_pct: float
    access_control_coverage_pct: float
    data_protection_coverage_pct: float

    # Gaps
    policy_gaps: tuple[PolicyGap, ...]
    overall_security_score: float  # 0.0-1.0


# =============================================================================
# Table Discovery Models
# =============================================================================


@dataclass(frozen=True)
class TableDiscoveryInput:
    """Input for table discovery operation.

    Provides the source material from which to extract table references.
    """

    sql_text: str | None = None
    adhoc_source: str | None = None
    task_sources: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class TableDiscoveryResult:
    """Result of table discovery operation.

    Contains categorized table references extracted from source code/SQL.

    Note: Requires importing TableReference from starboard_core when using
    the table_references field.
    """

    all_tables: list[str]
    source_tables: list[str]
    target_tables: list[str]
    tables_and_views: list[str]
    # Note: TableReference is from starboard_core.domain.models.databricks
    table_references: list  # list[TableReference] - use Any to avoid circular import


@dataclass(frozen=True)
class TableMetadataRequest:
    """Request for table metadata."""

    table_names: list[str]


@dataclass(frozen=True)
class TableEnrichmentInput:
    """Input for table enrichment operation."""

    # Note: TableReference is from starboard_core.domain.models.databricks
    table_references_data: list  # list[dict | TableReference]


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Asset models
    "UCAssetInfo",
    "UCAssetList",
    "ColumnInfo",
    "UCTableMetadata",
    # Lineage models
    "LineageNode",
    "TableLineage",
    # Grants models
    "Grant",
    "EffectivePermission",
    "TableGrants",
    # Schema analysis models
    "SchemaAnomaly",
    "SchemaAnalysis",
    "SchemaChange",
    "SchemaDriftAnalysis",
    # Delta history models
    "DeltaHistoryEntry",
    "DeltaHistory",
    # Access pattern models
    "UserAccess",
    "DailyAccess",
    "AccessPatterns",
    # Storage optimization models
    "StorageState",
    "StorageRecommendation",
    "ImpactEstimate",
    "StorageOptimizationReport",
    # Query impact models
    "JoinPrediction",
    "QueryImpactAnalysis",
    # Optimization simulation models
    "OptimizationScenario",
    "SimulationResult",
    # Table fingerprint models
    "ReadWorkloadMetrics",
    "WriteWorkloadMetrics",
    "CostMetrics",
    "WorkloadProfile",
    "TableFingerprint",
    # Cost attribution models
    "CostBreakdown",
    # Schema diff models
    "ColumnDiff",
    "SchemaDiff",
    # Policy coverage models
    "PolicyGap",
    "PolicyCoverageReport",
    # Table discovery models
    "TableDiscoveryInput",
    "TableDiscoveryResult",
    "TableMetadataRequest",
    "TableEnrichmentInput",
]
