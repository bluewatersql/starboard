"""Auto-provision serverless SQL warehouse on Databricks.

Creates a serverless warehouse when no warehouse ID is configured,
using the Databricks SQL Warehouses REST API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.exceptions import ConfigurationError, DatabricksAPIError
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)


class WarehouseProvisioner(BaseService):
    """Provisions a serverless SQL warehouse on Databricks.

    Intended for single-use during startup. Creates a SERVERLESS warehouse
    via the Databricks SDK and returns the new warehouse ID.

    Args:
        client: Authenticated Databricks WorkspaceClient.
        warehouse_name: Name for the new warehouse.
        warehouse_size: T-shirt size (e.g. "X-Large").

    Example:
        >>> provisioner = WarehouseProvisioner(client, "MY_DW", "Large")
        >>> warehouse_id = await provisioner.provision()
    """

    def __init__(
        self,
        client: WorkspaceClient,
        warehouse_name: str,
        warehouse_size: str,
    ) -> None:
        super().__init__(client)
        self._warehouse_name = warehouse_name
        self._warehouse_size = warehouse_size

    async def provision(self) -> str:
        """Create a serverless SQL warehouse and wait for it to be running.

        Returns:
            The warehouse ID of the newly created warehouse.

        Raises:
            DatabricksAPIError: If warehouse creation fails after retries.
            ConfigurationError: If the workspace does not support serverless.
        """
        logger.info(
            "warehouse_provisioner_starting",
            extra={
                "warehouse_name": self._warehouse_name,
                "warehouse_size": self._warehouse_size,
            },
        )

        # Step 1: Check if warehouse already exists (idempotent re-run guard)
        existing_id = await self._find_existing_warehouse()
        if existing_id is not None:
            return existing_id

        # Step 2: Create warehouse
        try:
            warehouse_id = await self._run_with_retry(
                self._create_warehouse,
                max_retries=3,
                retry_delay=2.0,
            )
        except Exception as exc:
            error_msg = str(exc).lower()
            if "serverless" in error_msg or "not supported" in error_msg:
                raise ConfigurationError(
                    config_key="databricks_warehouse_size",
                    reason=(
                        "This workspace does not support serverless warehouses. "
                        "Set DATABRICKS_WAREHOUSE_ID to an existing warehouse ID "
                        "or disable auto-creation with AUTOCREATE_DBX_DW=false."
                    ),
                ) from exc
            if "403" in error_msg or "permission" in error_msg:
                raise ConfigurationError(
                    config_key="autocreate_dbx_dw",
                    reason=(
                        "Permission denied creating warehouse. Verify the service "
                        "principal has CREATE WAREHOUSE privileges, or set "
                        "DATABRICKS_WAREHOUSE_ID to an existing warehouse."
                    ),
                ) from exc
            raise DatabricksAPIError(
                message=f"Failed to create warehouse: {exc}",
            ) from exc

        logger.info(
            "warehouse_provisioner_created",
            extra={
                "warehouse_id": warehouse_id,
                "warehouse_name": self._warehouse_name,
                "warehouse_size": self._warehouse_size,
            },
        )
        return warehouse_id

    async def _find_existing_warehouse(self) -> str | None:
        """Check if a warehouse with the configured name already exists."""
        try:
            warehouses = await self._run_sync(
                lambda: list(self._client.warehouses.list())
            )
        except Exception:
            logger.debug("warehouse_list_failed_continuing_to_create")
            return None

        for wh in warehouses:
            if wh.name == self._warehouse_name:
                state = str(getattr(wh, "state", "UNKNOWN"))
                if state in ("RUNNING", "STOPPED"):
                    logger.info(
                        "warehouse_already_exists",
                        extra={
                            "warehouse_id": wh.id,
                            "warehouse_name": wh.name,
                            "state": state,
                        },
                    )
                    return wh.id
                if state == "DELETED":
                    continue
                # Other states (STARTING, etc.) — use it
                return wh.id
        return None

    def _create_warehouse(self) -> str:
        """Synchronous warehouse creation via SDK."""
        from databricks.sdk.service.sql import (
            CreateWarehouseRequestWarehouseType,
            SpotInstancePolicy,
        )

        response = self._client.warehouses.create_and_wait(
            name=self._warehouse_name,
            cluster_size=self._warehouse_size,
            warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
            enable_serverless_compute=True,
            spot_instance_policy=SpotInstancePolicy.COST_OPTIMIZED,
            auto_stop_mins=10,
            min_num_clusters=1,
            max_num_clusters=1,
        )
        if response.id is None:
            msg = "Warehouse created but returned no ID"
            raise DatabricksAPIError(message=msg)
        return response.id
