# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Async data fetching functions for Databricks resources.

This module provides async functions for fetching data from Databricks.
All functions follow a consistent signature: async (client, resource_id, **kwargs)
and return raw data without transformation logic.

Transformation logic is handled separately by the transformers module.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from starboard_server.exceptions import AdapterError, DatabricksAPIError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.validation import (
    QualifiedTableName,
    validate_limit,
)

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_job_id(job_id: str) -> int:
    """
    Parse job ID by extracting numeric identifier using regex.

    Extracts the first numeric sequence from the input string.
    Supports any format containing a numeric ID.

    Examples:
        - "266829928906781" → 266829928906781
        - "job_id:266829928906781" → 266829928906781
        - "  12345  " → 12345

    Args:
        job_id: String containing a job ID

    Returns:
        Integer job ID

    Raises:
        ValueError: If no numeric ID can be extracted
    """
    if not job_id:
        raise ValueError("job_id cannot be empty")

    # Use regex to extract the first sequence of digits
    # Pattern: one or more digits (with optional leading minus for edge cases)
    pattern = r"(-?\d+)"
    match = re.search(pattern, job_id)

    if not match:
        raise ValueError(f"Invalid job_id format: '{job_id}'. No numeric ID found")

    # Extract and convert the first numeric sequence to int
    return int(match.group(1))


# =============================================================================
# Query Data Fetchers
# =============================================================================


