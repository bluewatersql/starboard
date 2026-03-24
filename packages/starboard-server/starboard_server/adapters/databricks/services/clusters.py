"""Async Cluster service implementation.

This module provides async cluster operations for Databricks compute clusters.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from databricks.sdk.errors import NotFound

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class ClusterService(BaseService):
    """Async service for Databricks cluster operations.

    Provides async methods for:
    - Getting cluster configuration
    - Listing clusters
    - Getting cluster state and events
    - Starting/stopping clusters
    - Creating clusters

    Example:
        >>> service = ClusterService(workspace_client)
        >>> cluster = await service.get_cluster("cluster-abc-123")
        >>> state = await service.get_cluster_state("cluster-abc-123")
    """

    def __init__(
        self,
        client: WorkspaceClient,
        default_cluster_config: Any = None,
    ) -> None:
        """Initialize cluster service.

        Args:
            client: Authenticated Databricks WorkspaceClient
            default_cluster_config: Optional default cluster configuration dataclass
        """
        super().__init__(client)
        self._default_cluster_config = default_cluster_config

    async def get_cluster(self, cluster_id: str) -> dict[str, Any] | None:
        """Get cluster configuration by ID.

        Args:
            cluster_id: Databricks cluster ID

        Returns:
            Cluster configuration dictionary, or None if not found

        Raises:
            DatabricksAPIError: If API call fails (other than NotFound)

        Example:
            >>> cluster = await service.get_cluster("cluster-abc-123")
            >>> if cluster:
            ...     print(f"Cluster: {cluster['cluster_name']}")
        """
        logger.debug("get_cluster", extra={"cluster_id": cluster_id})

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.clusters.get(cluster_id).as_dict()
            except NotFound:
                logger.warning("cluster_not_found", extra={"cluster_id": cluster_id})
                return None

        try:
            return await self._run_sync(_get)
        except NotFound:
            return None
        except Exception as e:
            logger.error(
                "get_cluster_failed",
                extra={"cluster_id": cluster_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get cluster {cluster_id}",
                details={"cluster_id": cluster_id, "error": str(e)},
            ) from e

    async def list_clusters(self) -> list[dict[str, Any]]:
        """List all clusters in the workspace.

        Returns:
            List of cluster configuration dictionaries

        Example:
            >>> clusters = await service.list_clusters()
            >>> for cluster in clusters:
            ...     print(f"{cluster['cluster_id']}: {cluster['cluster_name']}")
        """
        logger.debug("list_clusters")

        def _list() -> list[dict[str, Any]]:
            return [cluster.as_dict() for cluster in self._client.clusters.list()]

        return await self._run_sync(_list)

    async def get_cluster_state(self, cluster_id: str) -> str | None:
        """Get the current state of a cluster.

        Args:
            cluster_id: Databricks cluster ID

        Returns:
            Cluster state string (e.g., "RUNNING", "TERMINATED"), or None if not found

        Raises:
            DatabricksAPIError: If API call fails (other than NotFound)

        Example:
            >>> state = await service.get_cluster_state("cluster-abc-123")
            >>> if state == "RUNNING":
            ...     print("Cluster is running")
        """
        logger.debug("get_cluster_state", extra={"cluster_id": cluster_id})

        def _get_state() -> str | None:
            try:
                return str(self._client.clusters.get(cluster_id).state)
            except NotFound:
                return None

        try:
            return await self._run_sync(_get_state)
        except NotFound:
            return None
        except Exception as e:
            logger.error(
                "get_cluster_state_failed",
                extra={"cluster_id": cluster_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get cluster state for {cluster_id}",
                details={"cluster_id": cluster_id, "error": str(e)},
            ) from e

    async def get_cluster_events(self, cluster_id: str) -> list[dict[str, Any]]:
        """Get cluster events.

        Args:
            cluster_id: Databricks cluster ID

        Returns:
            List of cluster event dictionaries

        Raises:
            DatabricksAPIError: If API call fails

        Example:
            >>> events = await service.get_cluster_events("cluster-abc-123")
            >>> for event in events:
            ...     print(f"{event['type']}: {event['timestamp']}")
        """
        logger.debug("get_cluster_events", extra={"cluster_id": cluster_id})

        def _get_events() -> list[dict[str, Any]]:
            events = []
            for event in self._client.clusters.events(cluster_id):
                events.append(event.as_dict())
            return events

        try:
            return await self._run_sync(_get_events)
        except Exception as e:
            logger.error(
                "get_cluster_events_failed",
                extra={"cluster_id": cluster_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get cluster events for {cluster_id}",
                details={"cluster_id": cluster_id, "error": str(e)},
            ) from e

    async def start_cluster(self, cluster_id: str) -> None:
        """Start a cluster and wait for it to be running.

        Args:
            cluster_id: Databricks cluster ID

        Raises:
            TimeoutError: If cluster doesn't start within timeout
            DatabricksAPIError: If start fails

        Example:
            >>> await service.start_cluster("cluster-abc-123")
            >>> print("Cluster started")
        """
        logger.debug("start_cluster", extra={"cluster_id": cluster_id})

        def _start() -> None:
            waiter = self._client.clusters.wait_get_cluster_running(cluster_id)
            if hasattr(waiter, "result"):
                waiter.result(timeout=datetime.timedelta(minutes=5))

        await self._run_sync(_start)

    async def stop_cluster(self, cluster_id: str) -> None:
        """Stop (delete/terminate) a cluster.

        Args:
            cluster_id: Databricks cluster ID

        Example:
            >>> await service.stop_cluster("cluster-abc-123")
            >>> print("Cluster stopped")
        """
        logger.debug("stop_cluster", extra={"cluster_id": cluster_id})
        await self._run_sync(lambda: self._client.clusters.delete(cluster_id))

    async def create_cluster(self, cluster_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new cluster.

        Args:
            cluster_spec: Cluster configuration dictionary

        Returns:
            Created cluster info with cluster_id

        Example:
            >>> cluster = await service.create_cluster({
            ...     "cluster_name": "My Cluster",
            ...     "spark_version": "13.3.x-scala2.12",
            ...     "num_workers": 2,
            ... })
            >>> print(f"Created: {cluster['cluster_id']}")
        """
        logger.debug(
            "create_cluster", extra={"cluster_name": cluster_spec.get("cluster_name")}
        )

        def _create() -> dict[str, Any]:
            waiter = self._client.clusters.create(**cluster_spec)
            if hasattr(waiter, "result"):
                cluster = waiter.result()
                if hasattr(cluster, "as_dict"):
                    return dict(cluster.as_dict())
                return {"cluster_id": getattr(cluster, "cluster_id", None)}
            return {"cluster_id": getattr(waiter, "cluster_id", None)}

        return await self._run_sync(_create)

    async def create_default_cluster(self) -> dict[str, Any]:
        """Create a cluster with default configuration.

        Requires default_cluster_config to be set in constructor.

        Returns:
            Created cluster info

        Raises:
            ValueError: If default_cluster_config not configured
        """
        if self._default_cluster_config is None:
            raise ValueError("default_cluster_config not configured")

        def _create() -> dict[str, Any]:
            cluster_spec = self._default_cluster_config()
            cluster_spec.spark_version = self._client.clusters.select_spark_version(
                latest=True
            )
            cluster_spec.single_user_name = self._client.current_user.me().user_name
            return asdict(cluster_spec)

        spec = await self._run_sync(_create)
        return await self.create_cluster(spec)
