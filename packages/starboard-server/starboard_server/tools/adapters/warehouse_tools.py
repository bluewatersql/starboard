# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reasoning interface for warehouse portfolio tools.

Provides clean, parameter-based interface optimized for LLM reasoning agents.
These tools enable the warehouse domain agent to analyze and optimize
SQL warehouse portfolios.

Also includes basic warehouse config/metrics tools that support the compute agent
for simple warehouse lookups (migrated from ClusterTools for proper domain alignment).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.transforms import (
    analyze_warehouse_queries,
    get_transformed,
    transform_query_history,
    transform_warehouse_configuration,
)
from starboard_server.tools.adapters.base import BaseToolAdapter, tool_schema

if TYPE_CHECKING:
    from starboard_server.infra.observability.events import EventEmitter
    from starboard_server.services.context.provider import SharedContextProvider
    from starboard_server.tools.services.warehouse_portfolio_service import (
        WarehousePortfolioService,
    )

logger = get_logger(__name__)


class WarehouseTools(BaseToolAdapter):
    """Reasoning interface for warehouse portfolio operations.

    Provides tools for:
    - Portfolio-level warehouse analysis
    - Individual warehouse fingerprinting
    - Health scoring and recommendations
    - SLO configuration
    - Basic warehouse config and metrics lookups

    Example:
        >>> tools = WarehouseTools(warehouse_service, provider=provider)
        >>> portfolio = await tools.get_warehouse_portfolio(window_days=7)
        >>> for wh in portfolio["warehouses"]:
        ...     print(f"{wh['warehouse_name']}: {wh['health_score']}")
    """

    def __init__(
        self,
        warehouse_service: WarehousePortfolioService,
        *,
        provider: SharedContextProvider | None = None,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize warehouse tools.

        Args:
            warehouse_service: WarehousePortfolioService for portfolio operations.
            provider: Optional SharedContextProvider for basic config/metrics lookups.
            events: Optional event emitter for observability.
        """
        super().__init__(provider=provider, events=events)
        self.service = warehouse_service

    @tool_schema(
        description=(
            "Get portfolio view of all SQL warehouses with health scores, "
            "performance metrics, and summary statistics. Use this for fleet-wide "
            "visibility and to identify warehouses needing attention."
        ),
        properties_override={
            "window_days": {"enum": [7, 30, 90]},
        },
    )
    async def get_warehouse_portfolio(
        self,
        window_days: int = 7,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        """Get portfolio view of all SQL warehouses.

        Returns a summary of all warehouses with health scores, performance
        metrics, and aggregate statistics. Use this for fleet-wide visibility.

        Args:
            window_days: Analysis window (7, 30, or 90 days). Default: 7.
            include_inactive: Include warehouses with no recent activity. Default: False.

        Returns:
            Portfolio data with:
            - warehouses: List of warehouse summaries with health scores
            - portfolio_summary: Aggregate metrics (total, healthy, warning, critical counts)
            - window_days: Analysis window used
            - generated_at: Timestamp when portfolio was generated

        Example:
            >>> portfolio = await tools.get_warehouse_portfolio(window_days=30)
            >>> print(f"Total: {portfolio['portfolio_summary']['total_warehouses']}")
            >>> for wh in portfolio["warehouses"][:3]:
            ...     print(f"  {wh['warehouse_name']}: {wh['health_status']}")
        """
        self._log_obs_context(
            "get_warehouse_portfolio",
            {"window_days": window_days, "include_inactive": include_inactive},
        )
        return await self.service.get_portfolio(
            window_days=window_days,
            include_inactive=include_inactive,
        )

    @tool_schema(
        description=(
            "Generate detailed fingerprint for a specific warehouse including "
            "performance percentiles, workload patterns, time distribution, and "
            "query type breakdown. Use for deep analysis of a single warehouse."
        ),
        properties_override={
            "warehouse_id": {
                "description": (
                    "The warehouse ID OR warehouse name. Both formats are accepted - "
                    "the system will resolve names to IDs automatically."
                )
            },
            "window_days": {"enum": [7, 30, 90]},
        },
    )
    async def get_warehouse_fingerprint(
        self,
        warehouse_id: str,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """Generate detailed fingerprint for a specific warehouse.

        Analyzes query history to characterize the warehouse's workload
        including performance percentiles, time patterns, query types,
        and workload classification.

        Args:
            warehouse_id: Target warehouse ID.
            window_days: Analysis window (7, 30, or 90 days). Default: 7.

        Returns:
            Fingerprint data including:
            - warehouse_id, warehouse_name: Identification
            - total_queries, total_bytes_read/written: Volume metrics
            - p50/p75/p90/p95/p99_runtime_sec: Performance percentiles
            - avg_concurrency, peak_concurrency: Concurrency metrics
            - queue_rate_pct, avg_queue_time_sec: Queue metrics
            - query_type_distribution: SELECT/INSERT/UPDATE breakdown
            - time_distribution: Hourly query patterns
            - workload_pattern: Classification (interactive/batch/reporting/etc.)

        Example:
            >>> fp = await tools.get_warehouse_fingerprint("wh-analytics-prod")
            >>> print(f"Pattern: {fp['workload_pattern']['pattern_type']}")
            >>> print(f"P95 latency: {fp['p95_runtime_sec']:.1f}s")
        """
        self._log_obs_context(
            "get_warehouse_fingerprint",
            {"warehouse_id": warehouse_id, "window_days": window_days},
        )
        fingerprint = await self.service.get_fingerprint(
            warehouse_id=warehouse_id,
            window_days=window_days,
        )

        # Convert to dict for LLM consumption
        return {
            "warehouse_id": fingerprint.warehouse_id,
            "warehouse_name": fingerprint.warehouse_name,
            "analysis_window_days": fingerprint.analysis_window_days,
            "analyzed_at": fingerprint.analyzed_at.isoformat(),
            # Volume
            "total_queries": fingerprint.total_queries,
            "total_bytes_read": fingerprint.total_bytes_read,
            "total_bytes_written": fingerprint.total_bytes_written,
            "queries_per_day": fingerprint.queries_per_day,
            # Performance percentiles
            "p50_runtime_sec": fingerprint.p50_runtime_sec,
            "p75_runtime_sec": fingerprint.p75_runtime_sec,
            "p90_runtime_sec": fingerprint.p90_runtime_sec,
            "p95_runtime_sec": fingerprint.p95_runtime_sec,
            "p99_runtime_sec": fingerprint.p99_runtime_sec,
            # Concurrency
            "avg_concurrency": fingerprint.avg_concurrency,
            "peak_concurrency": fingerprint.peak_concurrency,
            # Queue
            "avg_queue_time_sec": fingerprint.avg_queue_time_sec,
            "p95_queue_time_sec": fingerprint.p95_queue_time_sec,
            "queue_rate_pct": fingerprint.queue_rate_pct,
            "has_queue_issues": fingerprint.has_queue_issues,
            # Distributions
            "query_type_distribution": {
                "select_pct": fingerprint.query_type_distribution.select_pct,
                "insert_pct": fingerprint.query_type_distribution.insert_pct,
                "update_pct": fingerprint.query_type_distribution.update_pct,
                "delete_pct": fingerprint.query_type_distribution.delete_pct,
                "merge_pct": fingerprint.query_type_distribution.merge_pct,
                "ddl_pct": fingerprint.query_type_distribution.ddl_pct,
                "other_pct": fingerprint.query_type_distribution.other_pct,
            },
            "time_distribution": {
                "hourly_distribution": list(
                    fingerprint.time_distribution.hourly_distribution
                ),
                "peak_hours": list(fingerprint.time_distribution.peak_hours),
                "quiet_hours": list(fingerprint.time_distribution.quiet_hours),
                "is_business_hours_heavy": fingerprint.time_distribution.is_business_hours_heavy,
            },
            # Pattern
            "workload_pattern": {
                "pattern_type": fingerprint.workload_pattern.pattern_type,
                "confidence": fingerprint.workload_pattern.confidence,
                "description": fingerprint.workload_pattern.description,
                "evidence": list(fingerprint.workload_pattern.evidence),
            },
        }

    @tool_schema(
        description=(
            "Get health score and SLO compliance for a warehouse. Returns overall "
            "score (0-100), risk factors, and recommendations. Use to assess a "
            "specific warehouse's health and get actionable suggestions."
        ),
        properties_override={
            "warehouse_id": {
                "description": "The warehouse ID OR warehouse name. Both formats are accepted - the system will resolve names to IDs automatically."
            },
        },
    )
    async def get_warehouse_health(
        self,
        warehouse_id: str,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """Get health score and SLO compliance for a warehouse.

        Calculates overall health score (0-100), identifies risk factors,
        and generates recommendations. Uses SLO configuration if set.

        Args:
            warehouse_id: Target warehouse ID.
            window_days: Analysis window for metrics. Default: 7.

        Returns:
            Health data including:
            - health_score: Overall score (0-100)
            - health_status: "healthy", "warning", or "critical"
            - health_trend: "improving", "stable", or "degrading"
            - slo_statuses: Compliance status for each SLO target
            - overall_slo_compliance: Aggregate SLO compliance percentage
            - risk_factors: Identified risks with severity and recommendations
            - risk_level: Aggregate risk ("low", "medium", "high", "critical")
            - immediate_actions: Urgent recommended actions
            - optimization_opportunities: Non-urgent improvements

        Example:
            >>> health = await tools.get_warehouse_health("wh-analytics-prod")
            >>> if health["health_status"] == "critical":
            ...     for action in health["immediate_actions"]:
            ...         print(f"ACTION: {action}")
        """
        self._log_obs_context(
            "get_warehouse_health",
            {"warehouse_id": warehouse_id, "window_days": window_days},
        )
        health = await self.service.get_health(
            warehouse_id=warehouse_id,
            window_days=window_days,
        )

        # Convert to dict for LLM consumption
        return {
            "warehouse_id": health.warehouse_id,
            "warehouse_name": health.warehouse_name,
            "health_score": health.health_score,
            "health_status": health.health_status,
            "health_trend": health.health_trend,
            "is_healthy": health.is_healthy,
            "needs_attention": health.needs_attention,
            # SLO
            "slo_statuses": [
                {
                    "slo_type": s.slo_type,
                    "target": s.target,
                    "actual": s.actual,
                    "compliant": s.compliant,
                    "compliance_pct": s.compliance_pct,
                    "trend": s.trend,
                }
                for s in health.slo_statuses
            ],
            "overall_slo_compliance": health.overall_slo_compliance,
            "has_slo_violations": health.has_slo_violations,
            # Risk
            "risk_factors": [
                {
                    "factor_id": r.factor_id,
                    "name": r.name,
                    "description": r.description,
                    "severity": r.severity,
                    "impact_score": r.impact_score,
                    "recommendation": r.recommendation,
                }
                for r in health.risk_factors
            ],
            "risk_level": health.risk_level,
            # Recommendations
            "immediate_actions": list(health.immediate_actions),
            "optimization_opportunities": list(health.optimization_opportunities),
        }

    @tool_schema(
        description=(
            "Configure SLO targets for a warehouse. Use preset profiles "
            "(interactive, batch_etl, critical_bi) or specify custom targets. "
            "SLOs affect health scoring and enable proactive alerting."
        ),
        properties_override={
            "warehouse_id": {
                "description": "The warehouse ID OR warehouse name. Both formats are accepted."
            },
            "slo_profile": {
                "enum": ["interactive", "batch_etl", "critical_bi"],
            },
        },
    )
    async def configure_warehouse_slo(
        self,
        warehouse_id: str,
        slo_profile: str | None = None,
        p95_latency_target_sec: float | None = None,
        availability_target_pct: float | None = None,
        queue_time_target_sec: float | None = None,
    ) -> dict[str, Any]:
        """Configure SLO targets for a warehouse.

        Set service level objectives using a preset profile or custom values.
        SLOs are used for health scoring and alerting.

        Args:
            warehouse_id: Target warehouse.
            slo_profile: Preset profile. Options:
                - "interactive": 15s p95, 99.5% availability, 5s queue (default)
                - "batch_etl": 5min p95, 99% availability
                - "critical_bi": 10s p95, 99.9% availability, 2s queue
            p95_latency_target_sec: Custom p95 latency target (overrides profile).
            availability_target_pct: Custom availability target (e.g., 99.9).
            queue_time_target_sec: Custom queue time target.

        Returns:
            SLO configuration with:
            - warehouse_id: Target warehouse
            - targets: List of SLO targets with thresholds
            - created_at, updated_at: Timestamps

        Example:
            >>> # Use preset profile
            >>> config = await tools.configure_warehouse_slo(
            ...     warehouse_id="wh-bi-prod",
            ...     slo_profile="critical_bi"
            ... )
            >>> # Or customize
            >>> config = await tools.configure_warehouse_slo(
            ...     warehouse_id="wh-bi-prod",
            ...     p95_latency_target_sec=8.0
            ... )
        """
        self._log_obs_context(
            "configure_warehouse_slo",
            {"warehouse_id": warehouse_id, "slo_profile": slo_profile},
        )
        config = await self.service.configure_slo(
            warehouse_id=warehouse_id,
            slo_profile=slo_profile,
            p95_latency_target_sec=p95_latency_target_sec,
            availability_target_pct=availability_target_pct,
            queue_time_target_sec=queue_time_target_sec,
        )

        # Convert to dict for LLM consumption
        return {
            "warehouse_id": config.warehouse_id,
            "targets": [
                {
                    "slo_type": t.slo_type,
                    "target_value": t.target_value,
                    "unit": t.unit,
                    "warning_threshold": t.warning_threshold,
                    "critical_threshold": t.critical_threshold,
                    "enabled": t.enabled,
                }
                for t in config.targets
            ],
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
        }

    @tool_schema(
        description=(
            "Get user activity breakdown for warehouses showing who is using them, "
            "how much, and resource consumption. Essential for understanding usage "
            "patterns and preparing chargeback data."
        ),
        properties_override={
            "warehouse_id": {
                "description": "Specific warehouse ID OR warehouse name (optional, omit for all). Both formats are accepted."
            },
        },
    )
    async def get_warehouse_user_activity(
        self,
        warehouse_id: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """Get user activity breakdown for warehouses.

        Shows who is using the warehouse, how much, and for what.
        Essential for chargeback allocation and understanding usage patterns.

        Args:
            warehouse_id: Specific warehouse (optional, None for all).
            window_days: Analysis window in days. Default: 30.

        Returns:
            User activity data with:
            - users: List of users with query counts, runtime, bytes processed
            - window_days: Analysis window used
            - warehouse_id: Filter applied (if any)

        Example:
            >>> activity = await tools.get_warehouse_user_activity("wh-analytics")
            >>> for user in activity["users"][:5]:
            ...     print(f"{user['user_name']}: {user['total_queries']} queries")
        """
        self._log_obs_context(
            "get_warehouse_user_activity",
            {"warehouse_id": warehouse_id, "window_days": window_days},
        )
        return await self.service.get_user_activity(
            warehouse_id=warehouse_id,
            window_days=window_days,
        )

    @tool_schema(
        description=(
            "Generate cost chargeback report for a specific warehouse. "
            "Automatically fetches actual cost from billing data and allocates it "
            "to users based on their usage share. Returns a detailed table showing "
            "each user's cost allocation. Use this for cost attribution, "
            "accountability reporting, and team chargeback."
        ),
        properties_override={
            "warehouse_id": {
                "description": "The warehouse ID OR warehouse name. Both formats are accepted - the system will resolve names to IDs automatically."
            },
            "allocation_method": {
                "enum": ["runtime", "queries", "bytes"],
            },
        },
    )
    async def generate_warehouse_chargeback(
        self,
        warehouse_id: str,
        total_cost_usd: float | None = None,
        window_days: int = 30,
        allocation_method: str = "runtime",
    ) -> dict[str, Any]:
        """Generate cost chargeback report for a warehouse.

        Fetches actual warehouse cost from billing data and allocates it
        to users based on their usage. Returns a detailed breakdown showing
        each user's share of the total cost.

        Args:
            warehouse_id: Target warehouse ID or name.
            total_cost_usd: Override cost (optional). If not provided,
                automatically fetches actual cost from system.billing.usage.
            window_days: Analysis window in days. Default: 30.
            allocation_method: How to allocate costs:
                - "runtime": Based on query runtime (default, most fair)
                - "queries": Based on query count
                - "bytes": Based on bytes processed

        Returns:
            Chargeback report with:
            - warehouse_id, warehouse_name: Warehouse info
            - period_start, period_end: Billing period
            - total_cost_usd: Total cost (from billing or override)
            - allocations: Per-user cost breakdown with:
                - user_name: User email/ID
                - allocated_cost_usd: Their share of the cost
                - usage_pct: Percentage of total usage
                - total_queries: Number of queries
                - total_runtime_sec: Total runtime in seconds
            - allocation_method: Method used

        Example:
            >>> cb = await tools.generate_warehouse_chargeback(
            ...     warehouse_id="lt-sql-endpoint"  # Name works too!
            ... )
            >>> print(f"Total: ${cb['total_cost_usd']:.2f}")
            >>> for alloc in cb["allocations"][:3]:
            ...     print(f"{alloc['user_name']}: ${alloc['allocated_cost_usd']:.2f} ({alloc['usage_pct']:.1f}%)")
        """
        self._log_obs_context(
            "generate_warehouse_chargeback",
            {"warehouse_id": warehouse_id, "total_cost_usd": total_cost_usd},
        )
        chargeback = await self.service.get_chargeback(
            warehouse_id=warehouse_id,
            total_cost_usd=total_cost_usd,
            window_days=window_days,
            allocation_method=allocation_method,
        )

        return {
            "warehouse_id": chargeback.warehouse_id,
            "warehouse_name": chargeback.warehouse_name,
            "period_start": chargeback.period_start.isoformat(),
            "period_end": chargeback.period_end.isoformat(),
            "total_cost_usd": chargeback.total_cost_usd,
            "allocation_method": chargeback.allocation_method,
            "allocations": [
                {
                    "user_name": a.user_name,
                    "total_queries": a.total_queries,
                    "total_runtime_sec": a.total_runtime_sec,
                    "total_bytes_read": a.total_bytes_read,
                    "usage_share_pct": a.usage_share_pct,
                    "allocated_cost_usd": a.allocated_cost_usd,
                }
                for a in chargeback.allocations
            ],
        }

    @tool_schema(
        description=(
            "Generate chargeback report across all warehouses. Aggregates user costs "
            "portfolio-wide for organization-level cost attribution."
        ),
        properties_override={
            "allocation_method": {
                "enum": ["runtime", "queries", "bytes"],
            },
        },
    )
    async def generate_portfolio_chargeback(
        self,
        window_days: int = 30,
        allocation_method: str = "runtime",
    ) -> dict[str, Any]:
        """Generate chargeback report across all warehouses.

        Aggregates user costs across the entire warehouse portfolio.
        Use for organization-wide cost attribution.

        Args:
            window_days: Analysis window in days. Default: 30.
            allocation_method: How to allocate costs.

        Returns:
            Portfolio chargeback with:
            - period_start, period_end: Billing period
            - total_cost_usd: Total across all warehouses
            - warehouse_count: Number of warehouses included
            - user_summary: Aggregated per-user costs across all warehouses
            - allocation_method: Method used

        Example:
            >>> cb = await tools.generate_portfolio_chargeback(window_days=30)
            >>> print(f"Total: ${cb['total_cost_usd']:.2f}")
            >>> for user in cb["user_summary"][:5]:
            ...     print(f"{user['user_name']}: ${user['allocated_cost_usd']:.2f}")
        """
        self._log_obs_context(
            "generate_portfolio_chargeback",
            {"window_days": window_days, "allocation_method": allocation_method},
        )
        return await self.service.get_portfolio_chargeback(
            window_days=window_days,
            allocation_method=allocation_method,
        )

    @tool_schema(
        description=(
            "Analyze warehouse fleet topology for optimization opportunities. "
            "Detects similar/duplicate warehouses, clusters by workload type, "
            "and identifies consolidation opportunities."
        ),
        properties_override={
            "window_days": {"enum": [7, 30, 90]},
        },
    )
    async def analyze_warehouse_topology(
        self,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """Analyze warehouse fleet topology for optimization opportunities.

        Identifies similar warehouses, workload clusters, and consolidation
        opportunities. Use to find redundancy and optimize the fleet.

        Args:
            window_days: Analysis window in days. Default: 7.

        Returns:
            Topology analysis with:
            - total_warehouses: Number analyzed
            - similar_pairs: Pairs of similar warehouses with scores
            - workload_clusters: Warehouses grouped by workload type
            - insights: Prioritized findings and recommendations
            - consolidation_opportunities: Count of high-similarity pairs
            - estimated_savings_pct: Potential cost reduction

        Example:
            >>> topology = await tools.analyze_warehouse_topology()
            >>> for insight in topology["insights"]:
            ...     if insight["severity"] == "warning":
            ...         print(f"ACTION: {insight['recommendation']}")
        """
        self._log_obs_context(
            "analyze_warehouse_topology", {"window_days": window_days}
        )
        return await self.service.analyze_topology(window_days=window_days)

    # =========================================================================
    # Basic Warehouse Config/Metrics Tools (migrated from ClusterTools)
    # =========================================================================

    @tool_schema(
        description="Get configuration for a SQL warehouse.",
        properties_override={
            "warehouse_id": {"description": "Warehouse ID to fetch configuration for."},
        },
    )
    async def get_warehouse_config(
        self,
        warehouse_id: str,
    ) -> dict[str, Any]:
        """Get configuration for a SQL warehouse.

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            On success: {"found": True, "warehouse_id": "...", "config": {...}}
            On failure: {"found": False, "reason": "..."}

        Example:
            >>> config = await tools.get_warehouse_config("wh-123")
            >>> if config["found"]:
            ...     print(config["config"]["name"])
        """
        self._log_obs_context("get_warehouse_config", {"warehouse_id": warehouse_id})

        if self.provider is None:
            return {
                "found": False,
                "warehouse_id": warehouse_id,
                "reason": "Provider not configured for warehouse config lookups.",
            }

        config = await get_transformed(
            self.provider,
            "warehouse_config",
            warehouse_id,
            transform_fn=transform_warehouse_configuration,
        )

        if config is None:
            logger.debug("Warehouse not found: {warehouse_id}")
            return {
                "found": False,
                "warehouse_id": warehouse_id,
                "reason": f"Warehouse '{warehouse_id}' not found or access denied.",
            }

        return {
            "found": True,
            "warehouse_id": warehouse_id,
            "config": config,
        }

    @tool_schema(
        description="Get query history metrics for a SQL warehouse.",
        properties_override={
            "warehouse_id": {"description": "Warehouse ID to fetch metrics for."},
        },
    )
    async def get_warehouse_metrics(
        self,
        warehouse_id: str,
    ) -> dict[str, Any]:
        """Get query history metrics for a SQL warehouse.

        Args:
            warehouse_id: Warehouse ID to fetch metrics for.

        Returns:
            On success: {"found": True, "warehouse_id": "...", "metrics": {...}}
            On failure: {"found": False, "reason": "..."}

        Example:
            >>> metrics = await tools.get_warehouse_metrics("wh-123")
            >>> if metrics["found"]:
            ...     print(f"Total queries: {metrics['metrics']['total_queries']}")
        """
        self._log_obs_context("get_warehouse_metrics", {"warehouse_id": warehouse_id})

        if self.provider is None:
            return {
                "found": False,
                "warehouse_id": warehouse_id,
                "reason": "Provider not configured for warehouse metrics lookups.",
            }

        metrics = await analyze_warehouse_queries(self.provider, warehouse_id)

        if metrics is None:
            logger.debug("Warehouse metrics unavailable: {warehouse_id}")
            return {
                "found": False,
                "warehouse_id": warehouse_id,
                "reason": f"Warehouse metrics for '{warehouse_id}' unavailable or access denied.",
            }

        return {
            "found": True,
            "warehouse_id": warehouse_id,
            "metrics": metrics,
        }

    @tool_schema(
        description="Get execution statistics for a query statement.",
        properties_override={
            "statement_id": {"description": "Statement ID to fetch metrics for."},
        },
    )
    async def get_query_runtime_metrics(
        self,
        statement_id: str,
    ) -> dict[str, Any]:
        """Get execution statistics for a query statement.

        Args:
            statement_id: Statement ID to fetch metrics for.

        Returns:
            On success: {"found": True, "statement_id": "...", "metrics": {...}}
            On failure: {"found": False, "reason": "..."}

        Example:
            >>> metrics = await tools.get_query_runtime_metrics("stmt-123")
            >>> if metrics["found"]:
            ...     print(metrics["metrics"])
        """
        self._log_obs_context(
            "get_query_runtime_metrics", {"statement_id": statement_id}
        )

        if self.provider is None:
            return {
                "found": False,
                "statement_id": statement_id,
                "reason": "Provider not configured for query metrics lookups.",
            }

        metrics = await get_transformed(
            self.provider,
            "query_history",
            statement_id,
            transform_fn=transform_query_history,
        )

        if metrics is None:
            logger.debug("Query metrics unavailable: {statement_id}")
            return {
                "found": False,
                "statement_id": statement_id,
                "reason": f"Query metrics for statement '{statement_id}' unavailable or not found.",
            }

        return {
            "found": True,
            "statement_id": statement_id,
            "metrics": metrics,
        }
