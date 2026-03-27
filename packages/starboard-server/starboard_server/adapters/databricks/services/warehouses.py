"""Async Warehouse service implementation.

This module provides async SQL warehouse operations for Databricks.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from databricks.sdk.errors import NotFound

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.exceptions import AdapterError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)


class WarehouseService(BaseService):
    """Async service for Databricks SQL warehouse operations.

    Provides async methods for:
    - Getting warehouse configuration
    - Listing warehouses
    - Getting warehouse state
    - Starting warehouses

    Example:
        >>> service = WarehouseService(workspace_client)
        >>> warehouse = await service.get_warehouse("warehouse-xyz")
        >>> state = await service.get_warehouse_state("warehouse-xyz")
    """

    def __init__(self, client: WorkspaceClient) -> None:
        """Initialize warehouse service.

        Args:
            client: Authenticated Databricks WorkspaceClient
        """
        super().__init__(client)

    async def get_warehouse(self, warehouse_id: str) -> dict[str, Any] | None:
        """Get warehouse configuration by ID.

        Args:
            warehouse_id: Databricks SQL warehouse ID

        Returns:
            Warehouse configuration dictionary, or None if not found

        Raises:
            DatabricksAPIError: If API call fails (other than NotFound)

        Example:
            >>> warehouse = await service.get_warehouse("warehouse-xyz")
            >>> if warehouse:
            ...     print(f"Warehouse: {warehouse['name']}")
        """
        logger.debug("get_warehouse", extra={"warehouse_id": warehouse_id})

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.warehouses.get(warehouse_id).as_dict()
            except NotFound:
                logger.warning(
                    "warehouse_not_found",
                    extra={"warehouse_id": warehouse_id},
                )
                return None

        try:
            return await self._run_sync(_get)
        except NotFound:
            return None
        except (DatabricksAPIError, AdapterError, OSError) as e:
            logger.error(
                "get_warehouse_failed",
                extra={"warehouse_id": warehouse_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get warehouse {warehouse_id}",
                details={"warehouse_id": warehouse_id, "error": str(e)},
            ) from e

    async def list_warehouses(self) -> list[dict[str, Any]]:
        """List all SQL warehouses in the workspace.

        Returns:
            List of warehouse configuration dictionaries

        Example:
            >>> warehouses = await service.list_warehouses()
            >>> for wh in warehouses:
            ...     print(f"{wh['id']}: {wh['name']} ({wh['state']})")
        """
        logger.debug("list_warehouses")

        def _list() -> list[dict[str, Any]]:
            return [wh.as_dict() for wh in self._client.warehouses.list()]

        return await self._run_sync(_list)

    async def get_warehouse_state(self, warehouse_id: str) -> str | None:
        """Get the current state of a warehouse.

        Args:
            warehouse_id: Databricks SQL warehouse ID

        Returns:
            Warehouse state string (e.g., "RUNNING", "STOPPED"), or None if not found

        Raises:
            DatabricksAPIError: If API call fails (other than NotFound)

        Example:
            >>> state = await service.get_warehouse_state("warehouse-xyz")
            >>> if state == "RUNNING":
            ...     print("Warehouse is ready")
        """
        logger.debug("get_warehouse_state", extra={"warehouse_id": warehouse_id})

        def _get_state() -> str | None:
            try:
                return str(self._client.warehouses.get(warehouse_id).state)
            except NotFound:
                return None

        try:
            return await self._run_sync(_get_state)
        except NotFound:
            return None
        except (DatabricksAPIError, AdapterError, OSError) as e:
            logger.error(
                "get_warehouse_state_failed",
                extra={"warehouse_id": warehouse_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get warehouse state for {warehouse_id}",
                details={"warehouse_id": warehouse_id, "error": str(e)},
            ) from e

    async def start_warehouse(self, warehouse_id: str) -> None:
        """Start a SQL warehouse and wait for it to be running.

        Args:
            warehouse_id: Databricks SQL warehouse ID

        Raises:
            TimeoutError: If warehouse doesn't start within timeout

        Example:
            >>> await service.start_warehouse("warehouse-xyz")
            >>> print("Warehouse started")
        """
        logger.debug("start_warehouse", extra={"warehouse_id": warehouse_id})

        def _start() -> None:
            waiter = self._client.warehouses.wait_get_warehouse_running(warehouse_id)
            if hasattr(waiter, "result"):
                waiter.result(timeout=datetime.timedelta(minutes=5))

        await self._run_sync(_start)
