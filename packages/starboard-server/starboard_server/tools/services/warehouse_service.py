# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse service for basic warehouse operations.

This service provides basic warehouse operations using the WarehouseDataProvider
protocol. It complements the existing WarehousePortfolioService which handles
portfolio-level operations (fingerprinting, health scoring, SLOs).

The service layer:
- Uses protocol-based dependency injection
- Raises domain-specific exceptions
- Provides both raising and non-raising method variants
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.exceptions import WarehouseNotFoundError

if TYPE_CHECKING:
    from starboard_server.tools.protocols import WarehouseDataProvider

logger = get_logger(__name__)


class WarehouseService:
    """Service for basic warehouse operations.

    Provides access to warehouse configuration, metrics, and query history.
    Uses WarehouseDataProvider protocol for data access.

    For portfolio-level operations (fingerprinting, health scoring, SLOs),
    use WarehousePortfolioService instead.

    Attributes:
        warehouse_data: Provider implementing WarehouseDataProvider protocol.

    Example:
        >>> # Use with a WarehouseDataProvider implementation
        >>> service = WarehouseService(warehouse_data=provider_impl)
        >>> config = await service.get_warehouse_config("wh-123")
    """

    def __init__(self, warehouse_data: WarehouseDataProvider) -> None:
        """Initialize warehouse service.

        Args:
            warehouse_data: Provider implementing WarehouseDataProvider protocol.
        """
        self.warehouse_data = warehouse_data

    async def get_warehouse_config(self, warehouse_id: str) -> dict[str, Any]:
        """Get warehouse configuration.

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            Transformed warehouse configuration dict.

        Raises:
            WarehouseNotFoundError: If warehouse not found.

        Example:
            >>> config = await service.get_warehouse_config("wh-123")
            >>> config["name"]
            'analytics-warehouse'
        """
        logger.debug("fetching_warehouse_config", warehouse_id=warehouse_id)

        config = await self.warehouse_data.get_warehouse_config(warehouse_id)

        if not config:
            logger.warning("warehouse_not_found", warehouse_id=warehouse_id)
            raise WarehouseNotFoundError(warehouse_id)

        logger.debug("fetched_warehouse_config", warehouse_id=warehouse_id)
        return config

    async def get_warehouse_config_or_none(
        self, warehouse_id: str
    ) -> dict[str, Any] | None:
        """Get warehouse configuration without raising.

        Args:
            warehouse_id: Warehouse ID to fetch configuration for.

        Returns:
            Transformed warehouse configuration dict, or None if not found.

        Example:
            >>> config = await service.get_warehouse_config_or_none("wh-123")
            >>> if config:
            ...     print(config["name"])
        """
        try:
            return await self.get_warehouse_config(warehouse_id)
        except WarehouseNotFoundError:
            return None

    async def get_warehouse_metrics(
        self, warehouse_id: str, days_history: int = 7
    ) -> dict[str, Any] | None:
        """Get warehouse metrics.

        Returns None rather than raising when metrics aren't available,
        as metrics may be unavailable for new or stopped warehouses.

        Args:
            warehouse_id: Warehouse ID to fetch metrics for.
            days_history: Number of days to look back for metrics.

        Returns:
            Warehouse metrics dict, or None if not available.

        Example:
            >>> metrics = await service.get_warehouse_metrics("wh-123")
            >>> if metrics:
            ...     print(metrics["query_count"])
        """
        logger.debug("fetching_warehouse_metrics", warehouse_id=warehouse_id)

        metrics = await self.warehouse_data.get_warehouse_metrics(
            warehouse_id, days_history=days_history
        )

        if not metrics:
            logger.debug("no_warehouse_metrics", warehouse_id=warehouse_id)
            return None

        logger.debug("fetched_warehouse_metrics", warehouse_id=warehouse_id)
        return metrics

    async def get_warehouse_query_history(
        self, warehouse_id: str, days_history: int = 30
    ) -> dict[str, Any] | None:
        """Get warehouse query history.

        Returns None rather than raising when history isn't available.

        Args:
            warehouse_id: Warehouse ID to fetch history for.
            days_history: Number of days to look back for history.

        Returns:
            Analyzed query history dict with patterns and summary,
            or None if not available.

        Example:
            >>> history = await service.get_warehouse_query_history("wh-123")
            >>> if history:
            ...     print(history["summary"]["total_queries"])
        """
        logger.debug("fetching_warehouse_query_history", warehouse_id=warehouse_id)

        history = await self.warehouse_data.get_warehouse_query_history(
            warehouse_id, days_history=days_history
        )

        if not history:
            logger.debug("no_warehouse_query_history", warehouse_id=warehouse_id)
            return None

        logger.debug("fetched_warehouse_query_history", warehouse_id=warehouse_id)
        return history

    async def list_warehouses(self) -> list[dict[str, Any]]:
        """List all SQL warehouses.

        Returns:
            List of warehouse configuration dicts. Returns empty list
            if no warehouses found.

        Example:
            >>> warehouses = await service.list_warehouses()
            >>> for wh in warehouses:
            ...     print(wh["name"])
        """
        logger.debug("listing_warehouses")

        warehouses = await self.warehouse_data.list_warehouses()

        logger.debug("listed_warehouses", count=len(warehouses))
        return warehouses
