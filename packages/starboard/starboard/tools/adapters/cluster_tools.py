# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reasoning interface for cluster operations.

This module provides LLM-facing tools for cluster operations.
Uses domain logic and transforms directly - no intermediate service layer.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.discovery.query import SystemQuery
from starboard_x.cluster import LIST_PRICE_DISCLAIMER

from starboard.discovery.executor import QueryPackExecutor, SQLExecutor
from starboard.discovery.query_packs.cluster_right_sizing import (
    CLUSTER_RIGHT_SIZING_PACK,
)
from starboard.exceptions import AdapterError, ToolError
from starboard.infra.observability.logging import get_logger
from starboard.services.context.transforms import (
    analyze_cluster_metrics,
    analyze_spark_logs,
    get_job_metadata,
    get_transformed,
    transform_cluster_config,
    transform_cluster_events,
)
from starboard.tools.adapters.base import BaseToolAdapter, OutputFormat
from starboard.tools.domain.cluster import ComputeResolver
from starboard.tools.domain.cluster.cluster_metrics_analyzer import (
    derive_rightsizing_signal,
)
from starboard.tools.domain.cluster.fingerprint_builder import (
    build_cluster_fingerprint,
)
from starboard.tools.domain.cluster.health_analyzer import analyze_cluster_health
from starboard.tools.exceptions import (
    ClusterNotFoundError,
    SparkLogsUnavailableError,
)
from starboard.tools.utils import extract_job_clusters

if TYPE_CHECKING:
    from starboard.infra.observability.events import EventEmitter
    from starboard.services.context.provider import SharedContextProvider

logger = get_logger(__name__)

# Default public list-price $/DBU used to project the DBU-only right-sizing pack
# into a labelled list-price estimate at the tool layer (the CRS pack itself is
# DBU-only). This mirrors the list-price convention used elsewhere in the tool
# tier (e.g. storage cost attribution); every $ output is explicitly labelled a
# **list-price DBU estimate** and is not a contracted-rate figure.
DEFAULT_LIST_PRICE_PER_DBU = 0.55

