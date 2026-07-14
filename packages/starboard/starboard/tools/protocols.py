# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Consolidated protocols for tool data providers.

This module defines the Protocol interfaces for all domain-specific
data providers. These protocols enable:
- Type checking with structural subtyping
- Clean dependency injection
- Testability with mock implementations

Protocol Hierarchy:
    ClusterDataProvider   - Cluster operations
    WarehouseDataProvider - Warehouse operations
    TableDataProvider     - Table/UC operations
    JobDataProvider       - Job operations
    QueryDataProvider     - Query operations

Usage:
    def __init__(self, cluster_data: ClusterDataProvider) -> None:
        self.cluster_data = cluster_data

    # Any class with matching methods satisfies the protocol
"""

from __future__ import annotations

from typing import Any, Protocol


class ClusterDataProvider(Protocol):
    """Protocol for cluster data access.

    Provides access to cluster configuration, events, metrics, and logs.
    For new code, use SharedContextProvider directly with transforms module.

    Example:
        from starboard.services.context.transforms import (
            get_transformed, transform_cluster_config
        )
        config = await get_transformed(
            provider, "cluster_config", cluster_id,
            transform_fn=transform_cluster_config
        )
    """

    async def get_cluster_config(self, cluster_id: str) -> dict[str, Any] | None:
        """Get cluster configuration.

        Args:
            cluster_id: Cluster ID to fetch configuration for.

        Returns:
            Transformed cluster configuration dict, or None if not found.
        """
        ...

    async def get_cluster_events(self, cluster_id: str) -> dict[str, Any] | None:
        """Get cluster events.

        Args:
            cluster_id: Cluster ID to fetch events for.

        Returns:
            Transformed cluster events dict, or None if not found.
        """
        ...

    async def get_cluster_metrics(
        self, cluster_ids: list[str]
    ) -> list[dict[str, Any]] | None:
        """Get metrics for one or more clusters.

        Args:
            cluster_ids: List of cluster IDs to fetch metrics for.

        Returns:
            List of cluster metrics dicts, or None if unavailable.
        """
        ...

    def get_spark_logs(
        self, cluster_id: str, path: str, raw: bool = False
    ) -> dict[str, Any] | None:
        """Get Spark application logs.

        Note: This is sync as it reads from local/DBFS path.

        Args:
            cluster_id: Cluster ID to fetch logs for.
            path: Base path to the logs directory.
            raw: If True, return raw data; if False, return analyzed results.

        Returns:
            Spark logs dict, or None if not found.
        """
        ...


class WarehouseDataProvider(Protocol):
    """Protocol for warehouse data access.

    Provides access to warehouse configuration, metrics, and query history.
    For new code, use SharedContextProvider directly with transforms module.

    Example:
        from starboard.services.context.transforms import (
            get_transformed, transform_warehouse_configuration
        )
        config = await get_transformed(
            provider, "warehouse_config", warehouse_id,
            transform_fn=transform_warehouse_configuration
        )
    """

    async def get_warehouse_config(self, warehouse_id: str) -> dict[str, Any] | None:
        """Get warehouse configuration.

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            Transformed warehouse configuration dict, or None if not found.
        """
        ...

    async def get_warehouse_metrics(
        self, warehouse_id: str, days_history: int = 7
    ) -> dict[str, Any] | None:
        """Get warehouse metrics.

        Args:
            warehouse_id: Warehouse ID to fetch metrics for.
            days_history: Number of days to look back.

        Returns:
            Warehouse metrics dict, or None if not found.
        """
        ...

    async def get_warehouse_query_history(
        self, warehouse_id: str, days_history: int = 30
    ) -> dict[str, Any] | None:
        """Get warehouse query history.

        Args:
            warehouse_id: Warehouse ID to fetch history for.
            days_history: Number of days to look back.

        Returns:
            Transformed query history dict, or None if not found.
        """
        ...

    async def list_warehouses(self) -> list[dict[str, Any]]:
        """List all SQL warehouses.

        Returns:
            List of warehouse configuration dicts.
        """
        ...

    async def get_warehouse(self, warehouse_id: str) -> dict[str, Any] | None:
        """Get a specific warehouse configuration by ID (used by WarehousePortfolioService).

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            Warehouse configuration dict, or None if not found.
        """
        ...


class WarehousePortfolioDataProvider(Protocol):
    """Narrow protocol for warehouse data access used by WarehousePortfolioService.

    Concrete implementers (e.g. WarehouseDataAdapter) only need these two
    methods. The broader WarehouseDataProvider above is used by WarehouseService
    which accesses transformed metrics through the shared context layer.
    """

    async def list_warehouses(self) -> list[dict[str, Any]]:
        """List all SQL warehouses.

        Returns:
            List of warehouse configuration dicts.
        """
        ...

    async def get_warehouse(self, warehouse_id: str) -> dict[str, Any] | None:
        """Get a specific warehouse configuration by ID.

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            Warehouse configuration dict, or None if not found.
        """
        ...


class TableDataProvider(Protocol):
    """Protocol for table/UC data access.

    Provides access to table metadata, lineage, and history.
    For new code, use SharedContextProvider directly with transforms module.

    Example:
        from starboard.services.context.transforms import (
            get_transformed, transform_table_metadata
        )
        metadata = await get_transformed(
            provider, "table_metadata", table_name,
            transform_fn=transform_table_metadata
        )
    """

    async def get_table_metadata(self, table_name: str) -> dict[str, Any] | None:
        """Get table metadata.

        Args:
            table_name: Fully qualified table name (catalog.schema.table).

        Returns:
            Transformed table metadata dict, or None if not found.
        """
        ...

    async def get_table_metadata_batch(
        self, table_names: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Get metadata for multiple tables.

        Args:
            table_names: List of fully qualified table names.

        Returns:
            Dictionary mapping table names to their metadata.
        """
        ...

    async def get_table_lineage(self, table_name: str) -> dict[str, Any] | None:
        """Get table lineage.

        Args:
            table_name: Fully qualified table name.

        Returns:
            Transformed table lineage dict, or None if not found.
        """
        ...

    async def get_delta_history(
        self, table_name: str, limit: int = 20
    ) -> list[dict[str, Any]] | None:
        """Get Delta table history.

        Args:
            table_name: Fully qualified table name.
            limit: Maximum number of history records.

        Returns:
            List of transformed history records, or None if not found.
        """
        ...


