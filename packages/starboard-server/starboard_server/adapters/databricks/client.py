# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unified async Databricks client with integrated caching.

This module provides the main entry point for all Databricks operations:
- Single client class for all operations
- Async-first design (all methods are async)
- Integrated caching with per-method control
- Connection lifecycle management

Usage:
    >>> async with AsyncDatabricksClient(cfg=config) as client:
    ...     job = await client.get_job(12345)
    ...     runs = await client.list_job_runs(12345)
    ...     df = await client.execute_sql("SELECT 1")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from databricks.sdk import WorkspaceClient

from starboard_server.adapters.databricks.cache.manager import CacheManager
from starboard_server.adapters.databricks.services.base import run_databricks_sync
from starboard_server.adapters.databricks.services.catalog import CatalogService
from starboard_server.adapters.databricks.services.clusters import ClusterService
from starboard_server.adapters.databricks.services.jobs import JobService
from starboard_server.adapters.databricks.services.sql import SQLService
from starboard_server.adapters.databricks.services.users import UsersService
from starboard_server.adapters.databricks.services.warehouses import WarehouseService
from starboard_server.adapters.databricks.services.workspace import WorkspaceService
from starboard_server.exceptions import DatabricksAPIError
from starboard_server.infra.core.config import EnvConfig, get_config
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.reliability.exceptions import ConfigurationError

if TYPE_CHECKING:
    import polars as pl
    from databricks.sdk.service.catalog import SecurableType

logger = get_logger(__name__)