# LIST_PRICE_DISCLAIMER is imported from starboard_x.cluster (single source of
# truth, shared with the autonomous monitor).


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

    def __init__(
        self,
        *,
        provider: SharedContextProvider | None = None,
        events: EventEmitter | None = None,
        sql_executor: SQLExecutor | None = None,
    ) -> None:
        """Initialize cluster tools.

        Args:
            provider: SharedContextProvider for config/metrics access.
            events: Optional event emitter for observability.
            sql_executor: Optional async SQL executor used by the right-sizing
                tools (``get_cluster_rightsizing`` / ``get_workload_rightsizing``)
                to run the ``cluster_right_sizing`` query pack. When absent, the
                right-sizing tools degrade gracefully with a clear message.
        """
        super().__init__(provider=provider, events=events)
        self._sql_executor = sql_executor

    @classmethod
    def from_provider(  # type: ignore[override]
        cls,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
        sql_executor: SQLExecutor | None = None,
    ) -> ClusterTools:
        """Create ClusterTools from a SharedContextProvider.

        Args:
            provider: SharedContextProvider for data access.
            events: Optional event emitter for observability.
            sql_executor: Optional async SQL executor for the right-sizing tools.

        Returns:
            Configured ClusterTools instance.
        """
        return cls(provider=provider, events=events, sql_executor=sql_executor)

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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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

        metrics = metrics_list[0]
        # Enrich with the right-sizing signal (D-2.3): reuses the pure
        # starboard_x.cluster logic via the analyzer (one source of truth).
        metrics["rightsizing"] = derive_rightsizing_signal(metrics)

        return {
            "found": True,
            "cluster_id": cluster_id,
            "metrics": metrics,
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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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
        except (ToolError, AdapterError, ValueError):
            logger.debug("Metrics unavailable for cluster {cluster_id}: {e}")

        # Build fingerprint from config and metrics
        fingerprint = build_cluster_fingerprint(config, metrics=metrics)

        # Analyze health
        health_report = analyze_cluster_health(fingerprint)

        # Right-sizing enrichment (D-2.3): reuse the pure starboard_x.cluster
        # logic via the analyzer. Degrades to available=False when metrics are
        # unavailable (e.g. terminated / short-lived job cluster).
        rightsizing = derive_rightsizing_signal(metrics or {})

        # Convert to dict for LLM consumption
        return {
            "found": True,
            "cluster_id": cluster_id,
            "cluster_name": health_report.cluster_name,
            "health": {
                "rightsizing": rightsizing,
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
    # Right-Sizing Operations (CRS-06 / CRS-07 / CRS-08)
    # -------------------------------------------------------------------------

    @staticmethod
    def _crs_query(query_id: str) -> SystemQuery | None:
        """Return the ``cluster_right_sizing`` SystemQuery with ``query_id``."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id == query_id:
                return query
        return None

    async def _run_crs_query(
        self,
        query_id: str,
        lookback_days: int,
        result_limit: int,
    ) -> list[dict[str, Any]] | None:
        """Execute a single ``cluster_right_sizing`` query and return its rows.

        Returns ``None`` when no SQL executor is configured, the query is
        unknown, or the query failed (e.g. an optional ``system.lakeflow.*``
        table is absent in the workspace) — the caller degrades gracefully.
        """
        if self._sql_executor is None:
            return None
        query = self._crs_query(query_id)
        if query is None:
            return None

        # Build a single-query pack so only the requested query runs (the full
        # pack has 8 queries, several of which need optional lakeflow tables).
        single_pack = dataclasses.replace(
            CLUSTER_RIGHT_SIZING_PACK,
            pack_id=f"cluster_right_sizing_{query_id}",
            queries=(query,),
        )
        executor = QueryPackExecutor(
            sql_executor=self._sql_executor,
            default_lookback_days=lookback_days,
            default_result_limit=result_limit,
            enable_cache=False,
        )
        pack_result = await executor.execute_pack(single_pack)
        for result in pack_result.results:
            if result.query_id == query_id:
                if result.succeeded and result.data is not None:
                    return list(result.data.iter_rows(named=True))
                return None
        return None

    @staticmethod
    def _list_price_block(
        dbus_per_day: float | None,
        reduction_pct: float | None,
        list_price_per_dbu: float,
    ) -> dict[str, Any]:
        """Project DBU-only figures into a labelled list-price DBU estimate."""
        dbus = float(dbus_per_day or 0.0)
        monthly_dbus = round(dbus * 30.0, 2)
        monthly_cost = round(monthly_dbus * list_price_per_dbu, 2)
        reduction = float(reduction_pct or 0.0)
        monthly_savings = round(monthly_cost * reduction / 100.0, 2)
        return {
            "cost_basis": "list-price DBU estimate",
            "list_price_per_dbu_usd": list_price_per_dbu,
            "dbus_per_day": round(dbus, 2),
            "estimated_monthly_dbus": monthly_dbus,
            "estimated_monthly_cost_usd": monthly_cost,
            "estimated_monthly_savings_usd": monthly_savings,
            "disclaimer": LIST_PRICE_DISCLAIMER,
        }

    async def get_cluster_rightsizing(
        self,
        cluster_id: str | None = None,
        lookback_days: int = 30,
        list_price_per_dbu: float | None = None,
    ) -> dict[str, Any]:
        """Right-size clusters using the CRS-06 cluster_rightsizing_summary query.

        Returns a per-cluster sizing verdict (direction + recommended action +
        target cores + reduction %) joined to a **list-price DBU cost estimate**
        projected at the tool layer (the CRS pack is DBU-only).

        Args:
            cluster_id: Optional cluster ID to scope the verdict to one cluster.
            lookback_days: Utilization/billing window (clamped to 90 by the pack).
            list_price_per_dbu: Optional list-price $/DBU (defaults to a public
                list-price rate). Every $ figure is labelled a list-price DBU estimate.

        Returns:
            On success: {"found": True, "clusters": [...], "summary": {...}}.
            On no executor/data: {"found": False, "reason": "..."}.
        """
        self._log_obs_context(
            "get_cluster_rightsizing",
            {"cluster_id": cluster_id, "lookback_days": lookback_days},
        )
        rate = (
            list_price_per_dbu
            if list_price_per_dbu is not None
            else DEFAULT_LIST_PRICE_PER_DBU
        )

        # When scoped to a single cluster, request an effectively-unbounded
        # result set so the target is not dropped by the default LIMIT *before*
        # the in-memory cluster_id filter runs (CRS-06 is ranked by dbus_per_day,
        # so a low-spend target would otherwise fall outside the top 200).
        # Per-cluster rows are bounded by the workspace's cluster count.
        result_limit = 5000 if cluster_id is not None else 200
        rows = await self._run_crs_query(
            "CRS-06", lookback_days, result_limit=result_limit
        )
        if rows is None:
            return {
                "found": False,
                "reason": (
                    "Cluster right-sizing data unavailable. Requires a SQL "
                    "executor and access to system.compute.* / system.billing.usage."
                ),
            }

        if cluster_id is not None:
            rows = [r for r in rows if r.get("cluster_id") == cluster_id]

        clusters: list[dict[str, Any]] = []
        direction_counts: dict[str, int] = {}
        total_monthly_savings = 0.0
        for row in rows:
            direction = row.get("sizing_direction") or "REVIEW"
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
            list_price = self._list_price_block(
                row.get("dbus_per_day"), row.get("reduction_pct"), rate
            )
            total_monthly_savings += list_price["estimated_monthly_savings_usd"]
            clusters.append(
                {
                    "workspace_id": row.get("workspace_id"),
                    "cluster_id": row.get("cluster_id"),
                    "sizing_reason": row.get("sizing_reason"),
                    "sizing_direction": direction,
                    "recommended_action": row.get("recommended_action"),
                    "target_cores_per_node": row.get("target_cores_per_node"),
                    "reduction_pct": row.get("reduction_pct"),
                    "list_price_estimate": list_price,
                }
            )

        return {
            "found": True,
            "lookback_days": lookback_days,
            "query_id": "CRS-06",
            "clusters": clusters,
            "summary": {
                "cluster_count": len(clusters),
                "by_direction": direction_counts,
                "estimated_total_monthly_savings_usd": round(total_monthly_savings, 2),
                "cost_basis": "list-price DBU estimate",
                "disclaimer": LIST_PRICE_DISCLAIMER,
            },
        }

    async def get_workload_rightsizing(
        self,
        workload_type: str | None = None,
        workload_id: str | None = None,
        lookback_days: int = 30,
        list_price_per_dbu: float | None = None,
    ) -> dict[str, Any]:
        """Right-size workloads via the CRS-07/08 job/workload summaries.

        Surfaces the unified per-workload sizing verdict (CRS-08, ranked by
        priority) and per-job reliability (CRS-07), plus a fleet-level
        **list-price DBU cost exposure** derived from CRS-06 for the underlying
        compute (the workload queries are DBU-less; cost is projected here).

        Downstream: the autonomous cluster right-sizing monitor (Wave-C 09) calls
        this and classifies PERSISTENT overprovision → DRAFT downsize,
        underprovision+autoscale-constrained → WARN (report-only).

        Args:
            workload_type: Optional filter, ``JOB`` or ``PIPELINE``.
            workload_id: Optional workload ID (job_id / pipeline_id) to scope to one.
            lookback_days: Utilization/reliability window (clamped to 90 by the pack).
            list_price_per_dbu: Optional list-price $/DBU (defaults to a public rate).

        Returns:
            On success: {"found": True, "workloads": [...], "jobs": [...],
            "summary": {...}, "list_price_estimate": {...}}.
            On no executor/data: {"found": False, "reason": "..."}.
        """
        self._log_obs_context(
            "get_workload_rightsizing",
            {
                "workload_type": workload_type,
                "workload_id": workload_id,
                "lookback_days": lookback_days,
            },
        )
        rate = (
            list_price_per_dbu
            if list_price_per_dbu is not None
            else DEFAULT_LIST_PRICE_PER_DBU
        )

        # CRS-08 (workload verdict), CRS-07 (per-job reliability) and CRS-06
        # (fleet cost exposure) are independent queries — run them concurrently
        # rather than serially (~3x fewer round-trips of latency).
        workload_rows, job_rows, cluster_rows = await asyncio.gather(
            self._run_crs_query("CRS-08", lookback_days, result_limit=200),
            self._run_crs_query("CRS-07", lookback_days, result_limit=200),
            self._run_crs_query("CRS-06", lookback_days, result_limit=200),
        )
        if workload_rows is None:
            return {
                "found": False,
                "reason": (
                    "Workload right-sizing data unavailable. Requires a SQL "
                    "executor and access to system.compute.node_timeline / "
                    "system.lakeflow.* (job/pipeline timelines)."
                ),
            }

        # Per-job reliability detail (CRS-07) may be absent when the lakeflow job
        # tables are missing — degrade to an empty list.
        job_rows = job_rows or []

        wtype = workload_type.upper() if workload_type else None
        workloads: list[dict[str, Any]] = []
        direction_counts: dict[str, int] = {}
        for row in workload_rows:
            if wtype is not None and (row.get("workload_type") or "").upper() != wtype:
                continue
            if workload_id is not None and row.get("workload_id") != workload_id:
                continue
            direction = row.get("sizing_direction") or "REVIEW"
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
            workloads.append(
                {
                    "workspace_id": row.get("workspace_id"),
                    "workload_type": row.get("workload_type"),
                    "workload_id": row.get("workload_id"),
                    "sizing_direction": direction,
                    "priority_score": row.get("priority_score"),
                }
            )

        jobs: list[dict[str, Any]] = []
        for row in job_rows:
            if wtype is not None and wtype != "JOB":
                continue
            if workload_id is not None and str(row.get("job_id")) != workload_id:
                continue
            jobs.append(
                {
                    "workspace_id": row.get("workspace_id"),
                    "job_id": row.get("job_id"),
                    "cluster_sizing_reason": row.get("cluster_sizing_reason"),
                    "job_sizing_direction": row.get("job_sizing_direction"),
                    "total_runs": row.get("total_runs"),
                    "success_rate_pct": row.get("success_rate_pct"),
                    "runtime_p95_minutes": row.get("runtime_p95_minutes"),
                }
            )

        # Fleet-level list-price DBU cost exposure for the underlying compute
        # (CRS-06 dbus_per_day summed, fetched concurrently above). Best-effort:
        # absent CRS-06 → zeroed.
        total_dbus_per_day = sum(
            float(r.get("dbus_per_day") or 0.0) for r in (cluster_rows or [])
        )
        list_price = self._list_price_block(total_dbus_per_day, None, rate)

        return {
            "found": True,
            "lookback_days": lookback_days,
            "query_ids": ["CRS-08", "CRS-07"],
            "workloads": workloads,
            "jobs": jobs,
            "summary": {
                "workload_count": len(workloads),
                "job_count": len(jobs),
                "by_direction": direction_counts,
            },
            "list_price_estimate": list_price,
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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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
        logs = analyze_spark_logs(
            cluster_id, log_destination, raw=fmt == OutputFormat.RAW
        )

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

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

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
            if self.provider is None:
                raise RuntimeError("SharedContextProvider not initialized")

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

            return analyze_spark_logs(
                cluster_id, log_destination, raw=fmt == OutputFormat.RAW
            )
        except (ToolError, AdapterError, ValueError):
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