class JobDataProvider(Protocol):
    """Protocol for job data access.

    Provides access to job listings, metadata, and run details.
    Use transforms module with SharedContextProvider instead.

    Example:
        from starboard.services.context.transforms import get_job_metadata
        job_data = await get_job_metadata(provider, job_id)
    """

    async def get_jobs_list(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get list of all jobs.

        Args:
            limit: Maximum number of jobs to return.

        Returns:
            List of job dictionaries.
        """
        ...

    async def get_job_metadata(
        self, job_id: str, max_runs: int = 5
    ) -> dict[str, Any] | None:
        """Get job metadata including runs.

        Args:
            job_id: Job ID to fetch metadata for.
            max_runs: Maximum number of runs to include.

        Returns:
            Dictionary with job config and runtime metadata, or None if not found.
        """
        ...

    async def get_job_run_detail(
        self, job_id: str, max_runs: int = 5
    ) -> dict[str, Any] | None:
        """Get detailed job run information from system tables.

        Args:
            job_id: Job ID to fetch details for.
            max_runs: Maximum number of runs to include.

        Returns:
            Transformed job run detail dict, or None if not found.
        """
        ...


class QueryDataProvider(Protocol):
    """Protocol for query data access.

    Provides access to query history and explain plans.
    Use transforms module with SharedContextProvider instead.

    Example:
        from starboard.services.context.transforms import get_explain_plan
        plan = await get_explain_plan(provider, sql_text)
    """

    async def get_query_history(self, statement_id: str) -> dict[str, Any] | None:
        """Get query execution history.

        Args:
            statement_id: Query statement ID.

        Returns:
            Transformed query history dict, or None if not found.
        """
        ...

    async def get_explain_plan(self, sql_text: str) -> str | None:
        """Get EXPLAIN plan for SQL.

        Args:
            sql_text: SQL query text.

        Returns:
            Raw EXPLAIN output text, or None if not available.
        """
        ...
