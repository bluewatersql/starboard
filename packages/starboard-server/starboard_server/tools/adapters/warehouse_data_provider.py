# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse data provider adapter.

Adapts existing context facades to the WarehouseDataProvider protocol
needed by WarehousePortfolioService.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.exceptions import (
    AdapterError,
    DatabricksAPIError,
    ResourceNotFoundError,
    wrap_databricks_error,
)
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.adapters.databricks.client import AsyncDatabricksClient

logger = get_logger(__name__)


class WarehouseDataAdapter:
    """Adapter to provide warehouse data to WarehousePortfolioService.

    Implements the WarehouseDataProvider protocol by wrapping
    the AsyncDatabricksClient for warehouse API access.

    Example:
        >>> adapter = WarehouseDataAdapter(client)
        >>> warehouses = await adapter.list_warehouses()
        >>> config = await adapter.get_warehouse("abc123")
    """

    def __init__(self, client: AsyncDatabricksClient) -> None:
        """Initialize the adapter.

        Args:
            client: Async Databricks client for API access.
        """
        self._client = client

    async def list_warehouses(self) -> list[dict[str, Any]]:
        """List all SQL warehouses.

        Returns:
            List of warehouse dictionaries with id and name.
        """
        logger.debug("listing_warehouses")

        try:
            # Use the warehouses API endpoint
            warehouses = await self._client.list_warehouses()

            logger.debug(
                "warehouses_listed",
                extra={"count": len(warehouses)},
            )

            return warehouses

        except DatabricksAPIError as e:
            logger.error(
                "list_warehouses_failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "retryable": e.details.get("retryable", False),
                },
            )
            return []
        except AdapterError as e:
            # Wrap and log unknown errors with context
            wrapped = wrap_databricks_error(e)
            logger.error(
                "list_warehouses_failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "wrapped_type": type(wrapped).__name__,
                },
            )
            return []

    async def get_warehouse(self, warehouse_id: str) -> dict[str, Any] | None:
        """Get a specific warehouse configuration.

        Args:
            warehouse_id: The warehouse ID.

        Returns:
            Warehouse configuration dict or None.
        """
        logger.debug(
            "getting_warehouse",
            extra={"warehouse_id": warehouse_id},
        )

        try:
            config = await self._client.get_warehouse(warehouse_id)
            return config

        except ResourceNotFoundError as e:
            logger.warning(
                "warehouse_not_found",
                extra={
                    "warehouse_id": warehouse_id,
                    "error": str(e),
                },
            )
            return None
        except DatabricksAPIError as e:
            logger.error(
                "get_warehouse_failed",
                extra={
                    "warehouse_id": warehouse_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "retryable": e.details.get("retryable", False),
                },
            )
            return None
        except AdapterError as e:
            # Wrap and log unknown errors with context
            wrapped = wrap_databricks_error(e)
            logger.error(
                "get_warehouse_failed",
                extra={
                    "warehouse_id": warehouse_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "wrapped_type": type(wrapped).__name__,
                },
            )
            return None
