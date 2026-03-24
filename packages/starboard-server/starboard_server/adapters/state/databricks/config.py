"""Databricks Lakebase configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabricksLakebaseConfig:
    """
    Configuration for Databricks Lakebase adapter.

    Lakebase is Databricks' managed PostgreSQL service with OAuth authentication.
    This config minimizes Databricks-specific configuration by using SDK defaults.

    Args:
        instance_name: Lakebase instance name (from Databricks workspace)
        database_name: Database name within the Lakebase instance
        pool_size: Connection pool size (default: 5)
        max_overflow: Maximum overflow connections (default: 10)
        pool_timeout: Pool connection timeout in seconds (default: 10)
        pool_recycle_interval: Connection recycle interval in seconds (default: 3600)
        command_timeout: SQL command timeout in seconds (default: 30)
        port: PostgreSQL port (default: 5432)

    Environment Variables:
        LAKEBASE_INSTANCE_NAME: Instance name (required)
        LAKEBASE_DATABASE_NAME: Database name (required)
        DATABRICKS_CLIENT_ID: OAuth client ID (optional, falls back to current user)
        DB_POOL_SIZE: Pool size (default: 5)
        DB_MAX_OVERFLOW: Max overflow (default: 10)
        DB_POOL_TIMEOUT: Pool timeout seconds (default: 10)
        DB_POOL_RECYCLE_INTERVAL: Recycle interval seconds (default: 3600)
        DB_COMMAND_TIMEOUT: Command timeout seconds (default: 30)
        DATABRICKS_DATABASE_PORT: Port (default: 5432)

    Reference:
        https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection
    """

    # Required settings
    instance_name: str
    database_name: str

    # Connection pool settings with defaults (aligned with Lakebase recommendations)
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 10
    pool_recycle_interval: int = 3600  # 1 hour
    command_timeout: int = 30
    port: int = 5432

    @classmethod
    def from_env(cls) -> "DatabricksLakebaseConfig":
        """
        Load configuration from environment variables.

        Returns:
            DatabricksLakebaseConfig instance with values from environment

        Raises:
            ValueError: If required environment variables are missing

        Example:
            ```python
            # Set environment variables
            os.environ["LAKEBASE_INSTANCE_NAME"] = "my-lakebase"
            os.environ["LAKEBASE_DATABASE_NAME"] = "starboard_db"

            # Load config
            config = DatabricksLakebaseConfig.from_env()
            ```
        """
        instance_name = os.getenv("LAKEBASE_INSTANCE_NAME")
        database_name = os.getenv("LAKEBASE_DATABASE_NAME")

        if not instance_name:
            raise ValueError("LAKEBASE_INSTANCE_NAME environment variable is required")
        if not database_name:
            raise ValueError("LAKEBASE_DATABASE_NAME environment variable is required")

        return cls(
            instance_name=instance_name,
            database_name=database_name,
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
            pool_recycle_interval=int(os.getenv("DB_POOL_RECYCLE_INTERVAL", "3600")),
            command_timeout=int(os.getenv("DB_COMMAND_TIMEOUT", "30")),
            port=int(os.getenv("DATABRICKS_DATABASE_PORT", "5432")),
        )

    def validate(self) -> None:
        """
        Validate configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if not self.instance_name:
            raise ValueError("instance_name cannot be empty")
        if not self.database_name:
            raise ValueError("database_name cannot be empty")
        if self.pool_size <= 0:
            raise ValueError("pool_size must be positive")
        if self.max_overflow < 0:
            raise ValueError("max_overflow must be non-negative")
        if self.pool_timeout <= 0:
            raise ValueError("pool_timeout must be positive")
        if self.pool_recycle_interval <= 0:
            raise ValueError("pool_recycle_interval must be positive")
        if self.command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("port must be between 1 and 65535")
