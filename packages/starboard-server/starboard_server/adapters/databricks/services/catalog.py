# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Async Unity Catalog service implementation.

This module provides async Unity Catalog operations for:
- Catalogs, schemas, and tables
- Table metadata and lineage
- Volumes and functions
- Grants and permissions
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound, PermissionDenied
    from databricks.sdk.service.catalog import SecurableType

logger = get_logger(__name__)


class CatalogService(BaseService):
    """Async service for Unity Catalog operations.

    Provides async methods for:
    - Catalog/schema/table enumeration
    - Table metadata and lineage
    - Volume and function listing
    - Grant management

    Example:
        >>> service = CatalogService(workspace_client, http_client)
        >>> table = await service.get_table("catalog.schema.table")
        >>> lineage = await service.get_table_lineage("catalog.schema.table")
    """

    def __init__(
        self,
        client: WorkspaceClient,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize catalog service.

        Args:
            client: Authenticated Databricks WorkspaceClient
            http_client: Optional async HTTP client for REST API calls (lineage)
        """
        super().__init__(client)
        self._http_client = http_client

    # =========================================================================
    # Catalog Operations
    # =========================================================================

    async def list_catalogs(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all catalogs.

        Args:
            limit: Maximum number of catalogs to return

        Returns:
            List of catalog dictionaries

        Example:
            >>> catalogs = await service.list_catalogs()
            >>> for cat in catalogs:
            ...     print(cat['name'])
        """
        logger.debug("list_catalogs", extra={"limit": limit})

        def _list() -> list[dict[str, Any]]:
            catalogs = []
            for catalog in self._client.catalogs.list():
                catalogs.append(catalog.as_dict())
                if len(catalogs) >= limit:
                    break
            return catalogs

        try:
            return await self._run_sync(_list)
        except (DatabricksAPIError, OSError) as e:
            logger.error("list_catalogs_failed", extra={"error": str(e)})
            raise DatabricksAPIError(
                message="Failed to list catalogs",
                details={"error": str(e)},
            ) from e

    async def get_catalog(self, name: str) -> dict[str, Any] | None:
        """Get catalog by name.

        Args:
            name: Catalog name

        Returns:
            Catalog dictionary, or None if not found
        """
        logger.debug("get_catalog", extra={"name": name})

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.catalogs.get(name).as_dict()
            except NotFound:
                return None

        try:
            return await self._run_sync(_get)
        except NotFound:
            return None
        except (DatabricksAPIError, OSError) as e:
            logger.error("get_catalog_failed", extra={"name": name, "error": str(e)})
            raise DatabricksAPIError(
                message=f"Failed to get catalog {name}",
                details={"catalog_name": name, "error": str(e)},
            ) from e

    # =========================================================================
    # Schema Operations
    # =========================================================================

    async def list_schemas(
        self,
        catalog_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List schemas in a catalog.

        Args:
            catalog_name: Name of the catalog
            limit: Maximum number of schemas to return

        Returns:
            List of schema dictionaries
        """
        logger.debug("list_schemas", extra={"catalog_name": catalog_name})

        def _list() -> list[dict[str, Any]]:
            schemas = []
            try:
                for schema in self._client.schemas.list(catalog_name=catalog_name):
                    schemas.append(schema.as_dict())
                    if len(schemas) >= limit:
                        break
            except NotFound:
                logger.warning(
                    "catalog_not_found", extra={"catalog_name": catalog_name}
                )
            return schemas

        return await self._run_sync(_list)

    async def get_schema(self, full_name: str) -> dict[str, Any] | None:
        """Get schema by full name (catalog.schema).

        Args:
            full_name: Full schema name

        Returns:
            Schema dictionary, or None if not found
        """
        logger.debug("get_schema", extra={"full_name": full_name})

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.schemas.get(full_name).as_dict()
            except NotFound:
                return None

        return await self._run_sync(_get)

    # =========================================================================
    # Table Operations
    # =========================================================================

    async def list_tables(
        self,
        catalog_name: str,
        schema_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List tables in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            limit: Maximum number of tables to return

        Returns:
            List of table dictionaries
        """
        logger.debug(
            "list_tables",
            extra={"catalog_name": catalog_name, "schema_name": schema_name},
        )

        def _list() -> list[dict[str, Any]]:
            tables = []
            try:
                for table in self._client.tables.list(
                    catalog_name=catalog_name,
                    schema_name=schema_name,
                ):
                    tables.append(table.as_dict())
                    if len(tables) >= limit:
                        break
            except NotFound:
                logger.warning(
                    "schema_not_found",
                    extra={"catalog": catalog_name, "schema": schema_name},
                )
            return tables

        return await self._run_sync(_list)

    async def get_table(
        self,
        full_name: str,
        include_delta_metadata: bool = True,
        include_manifest: bool = True,
    ) -> dict[str, Any] | None:
        """Get table metadata by full name.

        Args:
            full_name: Full table name (catalog.schema.table)
            include_delta_metadata: Include Delta metadata
            include_manifest: Include manifest capabilities

        Returns:
            Table dictionary, or None if not found

        Example:
            >>> table = await service.get_table("main.default.users")
            >>> print(table['columns'])
        """
        logger.debug("get_table", extra={"full_name": full_name})

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.tables.get(
                    full_name,
                    include_delta_metadata=include_delta_metadata,
                    include_manifest_capabilities=include_manifest,
                ).as_dict()
            except NotFound:
                return None

        try:
            return await self._run_sync(_get)
        except NotFound:
            return None
        except (DatabricksAPIError, OSError) as e:
            logger.error(
                "get_table_failed", extra={"full_name": full_name, "error": str(e)}
            )
            raise DatabricksAPIError(
                message=f"Failed to get table {full_name}",
                details={"table_name": full_name, "error": str(e)},
            ) from e

    async def get_table_lineage(
        self,
        table_name: str,
        include_entity_lineage: bool = True,
    ) -> dict[str, Any] | None:
        """Get table lineage via REST API.

        Creates a fresh HTTP client per request to avoid event loop binding issues
        when called from tool executor threads.

        Args:
            table_name: Fully qualified table name
            include_entity_lineage: Include entity lineage

        Returns:
            Lineage dictionary, empty dict if 403, or None if http_client not configured
        """
        if self._http_client is None:
            logger.warning("http_client_not_configured_for_lineage")
            return None

        logger.debug("get_table_lineage", extra={"table_name": table_name})

        endpoint = "api/2.0/lineage-tracking/table-lineage"
        params: dict[str, str] = {
            "table_name": table_name,
            "include_entity_lineage": str(include_entity_lineage).lower(),
        }

        # Create a fresh HTTP client for this request to avoid event loop binding issues.
        # When tools run in separate threads with their own event loops, the shared
        # _http_client (bound to the main loop) causes "Event loop is closed" errors.
        try:
            async with httpx.AsyncClient(
                base_url=str(self._http_client.base_url),
                headers=dict(self._http_client.headers),
                timeout=httpx.Timeout(30.0, connect=5.0),
            ) as client:
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.debug(
                    "lineage_api_forbidden",
                    extra={"table_name": table_name},
                )
                return {}
            logger.error(
                "get_table_lineage_failed",
                extra={"table_name": table_name, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Failed to get table lineage for {table_name}",
                details={"table_name": table_name, "error": str(e)},
            ) from e

    # =========================================================================
    # Volume Operations
    # =========================================================================

    async def list_volumes(
        self,
        catalog_name: str,
        schema_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List volumes in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            limit: Maximum number of volumes to return

        Returns:
            List of volume dictionaries
        """
        logger.debug(
            "list_volumes",
            extra={"catalog_name": catalog_name, "schema_name": schema_name},
        )

        def _list() -> list[dict[str, Any]]:
            volumes = []
            try:
                for volume in self._client.volumes.list(
                    catalog_name=catalog_name,
                    schema_name=schema_name,
                ):
                    volumes.append(volume.as_dict())
                    if len(volumes) >= limit:
                        break
            except NotFound:
                pass
            return volumes

        return await self._run_sync(_list)

    # =========================================================================
    # Function Operations
    # =========================================================================

    async def list_functions(
        self,
        catalog_name: str,
        schema_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List functions in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            limit: Maximum number of functions to return

        Returns:
            List of function dictionaries
        """
        logger.debug(
            "list_functions",
            extra={"catalog_name": catalog_name, "schema_name": schema_name},
        )

        def _list() -> list[dict[str, Any]]:
            functions = []
            try:
                for func in self._client.functions.list(
                    catalog_name=catalog_name,
                    schema_name=schema_name,
                ):
                    functions.append(func.as_dict())
                    if len(functions) >= limit:
                        break
            except NotFound:
                pass
            return functions

        return await self._run_sync(_list)

    # =========================================================================
    # Grant Operations
    # =========================================================================

    async def get_grants(
        self,
        securable_type: SecurableType,
        full_name: str,
    ) -> dict[str, Any] | None:
        """Get grants for a securable.

        Args:
            securable_type: Type of securable (TABLE, SCHEMA, CATALOG, etc.)
            full_name: Full name of the securable

        Returns:
            Grants dictionary, or None if access denied or not found
        """
        logger.debug(
            "get_grants",
            extra={"securable_type": securable_type.value, "full_name": full_name},
        )

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.grants.get(
                    securable_type.value,  # type: ignore[arg-type]
                    full_name,
                ).as_dict()
            except (PermissionDenied, NotFound):
                return None

        return await self._run_sync(_get)

    async def get_effective_grants(
        self,
        securable_type: SecurableType,
        full_name: str,
    ) -> dict[str, Any] | None:
        """Get effective (resolved) grants for a securable.

        Args:
            securable_type: Type of securable
            full_name: Full name of the securable

        Returns:
            Effective grants dictionary, or None if access denied or not found
        """
        logger.debug(
            "get_effective_grants",
            extra={"securable_type": securable_type.value, "full_name": full_name},
        )

        def _get() -> dict[str, Any] | None:
            try:
                return self._client.grants.get_effective(
                    securable_type.value,  # type: ignore[arg-type]
                    full_name,
                ).as_dict()
            except (PermissionDenied, NotFound):
                return None

        return await self._run_sync(_get)
