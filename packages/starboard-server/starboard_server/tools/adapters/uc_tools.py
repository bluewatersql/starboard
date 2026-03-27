"""Reasoning interface for Unity Catalog tools.

This module provides the LLM-facing interface for UC operations,
translating between tool call parameters and domain service methods.

Includes both Unity Catalog API operations and LLM-based table discovery.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl

    from starboard_server.adapters.databricks import AsyncDatabricksClient
    from starboard_server.adapters.llm.base import BaseLLMClient
    from starboard_server.infra.observability.events import EventEmitter

from starboard_server.exceptions import AdapterError, ToolError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter
from starboard_server.tools.services.query_workload_service import (
    QueryWorkloadService,
)
from starboard_server.tools.services.uc_service import (
    SQLQueryProvider,
    TableDiscoveryProvider,
    TableEnricherProvider,
    UCService,
)

logger = get_logger(__name__)


class DatabricksSQLProvider(SQLQueryProvider):
    """SQL provider adapter wrapping AsyncDatabricksClient for system table queries.

    Implements the SQLQueryProvider protocol to enable UC service
    operations that require SQL execution (e.g., DESCRIBE HISTORY,
    system tables for access patterns, costs).

    Supports both dict-based and Polars DataFrame outputs:
    - execute_query(): Returns list[dict] for legacy compatibility
    - execute_query_polars(): Returns pl.DataFrame for efficient processing

    Example:
        >>> provider = DatabricksSQLProvider(async_client)
        >>> rows = await provider.execute_query("SELECT 1")
        >>> len(rows) == 1
        True
        >>> df = await provider.execute_query_polars("SELECT 1")
        >>> df.shape[0] == 1
        True
    """

    def __init__(self, databricks_api: AsyncDatabricksClient) -> None:
        """Initialize SQL provider.

        Args:
            databricks_api: Async Databricks client with warehouse configured
        """
        self.api = databricks_api

    async def execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute SQL query and return results as list of dicts.

        Args:
            query: SQL query to execute

        Returns:
            List of row dictionaries

        Raises:
            Exception: If query execution fails
        """
        try:
            # Use async SQL execution from new client
            df = await self.api.sql.execute_polars(query)
            # Convert to list of dicts for protocol compatibility
            return df.to_dicts()
        except (ToolError, AdapterError, ValueError):
            logger.error("SQL execution failed: {e}", extra={"query": query[:200]})
            raise

    async def execute_query_polars(self, query: str) -> pl.DataFrame:
        """Execute SQL query and return Polars DataFrame directly.

        More efficient than execute_query() when working with
        QueryWorkloadService or other Polars-based processing.

        Args:
            query: SQL query to execute

        Returns:
            Polars DataFrame with query results

        Raises:
            Exception: If query execution fails
        """
        try:
            return await self.api.sql.execute_polars(query)
        except (ToolError, AdapterError, ValueError):
            logger.error("SQL execution failed: {e}", extra={"query": query[:200]})
            raise


