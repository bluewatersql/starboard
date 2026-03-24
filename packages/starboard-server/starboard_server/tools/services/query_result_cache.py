"""Query result cache for visualization data references.

This module provides Layer 2 caching for query results, enabling frontend
chart/table toggle without re-querying the backend. Complements Layer 1
(Databricks API cache) with longer TTL and frontend-oriented structure.

Caching Strategy:
    - Layer 1 (API Cache): sql:{hash}:{warehouse} - 5min TTL - Reduce API calls
    - Layer 2 (This file): data_ref_{hash} - 60min TTL - Frontend data fetching

Design Principles:
    - data_reference as unique key for cached results
    - Serialize DataFrames to JSON-compatible dict
    - 60-minute TTL with reset-on-hit (keeps hot data warm)
    - Target 80% hit rate for chart/table toggle

MIGRATION (Phase 4):
    - Now uses CacheStore protocol instead of concrete InMemoryCacheStore
    - Wraps with NamespacedCache for key isolation ("data" namespace)
    - Supports both InMemory and Redis backends via DI
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, cast

import polars as pl
from starboard_core.ports.cache_store import CacheMetrics, CacheStore

from starboard_server.infra.core.namespaced_cache import NamespacedCache
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.serialization import json_dumps_sorted as _json_dumps_sorted
from starboard_server.tools.domain.utils import polars_df_to_dict

logger = get_logger(__name__)


def generate_data_reference(query_id: str, parameters: dict[str, Any]) -> str:
    """Generate unique data_reference for query result (V1 - template-based queries).

    data_reference format: data_ref_{hash}
    Hash includes: query_id + sorted parameters + minute timestamp

    Args:
        query_id: Query identifier from catalog
        parameters: Query parameters (filters, date ranges, etc.)

    Returns:
        Unique data_reference string

    Examples:
        >>> generate_data_reference(
        ...     "b733352d-...",
        ...     {"start_date": "2024-11-01", "end_date": "2024-11-30"}
        ... )
        'data_ref_a7f3e2b1c9d4...'
    """
    # Sort parameters for deterministic hash (order-invariant)
    params_str = _json_dumps_sorted(parameters)

    # Include minute-level timestamp (same within 1 minute)
    minute_ts = int(time.time() / 60)

    # Generate hash
    key_parts = f"{query_id}:{params_str}:{minute_ts}"
    key_hash = hashlib.sha256(key_parts.encode()).hexdigest()[:16]

    return f"data_ref_{key_hash}"


def generate_data_reference_from_sql(
    sql: str, *, sql_cache_key: str | None = None
) -> str:
    """Generate unique data_reference from normalized SQL (V2/V3 - dynamic queries).

    Uses hash of normalized SQL as cache key. Sqlglot normalization ensures
    semantically equivalent queries share the same cache entry.

    data_reference format: data_ref_sql_{hash}

    Args:
        sql: SQL statement
        sql_cache_key: Cache key for SQL
    Returns:
        Unique data_reference string
    """
    if sql_cache_key:
        return f"data_ref_sql_{sql_cache_key}"
    else:
        # Hash normalized SQL (sqlglot ensures semantic equivalence)
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()[:16]

        return f"data_ref_sql_{sql_hash}"


class QueryResultCache:
    """Cache for query result DataFrames.

    Provides Layer 2 caching for frontend data fetching. Results are stored
    as JSON-compatible dicts with rows, columns, dtypes, and row_count.

    MIGRATION (Phase 4):
        - Now accepts CacheStore protocol instead of concrete InMemoryCacheStore
        - Uses NamespacedCache internally for key isolation
        - Supports both InMemory and Redis backends

    Attributes:
        default_ttl: Default time-to-live in seconds (default: 60 minutes)

    Examples:
        >>> from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
        >>> store = InMemoryCacheStore()
        >>> result_cache = QueryResultCache(store, default_ttl=600)
        >>> df = pl.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
        >>> data_ref = await result_cache.cache_result("query-123", {}, df)
        >>> data_ref
        'data_ref_a7f3e2b1c9d4...'
        >>> cached = await result_cache.get_cached_data(data_ref)
        >>> cached.keys()
        dict_keys(['rows', 'columns', 'dtypes', 'row_count'])
    """

    def __init__(
        self,
        cache_store: CacheStore,
        default_ttl: int = 3600,
        namespace: str = "data",
    ):
        """Initialize query result cache.

        Args:
            cache_store: Cache store implementation (InMemory or Redis).
                         Accepts CacheStore protocol for backend flexibility.
            default_ttl: Default time-to-live in seconds (default: 60 minutes)
            namespace: Cache key namespace (default: "data")

        Note:
            This cache explicitly enables TTL reset-on-hit for get operations
            to keep frequently accessed data warm. This is ideal for chart/table
            toggle scenarios where users actively explore data.
        """
        self._store = NamespacedCache(cache_store, namespace=namespace)
        self.default_ttl = default_ttl

        logger.debug(
            "query_result_cache_initialized",
            default_ttl=default_ttl,
            namespace=namespace,
        )

    async def cache_result(
        self,
        query_id: str,
        parameters: dict[str, Any],
        df: pl.DataFrame,
        ttl: int | None = None,
    ) -> str:
        """Cache query result and return data_reference (V1 - template-based queries).

        Args:
            query_id: Query identifier from catalog
            parameters: Query parameters used
            df: Query result DataFrame
            ttl: Optional TTL override (uses default_ttl if None)

        Returns:
            Unique data_reference string for retrieving cached data

        Examples:
            >>> df = pl.DataFrame({"id": [1, 2], "cost": [100.0, 200.0]})
            >>> data_ref = await cache.cache_result(
            ...     "b733352d-...",
            ...     {"start_date": "2024-11-01"},
            ...     df,
            ... )
            >>> data_ref
            'data_ref_a7f3e2b1c9d4...'
        """
        # Generate unique reference
        data_reference = generate_data_reference(query_id, parameters)

        # Normalize data types for Altair/Vega-Lite compatibility
        # 1. Datetime: Remove timezone (Altair only supports naive or 'UTC' string)
        # 2. Decimal: Convert to Float64 (Altair can't serialize Decimal to JSON)
        normalized_df = df
        datetime_cols_normalized = []
        decimal_cols_normalized = []

        for col in df.columns:
            dtype = df[col].dtype

            # Fix 1: Remove timezone from datetime columns
            # BUGFIX: dtype == pl.Datetime only matches base Datetime, not Datetime(time_zone='UTC')
            # Use hasattr to detect ANY Datetime variant, especially timezone-aware ones
            is_datetime = hasattr(dtype, "time_zone") or str(dtype).startswith(
                "Datetime"
            )
            if is_datetime:
                # Check if it has a timezone that needs to be removed
                if hasattr(dtype, "time_zone") and dtype.time_zone is not None:
                    normalized_df = normalized_df.with_columns(
                        pl.col(col).dt.replace_time_zone(None).alias(col)
                    )
                    datetime_cols_normalized.append(col)

            # Fix 2: Convert Decimal to Float64
            # Databricks returns Decimal(precision=38, scale=6) for monetary values
            # JSON/Altair can't handle Decimal objects → convert to float
            # BUGFIX: dtype == pl.Decimal doesn't match Decimal(precision=38, scale=18)
            elif str(dtype).startswith("Decimal"):
                normalized_df = normalized_df.with_columns(
                    pl.col(col).cast(pl.Float64).alias(col)
                )
                decimal_cols_normalized.append(col)

        if datetime_cols_normalized:
            logger.debug(
                "normalized_datetime_columns",
                data_reference=data_reference,
                columns=datetime_cols_normalized,
                note="Removed timezone for Altair compatibility",
            )

        if decimal_cols_normalized:
            logger.debug(
                "normalized_decimal_columns",
                data_reference=data_reference,
                columns=decimal_cols_normalized,
                note="Converted Decimal to Float64 for JSON serialization",
            )

        # Serialize DataFrame
        cached_data = {
            "rows": normalized_df.to_dicts(),
            "columns": normalized_df.columns,
            "dtypes": {
                col: str(dtype)
                for col, dtype in zip(normalized_df.columns, normalized_df.dtypes)
            },
            "row_count": len(normalized_df),
        }

        # Cache with TTL
        cache_ttl = ttl if ttl is not None else self.default_ttl
        await self._store.set(data_reference, cached_data, ttl=cache_ttl)

        logger.debug(
            "query_result_cached",
            data_reference=data_reference,
            query_id=query_id,
            row_count=len(df),
            column_count=len(df.columns),
            ttl=cache_ttl,
        )

        return data_reference

    async def cache_result_by_sql(
        self,
        sql: str,
        df: pl.DataFrame,
        ttl: int | None = None,
        *,
        sql_cache_key: str | None = None,
    ) -> str:
        """Cache query result by normalized SQL (V2/V3 - dynamic queries).

        Uses hash of normalized SQL as cache key. Sqlglot normalization ensures
        semantically equivalent queries share the same cache entry.

        Args:
            sql: SQL statement
            df: Query result DataFrame
            ttl: Optional TTL override (uses default_ttl if None)
            sql_cache_key: Cache key for SQL
        Returns:
            Unique data_reference string for retrieving cached data
        """
        # Generate unique reference from SQL
        data_reference = generate_data_reference_from_sql(
            sql, sql_cache_key=sql_cache_key
        )

        cached_data = polars_df_to_dict(df)

        # Cache with TTL
        cache_ttl = ttl if ttl is not None else self.default_ttl
        await self._store.set(data_reference, cached_data, ttl=cache_ttl)

        logger.debug(
            "query_result_cached_by_sql",
            data_reference=data_reference,
            sql_preview=sql[:100],
            row_count=len(df),
            column_count=len(df.columns),
            ttl=cache_ttl,
        )

        return data_reference

    async def get_cached_data(self, data_reference: str) -> dict[str, Any]:
        """Retrieve cached query results.

        Uses reset_ttl=True to keep frequently accessed data warm.
        This is ideal for chart/table toggle scenarios where users
        actively explore data - TTL resets on each access.

        Args:
            data_reference: Unique reference from cache_result()

        Returns:
            Dict with rows, columns, dtypes, row_count

        Raises:
            ValueError: If data_reference not found or expired

        Examples:
            >>> data = await cache.get_cached_data("data_ref_a7f3e2b1c9d4...")
            >>> data.keys()
            dict_keys(['rows', 'columns', 'dtypes', 'row_count'])
            >>> len(data['rows'])
            10
        """
        # Explicit opt-in to reset_ttl for chart/table toggle scenarios
        cached = await self._store.get(data_reference, reset_ttl=True)

        if cached is None:
            logger.warning(
                "query_result_cache_miss",
                data_reference=data_reference,
            )
            raise ValueError(f"Data reference {data_reference} not found or expired")

        logger.debug(
            "query_result_cache_hit",
            data_reference=data_reference,
            row_count=cached.get("row_count", 0),
        )

        return cast(dict[str, Any], cached)

    async def clear(self) -> None:
        """Clear all cached query results.

        Examples:
            >>> await cache.clear()
        """
        await self._store.clear()
        logger.debug("query_result_cache_cleared")

    def get_metrics(self) -> CacheMetrics:
        """Get cache metrics for this cache.

        Returns:
            CacheMetrics with hits, misses, hit_rate

        Examples:
            >>> metrics = cache.get_metrics()
            >>> metrics.hit_rate
            0.85
        """
        return self._store.get_metrics()
