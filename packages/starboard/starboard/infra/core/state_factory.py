# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Factory functions for creating state providers.

Zero-store default (A3): only the driver-free in-memory adapters are imported at
module load. Driver-backed backends (sqlite/postgres/databricks/redis) are
imported lazily inside their selection branch and guarded by :func:`_require`,
which raises an actionable ``pip install 'starboard[<extra>]'`` error when the
matching optional dependency is absent. This keeps ``import state_factory`` (and
therefore the CLI / in-memory server) working on a no-extras install.
"""

from __future__ import annotations

import importlib

from starboard_core.ports.cache_store import CacheStore
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.state_store import StateStore

# In-memory adapters carry no external driver, so they stay top-level.
from starboard.adapters.state.inmemory import (
    InMemoryCacheStore,
    InMemoryMemoryStore,
    InMemoryStateStore,
)
from starboard.infra.core.config import EnvConfig
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


def _require(module: str, *, extra: str, backend: str) -> None:
    """Ensure a backend's driver is importable, else raise an actionable error.

    Args:
        module: The importable driver module name (e.g. ``"aiosqlite"``).
        extra: The starboard extra that provides it (e.g. ``"sqlite"``).
        backend: The selected backend name, for the error message.

    Raises:
        RuntimeError: If the driver is not installed, naming the exact
            ``pip install`` command to fix it.
    """
    try:
        importlib.import_module(module)
    except ImportError as e:
        raise RuntimeError(
            f"database_backend={backend!r} needs the {module!r} driver: "
            f"pip install 'starboard[{extra}]'"
        ) from e


def _uc_not_implemented() -> StateStore:
    """UC-native state is reserved for Phase 2 (C2)."""
    raise RuntimeError(
        "database_backend='uc' (Unity Catalog native state) is not yet "
        "implemented (Phase 2). Use 'memory' (default), 'sqlite', 'postgres', "
        "or 'databricks'."
    )


def create_state_store(config: EnvConfig) -> StateStore:
    """
    Create state store based on environment configuration.

    Args:
        config: Environment configuration

    Returns:
        StateStore implementation (in-memory, SQLite, Postgres, or Databricks Lakebase)

    Raises:
        ValueError: If configuration is invalid
        RuntimeError: If a driver-backed backend is selected without its extra
            installed, or if an unimplemented backend (``uc``) is selected.

    Environment Variables:
        ENVIRONMENT: "dev", "test", "staging", or "production"
        DATABASE_BACKEND: "memory" (default), "sqlite", "postgres", "databricks", or "uc"
        DATABASE_URL: PostgreSQL connection string (for postgres backend)
        SQLITE_STATE_PATH: SQLite database path (for sqlite backend)
        LAKEBASE_INSTANCE_NAME: Lakebase instance name (for databricks backend)
        LAKEBASE_DATABASE_NAME: Lakebase database name (for databricks backend)
    """
    if config.database_backend == "uc":
        return _uc_not_implemented()

    if config.environment == "dev":
        if config.database_backend == "sqlite":
            # Development: SQLite with file persistence
            _require("aiosqlite", extra="sqlite", backend="sqlite")
            from starboard.adapters.state.sqlite import SQLiteStateStore

            logger.debug(
                "creating_sqlite_state_store",
                environment=config.environment,
                db_path=config.sqlite_state_path,
            )
            return SQLiteStateStore(config.sqlite_state_path)
        else:
            # Development default: in-memory store (no external dependencies)
            logger.debug(
                "creating_inmemory_state_store",
                environment=config.environment,
            )
            return InMemoryStateStore()

    elif config.environment == "test":
        # Testing: In-memory SQLite (isolated per test). Drivers present in CI.
        _require("aiosqlite", extra="sqlite", backend="sqlite")
        from starboard.adapters.state.sqlite import SQLiteStateStore

        logger.debug(
            "creating_sqlite_state_store",
            environment=config.environment,
            db_path=":memory:",
        )
        return SQLiteStateStore(":memory:")

    elif config.environment in ("staging", "production"):
        if config.database_backend == "memory":
            logger.debug(
                "creating_inmemory_state_store",
                environment=config.environment,
            )
            return InMemoryStateStore()
        elif config.database_backend == "databricks":
            # Databricks Lakebase: PostgreSQL-compatible with OAuth
            _require("asyncpg", extra="postgres", backend="databricks")
            from starboard.adapters.state.databricks import (
                DatabricksLakebaseConfig,
                DatabricksLakebaseStateStore,
            )

            logger.debug(
                "creating_databricks_lakebase_state_store",
                environment=config.environment,
            )
            lakebase_config = DatabricksLakebaseConfig.from_env()
            store: StateStore = DatabricksLakebaseStateStore(lakebase_config)
            # Note: connect() should be called separately in app startup
            return store
        elif config.database_backend == "postgres":
            # Standard Postgres: Direct connection string
            if not config.database_url:
                raise ValueError(
                    f"DATABASE_URL required for environment: {config.environment}"
                )
            _require("asyncpg", extra="postgres", backend="postgres")
            from starboard.adapters.state.postgres import PostgresStateStore

            logger.debug(
                "creating_postgres_state_store",
                environment=config.environment,
                has_database_url=bool(config.database_url),
            )
            # Note: connect() should be called separately in app startup
            return PostgresStateStore(config.database_url)
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

    Raises:
        RuntimeError: If ``redis_url`` is set but the ``redis`` extra is not installed.

    Note:
        Uses Redis only when REDIS_URL is provided; otherwise falls back to the
        driver-free in-memory cache (the default).
    """
    if config.redis_url:
        # Use Redis if available (production/staging)
        _require("redis", extra="redis", backend="redis")
        from starboard.adapters.state.redis import RedisCacheStore

        # Note: connect() should be called separately in app startup
        return RedisCacheStore(config.redis_url)
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
        RuntimeError: If a driver-backed backend is selected without its extra
            installed, or if an unimplemented backend (``uc``) is selected.

    Environment Variables:
        ENVIRONMENT: "dev", "test", "staging", or "production"
        DATABASE_BACKEND: "memory" (default), "sqlite", "postgres", "databricks", or "uc"
        DATABASE_URL: PostgreSQL connection string (for postgres backend)
        SQLITE_MEMORY_PATH: SQLite database path (for sqlite backend)
        LAKEBASE_INSTANCE_NAME: Lakebase instance name (for databricks backend)
        LAKEBASE_DATABASE_NAME: Lakebase database name (for databricks backend)
    """
    if config.database_backend == "uc":
        raise RuntimeError(
            "database_backend='uc' (Unity Catalog native state) is not yet "
            "implemented (Phase 2). Use 'memory' (default), 'sqlite', 'postgres', "
            "or 'databricks'."
        )

    if config.environment == "dev":
        if config.database_backend == "sqlite":
            # Development: SQLite with file persistence and vector support
            _require("aiosqlite", extra="sqlite", backend="sqlite")
            from starboard.adapters.state.sqlite import SQLiteMemoryStore

            logger.debug(
                "creating_sqlite_memory_store",
                environment=config.environment,
                db_path=config.sqlite_memory_path,
            )
            return SQLiteMemoryStore(config.sqlite_memory_path)  # type: ignore[return-value]
        else:
            # Development default: in-memory store (simplified, no vector search)
            logger.debug(
                "creating_inmemory_memory_store",
                environment=config.environment,
            )
            return InMemoryMemoryStore()

    elif config.environment == "test":
        # Testing: In-memory SQLite (isolated per test). Drivers present in CI.
        _require("aiosqlite", extra="sqlite", backend="sqlite")
        from starboard.adapters.state.sqlite import SQLiteMemoryStore

        logger.debug(
            "creating_sqlite_memory_store",
            environment=config.environment,
            db_path=":memory:",
        )
        return SQLiteMemoryStore(":memory:")  # type: ignore[return-value]

    elif config.environment in ("staging", "production"):
        if config.database_backend == "memory":
            logger.debug(
                "creating_inmemory_memory_store",
                environment=config.environment,
            )
            return InMemoryMemoryStore()
        elif config.database_backend == "databricks":
            # Databricks Lakebase: PostgreSQL-compatible with pgvector support
            _require("asyncpg", extra="postgres", backend="databricks")
            from starboard.adapters.state.databricks import (
                DatabricksLakebaseConfig,
                DatabricksLakebaseMemoryStore,
            )

            lakebase_config = DatabricksLakebaseConfig.from_env()
            store: MemoryStore = DatabricksLakebaseMemoryStore(lakebase_config)
            # Note: connect() should be called separately in app startup
            return store
        elif config.database_backend == "postgres":
            # Standard Postgres: Direct connection string with pgvector
            if not config.database_url:
                raise ValueError(
                    f"DATABASE_URL required for environment: {config.environment}"
                )
            _require("asyncpg", extra="postgres", backend="postgres")
            from starboard.adapters.state.postgres import PostgresMemoryStore

            # Note: connect() should be called separately in app startup
            return PostgresMemoryStore(config.database_url)
        else:
            raise ValueError(
                f"Invalid database backend for {config.environment}: {config.database_backend}"
            )

    else:
        raise ValueError(f"Unknown environment: {config.environment}")
