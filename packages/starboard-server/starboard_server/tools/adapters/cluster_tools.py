"""Reasoning interface for cluster operations.

This module provides LLM-facing tools for cluster operations.
Uses domain logic and transforms directly - no intermediate service layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.transforms import (
    analyze_cluster_metrics,
    analyze_spark_logs,
    get_job_metadata,
    get_transformed,
    transform_cluster_config,
    transform_cluster_events,
)
from starboard_server.tools.adapters.base import BaseToolAdapter, OutputFormat
from starboard_server.tools.domain.cluster import ComputeResolver
from starboard_server.tools.domain.cluster.fingerprint_builder import (
    build_cluster_fingerprint,
)
from starboard_server.tools.domain.cluster.health_analyzer import analyze_cluster_health
from starboard_server.tools.exceptions import (
    ClusterNotFoundError,
    SparkLogsUnavailableError,
)
from starboard_server.tools.utils import extract_job_clusters

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class ClusterTools(BaseToolAdapter):
    """Reasoning interface for cluster operations.

    Clean interface optimized for LLM reasoning. Uses SharedContextProvider
    directly with transforms and domain logic - no intermediate service layer.

    Architecture:
        ClusterTools → transforms + ComputeResolver (domain)

    Example:
        >>> tools = ClusterTools.from_provider(provider, events=events)
        >>> config = await tools.get_cluster_config("cluster-123")
    """

    # -------------------------------------------------------------------------
    # Cluster Discovery
    # -------------------------------------------------------------------------

    @staticmethod
    def _ms_to_datetime(ms: int | None) -> datetime | None:
        """Convert milliseconds since epoch to datetime.

        Args:
            ms: Milliseconds since epoch, or None.

        Returns:
            UTC datetime, or None if input is None.
        """
        if ms is None:
            return None
        return datetime.fromtimestamp(ms / 1000, tz=UTC)

    async def list_clusters(
        self,
        window_days: int = 30,
        include_terminated: bool = True,
    ) -> dict[str, Any]:
        """List accessible compute clusters with recent activity.

        Databricks clusters are ephemeral - job and pipeline clusters are
        typically TERMINATED after execution. This tool includes terminated
        clusters by default to provide visibility into workloads.

        Args:
            window_days: Only include clusters active within this window (default: 30).
            include_terminated: Include clusters in TERMINATED state (default: True).

        Returns:
            {
                "clusters": [...],
                "total_count": N,
                "summary": {"running": X, "terminated": Y, "pending": Z},
                "window_days": 30
            }

        Example:
            >>> clusters = await tools.list_clusters(window_days=7)
            >>> print(f"Found {clusters['total_count']} clusters")
        """
        logger.debug(
            "list_clusters",
            extra={
                "window_days": window_days,
                "include_terminated": include_terminated,
            },
        )

        # Query cluster list via provider
        all_clusters = await self.provider.get("cluster_list", "all")

        if not all_clusters:
            return {
                "clusters": [],
                "total_count": 0,
                "summary": {"running": 0, "terminated": 0, "pending": 0},
                "window_days": window_days,
            }

        # Calculate cutoff date for activity filter
        cutoff = datetime.now(UTC) - timedelta(days=window_days)

        # Filter clusters by recent activity
        clusters = []
        for c in all_clusters:
            # Parse activity timestamps (stored as milliseconds since epoch)
            last_activity_dt = self._ms_to_datetime(c.get("last_activity_time"))
            terminated_dt = self._ms_to_datetime(c.get("terminated_time"))

            # Include if cluster was active or terminated within the window
            # Running clusters always have recent activity (or are currently active)
            state = c.get("state", "UNKNOWN").upper()
            is_running = state in ("RUNNING", "PENDING", "STARTING", "RESTARTING")

            is_recent = (
                is_running
                or (last_activity_dt and last_activity_dt >= cutoff)
                or (terminated_dt and terminated_dt >= cutoff)
            )

            if is_recent:
                clusters.append(c)

        # Filter terminated if not requested
        if not include_terminated:
            clusters = [c for c in clusters if c.get("state") != "TERMINATED"]

        # Build state summary
        state_counts: dict[str, int] = {
            "running": 0,
            "terminated": 0,
            "pending": 0,
            "other": 0,
        }
        for c in clusters:
            state = c.get("state", "UNKNOWN").upper()
            if state == "RUNNING":
                state_counts["running"] += 1
            elif state == "TERMINATED":
                state_counts["terminated"] += 1
            elif state in ("PENDING", "STARTING", "RESTARTING"):
                state_counts["pending"] += 1
            else:
                state_counts["other"] += 1

        # Transform cluster data for LLM consumption
        cluster_list = [
            {
                "cluster_id": c.get("cluster_id"),
                "cluster_name": c.get("cluster_name"),
                "state": c.get("state"),
                "creator": c.get("creator"),
                "driver_node_type": c.get("driver_node_type_id"),
                "worker_node_type": c.get("node_type_id"),
                "num_workers": c.get(
                    "num_workers", c.get("autoscale", {}).get("min_workers", 0)
                ),
                "autoscale": c.get("autoscale"),
                "runtime_version": c.get("spark_version"),
                "cluster_source": c.get("cluster_source"),  # JOB, UI, API
                "last_activity_time": c.get("last_activity_time"),
                "terminated_time": c.get("terminated_time"),
            }
            for c in clusters
        ]

        # Sort by last activity (most recent first)
        cluster_list.sort(
            key=lambda x: x.get("last_activity_time") or x.get("terminated_time") or 0,
            reverse=True,
        )

        return {
            "clusters": cluster_list,
            "total_count": len(cluster_list),
            "summary": state_counts,
            "window_days": window_days,
        }

    # -------------------------------------------------------------------------
    # Cluster Operations
    # -------------------------------------------------------------------------

    async def get_cluster_config(self, cluster_id: str) -> dict[str, Any]:
        """Get configuration for a compute cluster.

        Args:
            cluster_id: Cluster ID to fetch configuration for.

        Returns:
            On success: {"found": True, "cluster_id": "...", "config": {...}}
            On failure: {"found": False, "error_type": "...", ...}

        Example:
            >>> config = await tools.get_cluster_config("cluster-123")
            >>> if config["found"]:
            ...     print(config["config"]["name"])
        """
        logger.debug("Fetching configuration for cluster: {cluster_id}")

        config = await get_transformed(
            self.provider,
            "cluster_config",
            cluster_id,
            transform_fn=transform_cluster_config,
        )

        if not config:
            logger.debug("Cluster not found: {cluster_id}")
            return ClusterNotFoundError(cluster_id).to_dict()

        return {
            "found": True,
            "cluster_id": cluster_id,
            "config": config,
        }

    async def get_cluster_events(self, cluster_id: str) -> dict[str, Any]:
        """Get events for a compute cluster.

        Args:
            cluster_id: Cluster ID to fetch events for.

        Returns:
            On success: {"found": True, "cluster_id": "...", "events": {...}}
            On failure: {"found": False, "error_type": "...", ...}

        Example:
            >>> events = await tools.get_cluster_events("cluster-123")
            >>> if events["found"]:
            ...     print(f"Found {len(events['events']['events'])} events")
        """
        logger.debug("Fetching events for cluster: {cluster_id}")

        events = await get_transformed(
            self.provider,
            "cluster_events",
            cluster_id,
            transform_fn=transform_cluster_events,
        )

        if not events:
            logger.debug("Cluster events not found: {cluster_id}")
            return ClusterNotFoundError(cluster_id).to_dict()

        return {
            "found": True,
            "cluster_id": cluster_id,
            "events": events,
        }

    async def get_cluster_metrics(self, cluster_id: str) -> dict[str, Any]:
        """Get performance metrics for a compute cluster.

        Note: Metrics may be unavailable for terminated clusters or
        short-lived job clusters.

        Args:
            cluster_id: Cluster ID to fetch metrics for.

        Returns:
            On success: {"found": True, "cluster_id": "...", "metrics": {...}}
            On failure: {"found": False, "reason": "..."}

        Example:
            >>> metrics = await tools.get_cluster_metrics("cluster-123")
            >>> if metrics["found"]:
            ...     print(f"CPU: {metrics['metrics']['cpu_utilization']}%")
        """
        logger.debug("Fetching metrics for cluster: {cluster_id}")

        metrics_list = await analyze_cluster_metrics(self.provider, [cluster_id])

        if not metrics_list:
            logger.debug("Cluster metrics unavailable: {cluster_id}")
            return {
                "found": False,
                "cluster_id": cluster_id,
                "reason": (
                    "Cluster metrics unavailable. Possible causes: "
                    "cluster terminated, metrics not collected, "
                    "or short-lived job cluster (metrics may not persist after termination)."
                ),
            }

        return {
            "found": True,
            "cluster_id": cluster_id,
            "metrics": metrics_list[0],
        }

    async def get_cluster_health(self, cluster_id: str) -> dict[str, Any]:
        """Get health score and risk analysis for a compute cluster.

        Analyzes cluster configuration and metrics to produce a health report
        with scores across dimensions (performance, cost, reliability, security)
        and identifies risks with recommendations.

        Args:
            cluster_id: Cluster ID to analyze health for.

        Returns:
            On success: {"found": True, "cluster_id": "...", "health": {...}}
            On failure: {"found": False, "error_type": "...", ...}

        Example:
            >>> health = await tools.get_cluster_health("cluster-123")
            >>> if health["found"]:
            ...     print(f"Health: {health['health']['health_score']}/100")
            ...     for risk in health['health']['risks']:
            ...         print(f"  - {risk['title']}")
        """
        logger.debug("Analyzing health for cluster: {cluster_id}")

        # Get cluster configuration (required)
        config = await get_transformed(
            self.provider,
            "cluster_config",
            cluster_id,
            transform_fn=transform_cluster_config,
        )

        if not config:
            logger.debug("Cluster not found: {cluster_id}")
            return ClusterNotFoundError(cluster_id).to_dict()

        # Get metrics (optional - may not be available for terminated clusters)
        metrics: dict[str, Any] | None = None
        try:
            metrics_list = await analyze_cluster_metrics(self.provider, [cluster_id])
            if metrics_list:
                metrics = metrics_list[0]
        except Exception:
            logger.debug("Metrics unavailable for cluster {cluster_id}: {e}")

        # Build fingerprint from config and metrics
        fingerprint = build_cluster_fingerprint(config, metrics=metrics)

        # Analyze health
        health_report = analyze_cluster_health(fingerprint)

        # Convert to dict for LLM consumption
        return {
            "found": True,
            "cluster_id": cluster_id,
            "cluster_name": health_report.cluster_name,
            "health": {
                "health_score": health_report.scores.overall,
                "health_status": health_report.health_status,
                "metric_scores": {
                    "performance": health_report.scores.performance,
                    "cost": health_report.scores.cost,
                    "reliability": health_report.scores.reliability,
                    "security": health_report.scores.security,
                },
                "risks": [
                    {
                        "category": risk.category.value,
                        "severity": risk.severity.value,
                        "title": risk.title,
                        "description": risk.description,
                        "impact": risk.impact,
                        "recommendation": risk.recommendation,
                    }
                    for risk in health_report.risks
                ],
                "critical_risks": len(health_report.critical_risks),
                "high_priority_risks": len(health_report.high_priority_risks),
                "summary": health_report.summary,
                "generated_at": health_report.generated_at.isoformat(),
            },
        }

    # -------------------------------------------------------------------------
    # Spark Logs Operations
    # -------------------------------------------------------------------------

    async def get_spark_logs(
        self,
        cluster_id: str | None = None,
        job_id: str | None = None,
        max_runs: int = 1,
        fmt: OutputFormat = OutputFormat.FORMATTED,
    ) -> dict[str, Any]:
        """Get Spark application logs for a cluster or job.

        Provide either cluster_id directly, or job_id to derive cluster(s)
        from recent job runs. The job_id approach uses "expand search" to
        try multiple clusters if the first doesn't have logs.

        Args:
            cluster_id: Cluster ID to fetch logs for (direct lookup).
            job_id: Job ID to derive cluster(s) from.
            max_runs: Number of runs to fetch when using job_id (1-5, default: 1).
            fmt: Output format selector (RAW or FORMATTED, default: FORMATTED).

        Returns:
            On success: {"found": True, "cluster_id": "...", "logs": {...}}
            On multi-run success: {"found": True, "runs": [...], "total_runs": N}
            On failure: {"found": False, "error_type": "...", "reason": "..."}

        Example:
            >>> # By cluster_id
            >>> logs = await tools.get_spark_logs(cluster_id="cluster-123")
            >>> # By job_id (derives cluster from recent run)
            >>> logs = await tools.get_spark_logs(job_id="12345")
            >>> # Multiple runs from job
            >>> logs = await tools.get_spark_logs(job_id="12345", max_runs=5)
        """
        # Route to job-based lookup if job_id provided
        if job_id:
            result = await self._get_spark_logs_for_job(
                job_id, max_runs=max_runs, fmt=fmt
            )
            if result is None:
                return {
                    "found": False,
                    "job_id": job_id,
                    "reason": (
                        "Spark logs unavailable. Possible causes: "
                        "cluster logging not configured, logs not yet written, "
                        "log destination inaccessible, or cluster terminated "
                        "before logs were captured."
                    ),
                }
            # Multi-run result has "runs" key
            if "runs" in result:
                return {"found": True, **result}
            # Single-run result is logs dict
            return {"found": True, "job_id": job_id, "logs": result}

        # Direct cluster_id lookup
        if not cluster_id:
            return {
                "found": False,
                "reason": "Either cluster_id or job_id must be provided.",
            }

        return await self._get_spark_logs_for_cluster(cluster_id, fmt=fmt)

    async def _get_spark_logs_for_cluster(
        self, cluster_id: str, fmt: OutputFormat = OutputFormat.FORMATTED
    ) -> dict[str, Any]:
        """Get Spark logs for a specific cluster (raising version).

        Args:
            cluster_id: Cluster ID to fetch logs for.
            fmt: Output format selector (default: FORMATTED).

        Returns:
            On success: {"found": True, "cluster_id": "...", "logs": {...}}
            On failure: {"found": False, ...}
        """
        logger.debug("Fetching Spark logs for cluster: {cluster_id}")

        # Get cluster config to find log destination
        config = await get_transformed(
            self.provider,
            "cluster_config",
            cluster_id,
            transform_fn=transform_cluster_config,
        )

        if not config:
            logger.debug("Cluster not found: {cluster_id}")
            return ClusterNotFoundError(cluster_id).to_dict()

        # Check if logging is configured
        if not ComputeResolver.is_logging_configured(config):
            logger.debug("Logging not configured for cluster: {cluster_id}")
            return SparkLogsUnavailableError(
                cluster_id=cluster_id,
                reason="Cluster logging is not configured",
            ).to_dict()

        # Extract log destination
        log_destination = ComputeResolver.extract_log_destination(config)
        if not log_destination:
            logger.debug("No log destination found for cluster: {cluster_id}")
            return SparkLogsUnavailableError(
                cluster_id=cluster_id,
                reason="No log destination configured",
            ).to_dict()

        # Fetch logs
        logs = analyze_spark_logs(cluster_id, log_destination, raw=fmt == OutputFormat.RAW)

        if logs is None:
            logger.debug("Spark logs not found for cluster: {cluster_id}")
            return SparkLogsUnavailableError(
                cluster_id=cluster_id,
                reason="Logs not found at configured destination",
            ).to_dict()

        return {
            "found": True,
            "cluster_id": cluster_id,
            "logs": logs,
        }

    async def _get_spark_logs_for_job(
        self,
        job_id: str,
        max_runs: int = 1,
        fmt: OutputFormat = OutputFormat.FORMATTED,
    ) -> dict[str, Any] | None:
        """Get Spark logs by deriving cluster_id from job runs.

        Uses expand search: tries multiple clusters if first doesn't have logs.

        Args:
            job_id: Job ID to derive cluster from.
            max_runs: Number of runs to fetch logs for (1-5).
            fmt: Output format selector (default: FORMATTED).

        Returns:
            - Single run: Logs dict or None
            - Multiple runs: {"runs": [...], "total_runs": N}
        """
        max_runs = min(max_runs, 5)  # Cap at 5

        # Fetch job metadata to get cluster IDs
        job_metadata = await get_job_metadata(
            self.provider, job_id, max_runs=max(max_runs, 10)
        )

        if not job_metadata:
            logger.debug("No job metadata found for job: {job_id}")
            return None

        job_clusters = extract_job_clusters(job_metadata.get("runs", []))
        if not job_clusters:
            logger.debug("No clusters found in job runs for job: {job_id}")
            return None

        # Multi-run mode: fetch logs for multiple clusters
        if max_runs > 1:
            return await self._fetch_spark_logs_multi_run(
                job_clusters, max_runs, fmt=fmt
            )

        # Single-run mode with expand search: try multiple clusters
        max_clusters_to_try = min(3, len(job_clusters))
        for cluster_entry in job_clusters[:max_clusters_to_try]:
            cluster_id = cluster_entry["cluster_id"]
            logs = await self._try_fetch_logs_for_cluster(cluster_id, fmt=fmt)
            if logs is not None:
                logger.debug("Found Spark logs from cluster {cluster_id}")
                return logs

        logger.debug(
            f"No Spark logs found after trying {max_clusters_to_try} clusters "
            f"for job {job_id}"
        )
        return None

    async def _try_fetch_logs_for_cluster(
        self, cluster_id: str, fmt: OutputFormat = OutputFormat.FORMATTED
    ) -> dict[str, Any] | None:
        """Try to fetch Spark logs for a single cluster (non-raising).

        Args:
            cluster_id: Cluster ID to fetch logs for.
            fmt: Output format selector (default: FORMATTED).

        Returns:
            Spark logs dict if available, None otherwise.
        """
        try:
            config = await get_transformed(
                self.provider,
                "cluster_config",
                cluster_id,
                transform_fn=transform_cluster_config,
            )

            if not config:
                return None

            if not ComputeResolver.is_logging_configured(config):
                return None

            log_destination = ComputeResolver.extract_log_destination(config)
            if not log_destination:
                return None

            return analyze_spark_logs(cluster_id, log_destination, raw=fmt == OutputFormat.RAW)
        except Exception:
            logger.debug("Error fetching logs for cluster {cluster_id}: {e}")
            return None

    async def _fetch_spark_logs_multi_run(
        self,
        job_clusters: list[dict[str, Any]],
        max_runs: int,
        fmt: OutputFormat = OutputFormat.FORMATTED,
    ) -> dict[str, Any]:
        """Fetch Spark logs for multiple job runs.

        Args:
            job_clusters: List of cluster entries from job runs.
            max_runs: Maximum runs to fetch.
            fmt: Output format selector (default: FORMATTED).

        Returns:
            Dict with runs list and total count.
        """
        logs_list = []
        for cluster_entry in job_clusters[:max_runs]:
            cluster_id = cluster_entry["cluster_id"]
            run_id = cluster_entry.get("run_id")

            logs = await self._try_fetch_logs_for_cluster(cluster_id, fmt=fmt)
            if logs:
                logs_list.append(
                    {
                        "cluster_id": cluster_id,
                        "run_id": run_id,
                        "run_date": cluster_entry.get("run_date"),
                        "logs": logs,
                    }
                )
                logger.debug("Fetched Spark logs for cluster: {cluster_id}")

        return {"runs": logs_list, "total_runs": len(logs_list)}
