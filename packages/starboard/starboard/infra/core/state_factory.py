# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Factory functions for creating state providers.

State is memory-only (native-first simplification): conversation and long-term
memory state are ephemeral, in-process, driver-free. The non-memory database
backends (sqlite / postgres / Databricks Lakebase / UC-native) were removed;
``database_backend`` is ``"memory"``. Durable CLI session persistence is
provided separately by the JSON-file ``SessionManager``.

The only driver-backed option here is the optional Redis cache, selected when
``redis_url`` is set and guarded by :func:`_require` (an actionable
``pip install 'starboard[redis]'`` error when the driver is absent). This keeps
``import state_factory`` (and therefore the CLI / in-memory server) working on a
no-extras install.
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
        module: The importable driver module name (e.g. ``"redis"``).
        extra: The starboard extra that provides it (e.g. ``"redis"``).
        backend: The selected backend name, for the error message.

    Raises:
        RuntimeError: If the driver is not installed, naming the exact
            ``pip install`` command to fix it.
    """
    try:
        importlib.import_module(module)
    except ImportError as e:
        raise RuntimeError(
            f"{backend!r} backend needs the {module!r} driver: "
            f"pip install 'starboard[{extra}]'"
        ) from e


def create_state_store(config: EnvConfig) -> StateStore:
    """Create the in-memory conversation state store (memory-only)."""
    logger.debug("creating_inmemory_state_store", environment=config.environment)
    return InMemoryStateStore()


def create_cache_store(config: EnvConfig) -> CacheStore:
    """Create the cache store: Redis when ``redis_url`` is set, else in-memory.

    Raises:
        RuntimeError: If ``redis_url`` is set but the ``redis`` extra is absent.
    """
    if config.redis_url:
        _require("redis", extra="redis", backend="redis")
        from starboard.adapters.state.redis import RedisCacheStore

        # Note: connect() should be called separately in app startup.
        return RedisCacheStore(config.redis_url)
    return InMemoryCacheStore(max_size=1000)


def create_memory_store(config: EnvConfig) -> MemoryStore:
    """Create the in-memory long-term memory store (memory-only)."""
    logger.debug("creating_inmemory_memory_store", environment=config.environment)
    return InMemoryMemoryStore()