class UCTools(BaseToolAdapter):
    """
    Reasoning interface for Unity Catalog operations.

    Provides clean, parameter-based interface optimized for LLM reasoning agents.
    All methods return dictionaries suitable for LLM consumption.

    Includes:
    - UC asset enumeration and metadata
    - Table lineage and grants
    - Schema analysis and drift detection
    - Storage optimization recommendations
    - LLM-based table discovery from source code

    Example:
        >>> tools = UCTools(databricks_api)
        >>> assets = await tools.enumerate_uc_assets(
        ...     catalog="my_catalog",
        ...     schema="my_schema",
        ...     asset_type="tables"
        ... )
        >>> len(assets["assets"]) > 0
        True
    """

    def __init__(
        self,
        databricks_api: AsyncDatabricksClient,
        llm_client: BaseLLMClient | None = None,
        *,
        events: EventEmitter | None = None,
    ) -> None:
        """
        Initialize UC tools.

        Args:
            databricks_api: Async Databricks client
            llm_client: Optional LLM client for table discovery from source code
            events: Optional event emitter for observability
        """
        super().__init__(events=events)
        self.databricks_api = databricks_api
        self.llm_client = llm_client

        # Use async CatalogService from AsyncDatabricksClient
        # CatalogService provides both catalog and lineage operations (all async)
        uc_provider = databricks_api.unity_catalog

        # Initialize SQL provider for system table queries
        # Required for: fetch_delta_history, analyze_access_patterns,
        # attribute_table_costs, generate_schema_diff
        sql_provider = DatabricksSQLProvider(databricks_api)

        # Initialize QueryWorkloadService for efficient query analysis
        # Used by: fetch_table_fingerprint, analyze_query_impact
        workload_service = QueryWorkloadService(sql_provider)

        # Initialize discovery and enricher providers if LLM client provided
        discovery_provider: TableDiscoveryProvider | None = None
        enricher_provider: TableEnricherProvider | None = None

        if llm_client:
            # Lazy import to avoid circular dependencies
            from starboard_server.services.analysis.table_metadata import (
                TableDiscovery,
                TableEnricher,
            )

            discovery_provider = TableDiscovery(llm_client)
            enricher_provider = TableEnricher(databricks_api)  # type: ignore[assignment]

        # Initialize UC service with async providers
        # CatalogService provides both catalog and lineage operations
        self.service = UCService(
            uc_provider=uc_provider,
            lineage_provider=uc_provider,
            sql_provider=sql_provider,
            discovery_provider=discovery_provider,
            enricher_provider=enricher_provider,
            workload_service=workload_service,
        )

    async def enumerate_uc_assets(
        self,
        catalog: str | None = None,
        schema: str | None = None,
        asset_type: str = "tables",
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Enumerate Unity Catalog assets.

        Args:
            catalog: Catalog name (required for schemas/tables/volumes/functions)
            schema: Schema name (required for tables/volumes/functions)
            asset_type: Type of assets: catalogs, schemas, tables, volumes, functions
            limit: Maximum number of assets to return

        Returns:
            Dictionary containing:
                - assets: List of asset info dicts
                - total_count: Number of assets returned
                - truncated: Whether results were truncated
                - catalog: Catalog name (if applicable)
                - schema: Schema name (if applicable)

        Examples:
            >>> tools = UCTools(api)
            >>> result = await tools.enumerate_uc_assets(asset_type="catalogs")
            >>> len(result["assets"]) >= 0
            True
        """
        try:
            result = await self.service.enumerate_assets(
                catalog=catalog,
                schema=schema,
                asset_type=asset_type,
                limit=limit,
            )

            return {
                "assets": [
                    {
                        "name": a.name,
                        "full_name": a.full_name,
                        "asset_type": a.asset_type,
                        "owner": a.owner,
                        "created_at": a.created_at.isoformat()
                        if a.created_at
                        else None,
                        "comment": a.comment,
                    }
                    for a in result.assets
                ],
                "total_count": result.total_count,
                "truncated": result.truncated,
                "catalog": result.catalog,
                "schema": result.schema,
                "asset_type": result.asset_type,
            }
        except ValueError as e:
            return {
                "error": str(e),
                "error_code": "tool_error",
                "assets": [],
                "total_count": 0,
            }
        except (ToolError, AdapterError) as e:
            logger.error("Error enumerating UC assets: {e}")
            return {
                "error": f"Failed to enumerate assets: {e}",
                "error_code": "tool_error",
                "assets": [],
                "total_count": 0,
            }

    async def fetch_uc_table_metadata(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Fetch comprehensive Unity Catalog table metadata.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)

        Returns:
            Dictionary containing table metadata including:
                - full_name, catalog, schema, table
                - table_type, data_format
                - columns: list of column info
                - storage info (location, num_files, size_bytes)
                - statistics (row_count, last_modified)
                - ownership info

        Examples:
            >>> tools = UCTools(api)
            >>> metadata = await tools.fetch_uc_table_metadata(
            ...     "catalog.schema.my_table"
            ... )
            >>> "columns" in metadata
            True
        """
        try:
            result = await self.service.fetch_table_metadata(table_name)
            if not result:
                return {
                    "error": f"Table not found: {table_name}",
                    "found": False,
                    "error_code": "tool_error",
                }

            return {
                "found": True,
                "full_name": result.full_name,
                "catalog": result.catalog,
                "schema": result.schema,
                "table": result.table,
                "table_type": result.table_type,
                "data_format": result.data_format,
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "position": c.position,
                        "nullable": c.nullable,
                        "comment": c.comment,
                        "is_partition": c.is_partition,
                        "is_clustering": c.is_clustering,
                    }
                    for c in result.columns
                ],
                "column_count": result.column_count,
                "location": result.location,
                "num_files": result.num_files,
                "size_bytes": result.size_bytes,
                "size_gb": round(result.size_bytes / 1e9, 2)
                if result.size_bytes
                else None,
                "partition_columns": list(result.partition_columns)
                if result.partition_columns
                else [],
                "clustering_columns": list(result.clustering_columns)
                if result.clustering_columns
                else [],
                "row_count": result.row_count,
                "last_modified": result.last_modified.isoformat()
                if result.last_modified
                else None,
                "properties": result.properties,
                "owner": result.owner,
                "created_at": result.created_at.isoformat()
                if result.created_at
                else None,
                "created_by": result.created_by,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error fetching table metadata for {table_name}: {e}")
            return {
                "error": f"Failed to fetch metadata: {e}",
                "found": False,
                "error_code": "tool_error",
            }

    @staticmethod
    def _serialize_lineage_nodes(nodes: Sequence[Any]) -> list[dict[str, Any]]:
        """Serialize lineage nodes to dicts for LLM consumption.

        Args:
            nodes: List of lineage node objects.

        Returns:
            List of serialized node dicts.
        """
        return [
            {
                "table_name": n.table_name,
                "catalog": n.catalog,
                "schema": n.schema,
                "table_type": n.table_type,
                "job_count": n.job_count,
                "notebook_count": n.notebook_count,
                "job_ids": list(n.job_ids),
                "notebook_ids": list(n.notebook_ids),
                "last_updated": n.last_updated,
            }
            for n in nodes
        ]

    async def fetch_table_lineage(
        self,
        table_name: str,
        max_items: int = 10,
    ) -> dict[str, Any]:
        """
        Fetch table lineage (upstream and downstream dependencies).

        The Databricks lineage REST API returns only direct (1-hop) dependencies.
        For transitive lineage, query system.access.table_lineage system table.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            max_items: Maximum items to return per direction (default 10)

        Returns:
            Dictionary containing:
                - table_name: The requested table
                - upstream: List of upstream tables with job/notebook info
                - downstream: List of downstream tables with job/notebook info
                - upstream_count: Number of upstream dependencies
                - downstream_count: Number of downstream dependencies
                - truncated: Whether results were truncated

        Examples:
            >>> tools = UCTools(api)
            >>> lineage = await tools.fetch_table_lineage("catalog.schema.fact_table")
            >>> "upstream" in lineage
            True
        """
        try:
            result = await self.service.fetch_table_lineage(table_name, max_items)

            return {
                "table_name": result.table_name,
                "upstream": self._serialize_lineage_nodes(result.upstream),
                "downstream": self._serialize_lineage_nodes(result.downstream),
                "upstream_count": len(result.upstream),
                "downstream_count": len(result.downstream),
                "truncated": result.truncated,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error fetching lineage for {table_name}: {e}")
            return {
                "error": f"Failed to fetch lineage: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
                "upstream": [],
                "downstream": [],
            }

    async def fetch_table_grants(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Fetch table access grants and effective permissions.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)

        Returns:
            Dictionary containing:
                - table_name: The requested table
                - owner: Table owner
                - direct_grants: Grants directly on this table
                - inherited_grants: Grants inherited from catalog/schema
                - effective_permissions: Resolved effective permissions
                - can_access_grants: Whether caller has permission to view grants

        Examples:
            >>> tools = UCTools(api)
            >>> grants = await tools.fetch_table_grants("catalog.schema.my_table")
            >>> "owner" in grants
            True
        """
        try:
            result = await self.service.fetch_table_grants(table_name)
            if not result:
                return {
                    "table_name": table_name,
                    "can_access_grants": False,
                    "error": "Permission denied or table not found",
                    "error_code": "tool_error",
                }

            return {
                "table_name": result.table_name,
                "can_access_grants": True,
                "owner": result.owner,
                "direct_grants": [
                    {
                        "principal": g.principal,
                        "principal_type": g.principal_type,
                        "privileges": list(g.privileges),
                    }
                    for g in result.direct_grants
                ],
                "inherited_grants": [
                    {
                        "principal": g.principal,
                        "principal_type": g.principal_type,
                        "privileges": list(g.privileges),
                        "inherited_from": g.inherited_from,
                    }
                    for g in result.inherited_grants
                ],
                "effective_permissions": [
                    {
                        "principal": p.principal,
                        "privilege": p.privilege,
                        "source": p.source,
                    }
                    for p in result.effective_permissions
                ],
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error fetching grants for {table_name}: {e}")
            return {
                "table_name": table_name,
                "can_access_grants": False,
                "error": f"Failed to fetch grants: {e}",
                "error_code": "tool_error",
            }

    async def analyze_table_schema(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Analyze table schema for patterns, classification, and anomalies.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - column_count: Number of columns
                - table_classification: fact, dimension, snapshot, etc.
                - data_layer: bronze, silver, gold, etc.
                - anomalies: List of detected issues
                - health_score: 0.0-1.0 health indicator
                - patterns: Semantic patterns detected (id, timestamp, etc.)

        Examples:
            >>> tools = UCTools(api)
            >>> analysis = await tools.analyze_table_schema("catalog.schema.my_table")
            >>> "health_score" in analysis
            True
        """
        try:
            result = await self.service.analyze_table_schema(table_name)
            if not result:
                return {
                    "error": f"Table not found: {table_name}",
                    "found": False,
                    "error_code": "tool_error",
                }

            return {
                "found": True,
                "table_name": result.table_name,
                "column_count": result.column_count,
                "table_classification": result.table_classification,
                "data_layer": result.data_layer,
                "classification_confidence": result.classification_confidence,
                "patterns": {
                    "id_columns": list(result.id_columns),
                    "timestamp_columns": list(result.timestamp_columns),
                    "partition_columns": list(result.partition_columns),
                    "clustering_columns": list(result.clustering_columns),
                },
                "anomalies": [
                    {
                        "type": a.anomaly_type,
                        "severity": a.severity,
                        "description": a.description,
                        "affected_columns": list(a.affected_columns),
                        "recommendation": a.recommendation,
                    }
                    for a in result.anomalies
                ],
                "health_score": result.health_score,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error analyzing schema for {table_name}: {e}")
            return {
                "error": f"Failed to analyze schema: {e}",
                "found": False,
                "error_code": "tool_error",
            }

    async def fetch_delta_history(
        self,
        table_name: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Fetch Delta table history.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            limit: Maximum history entries to return

        Returns:
            Dictionary containing:
                - table_name: The requested table
                - current_version: Latest version number
                - entries: List of history entries
                - operations_summary: Count by operation type
                - last_optimize: Last OPTIMIZE timestamp
                - last_vacuum: Last VACUUM timestamp
                - schema_changes_count: Number of schema changes

        Examples:
            >>> tools = UCTools(api)
            >>> history = await tools.fetch_delta_history("catalog.schema.my_table")
            >>> "current_version" in history
            True
        """
        try:
            result = await self.service.fetch_delta_history(table_name, limit)
            if not result:
                return {
                    "error": "Unable to fetch history (table not found or not a Delta table)",
                    "error_code": "tool_error",
                    "table_name": table_name,
                    "found": False,
                }

            return {
                "found": True,
                "table_name": result.table_name,
                "current_version": result.current_version,
                "total_versions": result.total_versions,
                "entries": [
                    {
                        "version": e.version,
                        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                        "user": e.user,
                        "operation": e.operation,
                        "is_schema_change": e.is_schema_change,
                    }
                    for e in result.entries[:20]  # Limit for LLM context
                ],
                "operations_summary": result.operations_summary,
                "last_optimize": result.last_optimize.isoformat()
                if result.last_optimize
                else None,
                "last_vacuum": result.last_vacuum.isoformat()
                if result.last_vacuum
                else None,
                "schema_changes_count": result.schema_changes_count,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error fetching history for {table_name}: {e}")
            return {
                "error": f"Failed to fetch history: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
                "found": False,
            }

    async def analyze_access_patterns(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Analyze table access patterns from system tables.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            window_days: Days to look back (default 30)

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - read_profile: Read query statistics
                - write_profile: Write operation statistics
                - access_pattern: Classification (high_read, high_write, balanced, inactive)
                - top_readers: Top users by access count
                - daily_trend: Access counts by day

        Examples:
            >>> tools = UCTools(api)
            >>> patterns = await tools.analyze_access_patterns("catalog.schema.my_table")
            >>> "access_pattern" in patterns
            True
        """
        try:
            result = await self.service.analyze_access_patterns(table_name, window_days)
            if not result:
                return {
                    "error": "Unable to analyze access patterns (system tables unavailable)",
                    "error_code": "tool_error",
                    "table_name": table_name,
                }

            return {
                "table_name": result.table_name,
                "window_days": result.window_days,
                "read_profile": {
                    "query_count": result.read_query_count,
                    "total_bytes": result.total_read_bytes,
                    "avg_gb": result.avg_read_gb,
                    "distinct_readers": result.distinct_readers,
                    "last_read": result.last_read.isoformat()
                    if result.last_read
                    else None,
                },
                "write_profile": {
                    "operation_count": result.write_operation_count,
                    "total_bytes": result.total_written_bytes,
                    "last_write": result.last_write.isoformat()
                    if result.last_write
                    else None,
                },
                "access_pattern": result.access_pattern,
                "top_readers": [
                    {"user": u.user, "count": u.access_count}
                    for u in (result.top_readers or [])[:5]
                ],
                "daily_trend": [
                    {"date": d.date, "count": d.count}
                    for d in (result.daily_trend or [])[:14]
                ],
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error analyzing access patterns for {table_name}: {e}")
            return {
                "error": f"Failed to analyze access patterns: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
            }

    async def detect_schema_drift(
        self,
        table_name: str,
        versions_to_analyze: int = 50,
    ) -> dict[str, Any]:
        """
        Detect schema drift over time.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            versions_to_analyze: Number of versions to analyze

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - drift_detected: Boolean indicating if drift was found
                - drift_severity: none, low, medium, high
                - changes: List of detected schema changes
                - summary: Count of adds, removes, modifications

        Examples:
            >>> tools = UCTools(api)
            >>> drift = await tools.detect_schema_drift("catalog.schema.my_table")
            >>> "drift_severity" in drift
            True
        """
        try:
            result = await self.service.detect_schema_drift(
                table_name, versions_to_analyze
            )
            if not result:
                return {
                    "error": "Unable to detect schema drift (history unavailable)",
                    "error_code": "tool_error",
                    "table_name": table_name,
                }

            return {
                "table_name": result.table_name,
                "current_version": result.current_version,
                "versions_analyzed": result.versions_analyzed,
                "drift_detected": result.drift_detected,
                "drift_severity": result.drift_severity,
                "schema_changes": [
                    {
                        "version": c.version,
                        "timestamp": c.timestamp.isoformat() if c.timestamp else None,
                        "change_type": c.change_type,
                        "column_name": c.column_name,
                        "user": c.user,
                    }
                    for c in result.schema_changes[:10]  # Limit for context
                ],
                "summary": {
                    "columns_added": result.columns_added,
                    "columns_removed": result.columns_removed,
                    "columns_modified": result.columns_modified,
                    "type_changes": result.type_changes,
                },
                "last_stable_version": result.last_stable_version,
                "last_stable_date": result.last_stable_date.isoformat()
                if result.last_stable_date
                else None,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error detecting schema drift for {table_name}: {e}")
            return {
                "error": f"Failed to detect schema drift: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
            }

    # =========================================================================
    # Phase 2: Advanced Tools
    # =========================================================================

    async def recommend_storage_optimization(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Generate storage optimization recommendations.

        Args:
            table_name: Fully qualified table name (catalog.schema.table)

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - current_state: Storage state metrics
                - recommendations: List of prioritized recommendations
                - estimated_impact: Impact estimates if optimizations applied

        Examples:
            >>> tools = UCTools(api)
            >>> report = await tools.recommend_storage_optimization("catalog.schema.my_table")
            >>> "recommendations" in report
            True
        """
        try:
            result = await self.service.recommend_storage_optimization(table_name)
            if not result:
                return {
                    "error": f"Table not found: {table_name}",
                    "found": False,
                    "error_code": "tool_error",
                }

            return {
                "found": True,
                "table_name": result.table_name,
                "current_state": {
                    "num_files": result.current_state.num_files,
                    "total_size_gb": round(result.current_state.total_size_gb, 2),
                    "avg_file_size_mb": round(result.current_state.avg_file_size_mb, 2),
                    "file_size_health": result.current_state.file_size_health,
                    "partition_count": result.current_state.partition_count,
                    "clustering_columns": list(
                        result.current_state.clustering_columns or []
                    ),
                    "last_optimize": result.current_state.last_optimize.isoformat()
                    if result.current_state.last_optimize
                    else None,
                    "last_vacuum": result.current_state.last_vacuum.isoformat()
                    if result.current_state.last_vacuum
                    else None,
                },
                "recommendations": [
                    {
                        "type": r.recommendation_type,
                        "priority": r.priority,
                        "title": r.title,
                        "description": r.description,
                        "sql_command": r.sql_command,
                        "estimated_improvement": r.estimated_improvement,
                        "effort": r.effort,
                        "risks": list(r.risks),
                    }
                    for r in result.recommendations
                ],
                "estimated_impact": {
                    "query_time_reduction_pct": result.estimated_impact.query_time_reduction_pct,
                    "storage_reduction_pct": result.estimated_impact.storage_reduction_pct,
                    "cost_reduction_pct": result.estimated_impact.cost_reduction_pct,
                    "confidence": result.estimated_impact.confidence,
                }
                if result.estimated_impact
                else None,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error(
                f"Error generating storage recommendations for {table_name}: {e}"
            )
            return {
                "error": f"Failed to generate recommendations: {e}",
                "found": False,
                "error_code": "tool_error",
            }

    async def analyze_query_impact(
        self,
        table_names: list[str],
        query_pattern: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze query performance impact for table joins.

        Args:
            table_names: Tables involved in query
            query_pattern: Optional query pattern hint (join, aggregate, filter, full_scan)

        Returns:
            Dictionary containing:
                - tables: Tables analyzed
                - total_rows_estimate: Estimated total rows
                - total_size_gb: Total size of tables
                - join_predictions: Predicted join behaviors
                - risks: Identified performance risks
                - recommendations: Join hints and optimization suggestions

        Examples:
            >>> tools = UCTools(api)
            >>> impact = await tools.analyze_query_impact(
            ...     ["catalog.schema.orders", "catalog.schema.customers"]
            ... )
            >>> "join_predictions" in impact
            True
        """
        try:
            result = await self.service.analyze_query_impact(table_names, query_pattern)
            if not result:
                return {
                    "error": "Unable to analyze query impact",
                    "error_code": "tool_error",
                    "tables": table_names,
                }

            return {
                "tables": list(result.tables),
                "total_rows_estimate": result.total_rows_estimate,
                "total_size_gb": round(result.total_size_gb, 2),
                "join_predictions": [
                    {
                        "left_table": p.left_table,
                        "right_table": p.right_table,
                        "join_type": p.join_type,
                        "estimated_shuffle_gb": round(p.estimated_shuffle_gb, 2),
                        "risk_level": p.risk_level,
                        "recommendation": p.recommendation,
                    }
                    for p in result.join_predictions
                ],
                "risks": {
                    "broadcast_risk": result.broadcast_risk,
                    "shuffle_explosion_risk": result.shuffle_explosion_risk,
                    "skew_risk": result.skew_risk,
                },
                "recommendations": {
                    "join_hints": list(result.join_hints),
                    "clustering_recommendations": list(
                        result.clustering_recommendations
                    ),
                    "filter_recommendations": list(result.filter_recommendations),
                },
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error analyzing query impact: {e}")
            return {
                "error": f"Failed to analyze query impact: {e}",
                "error_code": "tool_error",
                "tables": table_names,
            }

    async def fetch_table_fingerprint(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Generate comprehensive table fingerprint from system tables.

        Provides usage-driven analysis including:
        - Table structural metadata
        - Read workload metrics and query patterns
        - Write workload metrics by operation type
        - Cost attribution (DBU consumption)
        - Workload classification and tier recommendations

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            window_days: Analysis window in days (default 30)

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - window_days: Analysis period
                - metadata: Structural metadata (type, format, path)
                - read_workload: Read metrics and query patterns
                - write_workload: Write metrics by operation type
                - cost: DBU consumption metrics
                - classification: Workload type and tier recommendation

        Examples:
            >>> tools = UCTools(api)
            >>> fp = await tools.fetch_table_fingerprint("catalog.schema.orders")
            >>> fp["classification"]["workload_type"]
            'analytical'
        """
        try:
            result = await self.service.fetch_table_fingerprint(table_name, window_days)
            if not result:
                return {
                    "error": f"Table not found: {table_name}",
                    "found": False,
                    "error_code": "tool_error",
                }

            # Build response with new comprehensive structure
            response: dict[str, Any] = {
                "found": True,
                "table_name": result.table_name,
                "window_days": result.window_days,
                "metadata": {
                    "table_type": result.table_type,
                    "storage_format": result.storage_format,
                    "storage_path": result.storage_path,
                    "created": (result.created.isoformat() if result.created else None),
                    "last_altered": (
                        result.last_altered.isoformat() if result.last_altered else None
                    ),
                    "comment": result.comment,
                },
                "classification": {
                    "workload_type": result.workload_type,
                    "recommended_tier": result.recommended_tier,
                },
            }

            # Add read workload if available
            if result.read_metrics:
                rm = result.read_metrics
                response["read_workload"] = {
                    "query_count": rm.query_count,
                    "total_read_gb": round(rm.total_read_gb, 3),
                    "avg_read_gb": round(rm.avg_read_gb, 3),
                    "p95_read_gb": round(rm.p95_read_gb, 3),
                    "total_runtime_sec": round(rm.total_runtime_sec, 2),
                    "avg_runtime_sec": round(rm.avg_runtime_sec, 2),
                    "p95_runtime_sec": round(rm.p95_runtime_sec, 2),
                    "distinct_readers": rm.distinct_readers,
                    "last_read_time": (
                        rm.last_read_time.isoformat() if rm.last_read_time else None
                    ),
                    "peak_queries_per_hour": rm.peak_queries_per_hour,
                    "common_filters": list(rm.common_filters),
                    "common_aggregations": list(rm.common_aggregations),
                    "pct_queries_with_groupby": rm.pct_queries_with_groupby,
                }
            else:
                response["read_workload"] = None

            # Add write workload if available
            if result.write_metrics:
                wm = result.write_metrics
                response["write_workload"] = {
                    "write_op_count": wm.write_op_count,
                    "merge_op_count": wm.merge_op_count,
                    "insert_op_count": wm.insert_op_count,
                    "update_op_count": wm.update_op_count,
                    "delete_op_count": wm.delete_op_count,
                    "total_written_gb": round(wm.total_written_gb, 3),
                    "p95_write_runtime_sec": round(wm.p95_write_runtime_sec, 2),
                    "dominant_write_operation": wm.dominant_write_operation,
                }
            else:
                response["write_workload"] = None

            # Add cost metrics if available
            if result.cost_metrics:
                cm = result.cost_metrics
                response["cost"] = {
                    "total_dbus": round(cm.total_dbus, 2),
                    "avg_dbus_per_day": round(cm.avg_dbus_per_day, 2),
                }
            else:
                response["cost"] = None

            return response

        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error generating fingerprint for {table_name}: {e}")
            return {
                "error": f"Failed to generate fingerprint: {e}",
                "found": False,
                "error_code": "tool_error",
            }

    async def attribute_table_costs(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Attribute costs to a table.

        Args:
            table_name: Fully qualified table name
            window_days: Analysis window in days

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - storage_costs: Storage cost breakdown
                - compute_costs: Compute cost breakdown
                - total_cost_usd: Total cost
                - cost_metrics: Cost efficiency metrics

        Examples:
            >>> tools = UCTools(api)
            >>> costs = await tools.attribute_table_costs("catalog.schema.my_table")
            >>> "total_cost_usd" in costs
            True
        """
        try:
            result = await self.service.attribute_table_costs(table_name, window_days)
            if not result:
                return {
                    "error": "Unable to attribute costs (system tables unavailable)",
                    "error_code": "tool_error",
                    "table_name": table_name,
                }

            return {
                "table_name": result.table_name,
                "window_days": result.window_days,
                "storage_costs": {
                    "cost_usd": result.storage_cost_usd,
                    "size_gb": round(result.storage_gb, 2),
                },
                "compute_costs": {
                    "cost_usd": result.compute_cost_usd,
                    "dbu_consumed": result.total_dbu_consumed,
                    "query_count": result.query_count,
                },
                "write_costs": {
                    "cost_usd": result.write_cost_usd,
                    "dbu_consumed": result.write_dbu_consumed,
                },
                "total_cost_usd": result.total_cost_usd,
                "cost_metrics": {
                    "cost_per_gb": result.cost_per_gb,
                    "cost_per_query": result.cost_per_query,
                },
                "trend": {
                    "direction": result.cost_trend,
                    "change_pct": result.cost_change_pct,
                },
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error attributing costs for {table_name}: {e}")
            return {
                "error": f"Failed to attribute costs: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
            }

    async def generate_schema_diff(
        self,
        table_name: str,
        version_from: int,
        version_to: int | None = None,
    ) -> dict[str, Any]:
        """
        Generate schema diff between versions.

        Args:
            table_name: Fully qualified table name
            version_from: Starting version
            version_to: Ending version (defaults to current)

        Returns:
            Dictionary containing:
                - table_name: The analyzed table
                - versions: Version range analyzed
                - changes: Schema changes by type
                - is_breaking: Whether changes are breaking
                - migration_sql: Suggested migration SQL

        Examples:
            >>> tools = UCTools(api)
            >>> diff = await tools.generate_schema_diff(
            ...     "catalog.schema.my_table", version_from=10
            ... )
            >>> "is_breaking" in diff
            True
        """
        try:
            result = await self.service.generate_schema_diff(
                table_name, version_from, version_to
            )
            if not result:
                return {
                    "error": "Unable to generate schema diff",
                    "error_code": "tool_error",
                    "table_name": table_name,
                }

            return {
                "table_name": result.table_name,
                "versions": {
                    "from": result.version_from,
                    "to": result.version_to,
                    "timestamp_from": result.timestamp_from.isoformat()
                    if result.timestamp_from
                    else None,
                    "timestamp_to": result.timestamp_to.isoformat()
                    if result.timestamp_to
                    else None,
                },
                "changes": {
                    "added": [
                        {
                            "column": c.column_name,
                            "type": c.new_type,
                            "nullable": c.new_nullable,
                        }
                        for c in result.columns_added
                    ],
                    "removed": [
                        {"column": c.column_name, "type": c.old_type}
                        for c in result.columns_removed
                    ],
                    "modified": [
                        {
                            "column": c.column_name,
                            "old_type": c.old_type,
                            "new_type": c.new_type,
                            "old_nullable": c.old_nullable,
                            "new_nullable": c.new_nullable,
                        }
                        for c in result.columns_modified
                    ],
                },
                "is_breaking": result.is_breaking_change,
                "breaking_reason": result.breaking_reason,
                "migration_sql": result.migration_sql,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error generating schema diff for {table_name}: {e}")
            return {
                "error": f"Failed to generate schema diff: {e}",
                "error_code": "tool_error",
                "table_name": table_name,
            }

    async def analyze_policy_coverage(
        self,
        scope: str = "catalog",
        catalog: str | None = None,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze security policy coverage.

        Args:
            scope: 'catalog', 'schema', or 'table'
            catalog: Catalog name (required for schema/table scope)
            schema: Schema name (required for table scope)

        Returns:
            Dictionary containing:
                - scope: Analysis scope
                - assets_analyzed: Number of assets
                - coverage: Coverage percentages
                - gaps: Identified policy gaps
                - security_score: Overall security score

        Examples:
            >>> tools = UCTools(api)
            >>> coverage = await tools.analyze_policy_coverage(
            ...     scope="schema", catalog="main", schema="gold"
            ... )
            >>> "security_score" in coverage
            True
        """
        try:
            result = await self.service.analyze_policy_coverage(scope, catalog, schema)
            if not result:
                return {
                    "error": "Invalid scope or missing parameters",
                    "error_code": "tool_error",
                    "scope": scope,
                }

            return {
                "scope": result.scope,
                "assets_analyzed": result.assets_analyzed,
                "coverage": {
                    "ownership_pct": result.ownership_coverage_pct,
                    "access_control_pct": result.access_control_coverage_pct,
                    "data_protection_pct": result.data_protection_coverage_pct,
                },
                "asset_counts": {
                    "with_owner": result.assets_with_owner,
                    "with_grants": result.assets_with_grants,
                    "with_row_filters": result.assets_with_row_filters,
                    "with_column_masks": result.assets_with_column_masks,
                },
                "gaps": [
                    {
                        "type": g.gap_type,
                        "severity": g.severity,
                        "description": g.description,
                        "recommendation": g.recommendation,
                    }
                    for g in result.policy_gaps
                ],
                "security_score": result.overall_security_score,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error analyzing policy coverage: {e}")
            return {
                "error": f"Failed to analyze policy coverage: {e}",
                "scope": scope,
                "error_code": "tool_error",
            }

    # =========================================================================
    # Table Discovery (LLM-based)
    # =========================================================================

    async def discover_tables_from_source(
        self,
        source_text: str | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Discover table references from SQL or source code using LLM.

        Unified tool for table discovery - works with both SQL queries and
        Spark/PySpark/Scala notebook code. Automatically detects the source type.

        Requires LLM client to be provided during initialization.

        Args:
            source_text: SQL query or source code to analyze for table references
            budget: Optional token budget for tracking

        Returns:
            Dictionary containing:
                - all_tables: All discovered table names
                - source_tables: Tables being read from
                - target_tables: Tables being written to
                - tables_and_views: Only real tables/views (no temps/CTEs)
                - table_references: Full reference objects with metadata

        Examples:
            SQL input:
            >>> tools = UCTools(api, llm_client)
            >>> result = await tools.discover_tables_from_source(
            ...     "SELECT * FROM catalog.schema.source JOIN target"
            ... )
            >>> len(result["all_tables"])
            2

            PySpark code input:
            >>> result = await tools.discover_tables_from_source(
            ...     "df = spark.table('catalog.schema.mytable')"
            ... )
            >>> "catalog.schema.mytable" in result["all_tables"]
            True
        """
        if not source_text:
            return {
                "error": "No source_text provided",
                "error_code": "tool_error",
                "all_tables": [],
                "source_tables": [],
                "target_tables": [],
            }

        try:
            # The service handles both SQL and code - it passes to the LLM
            # which can parse either format
            result = await self.service.discover_tables(
                sql_text=source_text,
                budget=budget,
            )

            return {
                "all_tables": result.all_tables,
                "source_tables": result.source_tables,
                "target_tables": result.target_tables,
                "tables_and_views": result.tables_and_views,
                "table_references": [t.to_dict() for t in result.table_references],
            }
        except RuntimeError as e:
            # Discovery provider not configured
            return {
                "error": str(e),
                "error_code": "tool_error",
                "all_tables": [],
                "source_tables": [],
                "target_tables": [],
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error discovering tables from source: {e}")
            return {
                "error": f"Failed to discover tables: {e}",
                "error_code": "tool_error",
                "all_tables": [],
                "source_tables": [],
                "target_tables": [],
            }

    async def enrich_table_references(
        self,
        table_references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Enrich table references with Unity Catalog metadata and Delta history.

        Requires enricher provider to be configured (via LLM client initialization).

        Args:
            table_references: List of table reference dictionaries

        Returns:
            Dictionary containing:
                - enriched_tables: List of enriched table references
                - table_metadata: Metadata keyed by table name

        Examples:
            >>> tools = UCTools(api, llm_client)
            >>> refs = [{"resolved_3part": "catalog.schema.table1", ...}]
            >>> result = await tools.enrich_table_references(refs)
            >>> len(result["enriched_tables"]) == 1
            True
        """
        try:
            enriched_refs, table_metadata = await self.service.enrich_table_references(
                table_references  # type: ignore[arg-type]
            )

            return {
                "enriched_tables": [t.to_dict() for t in enriched_refs],
                "table_metadata": table_metadata,
            }
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Error enriching table references: {e}")
            return {
                "error": f"Failed to enrich tables: {e}",
                "error_code": "tool_error",
                "enriched_tables": [],
                "table_metadata": {},
            }
