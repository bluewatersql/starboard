# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Databricks Lakebase state store implementation."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from typing import Any

import asyncpg
from databricks.sdk import WorkspaceClient

from starboard.adapters.state.databricks.config import DatabricksLakebaseConfig
from starboard.adapters.state.postgres.state_store import PostgresStateStore
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class DatabricksLakebaseStateStore(PostgresStateStore):
    """

    Databricks Lakebase-backed conversation state store.

    Extends PostgresStateStore with Databricks OAuth token management:
    - Automatic token refresh every 50 minutes (tokens expire after 1 hour)
    - Databricks SDK integration for credential generation
    - PostgreSQL-compatible via asyncpg
    - SSL-required connections

    Architecture:
        Lakebase is Databricks' managed PostgreSQL service. This adapter extends
        the existing PostgreSQL adapter and adds automatic OAuth token refresh
        via a background task.

    Reference:
        https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection

    Example:
        ```python
        config = DatabricksLakebaseConfig.from_env()
        store = DatabricksLakebaseStateStore(config)
        await store.connect()

        # Use like a regular PostgreSQL store
        conversation = await store.get_conversation("conv-123")

        # Token refresh happens automatically in background
        await store.close()
        ```
    """

    def __init__(self, config: DatabricksLakebaseConfig):
        """
        Initialize Databricks Lakebase state store.

        Args:
            config: Databricks Lakebase configuration

        Raises:
            ValueError: If configuration is invalid
        """
        config.validate()
        self._config = config
        self._sdk_client: WorkspaceClient | None = None
        self._database_instance: Any = None
        self._current_password: str | None = None
        self._last_password_refresh: float = 0
        self._token_refresh_task: asyncio.Task[None] | None = None

        # PostgresStateStore expects connection_string in __init__
        # We'll set it to empty and override in connect()
        super().__init__("")

    @property
    def sdk_client(self) -> WorkspaceClient:
        """Get the SDK client, raising if not connected."""
        if self._sdk_client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._sdk_client

    @property
    def database_instance(self) -> Any:
        """Get the database instance, raising if not connected."""
        if self._database_instance is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._database_instance

    async def connect(self) -> None:
        """
        Initialize connection pool with automatic token refresh.

        Steps:
            1. Initialize Databricks SDK client
            2. Get database instance details from workspace
            3. Generate initial OAuth credentials
            4. Build PostgreSQL connection string
            5. Initialize asyncpg connection pool
            6. Start background token refresh task
        """
        logger.debug(
            "databricks_lakebase_connect_start",
            instance=self._config.instance_name,
        )

        # Initialize Databricks SDK client
        self._sdk_client = WorkspaceClient()

        # Get database instance details
        self._database_instance = self._sdk_client.database.get_database_instance(
            name=self._config.instance_name
        )

        # Generate initial OAuth credentials
        await self._refresh_credentials()

        # Build PostgreSQL connection string with resolved credentials
        username = (
            os.getenv("DATABRICKS_CLIENT_ID")
            or self.sdk_client.current_user.me().user_name
        )

        connection_string = (
            f"postgresql://{username}:{self._current_password}"
            f"@{self.database_instance.read_write_dns}:{self._config.port}"
            f"/{self._config.database_name}"
            f"?ssl=require"  # Lakebase requires SSL
            f"&command_timeout={self._config.command_timeout}"
        )

        # Initialize asyncpg connection pool via parent class
        self._pool = await asyncpg.create_pool(
            connection_string,
            min_size=self._config.pool_size,
            max_size=self._config.pool_size + self._config.max_overflow,
            command_timeout=self._config.command_timeout,
        )

        # Start background token refresh task (every 50 minutes)
        self._token_refresh_task = asyncio.create_task(self._refresh_token_background())

        logger.debug(
            "databricks_lakebase_connect_complete",
            instance=self._config.instance_name,
            host=self.database_instance.read_write_dns,
            pool_size=self._config.pool_size,
        )

    async def close(self) -> None:
        """Close connection pool and stop token refresh task."""
        logger.debug(
            "databricks_lakebase_close_start", instance=self._config.instance_name
        )

        # Stop token refresh task
        if self._token_refresh_task and not self._token_refresh_task.done():
            self._token_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._token_refresh_task

        # Close connection pool via parent class
        await super().close()

        logger.debug(
            "databricks_lakebase_close_complete", instance=self._config.instance_name
        )

    async def _refresh_credentials(self) -> None:
        """
        Refresh OAuth credentials from Databricks.

        Generates a new OAuth token for PostgreSQL authentication.
        Tokens expire after 1 hour, so we refresh every 50 minutes.
        """
        logger.debug(
            "databricks_token_refresh_start",
            instance=self._config.instance_name,
        )

        # Generate new database credentials via Databricks SDK
        cred = self.sdk_client.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[self.database_instance.name],
        )

        self._current_password = cred.token
        self._last_password_refresh = time.time()

        logger.debug(
            "databricks_token_refresh_complete",
            instance=self._config.instance_name,
            age_seconds=0,
        )

    async def _refresh_token_background(self) -> None:
        """
        Background task to refresh tokens every 50 minutes.

        OAuth tokens expire after 1 hour. We refresh at 50 minutes
        to ensure continuous connectivity with a safety margin.
        """
        while True:
            try:
                # Sleep for 50 minutes
                await asyncio.sleep(50 * 60)

                logger.debug(
                    "databricks_token_background_refresh_start",
                    instance=self._config.instance_name,
                    last_refresh_age=time.time() - self._last_password_refresh,
                )

                # Refresh credentials
                await self._refresh_credentials()

                # Recreate connection pool with new credentials
                await self._recreate_pool()

                logger.debug(
                    "databricks_token_background_refresh_complete",
                    instance=self._config.instance_name,
                )

            except asyncio.CancelledError:
                logger.debug(
                    "databricks_token_background_refresh_cancelled",
                    instance=self._config.instance_name,
                )
                break
            except (asyncpg.PostgresError, OSError) as e:
                logger.error(
                    "databricks_token_background_refresh_error",
                    instance=self._config.instance_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Continue running even if refresh fails
                # Next iteration will retry

    async def _recreate_pool(self) -> None:
        """
        Recreate connection pool with new credentials.

        Called after token refresh to ensure new connections use the fresh token.
        Existing connections will be recycled according to pool_recycle setting.
        """
        if self._pool:
            await self._pool.close()

        # Update connection string with new password
        username = (
            os.getenv("DATABRICKS_CLIENT_ID")
            or self.sdk_client.current_user.me().user_name
        )

        connection_string = (
            f"postgresql://{username}:{self._current_password}"
            f"@{self.database_instance.read_write_dns}:{self._config.port}"
            f"/{self._config.database_name}"
            f"?ssl=require"
            f"&command_timeout={self._config.command_timeout}"
        )

        # Recreate pool
        self._pool = await asyncpg.create_pool(
            connection_string,
            min_size=self._config.pool_size,
            max_size=self._config.pool_size + self._config.max_overflow,
            command_timeout=self._config.command_timeout,
        )

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""

    # All CRUD methods are inherited from PostgresStateStore
    # No need to override - they use self._pool which is managed above