class AsyncDatabricksClient:
    """Unified async Databricks client with integrated caching.

    Provides async access to all Databricks APIs with:
    - Automatic caching (configurable per-method)
    - Connection pooling for HTTP operations
    - Per-key locking for cache stampede prevention
    - Clean async context manager lifecycle

    Cache TTL Configuration:
        - Jobs: 10 minutes (stable configuration)
        - Job Runs: 1 minute (rapidly changing)
        - Jobs List: 2 minutes (semi-stable)
        - Clusters: 5 minutes (medium volatility)
        - Warehouses: 5 minutes (medium volatility)
        - Tables: 10 minutes (stable metadata)

    Example:
        >>> async with AsyncDatabricksClient(cfg=config) as client:
        ...     # Cached by default
        ...     job = await client.get_job(12345)
        ...
        ...     # Bypass cache for fresh data
        ...     job = await client.get_job(12345, use_cache=False)
        ...
        ...     # SQL with optional caching
        ...     df = await client.execute_sql("SELECT 1", cache_ttl=300)
    """

    # Cache TTL constants (seconds)
    TTL_JOB = 600  # 10 minutes
    TTL_JOB_RUNS = 60  # 1 minute
    TTL_JOBS_LIST = 120  # 2 minutes
    TTL_CLUSTER = 300  # 5 minutes
    TTL_WAREHOUSE = 300  # 5 minutes
    TTL_TABLE = 600  # 10 minutes
    TTL_SQL = 300  # 5 minutes (when explicitly requested)

    def __init__(
        self,
        cfg: EnvConfig | None = None,
        *,
        host: str | None = None,
        token: str | None = None,
        cache_enabled: bool = True,
        cache_max_size: int = 500,
    ) -> None:
        """Initialize async Databricks client.

        Args:
            cfg: Configuration containing Databricks credentials
            host: Optional host override
            token: Optional token override
            cache_enabled: Enable caching (default: True)
            cache_max_size: Maximum cache entries (default: 500)
        """
        self._cfg = cfg or get_config()
        self._host = host or self._cfg.databricks_host
        self._token = token or self._cfg.databricks_token
        self._cache_enabled = cache_enabled
        self._cache_max_size = cache_max_size

        # Lazy initialization
        self._sdk_client: WorkspaceClient | None = None
        self._cache: CacheManager | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._rest_client_instance: Any = None

        # Services (lazy)
        self._sql_service: SQLService | None = None
        self._job_service: JobService | None = None
        self._cluster_service: ClusterService | None = None
        self._warehouse_service: WarehouseService | None = None
        self._catalog_service: CatalogService | None = None
        self._workspace_service: WorkspaceService | None = None
        self._users_service: UsersService | None = None

        # Resolved warehouse ID
        self._warehouse_id: str | None = None

        # Initialization state
        self._initialized = False

        logger.debug(
            "async_databricks_client_created",
            extra={
                "host": self._host,
                "cache_enabled": cache_enabled,
                "cache_max_size": cache_max_size,
            },
        )

    async def __aenter__(self) -> AsyncDatabricksClient:
        """Async context manager entry - initialize client."""
        await self._initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - cleanup resources."""
        await self.close()

    async def _initialize(self) -> None:
        """Initialize client components.

        Called automatically when used as context manager.
        Can also be called explicitly for manual lifecycle management.
        """
        if self._initialized:
            return

        # Create SDK client (sync, but we wrap calls)
        self._sdk_client = WorkspaceClient(
            host=self._host,
            token=self._token,
        )

        # Verify authentication
        if not await self._verify_auth():
            raise ConfigurationError(
                config_key="databricks_credentials",
                reason="Failed to authenticate with Databricks",
                details={"host": self._host},
            )

        # Initialize cache
        if self._cache_enabled:
            self._cache = CacheManager(max_size=self._cache_max_size)

        # Initialize HTTP client for REST API calls
        self._http_client = httpx.AsyncClient(
            base_url=self._host or "",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=5.0),
        )

        # Auto-create warehouse if needed
        if (
            not self._cfg.databricks_warehouse_id
            and self._cfg.autocreate_dbx_dw
            and not self._cfg.offline_mode
        ):
            import os

            from starboard_server.adapters.databricks.warehouse_provisioner import (
                WarehouseProvisioner,
            )

            provisioner = WarehouseProvisioner(
                client=self._sdk_client,
                warehouse_name=self._cfg.databricks_warehouse_name,
                warehouse_size=self._cfg.databricks_warehouse_size,
            )
            new_warehouse_id = await provisioner.provision()

            self._cfg = self._cfg.model_copy(
                update={"databricks_warehouse_id": new_warehouse_id}
            )
            os.environ["DATABRICKS_WAREHOUSE_ID"] = new_warehouse_id

            logger.info(
                "auto_created_warehouse_configured",
                extra={"warehouse_id": new_warehouse_id},
            )

        # Resolve warehouse ID
        self._warehouse_id = await self._resolve_warehouse_id()

        # Support mode grants
        if self._cfg.is_dbx_support and not self._cfg.offline_mode:
            if self._warehouse_id:
                from starboard_server.adapters.databricks.support_mode import (
                    SupportModeInitializer,
                )

                initializer = SupportModeInitializer(sql_service=self._sql)
                await initializer.initialize()
            else:
                logger.warning(
                    "support_mode_skipped_no_warehouse",
                    extra={
                        "reason": "No warehouse ID available for executing grants",
                    },
                )

        self._initialized = True

        logger.debug(
            "async_databricks_client_initialized",
            extra={
                "warehouse_id": self._warehouse_id,
                "cache_enabled": self._cache_enabled,
            },
        )

    async def close(self) -> None:
        """Close client and release resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._rest_client_instance is not None:
            await self._rest_client_instance.close()
            self._rest_client_instance = None

        if self._cache:
            await self._cache.clear()
            self._cache = None

        self._initialized = False
        logger.debug("async_databricks_client_closed")

    async def _verify_auth(self) -> bool:
        """Verify authentication with Databricks."""

        def _check() -> bool:
            try:
                if self._sdk_client:
                    self._sdk_client.current_user.me()
                    return True
            except (DatabricksAPIError, OSError) as e:
                logger.error("auth_verification_failed", extra={"error": str(e)})
            return False

        return await run_databricks_sync(_check)

    async def _resolve_warehouse_id(self) -> str | None:
        """Resolve warehouse ID from config or workspace default."""
        # Use configured ID if provided
        if self._cfg.databricks_warehouse_id:
            logger.debug(
                "using_configured_warehouse",
                extra={"warehouse_id": self._cfg.databricks_warehouse_id},
            )
            return self._cfg.databricks_warehouse_id

        # Try to get default workspace warehouse
        def _get_default() -> str | None:
            try:
                if self._sdk_client:
                    setting = self._sdk_client.settings.default_warehouse_id.get()
                    if (
                        setting
                        and hasattr(setting, "string_val")
                        and setting.string_val
                    ):
                        return setting.string_val.value
            except (DatabricksAPIError, OSError) as e:
                logger.warning(
                    "failed_to_get_default_warehouse", extra={"error": str(e)}
                )
            return None

        default_id = await run_databricks_sync(_get_default)
        if default_id:
            logger.debug("using_default_warehouse", extra={"warehouse_id": default_id})
            return default_id

        logger.warning("no_warehouse_id_available")
        return None

    @property
    def config(self) -> EnvConfig:
        """Get the configuration."""
        return self._cfg

    @property
    def warehouse_id(self) -> str | None:
        """Get the resolved warehouse ID."""
        return self._warehouse_id

    @property
    def _client(self) -> WorkspaceClient:
        """Get underlying WorkspaceClient for compatibility.

        Used by UCCatalogService and other components that need direct SDK access.
        """
        if not self._sdk_client:
            raise RuntimeError("Client not initialized")
        return self._sdk_client

    @property
    def _rest_client(self):
        """Get HTTP client for REST API calls.

        Used by UCCatalogService for lineage queries.
        Cached after first creation to enable connection pooling.
        """
        if self._rest_client_instance is None:
            from starboard_server.adapters.apis.http_client import HTTPClient

            self._rest_client_instance = HTTPClient(
                base_url=self._host or "",
                auth_header={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
        return self._rest_client_instance

    def require_warehouse_id(self) -> str:
        """Get warehouse ID, raising error if not available."""
        if self._warehouse_id:
            return self._warehouse_id
        raise ConfigurationError(
            config_key="databricks_warehouse_id",
            reason="No warehouse ID configured and no default found",
            details={"hint": "Set DATABRICKS_WAREHOUSE_ID environment variable"},
        )

    # =========================================================================
    # Service Properties (Lazy Initialization)
    # =========================================================================

    @property
    def _jobs(self) -> JobService:
        if self._job_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._job_service = JobService(self._sdk_client)
        return self._job_service

    @property
    def _sql(self) -> SQLService:
        if self._sql_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._sql_service = SQLService(
                self._sdk_client, self._http_client, self._warehouse_id
            )
        return self._sql_service

    @property
    def _clusters(self) -> ClusterService:
        if self._cluster_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._cluster_service = ClusterService(self._sdk_client)
        return self._cluster_service

    @property
    def _warehouses(self) -> WarehouseService:
        if self._warehouse_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._warehouse_service = WarehouseService(self._sdk_client)
        return self._warehouse_service

    @property
    def _catalog(self) -> CatalogService:
        if self._catalog_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._catalog_service = CatalogService(self._sdk_client, self._http_client)
        return self._catalog_service

    @property
    def _workspace(self) -> WorkspaceService:
        if self._workspace_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._workspace_service = WorkspaceService(self._sdk_client)
        return self._workspace_service

    @property
    def _users(self) -> UsersService:
        if self._users_service is None:
            if not self._sdk_client:
                raise RuntimeError("Client not initialized")
            self._users_service = UsersService(self._sdk_client)
        return self._users_service

    # =========================================================================
    # Public Service Properties
    # =========================================================================

    @property
    def users(self) -> UsersService:
        """Access user service for authentication operations."""
        return self._users

    @property
    def sql(self) -> SQLService:
        """Access SQL service for query execution."""
        return self._sql

    @property
    def jobs(self) -> JobService:
        """Access jobs service for job operations."""
        return self._jobs

    @property
    def clusters(self) -> ClusterService:
        """Access clusters service for cluster operations."""
        return self._clusters

    @property
    def warehouses(self) -> WarehouseService:
        """Access warehouses service for warehouse operations."""
        return self._warehouses

    @property
    def unity_catalog(self) -> CatalogService:
        """Access Unity Catalog service for metadata operations."""
        return self._catalog

    @property
    def workspace(self) -> WorkspaceService:
        """Access workspace service for workspace operations."""
        return self._workspace

    # =========================================================================
    # Job Operations
    # =========================================================================

    async def get_job(self, job_id: int, *, use_cache: bool = True) -> dict[str, Any]:
        """Get job configuration by ID.

        Args:
            job_id: Databricks job ID
            use_cache: Use cache (default: True)

        Returns:
            Job configuration dictionary
        """
        cache_key = f"job:{job_id}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.get_job(job_id)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOB)

        return result

    async def list_job_runs(
        self,
        job_id: int,
        limit: int = 5,
        expand_tasks: bool = True,
        *,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """List recent runs for a job.

        Args:
            job_id: Databricks job ID
            limit: Maximum runs to return
            expand_tasks: Include task details
            use_cache: Use cache (default: True)

        Returns:
            List of run dictionaries (newest first)
        """
        cache_key = f"job_runs:{job_id}:{limit}:{expand_tasks}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.list_runs(job_id, limit, expand_tasks)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOB_RUNS)

        return result

    async def get_run(
        self,
        run_id: int,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get details of a specific job run.

        Args:
            run_id: Databricks run ID
            use_cache: Use cache (default: True)

        Returns:
            Run dictionary with state, tasks, timing, cluster info
        """
        cache_key = f"run:{run_id}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.get_run(run_id)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOB_RUNS)

        return result

    async def get_run_output(
        self,
        run_id: int,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get output and logs for a job run.

        Key diagnostic tool for understanding job failures.

        Args:
            run_id: Databricks run ID
            use_cache: Use cache (default: True)

        Returns:
            Run output with error messages, logs, notebook output
        """
        cache_key = f"run_output:{run_id}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.get_run_output(run_id)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOB_RUNS)

        return result

    async def get_task_logs(
        self,
        run_id: int,
        task_key: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get logs for a specific task within a job run.

        Retrieves detailed logs and output for a single task, useful
        when focusing on a specific failing task.

        Args:
            run_id: Databricks job run ID
            task_key: The task_key identifier for the specific task
            use_cache: Use cache (default: True)

        Returns:
            Task logs with error messages, logs, notebook output
        """
        cache_key = f"task_logs:{run_id}:{task_key}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.get_task_logs(run_id, task_key)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOB_RUNS)

        return result

    async def run_job(self, job_id: int, wait_timeout: int = 15) -> dict[str, Any]:
        """Run a job and wait for completion.

        Side effect: Invalidates related caches.

        Args:
            job_id: Job to run
            wait_timeout: Minutes to wait for completion

        Returns:
            Run result dictionary
        """
        result = await self._jobs.run_job(job_id, wait_timeout)

        # Invalidate related caches
        if self._cache:
            await self._cache.invalidate_pattern(f"job_runs:{job_id}:*")

        return result

    async def create_job(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new job.

        Args:
            job_spec: Job configuration

        Returns:
            Created job info with job_id
        """
        result = await self._jobs.create_job(job_spec)

        # Invalidate jobs list cache
        if self._cache:
            await self._cache.invalidate_pattern("jobs_list:*")

        return result

    async def list_jobs(
        self,
        limit: int = 100,
        *,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """List all jobs in the workspace.

        Args:
            limit: Maximum jobs to return
            use_cache: Use cache (default: True)

        Returns:
            List of job summary dictionaries
        """
        cache_key = f"jobs_list:{limit}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._jobs.list_jobs(limit)

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_JOBS_LIST)

        return result

    # =========================================================================
    # SQL Operations
    # =========================================================================

    async def execute_sql(
        self,
        query: str,
        *,
        sql_cache_key: str | None = None,
        warehouse_id: str | None = None,
        wait_timeout: str = "50s",
        cache_ttl: int | None = None,
    ) -> pl.DataFrame:
        """Execute SQL query and return Polars DataFrame.

        SQL results are NOT cached by default (query results vary).
        Pass cache_ttl to enable caching for specific queries.

        Args:
            query: SQL query to execute
            sql_cache_key: Cache key for SQL
            warehouse_id: Override warehouse ID
            wait_timeout: Query timeout
            cache_ttl: Cache TTL in seconds (None = no caching)

        Returns:
            Polars DataFrame with results
        """
        wh_id = warehouse_id or self._warehouse_id

        if cache_ttl and self._cache and wh_id:
            cache_key = self._cache.sql_key((sql_cache_key or query), wh_id)
            cached = await self._cache.get_dataframe(cache_key)
            if cached is not None:
                return cached

        result = await self._sql.execute_polars(query, wh_id, wait_timeout)

        if cache_ttl and self._cache and wh_id:
            cache_key = self._cache.sql_key(query, wh_id)
            await self._cache.set_dataframe(cache_key, result, ttl=cache_ttl)

        return result

    async def get_query_history(
        self,
        statement_id: str | None = None,
        warehouse_id: str | None = None,
        days_history: int | None = None,
    ) -> list[dict[str, Any]] | None:
        """Get query history with optional filters.

        Not cached (rapidly changing data).
        """
        return await self._sql.get_query_history(
            statement_id, warehouse_id, days_history
        )

    async def get_query(
        self,
        statement_id: str,
        include_plan: bool = False,
        include_metrics: bool = False,
    ) -> dict[str, Any] | None:
        """Get query details by statement ID.

        Fetches query information from the SQL history API including
        optional plan and metrics data.

        Args:
            statement_id: Statement ID to get query for
            include_plan: Include query plan data
            include_metrics: Include execution metrics

        Returns:
            Query details dict, or None if not found
        """
        return await self._sql.get_query(
            statement_id,
            include_plan=include_plan,
            include_metrics=include_metrics,
        )

    # =========================================================================
    # Cluster Operations
    # =========================================================================

    async def get_cluster(
        self,
        cluster_id: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        """Get cluster configuration by ID."""
        cache_key = f"cluster:{cluster_id}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._clusters.get_cluster(cluster_id)

        if result and self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_CLUSTER)

        return result

    async def list_clusters(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        """List all clusters in the workspace."""
        cache_key = "clusters:all"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._clusters.list_clusters()

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_CLUSTER)

        return result

    async def get_cluster_state(self, cluster_id: str) -> str | None:
        """Get cluster state (not cached - rapidly changing)."""
        return await self._clusters.get_cluster_state(cluster_id)

    async def get_cluster_events(self, cluster_id: str) -> list[dict[str, Any]]:
        """Get cluster events (not cached - rapidly changing)."""
        return await self._clusters.get_cluster_events(cluster_id)

    async def start_cluster(self, cluster_id: str) -> None:
        """Start a cluster."""
        await self._clusters.start_cluster(cluster_id)
        if self._cache:
            await self._cache.invalidate(f"cluster:{cluster_id}")

    async def stop_cluster(self, cluster_id: str) -> None:
        """Stop a cluster."""
        await self._clusters.stop_cluster(cluster_id)
        if self._cache:
            await self._cache.invalidate(f"cluster:{cluster_id}")

    # =========================================================================
    # Warehouse Operations
    # =========================================================================

    async def get_warehouse(
        self,
        warehouse_id: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        """Get warehouse configuration by ID."""
        cache_key = f"warehouse:{warehouse_id}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._warehouses.get_warehouse(warehouse_id)

        if result and self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_WAREHOUSE)

        return result

    async def list_warehouses(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        """List all SQL warehouses."""
        cache_key = "warehouses:all"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._warehouses.list_warehouses()

        if self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_WAREHOUSE)

        return result

    async def get_warehouse_state(self, warehouse_id: str) -> str | None:
        """Get warehouse state (not cached)."""
        return await self._warehouses.get_warehouse_state(warehouse_id)

    async def start_warehouse(self, warehouse_id: str) -> None:
        """Start a SQL warehouse."""
        await self._warehouses.start_warehouse(warehouse_id)
        if self._cache:
            await self._cache.invalidate(f"warehouse:{warehouse_id}")

    # =========================================================================
    # Unity Catalog Operations
    # =========================================================================

    async def get_table(
        self,
        full_name: str,
        *,
        include_delta_metadata: bool = True,
        include_manifest: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        """Get Unity Catalog table metadata."""
        cache_key = f"table:{full_name}:{include_delta_metadata}:{include_manifest}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._catalog.get_table(
            full_name, include_delta_metadata, include_manifest
        )

        if result and self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_TABLE)

        return result

    async def get_table_lineage(
        self,
        table_name: str,
        *,
        include_entity_lineage: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        """Get table lineage."""
        cache_key = f"table_lineage:{table_name}:{include_entity_lineage}"

        if use_cache and self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._catalog.get_table_lineage(
            table_name, include_entity_lineage
        )

        if result and self._cache:
            await self._cache.set(cache_key, result, ttl=self.TTL_TABLE)

        return result

    async def list_catalogs(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all catalogs (not cached)."""
        return await self._catalog.list_catalogs(limit)

    async def list_schemas(
        self,
        catalog_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List schemas in a catalog (not cached)."""
        return await self._catalog.list_schemas(catalog_name, limit)

    async def list_tables(
        self,
        catalog_name: str,
        schema_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List tables in a schema (not cached)."""
        return await self._catalog.list_tables(catalog_name, schema_name, limit)

    async def get_grants(
        self,
        securable_type: SecurableType,
        full_name: str,
    ) -> dict[str, Any] | None:
        """Get grants for a securable (not cached)."""
        return await self._catalog.get_grants(securable_type, full_name)

    # =========================================================================
    # Workspace Operations
    # =========================================================================

    async def get_notebook_content(self, notebook_path: str) -> str | None:
        """Get notebook content (not cached)."""
        return await self._workspace.get_notebook_content(notebook_path)

    async def read_dbfs_file(
        self,
        dbfs_path: str,
        max_bytes: int = 2_000_000,
    ) -> str | None:
        """Read text file from DBFS (not cached)."""
        return await self._workspace.read_dbfs_file(dbfs_path, max_bytes)

    async def dbfs_path_exists(self, dbfs_path: str) -> bool:
        """Check if DBFS path exists (not cached)."""
        return await self._workspace.dbfs_path_exists(dbfs_path)

    async def list_dbfs_files(
        self,
        dbfs_path: str,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """List DBFS files (not cached)."""
        return await self._workspace.list_dbfs_files(dbfs_path, recursive)

    # =========================================================================
    # Cache Management
    # =========================================================================

    async def clear_cache(self) -> None:
        """Clear all cached data."""
        if self._cache:
            await self._cache.clear()
            logger.debug("client_cache_cleared")

    async def invalidate_job(self, job_id: int) -> None:
        """Invalidate all cached data for a job."""
        if self._cache:
            await self._cache.invalidate(f"job:{job_id}")
            await self._cache.invalidate_pattern(f"job_runs:{job_id}:*")

    async def invalidate_cluster(self, cluster_id: str) -> None:
        """Invalidate cached cluster data."""
        if self._cache:
            await self._cache.invalidate(f"cluster:{cluster_id}")

    async def invalidate_warehouse(self, warehouse_id: str) -> None:
        """Invalidate cached warehouse data."""
        if self._cache:
            await self._cache.invalidate(f"warehouse:{warehouse_id}")

    async def invalidate_table(self, table_name: str) -> None:
        """Invalidate cached table data."""
        if self._cache:
            await self._cache.invalidate_pattern(f"table:{table_name}:*")
            await self._cache.invalidate_pattern(f"table_lineage:{table_name}:*")

    def get_cache_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics."""
        if self._cache:
            return self._cache.get_metrics()
        return {"enabled": False}

    # =========================================================================
    # Current User
    # =========================================================================

    async def get_current_user(self) -> dict[str, Any]:
        """Get current authenticated user."""

        def _get() -> dict[str, Any]:
            if self._sdk_client:
                return self._sdk_client.current_user.me().as_dict()
            return {}

        return await run_databricks_sync(_get)

    def is_authenticated(self) -> bool:
        """Check if client is authenticated (sync check)."""
        try:
            if self._sdk_client:
                self._sdk_client.current_user.me()
                return True
        except (DatabricksAPIError, OSError):
            pass
        return False
