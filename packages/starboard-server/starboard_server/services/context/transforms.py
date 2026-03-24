"""Data transformation utilities for context data.

This module provides transform functions and helper utilities that replace
the facade pattern. Instead of using facades for data access + transformation,
callers now use SharedContextProvider directly with these transforms.

The module provides:
1. Re-exports of domain transform functions for convenient access
2. Helper functions (get_transformed, analyze_*) that combine fetch + transform
3. Analyzer classes for complex transformations

Example Usage:
    >>> from starboard_server.services.context.transforms import (
    ...     get_transformed,
    ...     transform_cluster_config,
    ... )
    >>> # Direct transform usage
    >>> raw = await provider.get("cluster_config", "cluster-123")
    >>> config = transform_cluster_config(raw) if raw else None
    >>>
    >>> # Helper function usage
    >>> config = await get_transformed(
    ...     provider, "cluster_config", "cluster-123",
    ...     transform_fn=transform_cluster_config
    ... )

Migration from Facades:
    Before (facade pattern):
        facade = ClusterContextFacade(provider)
        config = await facade.get_cluster_config(cluster_id)

    After (direct + transforms):
        config = await get_transformed(
            provider, "cluster_config", cluster_id,
            transform_fn=transform_cluster_config
        )
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

# Table transforms
from starboard_core.domain.transformers import (
    transform_delta_history,
    transform_table_lineage,
    transform_table_metadata,
)

# Job transforms
from starboard_core.domain.transformers.job_transformers import (
    transform_job_config,
    transform_job_runs,
    transform_system_tables_job_detail,
)
from starboard_log_parser import SparkLogPathNotFoundError, create_spark_application

from starboard_server.infra.observability.logging import get_logger

# Cluster transforms
from starboard_server.tools.domain.cluster.cluster_metrics_analyzer import (
    ClusterMetricsAnalyzer,
)
from starboard_server.tools.domain.cluster.transformers import (
    transform_cluster_config,
    transform_cluster_events,
)
from starboard_server.tools.domain.job.spark_ui_analyzer import SparkUIAnalyzer

# Warehouse/Query transforms
from starboard_server.tools.domain.query.transformers import (
    transform_query_history,
    transform_warehouse_configuration,
)
from starboard_server.tools.domain.query.warehouse_query_analyzer import (
    WarehouseQueryAnalyzer,
)

if TYPE_CHECKING:
    from starboard_server.services.context.provider import SharedContextProvider

logger = get_logger(__name__)

__all__ = [
    # Cluster transforms
    "transform_cluster_config",
    "transform_cluster_events",
    "ClusterMetricsAnalyzer",
    "SparkUIAnalyzer",
    # Warehouse/Query transforms
    "transform_warehouse_configuration",
    "transform_query_history",
    "WarehouseQueryAnalyzer",
    # Table transforms
    "transform_delta_history",
    "transform_table_lineage",
    "transform_table_metadata",
    # Job transforms
    "transform_job_config",
    "transform_job_runs",
    "transform_system_tables_job_detail",
    # Helper functions
    "get_transformed",
    "analyze_cluster_metrics",
    "analyze_spark_logs",
    "analyze_warehouse_queries",
    # Job helper functions
    "get_job_metadata",
    "search_jobs_by_name",
    "get_jobs_list",
    # Query helper functions
    "get_explain_plan",
]


async def get_transformed(
    provider: SharedContextProvider,
    resource_type: str,
    resource_id: str,
    transform_fn: Callable[[Any], Any] | None = None,
    **kwargs: Any,
) -> Any | None:
    """Get resource and optionally transform.

    Convenience function replacing the facade pattern. Fetches data from
    the provider and applies an optional transform function.

    Args:
        provider: SharedContextProvider instance for data access.
        resource_type: Type of resource to fetch (e.g., 'cluster_config').
        resource_id: Resource identifier.
        transform_fn: Optional transform function to apply to raw data.
        **kwargs: Additional parameters passed to provider.get().

    Returns:
        Transformed data if transform_fn provided, raw data otherwise.
        Returns None if resource not found.

    Example:
        >>> config = await get_transformed(
        ...     provider, "cluster_config", "cluster-123",
        ...     transform_fn=transform_cluster_config
        ... )
    """
    raw = await provider.get(resource_type, resource_id, **kwargs)
    if raw and transform_fn:
        return transform_fn(raw)
    return raw


async def analyze_cluster_metrics(
    provider: SharedContextProvider,
    cluster_ids: list[str],
) -> list[dict[str, Any]] | None:
    """Get and analyze cluster metrics.

    Fetches metrics for the specified clusters and runs analysis.

    Args:
        provider: SharedContextProvider instance for data access.
        cluster_ids: List of cluster IDs to analyze.

    Returns:
        List of analyzed metrics dicts, or None if no data available.

    Example:
        >>> metrics = await analyze_cluster_metrics(provider, ["cluster-123"])
        >>> if metrics:
        ...     print(metrics[0]["cpu_utilization"])
    """
    if not cluster_ids:
        return None

    # Use first cluster ID as the resource_id for cache key
    raw_data = await provider.get("cluster_metrics", cluster_ids[0])
    if raw_data:
        analyzer = ClusterMetricsAnalyzer(raw_data)
        return analyzer.analyze()
    return None


async def analyze_warehouse_queries(
    provider: SharedContextProvider,
    warehouse_id: str,
    days_history: int = 30,
) -> dict[str, Any] | None:
    """Get and analyze warehouse query history.

    Fetches query history for the specified warehouse and runs analysis.

    Args:
        provider: SharedContextProvider instance for data access.
        warehouse_id: SQL warehouse ID.
        days_history: Number of days to look back (default: 30).

    Returns:
        Analyzed query history dict with patterns and summary,
        or None if no data available.

    Example:
        >>> history = await analyze_warehouse_queries(provider, "wh-123")
        >>> if history:
        ...     print(history["summary"]["total_queries"])
    """
    raw_data = await provider.get(
        "warehouse_query_history", warehouse_id, days_history=days_history
    )
    if raw_data:
        analyzer = WarehouseQueryAnalyzer(raw_data)
        return analyzer.analyze()
    return None


def analyze_spark_logs(
    cluster_id: str,
    path: str,
    raw: bool = False,
) -> dict[str, Any] | None:
    """Retrieve and analyze Spark application logs.

    Note: This is sync as it reads from local/DBFS path using
    starboard_log_parser which does its own file handling.

    Args:
        cluster_id: The cluster identifier.
        path: Base path to the logs directory.
        raw: If True, return raw data; if False, return analyzed results.

    Returns:
        Dictionary containing parsed Spark application log data,
        None if logs don't exist.

    Raises:
        Exception: For parse errors (corrupt logs, etc.) - these are
            real failures that should propagate.

    Example:
        >>> logs = analyze_spark_logs("cluster-123", "dbfs:/logs")
        >>> if logs:
        ...     print(logs["summary"]["total_duration_ms"])
    """
    log_path = f"{path}/{cluster_id}/eventlog/"

    try:
        app = create_spark_application(path=log_path)

        # If app is None, logs don't exist
        if app is None:
            return None

        data = app.to_dict(include_spark_params=False, df_format="records")
        del data["accumData"]

        if raw:
            return data

        analyzer = SparkUIAnalyzer(data)
        result = analyzer.analyze()
        return result.to_dict()

    except SparkLogPathNotFoundError:
        # Path not found is NOT a failure - just means logs don't exist yet
        return None
    except Exception as e:
        # Parse errors, corrupt files, etc. ARE failures - re-raise
        logger.error(
            "spark_log_parse_error",
            cluster_id=cluster_id,
            error=str(e),
            exc_info=True,
        )
        raise


async def get_job_metadata(
    provider: SharedContextProvider,
    job_id: str,
    max_runs: int = 5,
) -> dict[str, Any] | None:
    """Get transformed job metadata with config and runtime info.

    Fetches job metadata from the provider and transforms it into a
    structured format with parsed settings and runtime metrics.

    Args:
        provider: SharedContextProvider instance for data access.
        job_id: Databricks job ID.
        max_runs: Maximum number of runs to fetch (default: 5).

    Returns:
        Dictionary with:
        - job_settings: Raw job settings from API
        - parsed_settings: Transformed job configuration
        - runtime_meta: Transformed runtime metadata from runs
        - runs: Raw run data
        Returns None if job not found.

    Example:
        >>> metadata = await get_job_metadata(provider, "12345", max_runs=10)
        >>> if metadata:
        ...     print(metadata["parsed_settings"]["job"]["name"])
    """
    raw_data = await provider.get("job_metadata", job_id, max_runs=max_runs)
    if not raw_data:
        return None

    job_settings = raw_data.get("job_settings", {})
    runs = raw_data.get("runs", [])

    parsed_settings = transform_job_config(job_settings)
    runtime_meta = transform_job_runs(runs, parsed_settings)

    return {
        "job_settings": job_settings,
        "parsed_settings": parsed_settings,
        "runtime_meta": runtime_meta,
        "runs": runs,
    }


async def search_jobs_by_name(
    provider: SharedContextProvider,
    job_name: str,
    exact_match: bool = True,
    limit: int = 5,
) -> dict[str, Any] | None:
    """Search for jobs by name.

    Uses SDK's name filter for exact match (server-side), falls back to
    partial match if no exact match found.

    Args:
        provider: SharedContextProvider instance for data access.
        job_name: Job name to search for.
        exact_match: If True, try exact match first (default: True).
        limit: Maximum results for partial match (default: 5).

    Returns:
        Dictionary with:
        - exact_match: Whether an exact match was found
        - matches: List of matching job dictionaries
        - job_id: Job ID if exactly one match found
        Returns None on error.

    Example:
        >>> result = await search_jobs_by_name(provider, "my-job")
        >>> if result and result.get("exact_match"):
        ...     print(f"Found job: {result['job_id']}")
    """
    return await provider.get(
        "jobs_by_name",
        job_name,
        exact_match=exact_match,
        limit=limit,
    )


async def get_jobs_list(
    provider: SharedContextProvider,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get list of all jobs in the workspace.

    Args:
        provider: SharedContextProvider instance for data access.
        limit: Maximum number of jobs to return (default: 100).

    Returns:
        List of job dictionaries, empty list if none found.

    Example:
        >>> jobs = await get_jobs_list(provider, limit=50)
        >>> for job in jobs:
        ...     print(job["settings"]["name"])
    """
    raw_data = await provider.get("jobs_list", "all", limit=limit)
    if raw_data:
        return raw_data
    return []


async def get_explain_plan(
    provider: SharedContextProvider,
    sql_text: str,
) -> str | None:
    """Get raw EXPLAIN plan text for SQL query.

    Args:
        provider: SharedContextProvider instance for data access.
        sql_text: SQL query text to explain.

    Returns:
        Raw EXPLAIN output text, or None if not available.

    Example:
        >>> plan = await get_explain_plan(provider, "SELECT * FROM table")
        >>> if plan:
        ...     print(plan)
    """
    return await provider.get("explain_plan", sql_text)
