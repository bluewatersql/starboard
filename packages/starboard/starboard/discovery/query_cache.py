# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery result caching — dedupe hot-table scans within and across runs.

Discovery packs share hot ``system.*`` tables (``system.billing.usage`` is
scanned by many packs), so identical rendered scans are executed repeatedly in
a single run. This cache sits between :mod:`starboard.discovery.executor` and
the SQL client and provides two things:

1. **In-run deduplication** — concurrent, identical scans coalesce onto a
   single in-flight execution (biggest win; ``system.billing.usage`` etc.).
2. **Cross-run TTL caching** — results are held in a
   :class:`~starboard_core.ports.cache_store.CacheStore` (in-memory by default)
   for a bounded *freshness floor* so a fresh run reuses recent scans.

The cache key is ``sha256(rendered_sql + '|' + workspace_id)``. Because the
executor renders ``{lookback_days}``/``{result_limit}`` before caching, the key
already folds in ``sql_template + resolved_params + lookback``; the workspace is
mixed in explicitly so two workspaces never share a cached scan.

DataFrames are held in-process (no serialization), so cached results are
byte-for-byte identical to a fresh scan — this cache is a performance
optimization, never a data transformation.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    import polars as pl
    from starboard_core.ports.cache_store import CacheStore

logger = get_logger(__name__)

# Default freshness floor: served entries must be younger than this. Keeps the
# cross-run cache from serving stale scans of volatile tables. Tuned for a
# single discovery run plus rapid re-runs; billing has a daily grain.
DEFAULT_FRESHNESS_FLOOR_S = 900

Loader = Callable[[], Awaitable["pl.DataFrame"]]


class DiscoveryQueryCache:
    """Coalescing + TTL cache for discovery SQL scans.

    Args:
        cache_store: Backing key-value store. Defaults to an in-memory store.
        freshness_floor_s: Maximum age (seconds) a cached scan may have and
            still be served. Older entries are re-executed. This is the
            executor's *freshness floor* for time-sensitive queries.
    """

    def __init__(
        self,
        cache_store: CacheStore | None = None,
        freshness_floor_s: int = DEFAULT_FRESHNESS_FLOOR_S,
    ) -> None:
        if cache_store is None:
            from starboard.adapters.state.inmemory.cache_store import (
                InMemoryCacheStore,
            )

            cache_store = InMemoryCacheStore()
        self._store = cache_store
        self._freshness_floor_s = freshness_floor_s
        # In-run coalescing: key -> in-flight future for the running scan.
        self._inflight: dict[str, asyncio.Future[pl.DataFrame]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(rendered_sql: str, workspace_id: str | None) -> str:
        """Build the cache key from rendered SQL and workspace.

        Args:
            rendered_sql: SQL with ``{lookback_days}``/``{result_limit}`` already
                substituted (so params + lookback are folded into the key).
            workspace_id: Workspace scope, or ``None`` for the default workspace.

        Returns:
            A stable ``sha256`` hex digest.
        """
        payload = f"{rendered_sql}|{workspace_id or ''}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def get_or_execute(self, key: str, loader: Loader) -> pl.DataFrame:
        """Return a cached scan or execute ``loader`` exactly once for ``key``.

        Concurrent callers for the same key await a single in-flight execution
        (in-run dedup); a subsequent call within the freshness floor is served
        from the store (cross-run dedup).

        Args:
            key: Cache key from :meth:`make_key`.
            loader: Zero-arg coroutine that performs the actual SQL scan.

        Returns:
            The scan's ``polars.DataFrame`` (shared reference on a hit).
        """
        cached = await self._store.get(key)
        if cached is not None:
            logger.debug("discovery_cache_hit", key=key[:12])
            return cached

        async with self._lock:
            # Re-check under the lock to close the miss/register race.
            cached = await self._store.get(key)
            if cached is not None:
                return cached
            existing = self._inflight.get(key)
            if existing is not None:
                fut = existing
                is_owner = False
            else:
                fut = asyncio.get_event_loop().create_future()
                self._inflight[key] = fut
                is_owner = True

        if not is_owner:
            logger.debug("discovery_cache_coalesced", key=key[:12])
            return await fut

        try:
            df = await loader()
        except Exception as exc:
            fut.set_exception(exc)
            raise
        else:
            await self._store.set(key, df, ttl=self._freshness_floor_s)
            fut.set_result(df)
            return df
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

    async def clear(self) -> None:
        """Drop all cached scans."""
        await self._store.clear()
