# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Type-safe models for cached query results.

Ensures consistent structure across caching and retrieval operations,
preventing KeyError issues and providing validation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CachedQueryResult(BaseModel):
    """
    Type-safe model for cached query results.

    This model ensures consistency between cache writes (QueryResultCache.cache_result)
    and cache reads (visualization endpoint, data fetching).

    Attributes:
        rows: List of row dictionaries (JSON-serializable)
        columns: List of column names
        dtypes: Mapping of column name to dtype string
        row_count: Total number of rows
        query_id: Original query catalog ID (for debugging)
        cached_at: ISO timestamp when cached

    Examples:
        >>> result = CachedQueryResult(
        ...     rows=[{"id": 1, "cost": 100.0}, {"id": 2, "cost": 200.0}],
        ...     columns=["id", "cost"],
        ...     dtypes={"id": "Int64", "cost": "Float64"},
        ...     row_count=2,
        ...     query_id="b733352d-...",
        ...     cached_at="2025-11-28T14:00:00Z"
        ... )
    """

    rows: list[dict[str, Any]] = Field(
        ...,
        description="List of row dictionaries (JSON-serializable)",
    )
    columns: list[str] = Field(
        ...,
        description="List of column names",
    )
    dtypes: dict[str, str] = Field(
        ...,
        description="Mapping of column name to dtype string",
    )
    row_count: int = Field(
        ...,
        ge=0,
        description="Total number of rows",
    )
    query_id: str = Field(
        ...,
        description="Original query catalog ID (for debugging/auditing)",
    )
    cached_at: str = Field(
        ...,
        description="ISO timestamp when cached (for debugging/auditing)",
    )

    def to_polars(self) -> Any:
        """
        Convert cached data to Polars DataFrame.

        Returns:
            Polars DataFrame with original schema

        Examples:
            >>> result = CachedQueryResult(...)
            >>> df = result.to_polars()
            >>> df.columns
            ['id', 'cost']
        """
        import polars as pl

        return pl.DataFrame(self.rows)

    @classmethod
    def from_polars(
        cls,
        df: Any,  # pl.DataFrame
        query_id: str,
    ) -> CachedQueryResult:
        """
        Create CachedQueryResult from Polars DataFrame.

        Normalizes datetime columns to remove timezone info (Altair compatibility).
        Timezone-aware datetimes are converted to naive UTC datetimes.

        Args:
            df: Polars DataFrame to cache
            query_id: Query catalog ID

        Returns:
            CachedQueryResult instance

        Examples:
            >>> import polars as pl
            >>> df = pl.DataFrame({"id": [1, 2], "cost": [100.0, 200.0]})
            >>> result = CachedQueryResult.from_polars(df, "query-123")
        """
        from datetime import UTC, datetime

        import polars as pl

        # Normalize data types for Altair/Vega-Lite compatibility
        # 1. Datetime: Remove timezone (Altair only supports naive or 'UTC' string)
        # 2. Decimal: Convert to Float64 (Altair can't serialize Decimal to JSON)
        normalized_df = df
        for col in df.columns:
            dtype = df[col].dtype

            # Fix 1: Remove timezone from datetime columns
            if dtype == pl.Datetime:
                # Convert timezone-aware to naive UTC
                # Prevents: "Unsupported timezone zoneinfo.ZoneInfo(key='UTC')"
                normalized_df = normalized_df.with_columns(
                    pl.col(col).dt.replace_time_zone(None).alias(col)
                )

            # Fix 2: Convert Decimal to Float64
            elif dtype == pl.Decimal:
                # Databricks returns Decimal(precision=38, scale=6) for monetary values
                # Prevents: "Failed to parse vl_spec dict as JSON: unsupported type Decimal"
                normalized_df = normalized_df.with_columns(
                    pl.col(col).cast(pl.Float64).alias(col)
                )

        return cls(
            rows=normalized_df.to_dicts(),
            columns=normalized_df.columns,
            dtypes={
                col: str(dtype)
                for col, dtype in zip(normalized_df.columns, normalized_df.dtypes)
            },
            row_count=len(normalized_df),
            query_id=query_id,
            cached_at=datetime.now(UTC).isoformat(),
        )
