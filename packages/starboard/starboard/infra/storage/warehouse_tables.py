# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""UC table definitions for warehouse agent.

Defines Delta tables stored in Unity Catalog for warehouse agent state,
SLO configurations, and historical fingerprints.
"""

from starboard.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)


def register_warehouse_tables(registry: TableRegistry) -> None:
    """Register all warehouse-specific tables.

    Args:
        registry: Table registry to register tables in.
    """
    # SLO Configuration Table
    registry.register(
        TableDef(
            table_id="warehouse_slo_config",
            table_name="warehouse_slo_config",
            columns=(
                ColumnDef(
                    "warehouse_id",
                    "STRING",
                    nullable=False,
                    comment="Warehouse identifier",
                ),
                ColumnDef(
                    "slo_type",
                    "STRING",
                    nullable=False,
                    comment="SLO type (p95_latency, availability, etc.)",
                ),
                ColumnDef(
                    "target_value",
                    "DOUBLE",
                    nullable=False,
                    comment="Target value for the SLO",
                ),
                ColumnDef(
                    "unit", "STRING", nullable=False, comment="Unit of measurement"
                ),
                ColumnDef(
                    "warning_threshold", "DOUBLE", comment="Warning threshold value"
                ),
                ColumnDef(
                    "critical_threshold", "DOUBLE", comment="Critical threshold value"
                ),
                ColumnDef(
                    "enabled",
                    "BOOLEAN",
                    nullable=False,
                    comment="Whether SLO is active",
                ),
                ColumnDef(
                    "created_at",
                    "TIMESTAMP",
                    nullable=False,
                    comment="Creation timestamp",
                ),
                ColumnDef(
                    "updated_at",
                    "TIMESTAMP",
                    nullable=False,
                    comment="Last update timestamp",
                ),
                ColumnDef(
                    "created_by", "STRING", comment="User who created the config"
                ),
                ColumnDef("notes", "STRING", comment="Optional notes"),
            ),
            primary_key=("warehouse_id", "slo_type"),
            comment="SLO configurations for SQL warehouses",
            properties={"delta.autoOptimize.optimizeWrite": "true"},
        )
    )

    # Fingerprint History Table
    registry.register(
        TableDef(
            table_id="warehouse_fingerprint_history",
            table_name="warehouse_fingerprint_history",
            columns=(
                ColumnDef(
                    "fingerprint_id",
                    "STRING",
                    nullable=False,
                    comment="Unique fingerprint ID",
                ),
                ColumnDef(
                    "warehouse_id",
                    "STRING",
                    nullable=False,
                    comment="Warehouse identifier",
                ),
                ColumnDef(
                    "warehouse_name", "STRING", nullable=False, comment="Warehouse name"
                ),
                ColumnDef(
                    "analysis_window_days",
                    "INT",
                    nullable=False,
                    comment="Days of data analyzed",
                ),
                ColumnDef(
                    "analyzed_at",
                    "TIMESTAMP",
                    nullable=False,
                    comment="When fingerprint was generated",
                ),
                # Volume metrics
                ColumnDef("total_queries", "BIGINT", comment="Total query count"),
                ColumnDef("total_bytes_read", "BIGINT", comment="Total bytes read"),
                ColumnDef(
                    "total_bytes_written", "BIGINT", comment="Total bytes written"
                ),
                # Performance baseline
                ColumnDef("p50_runtime_sec", "DOUBLE", comment="Median runtime"),
                ColumnDef(
                    "p75_runtime_sec", "DOUBLE", comment="75th percentile runtime"
                ),
                ColumnDef(
                    "p90_runtime_sec", "DOUBLE", comment="90th percentile runtime"
                ),
                ColumnDef(
                    "p95_runtime_sec", "DOUBLE", comment="95th percentile runtime"
                ),
                ColumnDef(
                    "p99_runtime_sec", "DOUBLE", comment="99th percentile runtime"
                ),
                # Concurrency
                ColumnDef(
                    "avg_concurrency", "DOUBLE", comment="Average concurrent queries"
                ),
                ColumnDef(
                    "peak_concurrency", "INT", comment="Maximum concurrent queries"
                ),
                # Queue metrics
                ColumnDef("avg_queue_time_sec", "DOUBLE", comment="Average queue time"),
                ColumnDef(
                    "p95_queue_time_sec", "DOUBLE", comment="95th percentile queue time"
                ),
                ColumnDef(
                    "queue_rate_pct",
                    "DOUBLE",
                    comment="Percentage of queries that queued",
                ),
                # Patterns (stored as JSON)
                ColumnDef(
                    "query_type_distribution",
                    "STRING",
                    comment="Query type distribution JSON",
                ),
                ColumnDef(
                    "hourly_distribution", "STRING", comment="Hourly distribution JSON"
                ),
                ColumnDef(
                    "workload_pattern",
                    "STRING",
                    comment="Workload pattern classification",
                ),
            ),
            primary_key=("fingerprint_id",),
            partition_by=("warehouse_id",),
            comment="Historical fingerprints for warehouses",
            properties={
                "delta.autoOptimize.optimizeWrite": "true",
                "delta.autoOptimize.autoCompact": "true",
            },
        )
    )

    # Health History Table
    registry.register(
        TableDef(
            table_id="warehouse_health_history",
            table_name="warehouse_health_history",
            columns=(
                ColumnDef(
                    "health_id",
                    "STRING",
                    nullable=False,
                    comment="Unique health record ID",
                ),
                ColumnDef(
                    "warehouse_id",
                    "STRING",
                    nullable=False,
                    comment="Warehouse identifier",
                ),
                ColumnDef(
                    "warehouse_name", "STRING", nullable=False, comment="Warehouse name"
                ),
                ColumnDef(
                    "recorded_at",
                    "TIMESTAMP",
                    nullable=False,
                    comment="When health was recorded",
                ),
                # Health scores
                ColumnDef(
                    "health_score",
                    "DOUBLE",
                    nullable=False,
                    comment="Overall health score 0-100",
                ),
                ColumnDef(
                    "health_status",
                    "STRING",
                    nullable=False,
                    comment="Status: healthy/warning/critical",
                ),
                # SLO compliance
                ColumnDef(
                    "overall_slo_compliance",
                    "DOUBLE",
                    comment="Aggregate SLO compliance %",
                ),
                ColumnDef("slo_details", "STRING", comment="SLO status details JSON"),
                # Risk factors
                ColumnDef("risk_level", "STRING", comment="Aggregate risk level"),
                ColumnDef("risk_factors", "STRING", comment="Risk factors JSON"),
            ),
            primary_key=("health_id",),
            partition_by=("warehouse_id",),
            cluster_by=("recorded_at",),
            comment="Health history for warehouses",
            properties={"delta.autoOptimize.optimizeWrite": "true"},
        )
    )

    # What-If Scenario Results Table
    registry.register(
        TableDef(
            table_id="warehouse_scenario_results",
            table_name="warehouse_scenario_results",
            columns=(
                ColumnDef(
                    "scenario_id",
                    "STRING",
                    nullable=False,
                    comment="Unique scenario ID",
                ),
                ColumnDef(
                    "warehouse_id",
                    "STRING",
                    nullable=False,
                    comment="Warehouse being evaluated",
                ),
                ColumnDef(
                    "scenario_name", "STRING", nullable=False, comment="Scenario name"
                ),
                ColumnDef(
                    "scenario_description", "STRING", comment="Scenario description"
                ),
                ColumnDef(
                    "created_at",
                    "TIMESTAMP",
                    nullable=False,
                    comment="When scenario was evaluated",
                ),
                ColumnDef("created_by", "STRING", comment="User who created scenario"),
                # Parameters
                ColumnDef("parameters", "STRING", comment="Scenario parameters JSON"),
                # Predictions
                ColumnDef(
                    "predicted_cost_usd", "DOUBLE", comment="Predicted monthly cost"
                ),
                ColumnDef(
                    "predicted_p95_latency", "DOUBLE", comment="Predicted p95 latency"
                ),
                ColumnDef("risk_score", "DOUBLE", comment="Risk score 0-1"),
                ColumnDef("confidence", "STRING", comment="Confidence level"),
                # Results
                ColumnDef(
                    "recommended", "BOOLEAN", comment="Whether scenario is recommended"
                ),
                ColumnDef("recommendation_rationale", "STRING", comment="Explanation"),
                ColumnDef("full_results", "STRING", comment="Complete results JSON"),
            ),
            primary_key=("scenario_id",),
            partition_by=("warehouse_id",),
            comment="What-if scenario evaluation results",
            properties={"delta.autoOptimize.optimizeWrite": "true"},
        )
    )


# Pre-instantiated registry with warehouse tables
WAREHOUSE_TABLE_REGISTRY = TableRegistry()
register_warehouse_tables(WAREHOUSE_TABLE_REGISTRY)
