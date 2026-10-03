# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure domain logic for compute resource resolution."""

from typing import Any

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class ComputeResolver:
    """Pure functions for resolving compute identifiers."""

    @staticmethod
    def resolve_cluster_from_job_clusters(
        job_clusters: list[dict[str, Any]] | None,
    ) -> str | None:
        """
        Extract cluster ID from job clusters list.

        Sorts clusters by run_date descending (newest first) and returns the
        cluster_id from the most recent entry.

        Args:
            job_clusters: List of job cluster dictionaries with run_date field

        Returns:
            Cluster ID if found, None otherwise

        Examples:
            >>> clusters = [
            ...     {"cluster_id": "cluster-123", "run_date": 1704067200000},  # 2024-01-01
            ...     {"cluster_id": "cluster-456", "run_date": 1704153600000}   # 2024-01-02
            ... ]
            >>> ComputeResolver.resolve_cluster_from_job_clusters(clusters)
            'cluster-456'  # Returns newest cluster
            >>> ComputeResolver.resolve_cluster_from_job_clusters([])
            >>> ComputeResolver.resolve_cluster_from_job_clusters(None)
        """
        if not job_clusters:
            logger.debug("No job_clusters provided")
            return None

        if not isinstance(job_clusters, list) or len(job_clusters) == 0:
            logger.warning("job_clusters is empty or invalid format")
            return None

        # Sort by run_date descending (newest first), handling None/missing values
        sorted_clusters = sorted(
            job_clusters,
            key=lambda x: x.get("run_date") or 0,
            reverse=True,
        )

        # Extract cluster_id from newest entry
        newest_cluster = sorted_clusters[0]
        extracted_cluster_id = newest_cluster.get("cluster_id")

        if not extracted_cluster_id:
            logger.warning(
                f"Newest job_clusters entry missing cluster_id: {newest_cluster}"
            )
            return None

        logger.debug(
            f"Resolved cluster_id={extracted_cluster_id} from newest cluster "
            f"(run_date={newest_cluster.get('run_date')})"
        )
        return extracted_cluster_id

    @staticmethod
    def extract_log_destination(
        cluster_config: dict[str, Any],
    ) -> str | None:
        """
        Extract log destination from TRANSFORMED cluster configuration.

        Important: This expects the transformed cluster config with "logs" field,
        NOT the raw API response with "cluster_log_conf". The transformation is
        done by transform_cluster_config() which normalizes various log formats
        (dbfs/s3/abfss/gs/volumes) into a consistent structure.

        Args:
            cluster_config: TRANSFORMED cluster configuration dictionary
                           (from get_cluster_config(), not raw API response)

        Returns:
            Log destination string if configured, None otherwise

        Examples:
            >>> # Transformed format (after transform_cluster_config)
            >>> config = {
            ...     "id": "cluster-123",
            ...     "logs": {"type": "dbfs", "destination": "dbfs:/logs/cluster-123"}
            ... }
            >>> ComputeResolver.extract_log_destination(config)
            'dbfs:/logs/cluster-123'
            >>> ComputeResolver.extract_log_destination({})
        """
        if not cluster_config:
            return None

        # "logs" field is from transformed config (not raw "cluster_log_conf")
        cluster_logs = cluster_config.get("logs")
        if not cluster_logs:
            return None

        return cluster_logs.get("destination")

    @staticmethod
    def is_logging_configured(cluster_config: dict[str, Any]) -> bool:
        """
        Check if cluster logging is configured.

        Important: This expects the transformed cluster config with "logs" field,
        NOT the raw API response with "cluster_log_conf".

        Args:
            cluster_config: TRANSFORMED cluster configuration dictionary
                           (from get_cluster_config(), not raw API response)

        Returns:
            True if logging is configured, False otherwise

        Examples:
            >>> # Transformed format (after transform_cluster_config)
            >>> config = {
            ...     "logs": {"type": "dbfs", "destination": "dbfs:/logs/cluster-123"}
            ... }
            >>> ComputeResolver.is_logging_configured(config)
            True
            >>> ComputeResolver.is_logging_configured({})
            False
        """
        log_dest = ComputeResolver.extract_log_destination(cluster_config)
        return log_dest is not None
