# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse Portfolio Service.

Orchestrates warehouse portfolio analysis by coordinating:
- Direct SQL execution via AsyncSQLExecutor
- FingerprintCalculator for workload characterization
- HealthScorer for health assessment
- SLO configuration management

This service is the main entry point for warehouse portfolio tools.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from starboard_core.domain.analyzers.warehouse_analyzer import (
    FingerprintCalculator,
    HealthScorer,
)
from starboard_core.domain.models.warehouse import (
    HealthSummary,
    SLOConfig,
    SLOTarget,
    WarehouseFingerprint,
)

from starboard.exceptions import AdapterError
from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.warehouse.chargeback import (
    ChargebackCalculator,
    WarehouseChargeback,
    aggregate_user_chargebacks,
)
from starboard.tools.domain.warehouse.topology import (
    TopologyAnalyzer,
)
from starboard.tools.protocols import WarehousePortfolioDataProvider
from starboard.tools.services.validation import validate_warehouse_id

if TYPE_CHECKING:
    from starboard.adapters.databricks.async_sql_executor import AsyncSQLExecutor
    from starboard.infra.observability.events import EventEmitter

logger = get_logger(__name__)


class SLOConfigStore(Protocol):
    """Protocol for SLO configuration storage."""

    async def get_slo_config(self, warehouse_id: str) -> SLOConfig | None:
        """Get SLO configuration for a warehouse."""
        ...

    async def save_slo_config(self, config: SLOConfig) -> None:
        """Save SLO configuration for a warehouse."""

    async def close(self) -> None:
        """Release resources and close connections."""
        ...

    async def connect(self) -> None:
        """Initialize connection to the backing store."""
        ...

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        ...

    async def get(self, key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        ...

    async def set(self, key: str, value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
        ...

        ...


class WarehousePortfolioService:
    """Service for warehouse portfolio analysis and optimization.

    Orchestrates:
    - Fingerprint generation from query history
    - Health scoring based on fingerprint and SLO config
    - Portfolio-level views and comparisons
    - SLO configuration management

    Example:
        >>> service = WarehousePortfolioService(
        ...     sql_executor=async_sql_executor,
        ...     warehouse_data=databricks_client,
        ...     slo_store=uc_repository,
        ... )
        >>> portfolio = await service.get_portfolio(window_days=7)
        >>> for wh in portfolio.warehouses:
        ...     print(f"{wh.name}: {wh.health_score}")

    Attributes:
        sql_executor: Direct SQL executor for analytics queries.
        warehouse_data: Provider for warehouse configuration.
        slo_store: Storage for SLO configurations.
        events: Event emitter for observability.
    """

    def __init__(
        self,
        sql_executor: AsyncSQLExecutor,
        warehouse_data: WarehousePortfolioDataProvider,
        slo_store: SLOConfigStore | None = None,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize the warehouse portfolio service.

        Args:
            sql_executor: Direct SQL executor for analytics queries.
            warehouse_data: Provider for warehouse data.
            slo_store: Optional SLO configuration storage.
            events: Optional event emitter.
        """
        self._sql_executor = sql_executor
        self._warehouse_data = warehouse_data
        self._slo_store = slo_store
        self._events = events
        # Cache for warehouse name-to-id lookup
        self._warehouse_cache: dict[str, tuple[str, str]] | None = None

    def _calculate_date_range(self, window_days: int) -> tuple[str, str]:
        """Calculate start_date and end_date from window_days.

        Args:
            window_days: Number of days to look back.

        Returns:
            Tuple of (start_date, end_date) in YYYY-MM-DD format.
        """
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=window_days)
        return (str(start_date), str(end_date))

    async def _resolve_warehouse(self, warehouse_id_or_name: str) -> tuple[str, str]:
        """Resolve warehouse identifier to (warehouse_id, warehouse_name).

        Handles both warehouse IDs and names. If the input matches a known
        warehouse ID, returns it directly. Otherwise, searches by name.

        Args:
            warehouse_id_or_name: Warehouse ID or name to resolve.

        Returns:
            Tuple of (warehouse_id, warehouse_name).

        Raises:
            ValueError: If warehouse cannot be found.
        """
        # Try direct lookup by ID first
        config = await self._warehouse_data.get_warehouse(warehouse_id_or_name)
        if config:
            return (
                config.get("id", warehouse_id_or_name),
                config.get("name", warehouse_id_or_name),
            )

        # Not found by ID, try name lookup
        warehouses = await self._warehouse_data.list_warehouses()

        # Build lookup maps
        id_map = {w.get("id", ""): w for w in warehouses}
        name_map = {w.get("name", "").lower(): w for w in warehouses}

        # Check if input is a valid ID
        if warehouse_id_or_name in id_map:
            w = id_map[warehouse_id_or_name]
            return (
                w.get("id", warehouse_id_or_name),
                w.get("name", warehouse_id_or_name),
            )

        # Check if input matches a name (case-insensitive)
        normalized_input = warehouse_id_or_name.lower()
        if normalized_input in name_map:
            w = name_map[normalized_input]
            return (w.get("id", ""), w.get("name", warehouse_id_or_name))

        # Try partial name match
        for name, w in name_map.items():
            if normalized_input in name or name in normalized_input:
                logger.debug(
                    "warehouse_name_partial_match",
                    input=warehouse_id_or_name,
                    matched_name=w.get("name"),
                    matched_id=w.get("id"),
                )
                return (w.get("id", ""), w.get("name", warehouse_id_or_name))

        # Not found - use input as-is (will likely return empty results)
        logger.warning(
            "warehouse_not_found",
            input=warehouse_id_or_name,
            available_warehouses=len(warehouses),
        )
        return (warehouse_id_or_name, warehouse_id_or_name)

    async def get_portfolio(
        self,
        window_days: int = 7,
        include_inactive: bool = False,
        min_queries: int | None = None,
    ) -> dict[str, Any]:
        """Get portfolio view of all warehouses.

        Args:
            window_days: Analysis window in days (7, 30, or 90).
            include_inactive: Include warehouses with no recent activity.
            min_queries: Minimum queries to include warehouse (default: 10).

        Returns:
            Dictionary with portfolio data including warehouses list.
        """
        logger.debug(
            "fetching_warehouse_portfolio",
            window_days=window_days,
            include_inactive=include_inactive,
        )

        # Calculate date range
        start_date, end_date = self._calculate_date_range(window_days)
        min_queries_filter = min_queries or (None if include_inactive else 10)
        limit = 100

        # Build SQL (from warehouse/portfolio.py template)
        sql = f"""
WITH warehouse_metrics AS (
    SELECT
        compute.warehouse_id AS warehouse_id,
        COUNT(*) AS total_queries,
        COUNT(DISTINCT executed_by) AS unique_users,
        AVG(total_duration_ms) AS avg_duration_ms,
        PERCENTILE_APPROX(total_duration_ms, 0.5) AS p50_duration_ms,
        PERCENTILE_APPROX(total_duration_ms, 0.95) AS p95_duration_ms,
        PERCENTILE_APPROX(total_duration_ms, 0.99) AS p99_duration_ms,
        AVG(COALESCE(waiting_at_capacity_duration_ms, 0) + COALESCE(waiting_for_compute_duration_ms, 0)) AS avg_queue_time_ms,
        SUM(CASE WHEN COALESCE(waiting_at_capacity_duration_ms, 0) + COALESCE(waiting_for_compute_duration_ms, 0) > 0 THEN 1 ELSE 0 END) AS queued_queries,
        SUM(COALESCE(read_bytes, 0)) AS total_bytes_read,
        SUM(CASE WHEN execution_status != 'FINISHED' THEN 1 ELSE 0 END) AS error_count
    FROM system.query.history
    WHERE
        start_time >= '{start_date}'
        AND start_time < '{end_date}'
        AND compute.type = 'WAREHOUSE'
    GROUP BY ALL
    {f"HAVING COUNT(*) >= {min_queries_filter}" if min_queries_filter else ""}
)
SELECT
    warehouse_id,
    total_queries,
    unique_users,
    ROUND(avg_duration_ms, 2) AS avg_duration_ms,
    ROUND(p50_duration_ms, 2) AS p50_duration_ms,
    ROUND(p95_duration_ms, 2) AS p95_duration_ms,
    ROUND(p99_duration_ms, 2) AS p99_duration_ms,
    ROUND(avg_queue_time_ms, 2) AS avg_queue_time_ms,
    ROUND(100.0 * queued_queries / total_queries, 2) AS queued_query_pct,
    total_bytes_read,
    error_count,
    ROUND(100.0 * error_count / total_queries, 2) AS error_rate_pct
FROM warehouse_metrics
ORDER BY total_queries DESC
LIMIT {limit}
        """

        # Execute SQL
        df = await self._sql_executor.execute_sql(sql=sql, use_cache=True)
        rows = df.to_dicts()

        # Get warehouse configurations
        warehouses_config = await self._warehouse_data.list_warehouses()
        config_map = {w.get("id", ""): w for w in warehouses_config}

        # Build warehouse summaries
        warehouses: list[dict[str, Any]] = []
        total_queries = 0
        healthy_count = 0
        warning_count = 0
        critical_count = 0

        for row in rows:
            warehouse_id = row.get("warehouse_id", "")
            config = config_map.get(warehouse_id, {})

            # Get SLO config if available
            slo_config = None
            if self._slo_store:
                slo_config = await self._slo_store.get_slo_config(warehouse_id)

            # Calculate health score from metrics
            health_score = self._estimate_health_score(row, slo_config)

            # Determine health status
            if health_score >= 80:
                health_status = "healthy"
                healthy_count += 1
            elif health_score >= 40:
                health_status = "warning"
                warning_count += 1
            else:
                health_status = "critical"
                critical_count += 1

            query_count = int(row.get("total_queries", 0))
            total_queries += query_count

            warehouses.append(
                {
                    "warehouse_id": warehouse_id,
                    "warehouse_name": config.get("name", warehouse_id),
                    "warehouse_type": config.get("warehouse_type", "UNKNOWN"),
                    "state": config.get("state", "UNKNOWN"),
                    "total_queries": query_count,
                    "avg_duration_ms": float(row.get("avg_duration_ms", 0)),
                    "p50_duration_ms": float(row.get("p50_duration_ms", 0)),
                    "p95_duration_ms": float(row.get("p95_duration_ms", 0)),
                    "p99_duration_ms": float(row.get("p99_duration_ms", 0)),
                    "avg_queue_time_ms": float(row.get("avg_queue_time_ms", 0)),
                    "queued_query_pct": float(row.get("queued_query_pct", 0)),
                    "unique_users": int(row.get("unique_users", 0)),
                    "error_rate_pct": float(row.get("error_rate_pct", 0)),
                    "health_score": health_score,
                    "health_status": health_status,
                }
            )

        logger.debug(
            "warehouse_portfolio_fetched",
            warehouse_count=len(warehouses),
            window_days=window_days,
        )

        return {
            "warehouses": warehouses,
            "portfolio_summary": {
                "total_warehouses": len(warehouses),
                "total_queries": total_queries,
                "healthy_count": healthy_count,
                "warning_count": warning_count,
                "critical_count": critical_count,
                "avg_health_score": (
                    sum(w["health_score"] for w in warehouses) / len(warehouses)
                    if warehouses
                    else 0
                ),
            },
            "window_days": window_days,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def get_fingerprint(
        self,
        warehouse_id: str,
        window_days: int = 7,
    ) -> WarehouseFingerprint:
        """Generate fingerprint for a specific warehouse.

        Args:
            warehouse_id: Target warehouse ID or name (will be resolved).
            window_days: Analysis window in days.

        Returns:
            Complete WarehouseFingerprint with workload characterization.
        """
        # Resolve warehouse ID (handles both ID and name lookup)
        resolved_id, warehouse_name = await self._resolve_warehouse(warehouse_id)

        logger.debug(
            "generating_warehouse_fingerprint",
            warehouse_id=resolved_id,
            warehouse_name=warehouse_name,
            original_input=warehouse_id,
            window_days=window_days,
        )

        # Calculate date range
        start_date, end_date = self._calculate_date_range(window_days)
        limit = 10000

        # SECURITY: resolved_id is interpolated into a string-literal filter
        # (compute.warehouse_id = '<id>'). Warehouse ids are not bindable as SQL
        # parameter markers in these system-table queries, so the value is
        # validated to be a plain alphanumeric token (rejects quotes/semicolons/
        # whitespace) before interpolation. start_date/end_date are derived
        # internally from an int window and limit is a literal int.
        safe_warehouse_id = validate_warehouse_id(resolved_id)

        # Build SQL (from warehouse/fingerprint.py template)
        sql = f"""
SELECT
    statement_id,
    compute.warehouse_id AS warehouse_id,
    statement_type,
    total_duration_ms,
    COALESCE(waiting_at_capacity_duration_ms, 0) + COALESCE(waiting_for_compute_duration_ms, 0) AS waiting_in_queue_ms,
    COALESCE(read_bytes, 0) AS read_bytes,
    COALESCE(produced_rows, 0) * 100 AS written_bytes,
    start_time,
    COALESCE(read_rows, 0) AS read_rows,
    executed_by
FROM system.query.history
WHERE compute.warehouse_id = '{safe_warehouse_id}'
  AND compute.type = 'WAREHOUSE'
  AND start_time >= '{start_date}'
  AND start_time < '{end_date}'
ORDER BY start_time DESC
LIMIT {limit}
        """

        # Execute SQL
        df = await self._sql_executor.execute_sql(sql=sql, use_cache=True)
        rows = df.to_dicts()

        # Calculate fingerprint using pure domain logic
        calculator = FingerprintCalculator(
            records=rows,
            warehouse_id=resolved_id,
            warehouse_name=warehouse_name,
            analysis_window_days=window_days,
        )

        fingerprint = calculator.calculate()

        logger.debug(
            "warehouse_fingerprint_generated",
            warehouse_id=resolved_id,
            total_queries=fingerprint.total_queries,
            workload_pattern=fingerprint.workload_pattern.pattern_type,
        )

        return fingerprint

    async def get_health(
        self,
        warehouse_id: str,
        window_days: int = 7,
    ) -> HealthSummary:
        """Get health summary for a warehouse.

        Args:
            warehouse_id: Target warehouse ID.
            window_days: Analysis window in days.

        Returns:
            HealthSummary with scores, risks, and recommendations.
        """
        logger.debug(
            "calculating_warehouse_health",
            warehouse_id=warehouse_id,
            window_days=window_days,
        )

        # Get current fingerprint
        fingerprint = await self.get_fingerprint(warehouse_id, window_days)

        # Get SLO config if available
        slo_config = None
        if self._slo_store:
            slo_config = await self._slo_store.get_slo_config(warehouse_id)

        # Get previous fingerprint for trend comparison (optional)
        # We intentionally catch and ignore errors here - if historical data
        # is unavailable, we simply proceed without trend information
        previous_fingerprint: WarehouseFingerprint | None = None
        try:
            previous_fingerprint = await self.get_fingerprint(
                warehouse_id, window_days * 2
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "previous_fingerprint_unavailable",
                warehouse_id=warehouse_id,
            )

        # Calculate health using pure domain logic
        scorer = HealthScorer(
            fingerprint=fingerprint,
            slo_config=slo_config,
            previous_fingerprint=previous_fingerprint,
        )

        health = scorer.calculate()

        logger.debug(
            "warehouse_health_calculated",
            warehouse_id=warehouse_id,
            health_score=health.health_score,
            health_status=health.health_status,
            risk_count=len(health.risk_factors),
        )

        return health

    async def configure_slo(
        self,
        warehouse_id: str,
        slo_profile: str | None = None,
        p95_latency_target_sec: float | None = None,
        availability_target_pct: float | None = None,
        queue_time_target_sec: float | None = None,
    ) -> SLOConfig:
        """Configure SLO targets for a warehouse.

        Args:
            warehouse_id: Target warehouse.
            slo_profile: Preset profile ("interactive", "batch_etl", "critical_bi").
            p95_latency_target_sec: Custom p95 latency target.
            availability_target_pct: Custom availability target.
            queue_time_target_sec: Custom queue time target.

        Returns:
            Updated SLOConfig.

        Raises:
            ValueError: If slo_store is not configured.
        """
        if not self._slo_store:
            raise ValueError("SLO storage not configured")

        # Get profile defaults
        targets = self._get_profile_targets(slo_profile)

        # Override with custom values if provided
        final_targets: list[SLOTarget] = []
        for target in targets:
            if target.slo_type == "p95_latency" and p95_latency_target_sec is not None:
                target = SLOTarget(
                    slo_type="p95_latency",
                    target_value=p95_latency_target_sec,
                    unit="seconds",
                    warning_threshold=p95_latency_target_sec * 1.5,
                    critical_threshold=p95_latency_target_sec * 2.0,
                )
            elif (
                target.slo_type == "availability"
                and availability_target_pct is not None
            ):
                target = SLOTarget(
                    slo_type="availability",
                    target_value=availability_target_pct,
                    unit="percent",
                    warning_threshold=availability_target_pct - 0.5,
                    critical_threshold=availability_target_pct - 1.5,
                )
            elif target.slo_type == "queue_time" and queue_time_target_sec is not None:
                target = SLOTarget(
                    slo_type="queue_time",
                    target_value=queue_time_target_sec,
                    unit="seconds",
                    warning_threshold=queue_time_target_sec * 2.0,
                    critical_threshold=queue_time_target_sec * 4.0,
                )
            final_targets.append(target)

        config = SLOConfig(
            warehouse_id=warehouse_id,
            targets=tuple(final_targets),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        await self._slo_store.save_slo_config(config)

        logger.debug(
            "slo_config_saved",
            warehouse_id=warehouse_id,
            target_count=len(final_targets),
        )

        return config

    def _get_profile_targets(self, profile: str | None) -> list[SLOTarget]:
        """Get SLO targets for a preset profile.

        Args:
            profile: Profile name or None for defaults.

        Returns:
            List of SLOTarget for the profile.
        """
        profiles = {
            "interactive": [
                SLOTarget(
                    slo_type="p95_latency",
                    target_value=15.0,
                    unit="seconds",
                    warning_threshold=22.5,
                    critical_threshold=30.0,
                ),
                SLOTarget(
                    slo_type="availability",
                    target_value=99.5,
                    unit="percent",
                    warning_threshold=99.0,
                    critical_threshold=98.0,
                ),
                SLOTarget(
                    slo_type="queue_time",
                    target_value=5.0,
                    unit="seconds",
                    warning_threshold=10.0,
                    critical_threshold=20.0,
                ),
            ],
            "batch_etl": [
                SLOTarget(
                    slo_type="p95_latency",
                    target_value=300.0,  # 5 minutes
                    unit="seconds",
                    warning_threshold=600.0,
                    critical_threshold=900.0,
                ),
                SLOTarget(
                    slo_type="availability",
                    target_value=99.0,
                    unit="percent",
                    warning_threshold=98.0,
                    critical_threshold=95.0,
                ),
            ],
            "critical_bi": [
                SLOTarget(
                    slo_type="p95_latency",
                    target_value=10.0,
                    unit="seconds",
                    warning_threshold=15.0,
                    critical_threshold=20.0,
                ),
                SLOTarget(
                    slo_type="availability",
                    target_value=99.9,
                    unit="percent",
                    warning_threshold=99.5,
                    critical_threshold=99.0,
                ),
                SLOTarget(
                    slo_type="queue_time",
                    target_value=2.0,
                    unit="seconds",
                    warning_threshold=5.0,
                    critical_threshold=10.0,
                ),
            ],
        }

        return profiles.get(profile or "interactive", profiles["interactive"])

    def _estimate_health_score(
        self,
        row: dict[str, Any],
        slo_config: SLOConfig | None,
    ) -> int:
        """Estimate health score from portfolio row data.

        Uses the same scoring logic as HealthScorer for consistency:
        - Performance score (p95 latency): 55% weight (or 35% with SLO)
        - Queue score (queue rate + queue time): 45% weight (or 25% with SLO)
        - SLO compliance: 40% weight (when configured)

        Thresholds match HealthScorer defaults:
        - P95 latency: 15s healthy, 30s warning, 60s critical
        - Queue rate: 10% healthy, 25% warning, 50% critical
        - Queue time: 5s healthy, 15s warning, 30s critical

        Args:
            row: Portfolio query result row.
            slo_config: Optional SLO configuration.

        Returns:
            Estimated health score (0-100).
        """
        # Calculate performance score (based on p95 latency)
        p95_sec = float(row.get("p95_duration_ms", 0)) / 1000.0

        if p95_sec <= 15.0:
            performance_score = 100.0
        elif p95_sec <= 30.0:
            ratio = (p95_sec - 15.0) / 15.0
            performance_score = 100.0 - (ratio * 30.0)  # 100 -> 70
        elif p95_sec <= 60.0:
            ratio = (p95_sec - 30.0) / 30.0
            performance_score = 70.0 - (ratio * 40.0)  # 70 -> 30
        else:
            performance_score = max(0.0, 30.0 - ((p95_sec - 60.0) / 10.0) * 10.0)

        # Calculate queue score (based on queue rate + queue time)
        queue_pct = float(row.get("queued_query_pct", 0))
        avg_queue_sec = float(row.get("avg_queue_time_ms", 0)) / 1000.0

        # Queue rate component (60% of queue score)
        if queue_pct <= 10.0:
            rate_score = 100.0
        elif queue_pct <= 25.0:
            ratio = (queue_pct - 10.0) / 15.0
            rate_score = 100.0 - (ratio * 30.0)
        elif queue_pct <= 50.0:
            ratio = (queue_pct - 25.0) / 25.0
            rate_score = 70.0 - (ratio * 40.0)
        else:
            rate_score = max(0.0, 30.0 - ((queue_pct - 50.0) / 20.0) * 20.0)

        # Queue time component (40% of queue score)
        if avg_queue_sec <= 5.0:
            time_score = 100.0
        elif avg_queue_sec <= 15.0:
            ratio = (avg_queue_sec - 5.0) / 10.0
            time_score = 100.0 - (ratio * 30.0)
        elif avg_queue_sec <= 30.0:
            ratio = (avg_queue_sec - 15.0) / 15.0
            time_score = 70.0 - (ratio * 40.0)
        else:
            time_score = max(0.0, 30.0 - ((avg_queue_sec - 30.0) / 15.0) * 15.0)

        queue_score = rate_score * 0.6 + time_score * 0.4

        # Calculate SLO compliance if configured
        slo_score = 100.0
        if slo_config and slo_config.enabled_targets:
            violations = 0
            total_targets = len(slo_config.enabled_targets)
            for target in slo_config.enabled_targets:
                if target.slo_type == "p95_latency":
                    if p95_sec > target.target_value:
                        violations += 1
                elif (target.slo_type == "queue_time") and (
                    avg_queue_sec > target.target_value
                ):
                    violations += 1
            if total_targets > 0:
                slo_score = ((total_targets - violations) / total_targets) * 100.0

        # Weighted combination (matches HealthScorer logic)
        if slo_config and slo_config.enabled_targets:
            # With SLO: 35% performance + 25% queue + 40% SLO
            overall = performance_score * 0.35 + queue_score * 0.25 + slo_score * 0.40
        else:
            # Without SLO: 55% performance + 45% queue
            overall = performance_score * 0.55 + queue_score * 0.45

        return max(0, min(100, int(round(overall))))

    async def get_user_activity(
        self,
        warehouse_id: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """Get user activity for warehouses.

        Args:
            warehouse_id: Optional specific warehouse ID or name. None for all.
            window_days: Analysis window in days.

        Returns:
            User activity data with query counts and runtime.
        """
        # Resolve warehouse ID if provided (handles both ID and name)
        resolved_id: str | None = None
        if warehouse_id:
            resolved_id, _ = await self._resolve_warehouse(warehouse_id)

        logger.debug(
            "fetching_user_activity",
            warehouse_id=resolved_id,
            original_input=warehouse_id,
            window_days=window_days,
        )

        # Calculate date range
        start_date, end_date = self._calculate_date_range(window_days)
        limit = 500
        min_queries = 1

        # Build SQL (from warehouse/user_activity.py template)
        # SECURITY: resolved_id is interpolated into a string-literal filter and
        # cannot be bound as a SQL parameter marker here, so validate it as a
        # plain alphanumeric warehouse id (rejects quotes/semicolons/whitespace)
        # before interpolation. start_date/end_date are derived internally and
        # min_queries/limit are literal ints.
        warehouse_filter = (
            f"AND compute.warehouse_id = '{validate_warehouse_id(resolved_id)}'"
            if resolved_id
            else ""
        )
        sql = f"""
WITH user_activity AS (
    SELECT
        compute.warehouse_id AS warehouse_id,
        executed_by AS user_name,
        COUNT(*) AS total_queries,
        SUM(total_duration_ms) / 1000.0 AS total_runtime_sec,
        SUM(COALESCE(read_bytes, 0)) AS total_bytes_read,
        SUM(COALESCE(produced_rows, 0) * 100) AS total_bytes_written,
        AVG(total_duration_ms) / 1000.0 AS avg_runtime_sec
    FROM system.query.history
    WHERE
        start_time >= '{start_date}'
        AND start_time < '{end_date}'
        AND compute.type = 'WAREHOUSE'
        AND executed_by IS NOT NULL
        {warehouse_filter}
    GROUP BY ALL
),
warehouse_totals AS (
    SELECT
        warehouse_id,
        SUM(total_runtime_sec) AS warehouse_total_runtime
    FROM user_activity
    GROUP BY warehouse_id
)
SELECT
    ua.warehouse_id,
    ua.user_name,
    ua.total_queries,
    ROUND(ua.total_runtime_sec, 2) AS total_runtime_sec,
    ua.total_bytes_read,
    ua.total_bytes_written,
    ROUND(ua.avg_runtime_sec, 3) AS avg_runtime_sec,
    ROUND(ua.total_runtime_sec / NULLIF(wt.warehouse_total_runtime, 0) * 100, 2) AS usage_share_pct
FROM user_activity ua
JOIN warehouse_totals wt ON ua.warehouse_id = wt.warehouse_id
WHERE ua.total_queries >= {min_queries}
ORDER BY ua.total_runtime_sec DESC
LIMIT {limit}
        """

        # Execute SQL
        df = await self._sql_executor.execute_sql(sql=sql, use_cache=True)
        rows = df.to_dicts()

        logger.debug(
            "user_activity_fetched",
            user_count=len(rows),
            window_days=window_days,
        )

        return {
            "users": rows,
            "window_days": window_days,
            "warehouse_id": warehouse_id,
        }

    async def _fetch_warehouse_cost(
        self,
        warehouse_id: str,
        window_days: int,
    ) -> float:
        """Fetch actual warehouse cost from billing system table.

        Args:
            warehouse_id: Warehouse ID (must be resolved ID, not name).
            window_days: Number of days to look back.

        Returns:
            Total cost in USD for the period. Returns 0.0 if no billing data.
        """
        start_date, end_date = self._calculate_date_range(window_days)

        logger.debug(
            "fetching_warehouse_cost_from_billing",
            warehouse_id=warehouse_id,
            start_date=start_date,
            end_date=end_date,
        )

        # SECURITY: warehouse_id is interpolated into a string-literal filter
        # below and cannot be bound as a SQL parameter marker here. Validate it
        # as a plain alphanumeric warehouse id (rejects quotes/semicolons/
        # whitespace) before interpolation; start_date/end_date are derived
        # internally from an int window.
        safe_warehouse_id = validate_warehouse_id(warehouse_id)

        try:
            # Build SQL (from warehouse/cost.py template)
            sql = f"""
SELECT
  u.workspace_id,
  u.usage_metadata.warehouse_id,
  SUM(u.usage_quantity) AS total_dbu,
  SUM(u.usage_quantity * lp.pricing.default) AS total_cost_usd,
  COUNT(DISTINCT u.usage_date) AS usage_days
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices lp
  ON u.sku_name = lp.sku_name
  AND u.cloud = lp.cloud
  AND u.usage_date >= lp.price_start_time
  AND (u.usage_date < lp.price_end_time OR lp.price_end_time IS NULL)
WHERE u.usage_date >= '{start_date}'
  AND u.usage_date < '{end_date}'
  AND u.sku_name LIKE '%SQL%'
  AND u.usage_metadata.warehouse_id IS NOT NULL
  AND u.usage_metadata.warehouse_id = '{safe_warehouse_id}'
GROUP BY u.workspace_id, u.usage_metadata.warehouse_id
ORDER BY total_cost_usd DESC
LIMIT 1
            """

            df = await self._sql_executor.execute_sql(sql=sql, use_cache=True)
            rows = df.to_dicts()

            if rows:
                cost = rows[0].get("total_cost_usd", 0.0)
                logger.debug(
                    "warehouse_cost_fetched",
                    warehouse_id=warehouse_id,
                    total_cost_usd=cost,
                    window_days=window_days,
                )
                return float(cost) if cost else 0.0

            logger.warning(
                "no_billing_data_for_warehouse",
                warehouse_id=warehouse_id,
                window_days=window_days,
            )
            return 0.0

        except (AdapterError, ValueError) as e:
            logger.warning(
                "failed_to_fetch_warehouse_cost",
                warehouse_id=warehouse_id,
                error=str(e),
            )
            return 0.0

    async def get_chargeback(
        self,
        warehouse_id: str,
        total_cost_usd: float | None = None,
        window_days: int = 30,
        allocation_method: str = "runtime",
    ) -> WarehouseChargeback:
        """Generate chargeback report for a warehouse.

        Args:
            warehouse_id: Target warehouse ID or name.
            total_cost_usd: Total cost to allocate. If None, fetches actual
                cost from billing.usage system table.
            window_days: Analysis window in days.
            allocation_method: How to allocate ("runtime", "queries", "bytes").

        Returns:
            WarehouseChargeback with per-user cost allocations.
        """
        # Resolve warehouse ID (handles both ID and name lookup)
        resolved_id, warehouse_name = await self._resolve_warehouse(warehouse_id)

        # If total_cost_usd not provided, fetch from billing
        if total_cost_usd is None:
            total_cost_usd = await self._fetch_warehouse_cost(resolved_id, window_days)

        logger.debug(
            "calculating_warehouse_chargeback",
            warehouse_id=resolved_id,
            warehouse_name=warehouse_name,
            original_input=warehouse_id,
            total_cost_usd=total_cost_usd,
            allocation_method=allocation_method,
            cost_source="billing" if total_cost_usd else "provided",
        )

        # Get user activity using resolved ID
        activity_result = await self.get_user_activity(
            warehouse_id=resolved_id,
            window_days=window_days,
        )

        # Calculate chargeback
        now = datetime.now(UTC)
        calculator = ChargebackCalculator(
            warehouse_id=resolved_id,
            warehouse_name=warehouse_name,
            total_cost_usd=total_cost_usd,
            period_start=now - timedelta(days=window_days),
            period_end=now,
            allocation_method=allocation_method,
        )

        chargeback = calculator.calculate(activity_result["users"])

        logger.debug(
            "warehouse_chargeback_calculated",
            warehouse_id=resolved_id,
            warehouse_name=warehouse_name,
            user_count=len(chargeback.allocations),
            total_cost_usd=total_cost_usd,
        )

        return chargeback

    async def get_portfolio_chargeback(
        self,
        window_days: int = 30,
        allocation_method: str = "runtime",
    ) -> dict[str, Any]:
        """Generate chargeback report for all warehouses.

        Args:
            window_days: Analysis window in days.
            allocation_method: How to allocate costs.

        Returns:
            Portfolio-level chargeback with aggregated user costs.
        """
        logger.debug(
            "calculating_portfolio_chargeback",
            window_days=window_days,
            allocation_method=allocation_method,
        )

        # Get portfolio for warehouse list and costs
        portfolio = await self.get_portfolio(window_days=window_days)
        warehouses = portfolio["warehouses"]

        # Get chargeback for each warehouse
        # Note: In production, we'd get actual costs from billing
        # Here we estimate from query volume
        chargebacks: list[WarehouseChargeback] = []
        for wh in warehouses:
            # Estimate cost based on query volume (placeholder)
            # Real implementation would use billing.usage data
            estimated_cost = wh.get("total_queries", 0) * 0.01  # $0.01/query estimate

            if estimated_cost > 0:
                cb = await self.get_chargeback(
                    warehouse_id=wh["warehouse_id"],
                    total_cost_usd=estimated_cost,
                    window_days=window_days,
                    allocation_method=allocation_method,
                )
                chargebacks.append(cb)

        # Aggregate across warehouses
        user_summary = aggregate_user_chargebacks(chargebacks)

        total_cost = sum(cb.total_cost_usd for cb in chargebacks)

        logger.debug(
            "portfolio_chargeback_calculated",
            warehouse_count=len(chargebacks),
            user_count=len(user_summary),
            total_cost_usd=total_cost,
        )

        return {
            "period_start": (
                datetime.now(UTC) - timedelta(days=window_days)
            ).isoformat(),
            "period_end": datetime.now(UTC).isoformat(),
            "total_cost_usd": round(total_cost, 2),
            "warehouse_count": len(chargebacks),
            "user_summary": [
                {
                    "user_name": u.user_name,
                    "total_queries": u.total_queries,
                    "total_runtime_sec": u.total_runtime_sec,
                    "allocated_cost_usd": u.allocated_cost_usd,
                    "usage_share_pct": u.usage_share_pct,
                }
                for u in user_summary
            ],
            "allocation_method": allocation_method,
        }

    async def analyze_topology(
        self,
        window_days: int = 7,
    ) -> dict[str, Any]:
        """Analyze warehouse fleet topology for optimization opportunities.

        Uses portfolio data for efficient analysis without individual queries.
        Identifies:
        - Similar/duplicate warehouses (by performance profile)
        - Workload clusters (by latency characteristics)
        - Consolidation opportunities
        - Underutilized warehouses

        Args:
            window_days: Analysis window in days.

        Returns:
            Topology analysis with insights and recommendations.
        """
        logger.debug(
            "analyzing_warehouse_topology",
            window_days=window_days,
        )

        # Get portfolio data (single query, already has all metrics we need)
        portfolio = await self.get_portfolio(window_days=window_days)
        warehouses = portfolio["warehouses"]

        # Build simplified fingerprints from portfolio data
        # This avoids 60+ individual SQL queries
        fingerprints: list[dict[str, Any]] = []
        for wh in warehouses:
            warehouse_id = wh.get("warehouse_id", "")
            if not warehouse_id:
                continue

            # Estimate workload pattern from portfolio metrics
            p95_sec = wh.get("p95_duration_ms", 0) / 1000.0
            avg_sec = wh.get("avg_duration_ms", 0) / 1000.0
            total_queries = wh.get("total_queries", 0)
            queries_per_day = total_queries / max(window_days, 1)

            # Classify workload based on latency profile
            if p95_sec <= 10.0 and queries_per_day > 100:
                pattern_type = "interactive"
            elif p95_sec > 60.0 or avg_sec > 30.0:
                pattern_type = "batch"
            elif queries_per_day < 50:
                pattern_type = "ad_hoc"
            else:
                pattern_type = "reporting"

            fp_dict = {
                "warehouse_id": warehouse_id,
                "warehouse_name": wh.get("warehouse_name", warehouse_id),
                "workload_pattern": {
                    "pattern_type": pattern_type,
                    "confidence": 0.7,  # Lower confidence since derived from portfolio
                },
                "p95_runtime_sec": p95_sec,
                "total_queries": total_queries,
                "queries_per_day": queries_per_day,
                # Simplified distributions (not available from portfolio)
                "query_type_distribution": {
                    "select_pct": 80.0,  # Default assumption
                    "insert_pct": 10.0,
                    "update_pct": 5.0,
                    "delete_pct": 5.0,
                },
                "time_distribution": {
                    "peak_hours": [9, 10, 11, 14, 15, 16],  # Default business hours
                },
                # Include health metrics for richer analysis
                "health_score": wh.get("health_score", 50),
                "health_status": wh.get("health_status", "unknown"),
                "queue_pct": wh.get("queued_query_pct", 0),
                "error_pct": wh.get("error_rate_pct", 0),
            }
            fingerprints.append(fp_dict)

        # Run topology analysis
        analyzer = TopologyAnalyzer()
        analysis = analyzer.analyze(fingerprints)

        logger.debug(
            "topology_analysis_complete",
            warehouses_analyzed=analysis.total_warehouses,
            similar_pairs=len(analysis.similar_pairs),
            insights=len(analysis.insights),
        )

        return {
            "total_warehouses": analysis.total_warehouses,
            "similar_pairs": [
                {
                    "warehouse_id_a": p.warehouse_id_a,
                    "warehouse_id_b": p.warehouse_id_b,
                    "warehouse_name_a": p.warehouse_name_a,
                    "warehouse_name_b": p.warehouse_name_b,
                    "similarity_score": p.similarity_score,
                    "workload_similarity": p.workload_similarity,
                    "user_overlap_pct": p.user_overlap_pct,
                    "time_overlap_pct": p.time_overlap_pct,
                    "consolidation_potential": p.consolidation_potential,
                    "recommendation": p.recommendation,
                }
                for p in analysis.similar_pairs
            ],
            "workload_clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "cluster_type": c.cluster_type,
                    "warehouse_ids": list(c.warehouse_ids),
                    "warehouse_names": list(c.warehouse_names),
                    "avg_p95_latency_sec": c.avg_p95_latency_sec,
                    "total_queries": c.total_queries,
                    "consolidation_candidate": c.consolidation_candidate,
                }
                for c in analysis.workload_clusters
            ],
            "insights": [
                {
                    "insight_type": i.insight_type,
                    "severity": i.severity,
                    "title": i.title,
                    "description": i.description,
                    "affected_warehouses": list(i.affected_warehouses),
                    "recommendation": i.recommendation,
                    "estimated_impact": i.estimated_impact,
                }
                for i in analysis.insights
            ],
            "consolidation_opportunities": analysis.consolidation_opportunities,
            "estimated_savings_pct": analysis.estimated_savings_pct,
        }