async def fetch_query_history(
    client: AsyncDatabricksClient,
    statement_id: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch query execution history by statement ID.

    Args:
        client: Async Databricks client
        statement_id: Query statement ID
        **kwargs: Additional parameters (unused)

    Returns:
        Query history record or None if not found
    """
    try:
        history = await client.sql.get_query_history(statement_id=statement_id)
        if history:
            return history[0]
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error(
            "fetch_query_history_error", statement_id=statement_id, error=str(e)
        )
        return None


async def fetch_explain_plan(
    client: AsyncDatabricksClient,
    sql_text: str,
    **kwargs,  # noqa: ARG001
) -> str | None:
    """
    Fetch EXPLAIN plan for SQL query.

    Args:
        client: Async Databricks client
        sql_text: SQL query text
        **kwargs: Additional parameters (unused)

    Returns:
        EXPLAIN output text or None if execution failed
    """
    try:
        explain_sql = f"EXPLAIN {sql_text}"
        df = await client.sql.execute_polars(explain_sql)
        if len(df) > 0:
            return str(df.row(0)[0])
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_explain_plan_error", error=str(e))
        return None


async def fetch_warehouse_query_history(
    client: AsyncDatabricksClient, warehouse_id: str, **kwargs
) -> list[dict[str, Any]] | None:
    """
    Fetch query execution history for a warehouse.

    Args:
        client: Async Databricks client
        warehouse_id: SQL warehouse ID
        **kwargs: Additional parameters (days_history)

    Returns:
        List of query history records or None if not found
    """
    days_history = kwargs.get("days_history", 30)
    try:
        return await client.sql.get_query_history(
            warehouse_id=warehouse_id, days_history=days_history
        )
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error(
            "fetch_warehouse_query_history_error",
            warehouse_id=warehouse_id,
            error=str(e),
        )
        return None


# =============================================================================
# Table Data Fetchers
# =============================================================================


async def fetch_table_metadata(
    client: AsyncDatabricksClient,
    table_name: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch Unity Catalog table metadata.

    Args:
        client: Async Databricks client
        table_name: Fully qualified table name (catalog.schema.table)
        **kwargs: Additional parameters (unused)

    Returns:
        Table metadata or None if not found
    """
    try:
        # Use the catalog service to get table metadata
        return await client.unity_catalog.get_table(table_name)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_table_metadata_error", table_name=table_name, error=str(e))
        return None


async def fetch_table_lineage(
    client: AsyncDatabricksClient,
    table_name: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch Unity Catalog table lineage.

    Args:
        client: Async Databricks client
        table_name: Fully qualified table name
        **kwargs: Additional parameters (unused)

    Returns:
        Raw lineage data or None if not found
    """
    try:
        return await client.unity_catalog.get_table_lineage(table_name)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_table_lineage_error", table_name=table_name, error=str(e))
        return None


async def fetch_delta_history(
    client: AsyncDatabricksClient, table_name: str, **kwargs
) -> list[dict[str, Any]] | None:
    """
    Fetch Delta table history.

    Args:
        client: Async Databricks client
        table_name: Fully qualified table name
        **kwargs: Additional parameters (limit)

    Returns:
        List of history records or None if not found
    """
    try:
        limit = kwargs.get("limit", 20)
        # Validate table name and limit to prevent SQL injection (C1 fix)
        validated_name = QualifiedTableName.from_string(table_name)
        validated_limit = validate_limit(limit)
        sql = f"DESCRIBE HISTORY {validated_name.to_sql_identifier()} LIMIT {validated_limit}"
        df = await client.sql.execute_polars(sql)
        if len(df) > 0:
            return df.to_dicts()
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_delta_history_error", table_name=table_name, error=str(e))
        return None


# =============================================================================
# Warehouse/Compute Data Fetchers
# =============================================================================


async def fetch_warehouse_config(
    client: AsyncDatabricksClient,
    warehouse_id: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch SQL warehouse configuration.

    Args:
        client: Async Databricks client
        warehouse_id: SQL warehouse ID
        **kwargs: Additional parameters (unused)

    Returns:
        Warehouse configuration or None if not found
    """
    try:
        return await client.warehouses.get_warehouse(warehouse_id)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error(
            "fetch_warehouse_config_error", warehouse_id=warehouse_id, error=str(e)
        )
        return None


async def fetch_warehouse_metrics(
    client: AsyncDatabricksClient,
    warehouse_id: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch SQL warehouse metrics from system tables.

    Args:
        client: Async Databricks client
        warehouse_id: SQL warehouse ID
        **kwargs: Additional parameters (days_history)

    Returns:
        Warehouse metrics or None if not found
    """
    days_history = kwargs.get("days_history", 7)
    try:
        sql = f"""
        SELECT
            warehouse_id,
            cluster_count,
            avg(query_count) as avg_queries_per_hour,
            percentile(execution_time_ms, 0.5) as p50_exec_time_ms,
            percentile(execution_time_ms, 0.95) as p95_exec_time_ms,
            percentile(execution_time_ms, 0.99) as p99_exec_time_ms,
            sum(rows_produced) as total_rows_produced,
            sum(bytes_read) as total_bytes_read
        FROM system.query.history
        WHERE warehouse_id = '{warehouse_id}'
        AND start_time >= current_timestamp() - INTERVAL {days_history} DAYS
        GROUP BY warehouse_id, cluster_count
        """
        df = await client.sql.execute_polars(sql)
        if len(df) > 0:
            return df.to_dicts()[0]
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error(
            "fetch_warehouse_metrics_error", warehouse_id=warehouse_id, error=str(e)
        )
        return None


async def fetch_cluster_events(
    client: AsyncDatabricksClient,
    cluster_id: str,
    **kwargs,  # noqa: ARG001
) -> list[dict[str, Any]] | None:
    """
    Fetch compute cluster events.
    """
    try:
        return await client.clusters.get_cluster_events(cluster_id)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_cluster_events_error", cluster_id=cluster_id, error=str(e))
        return None


async def fetch_cluster_config(
    client: AsyncDatabricksClient,
    cluster_id: str,
    **kwargs,  # noqa: ARG001
) -> dict[str, Any] | None:
    """
    Fetch compute cluster configuration.

    Args:
        client: Async Databricks client
        cluster_id: Cluster ID
        **kwargs: Additional parameters (unused)

    Returns:
        Cluster configuration or None if not found
    """
    try:
        return await client.clusters.get_cluster(cluster_id)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_cluster_config_error", cluster_id=cluster_id, error=str(e))
        return None


async def fetch_cluster_metrics(
    client: AsyncDatabricksClient,
    cluster_ids: str | list[str],
    **kwargs,  # noqa: ARG001
) -> list[dict[str, Any]] | None:
    """
    Fetch compute cluster metrics from system tables.

    Args:
        client: Async Databricks client
        cluster_ids: Single cluster ID or list of cluster IDs
        **kwargs: Additional parameters (unused)

    Returns:
        List of cluster metrics or None if not found
    """
    if isinstance(cluster_ids, str):
        cluster_ids = [cluster_ids]

    if not cluster_ids:
        return None

    try:
        predicate = ",".join([f"'{c}'" for c in cluster_ids])
        sql = f"""
        SELECT
            c.cluster_name, c.worker_count, c.min_autoscale_workers,
            c.max_autoscale_workers, c.auto_termination_minutes,
            c.enable_elastic_disk, c.cluster_source, c.dbr_version,
            c.data_security_mode, t.*, n.core_count, n.gpu_count, n.memory_mb
        FROM system.compute.clusters c
        JOIN system.compute.node_timeline t ON
            c.cluster_id=t.cluster_id
            AND c.workspace_id=t.workspace_id
            AND c.account_id=t.account_id
        JOIN system.compute.node_types n ON
            t.account_id=n.account_id
            AND t.node_type=n.node_type
        WHERE c.cluster_id IN ({predicate})
        """
        df = await client.sql.execute_polars(sql)
        if len(df) > 0:
            return df.to_dicts()
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_cluster_metrics_error", error=str(e))
        return None


# =============================================================================
# Job Data Fetchers
# =============================================================================


async def fetch_jobs_list(
    client: AsyncDatabricksClient,
    _resource_id: str,  # noqa: ARG001
    **kwargs,
) -> list[dict[str, Any]] | None:
    """
    Fetch list of all jobs in the workspace.

    Args:
        client: Async Databricks client
        _resource_id: Unused (required for fetcher signature)
        **kwargs: Additional parameters (limit)

    Returns:
        List of job dictionaries or None if error occurs
    """
    limit = kwargs.get("limit", 100)
    try:
        return await client.jobs.list_jobs(limit=limit)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_jobs_list_error", error=str(e))
        return None


async def fetch_jobs_by_name(
    client: AsyncDatabricksClient,
    job_name: str,
    **kwargs,
) -> dict[str, Any] | None:
    """
    Search for jobs by name using efficient SDK filters.

    Tries exact match first (server-side filter), then falls back to
    partial match if no exact match found.

    Args:
        client: Async Databricks client
        job_name: Job name to search for
        **kwargs: Additional parameters (exact_match, limit)

    Returns:
        Dictionary with:
        - exact_match: Whether an exact match was found
        - matches: List of matching job dictionaries
        - job_id: Job ID if exactly one match found (convenience field)
        Returns None on error.
    """
    exact_match = kwargs.get("exact_match", True)
    limit = kwargs.get("limit", 5)

    try:
        matches = await client.jobs.search_jobs_by_name(
            job_name=job_name,
            exact_match=exact_match,
            limit=limit,
        )

        # Determine if we have an exact match
        is_exact = False
        if matches and len(matches) == 1:
            match_name = matches[0].get("settings", {}).get("name", "")
            is_exact = match_name.lower() == job_name.lower()

        result = {
            "exact_match": is_exact,
            "matches": matches,
            "total_matches": len(matches),
        }

        # Add convenience field for single exact match
        if is_exact:
            result["job_id"] = str(matches[0].get("job_id"))

        return result
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_jobs_by_name_error", job_name=job_name, error=str(e))
        return None


async def fetch_job_metadata(
    client: AsyncDatabricksClient, job_id: str, **kwargs
) -> dict[str, Any] | None:
    """
    Fetch job configuration and metadata.

    Args:
        client: Async Databricks client
        job_id: Databricks job ID (supports "job_id:12345" or "12345" formats)
        **kwargs: Additional parameters (max_runs)

    Returns:
        Dictionary with job settings and runs or None if not found
    """
    max_runs = kwargs.get("max_runs", 5)
    try:
        # Extract numeric job_id from string
        parsed_job_id = _parse_job_id(job_id)

        job_settings = await client.jobs.get_job(parsed_job_id)

        # Try to fetch runs with limit, fallback to all runs if limit exceeds available runs
        try:
            runs = await client.list_job_runs(
                parsed_job_id, limit=max_runs, expand_tasks=True
            )
        except (DatabricksAPIError, AdapterError, OSError) as limit_error:
            # If limit error (e.g., "Invalid limit 30 - it has to be no more than 26")
            # retry without limit to get all available runs
            error_msg = str(limit_error)
            if (
                "limit" in error_msg.lower()
                and "has to be no more than" in error_msg.lower()
            ):
                logger.warning(
                    "job_runs_limit_exceeded_retrying",
                    job_id=job_id,
                    requested_limit=max_runs,
                    error=error_msg,
                )
                runs = await client.list_job_runs(parsed_job_id, expand_tasks=True)
            else:
                raise  # Re-raise if it's not a limit error

        return {
            "job_settings": job_settings,
            "runs": runs,
        }
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_job_metadata_error", job_id=job_id, error=str(e))
        return None


async def fetch_job_run_detail(
    client: AsyncDatabricksClient, job_id: str, **kwargs
) -> list[dict[str, Any]] | None:
    """
    Fetch detailed job run information from system tables (for serverless jobs).

    Args:
        client: Async Databricks client
        job_id: Databricks job ID (supports "12345" formats)
        **kwargs: Additional parameters (max_runs)

    Returns:
        List of detailed job run records or None if not found
    """
    max_runs = kwargs.get("max_runs", 5)
    try:
        # Extract numeric job_id from string
        parsed_job_id = _parse_job_id(job_id)

        sql = f"""
        WITH filtered_jobs AS (
            SELECT
                *,
                ROW_NUMBER() OVER(
                    PARTITION BY j.workspace_id, j.job_id
                    ORDER BY j.period_start_time DESC
                ) as rn
            FROM system.lakeflow.job_run_timeline j
            WHERE j.job_id='{parsed_job_id}'
            QUALIFY rn<={max_runs}
        )
        SELECT
            j.rn, j.account_id, j.workspace_id, j.job_id, j.run_id,
            j.period_start_time AS run_start, j.period_end_time AS run_end,
            j.trigger_type, j.result_state AS run_result, j.run_type,
            j.run_name, j.termination_code AS job_termination_code,
            j.job_parameters,
            r.run_id AS run_task_id, r.period_start_time AS task_start,
            r.period_end_time AS task_end, r.task_key, r.compute_ids,
            r.result_state AS task_result,
            r.parent_run_id AS parent_run_task_id,
            r.termination_code AS task_termination_code,
            q.statement_id, q.executed_by, q.session_id,
            q.execution_status, q.compute, q.executed_by_user_id,
            q.statement_text, q.statement_type, q.error_message,
            q.client_application, q.client_driver, q.total_duration_ms,
            q.waiting_for_compute_duration_ms, q.waiting_at_capacity_duration_ms,
            q.execution_duration_ms, q.compilation_duration_ms,
            q.total_task_duration_ms, q.result_fetch_duration_ms,
            q.start_time, q.end_time, q.update_time, q.read_partitions,
            q.pruned_files, q.read_files, q.read_rows, q.produced_rows,
            q.read_bytes, q.read_io_cache_percent, q.from_result_cache,
            q.spilled_local_bytes, q.written_bytes, q.shuffle_read_bytes,
            q.query_source, q.executed_as_user_id, q.executed_as,
            q.written_rows, q.written_files, q.cache_origin_statement_id,
            q.query_parameters, q.query_tags
        FROM filtered_jobs j
        LEFT JOIN system.lakeflow.job_task_run_timeline r
            ON j.job_id=r.job_id AND j.run_id=r.job_run_id
        LEFT JOIN system.query.history q ON
            j.job_id=q.query_source.job_info.job_id
            AND j.run_id=q.query_source.job_info.job_run_id
            AND r.run_id=q.query_source.job_info.job_task_run_id
        """
        df = await client.sql.execute_polars(sql)
        if len(df) > 0:
            return df.to_dicts()
        return None
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_job_run_detail_error", job_id=job_id, error=str(e))
        return None


# =============================================================================
# Workspace Data Fetchers
# =============================================================================


async def fetch_notebook_source(
    client: AsyncDatabricksClient,
    notebook_path: str,
    **kwargs,  # noqa: ARG001
) -> str | None:
    """
    Fetch notebook source code.

    Args:
        client: Async Databricks client
        notebook_path: Workspace path to notebook
        **kwargs: Additional parameters (unused)

    Returns:
        Notebook source code or None if not found
    """
    try:
        return await client.workspace.export_workspace_file(notebook_path)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error(
            "fetch_notebook_source_error", notebook_path=notebook_path, error=str(e)
        )
        return None


async def fetch_dbfs_file(
    client: AsyncDatabricksClient,
    dbfs_path: str,
    **kwargs,  # noqa: ARG001
) -> str | None:
    """
    Fetch file content from DBFS.

    Args:
        client: Async Databricks client
        dbfs_path: DBFS file path
        **kwargs: Additional parameters (unused)

    Returns:
        File content or None if not found
    """
    try:
        return await client.workspace.read_dbfs_file(dbfs_path)
    except (DatabricksAPIError, AdapterError, OSError) as e:
        logger.error("fetch_dbfs_file_error", dbfs_path=dbfs_path, error=str(e))
        return None
