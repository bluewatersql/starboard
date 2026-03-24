"""Factory functions for creating state providers."""

from starboard_core.ports.cache_store import CacheStore
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.state_store import StateStore

from starboard_server.adapters.state.databricks import (
    DatabricksLakebaseConfig,
    DatabricksLakebaseMemoryStore,
    DatabricksLakebaseStateStore,
)
from starboard_server.adapters.state.inmemory import (
    InMemoryCacheStore,
    InMemoryMemoryStore,
    InMemoryStateStore,
)
from starboard_server.adapters.state.postgres import (
    PostgresMemoryStore,
    PostgresStateStore,
)
from starboard_server.adapters.state.redis import RedisCacheStore
from starboard_server.adapters.state.sqlite import (
    SQLiteMemoryStore,
    SQLiteStateStore,
)
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


def create_state_store(config: EnvConfig) -> StateStore:
    """
    Create state store based on environment configuration.

    Args:
        config: Environment configuration

    Returns:
        StateStore implementation (in-memory, SQLite, Postgres, or Databricks Lakebase)

    Raises:
        ValueError: If configuration is invalid

    Environment Variables:
        ENVIRONMENT: "dev", "test", "staging", or "production"
        DATABASE_BACKEND: "sqlite", "postgres", or "databricks" (default: "postgres")
        DATABASE_URL: PostgreSQL connection string (for postgres backend)
        SQLITE_STATE_PATH: SQLite database path (for sqlite backend)
        LAKEBASE_INSTANCE_NAME: Lakebase instance name (for databricks backend)
        LAKEBASE_DATABASE_NAME: Lakebase database name (for databricks backend)
    """
    if config.environment == "dev":
        if config.database_backend == "sqlite":
            # Development: SQLite with file persistence
            logger.debug(
                "creating_sqlite_state_store",
                environment=config.environment,
                db_path=config.sqlite_state_path,
            )
            return SQLiteStateStore(config.sqlite_state_path)
        else:
            # Development: In-memory store (no external dependencies)
            logger.debug(
                "creating_inmemory_state_store",
                environment=config.environment,
            )
            return InMemoryStateStore()

    elif config.environment == "test":
        # Testing: In-memory SQLite (isolated per test)
        logger.debug(
            "creating_sqlite_state_store",
            environment=config.environment,
            db_path=":memory:",
        )
        return SQLiteStateStore(":memory:")

    elif config.environment in ("staging", "production"):
        if config.database_backend == "databricks":
            # Databricks Lakebase: PostgreSQL-compatible with OAuth
            logger.debug(
                "creating_databricks_lakebase_state_store",
                environment=config.environment,
            )
            lakebase_config = DatabricksLakebaseConfig.from_env()
            store = DatabricksLakebaseStateStore(lakebase_config)
            # Note: connect() should be called separately in app startup
            return store
        elif config.database_backend == "postgres":
            # Standard Postgres: Direct connection string
            if not config.database_url:
                raise ValueError(
                    f"DATABASE_URL required for environment: {config.environment}"
                )

            logger.debug(
                "creating_postgres_state_store",
                environment=config.environment,
                has_database_url=bool(config.database_url),
            )
            store = PostgresStateStore(config.database_url)  # type: ignore[assignment]
            # Note: connect() should be called separately in app startup
            return store
        else:
            raise ValueError(
                f"Invalid database backend for {config.environment}: {config.database_backend}"
            )

    else:
        raise ValueError(f"Unknown environment: {config.environment}")


def create_cache_store(config: EnvConfig) -> CacheStore:
    """
    Create cache store based on environment configuration.

    Args:
        config: Environment configuration

    Returns:
        CacheStore implementation (Redis or in-memory)

    Note:
        Always tries Redis first if REDIS_URL is provided,
        falls back to in-memory if not available.
    """
    if config.redis_url:
        # Use Redis if available (production/staging)
        store = RedisCacheStore(config.redis_url)
        # Note: connect() should be called separately in app startup
        return store
    else:
        # Fallback to in-memory (development or when Redis not available)
        return InMemoryCacheStore(max_size=1000)


def create_memory_store(config: EnvConfig) -> MemoryStore:
    """
    Create memory store based on environment configuration.

    Args:
        config: Environment configuration

    Returns:
        MemoryStore implementation (in-memory, SQLite, Postgres, or Databricks Lakebase)

    Raises:
        ValueError: If configuration is invalid

    Environment Variables:
        ENVIRONMENT: "dev", "test", "staging", or "production"
        DATABASE_BACKEND: "sqlite", "postgres", or "databricks" (default: "postgres")
        DATABASE_URL: PostgreSQL connection string (for postgres backend)
        SQLITE_MEMORY_PATH: SQLite database path (for sqlite backend)
        LAKEBASE_INSTANCE_NAME: Lakebase instance name (for databricks backend)
        LAKEBASE_DATABASE_NAME: Lakebase database name (for databricks backend)
    """
    if config.environment == "dev":
        if config.database_backend == "sqlite":
            # Development: SQLite with file persistence and vector support
            logger.debug(
                "creating_sqlite_memory_store",
                environment=config.environment,
                db_path=config.sqlite_memory_path,
            )
            return SQLiteMemoryStore(config.sqlite_memory_path)  # type: ignore[return-value]
        else:
            # Development: In-memory store (simplified, no vector search)
            logger.debug(
                "creating_inmemory_memory_store",
                environment=config.environment,
            )
            return InMemoryMemoryStore()

    elif config.environment == "test":
        # Testing: In-memory SQLite (isolated per test)
        logger.debug(
            "creating_sqlite_memory_store",
            environment=config.environment,
            db_path=":memory:",
        )
        return SQLiteMemoryStore(":memory:")  # type: ignore[return-value]

    elif config.environment in ("staging", "production"):
        if config.database_backend == "databricks":
            # Databricks Lakebase: PostgreSQL-compatible with pgvector support
            lakebase_config = DatabricksLakebaseConfig.from_env()
            store = DatabricksLakebaseMemoryStore(lakebase_config)
            # Note: connect() should be called separately in app startup
            return store
        elif config.database_backend == "postgres":
            # Standard Postgres: Direct connection string with pgvector
            if not config.database_url:
                raise ValueError(
                    f"DATABASE_URL required for environment: {config.environment}"
                )

            store = PostgresMemoryStore(config.database_url)  # type: ignore[assignment]
            # Note: connect() should be called separately in app startup
            return store
        else:
            raise ValueError(
                f"Invalid database backend for {config.environment}: {config.database_backend}"
            )

    else:
        raise ValueError(f"Unknown environment: {config.environment}")
