"""Cluster analysis service.

Orchestrates cluster data gathering and analysis operations.
Follows WarehousePortfolioService pattern for consistency.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.cluster import (
    ClusterFingerprint,
    ClusterHealthReport,
    FingerprintScope,
)

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.cluster import (
    analyze_cluster_health,
    build_cluster_fingerprint,
)
from starboard_server.tools.exceptions import ClusterNotFoundError

if TYPE_CHECKING:
    from starboard_server.infra.observability.events import EventEmitter
    from starboard_server.services.context.provider import SharedContextProvider

logger = get_logger(__name__)


class ClusterService:
    """Service for cluster analysis operations.

    Orchestrates data gathering and analysis for cluster optimization.
    Uses SharedContextProvider for data access (like other services).

    Example:
        >>> service = ClusterService(provider)
        >>> fingerprint = await service.get_fingerprint("cluster-123")
        >>> health = await service.get_health("cluster-123")
    """

    # Concurrency limit for parallel operations (prevents API throttling)
    MAX_CONCURRENT_OPERATIONS = 10

    def __init__(
        self,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize cluster service.

        Args:
            provider: SharedContextProvider for data access.
            events: Optional event emitter for observability.
        """
        self.provider = provider
        self.events = events
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_OPERATIONS)

    async def get_cluster_config(self, cluster_id: str) -> dict[str, Any]:
        """Get cluster configuration.

        Args:
            cluster_id: Databricks cluster ID.

        Returns:
            Cluster configuration dictionary.

        Raises:
            ClusterNotFoundError: If cluster doesn't exist.
        """
        logger.debug("get_cluster_config", cluster_id=cluster_id)

        config = await self.provider.get("cluster_config", cluster_id)

        if not config:
            raise ClusterNotFoundError(cluster_id)

        return config

    async def get_fingerprint(
        self,
        cluster_id: str,
        scope: FingerprintScope = FingerprintScope.CONFIG_ONLY,
    ) -> ClusterFingerprint:
        """Build comprehensive cluster fingerprint.

        Gathers configuration, events, and metrics to create
        a normalized snapshot of the cluster.

        Args:
            cluster_id: Databricks cluster ID.
            scope: Controls what data to fetch. Use CONFIG_ONLY for fast
                   responses, FULL for comprehensive analysis.

        Returns:
            ClusterFingerprint with normalized data.

        Raises:
            ClusterNotFoundError: If cluster doesn't exist.

        Example:
            >>> # Fast fingerprint (config only)
            >>> fp = await service.get_fingerprint("cluster-123")
            >>>
            >>> # Full fingerprint with metrics and cost
            >>> fp = await service.get_fingerprint(
            ...     "cluster-123",
            ...     scope=FingerprintScope.FULL
            ... )
        """
        logger.debug(
            "get_fingerprint",
            cluster_id=cluster_id,
            scope=scope.value,
        )

        # Fetch configuration (required)
        config = await self.provider.get("cluster_config", cluster_id)

        if not config:
            raise ClusterNotFoundError(cluster_id)

        # Fetch optional data based on scope
        metrics = None
        cost_data = None

        if scope in (FingerprintScope.WITH_METRICS, FingerprintScope.FULL):
            metrics = await self._fetch_metrics(cluster_id)

        if scope in (FingerprintScope.WITH_COST, FingerprintScope.FULL):
            cost_data = await self._fetch_cost_data(cluster_id)

        # Build fingerprint using pure domain logic
        return build_cluster_fingerprint(
            config=config,
            metrics=metrics,
            cost_data=cost_data,
        )

    async def get_health(
        self,
        cluster_id: str,
        scope: FingerprintScope = FingerprintScope.WITH_METRICS,
    ) -> ClusterHealthReport:
        """Analyze cluster health.

        Builds fingerprint and analyzes health across dimensions:
        performance, cost, reliability, security.

        Args:
            cluster_id: Databricks cluster ID.
            scope: Controls fingerprint data depth.

        Returns:
            ClusterHealthReport with scores and risks.

        Raises:
            ClusterNotFoundError: If cluster doesn't exist.
        """
        logger.debug(
            "get_health",
            cluster_id=cluster_id,
            scope=scope.value,
        )

        fingerprint = await self.get_fingerprint(cluster_id, scope=scope)
        return analyze_cluster_health(fingerprint)

    async def analyze_fleet(
        self,
        cluster_ids: list[str] | None = None,
        scope: FingerprintScope = FingerprintScope.CONFIG_ONLY,
    ) -> list[ClusterHealthReport]:
        """Analyze health of multiple clusters.

        Uses semaphore-bounded concurrency to prevent API throttling.

        Args:
            cluster_ids: Optional list of cluster IDs. If None, analyzes
                         all clusters.
            scope: Controls fingerprint data depth.

        Returns:
            List of ClusterHealthReport for each cluster.
        """
        if cluster_ids is None:
            # Fetch all cluster IDs
            clusters = await self.provider.get("cluster_list", "all")
            if clusters:
                cluster_ids = [
                    c.get("cluster_id") for c in clusters if c.get("cluster_id")
                ]
            else:
                cluster_ids = []

        logger.info(
            "analyze_fleet",
            cluster_count=len(cluster_ids),
            scope=scope.value,
        )

        # Use semaphore to bound concurrency
        async def analyze_with_limit(cid: str) -> ClusterHealthReport | None:
            async with self._semaphore:
                try:
                    return await self.get_health(cid, scope=scope)
                except ClusterNotFoundError:
                    logger.warning("cluster_not_found_in_fleet", cluster_id=cid)
                    return None
                except Exception as e:
                    logger.error(
                        "cluster_analysis_failed",
                        cluster_id=cid,
                        error=str(e),
                    )
                    return None

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(analyze_with_limit(cid)) for cid in cluster_ids]
        results = [t.result() for t in tasks]

        # Filter out None results
        return [r for r in results if r is not None]

    async def _fetch_metrics(self, cluster_id: str) -> dict[str, Any] | None:
        """Fetch performance metrics for a cluster.

        Args:
            cluster_id: Databricks cluster ID.

        Returns:
            Metrics dictionary or None if unavailable.
        """
        try:
            return await self.provider.get("cluster_metrics", cluster_id)
        except Exception as e:
            logger.debug(
                "metrics_fetch_failed",
                cluster_id=cluster_id,
                error=str(e),
            )
            return None

    async def _fetch_cost_data(self, cluster_id: str) -> dict[str, Any] | None:
        """Fetch cost data for a cluster.

        Args:
            cluster_id: Databricks cluster ID.

        Returns:
            Cost data dictionary or None if unavailable.
        """
        try:
            return await self.provider.get("cluster_cost", cluster_id)
        except Exception as e:
            logger.debug(
                "cost_fetch_failed",
                cluster_id=cluster_id,
                error=str(e),
            )
            return None
