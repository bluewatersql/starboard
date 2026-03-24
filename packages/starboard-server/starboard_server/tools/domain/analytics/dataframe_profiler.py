"""Dynamic DataFrame profiling for LLM consumption.

This module provides comprehensive profiling of Polars DataFrames to generate
rich summaries for LLM analysis, including:
- Column metadata (types, nulls, unique counts)
- Numeric statistics (min, max, mean, std, quantiles)
- Categorical distributions (top values for low-cardinality columns)
- Temporal ranges and optional time-series trend analysis
- Sample rows for context
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import polars as pl


def _serialize_value(value: Any) -> Any:
    """Convert non-JSON-serializable types to JSON-safe equivalents.

    Handles Decimal, datetime, date, and nested structures.
    """
    if isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, (datetime, date)):
        return value.isoformat()
    elif isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    else:
        return value


def profile_dataframe(
    df: pl.DataFrame,
    *,
    max_categories: int = 30,
    max_top_values: int = 10,
    sample_rows: int = 20,
    trend_time_column: str | None = None,
    trend_metric_column: str | None = None,
) -> dict[str, Any]:
    """Dynamically summarize a Polars DataFrame for LLM consumption.

    Returns a 'DataProfile' dict with:
      - row/column counts
      - per-column metadata & basic stats
      - numeric stats (min, max, mean, quantiles, etc.)
      - categorical distributions (top values)
      - temporal ranges and optional simple time-series trend
      - a small sample of rows

    Args:
        df: Input Polars DataFrame
        max_categories: Max unique values for categorical distribution (default: 30)
        max_top_values: Max top values to return per categorical column (default: 10)
        sample_rows: Number of sample rows to include (default: 20)
        trend_time_column: Column name for trend analysis time dimension (auto-detect if None)
        trend_metric_column: Column name for trend analysis metric (auto-detect if None)

    Returns:
        DataProfile dictionary with comprehensive statistics
    """
    if df.height == 0:
        return {
            "row_count": 0,
            "column_count": len(df.columns),
            "columns": [],
            "numeric_stats": {},
            "categorical_stats": {},
            "temporal_stats": {},
            "trend": None,
            "sample_rows": [],
        }

    row_count = df.height
    column_count = len(df.columns)

    # --- classify columns ---
    numeric_dtypes = (
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Float32,
        pl.Float64,
        pl.Decimal,
    )
    temporal_dtypes = (pl.Date, pl.Datetime, pl.Time)
    categorical_dtypes = (pl.Utf8, pl.Categorical)

    numeric_cols: list[str] = []
    temporal_cols: list[str] = []
    categorical_cols: list[str] = []

    for col in df.columns:
        dt = df[col].dtype
        if isinstance(dt, numeric_dtypes):
            numeric_cols.append(col)
        elif isinstance(dt, temporal_dtypes):
            temporal_cols.append(col)
        elif isinstance(dt, (categorical_dtypes, pl.Boolean)):
            categorical_cols.append(col)

    # --- null counts & nunique ---
    null_counts_row = df.select(
        [pl.col(c).null_count().alias(c) for c in df.columns]
    ).row(0)
    null_counts = dict(zip(df.columns, null_counts_row))

    nunique_row = df.select([pl.col(c).n_unique().alias(c) for c in df.columns]).row(0)
    nunique_counts = dict(zip(df.columns, nunique_row))

    # --- column metadata ---
    columns_meta: list[dict[str, Any]] = []
    for col in df.columns:
        dt = df[col].dtype
        if col in numeric_cols:
            semantic_type = "numeric"
        elif col in temporal_cols:
            semantic_type = "temporal"
        elif col in categorical_cols:
            semantic_type = "categorical"
        else:
            semantic_type = "other"

        columns_meta.append(
            {
                "name": col,
                "dtype": str(dt),
                "semantic_type": semantic_type,
                "null_count": int(null_counts[col]),
                "n_unique": int(nunique_counts[col]),
            }
        )

    # --- numeric stats ---
    numeric_stats: dict[str, dict[str, Any]] = {}
    if numeric_cols:
        exprs = []
        for col in numeric_cols:
            exprs.extend(
                [
                    pl.col(col).sum().alias(f"{col}__sum"),
                    pl.col(col).min().alias(f"{col}__min"),
                    pl.col(col).max().alias(f"{col}__max"),
                    pl.col(col).mean().alias(f"{col}__mean"),
                    pl.col(col).std().alias(f"{col}__std"),
                    pl.col(col).quantile(0.25).alias(f"{col}__p25"),
                    pl.col(col).quantile(0.5).alias(f"{col}__p50"),
                    pl.col(col).quantile(0.75).alias(f"{col}__p75"),
                    pl.col(col).quantile(0.95).alias(f"{col}__p95"),
                ]
            )

        stats_row = df.select(exprs).row(0)
        stats_map = dict(zip([e.meta.output_name() for e in exprs], stats_row))

        for col in numeric_cols:
            numeric_stats[col] = {
                "sum": stats_map[f"{col}__sum"],
                "min": stats_map[f"{col}__min"],
                "max": stats_map[f"{col}__max"],
                "mean": stats_map[f"{col}__mean"],
                "std": stats_map[f"{col}__std"],
                "p25": stats_map[f"{col}__p25"],
                "p50": stats_map[f"{col}__p50"],
                "p75": stats_map[f"{col}__p75"],
                "p95": stats_map[f"{col}__p95"],
                "n_unique": int(nunique_counts[col]),
                "null_count": int(null_counts[col]),
            }

    # --- categorical stats (only low-cardinality) ---
    categorical_stats: dict[str, dict[str, Any]] = {}
    for col in categorical_cols:
        nuniq = int(nunique_counts[col])
        if nuniq <= max_categories:
            value_counts = (
                df.group_by(col)
                .agg(pl.len().alias("count"))
                .sort("count", descending=True)
                .head(max_top_values)
                .to_dicts()
            )
        else:
            value_counts = []

        categorical_stats[col] = {
            "n_unique": nuniq,
            "null_count": int(null_counts[col]),
            "top_values": [
                {"value": row[col], "count": row["count"]} for row in value_counts
            ],
        }

    # --- temporal stats & trend ---
    temporal_stats: dict[str, dict[str, Any]] = {}
    for col in temporal_cols:
        col_min, col_max = df.select(
            [pl.col(col).min().alias("min"), pl.col(col).max().alias("max")]
        ).row(0)
        temporal_stats[col] = {
            "min": col_min,
            "max": col_max,
            "null_count": int(null_counts[col]),
            "n_unique": int(nunique_counts[col]),
        }

    trend: dict[str, Any] | None = None
    time_col = trend_time_column or (temporal_cols[0] if temporal_cols else None)
    metric_col = trend_metric_column or (numeric_cols[0] if numeric_cols else None)

    if time_col and metric_col:
        try:
            trend_df = (
                df.with_columns(pl.col(time_col).cast(pl.Date).alias("_date_for_trend"))
                .group_by("_date_for_trend")
                .agg(pl.col(metric_col).mean().alias("value"))
                .sort("_date_for_trend")
            )
            trend = {
                "time_column": time_col,
                "metric_column": metric_col,
                "points": [
                    {"time": str(row["_date_for_trend"]), "value": row["value"]}
                    for row in trend_df.to_dicts()
                ],
            }
        except Exception:
            # Trend analysis failed (e.g., incompatible types), skip it
            trend = None

    # --- sample rows ---
    sample_rows_list = df.head(sample_rows).to_dicts()

    # Serialize all values to JSON-safe types (Decimal -> float, datetime -> ISO string)
    profile = {
        "row_count": row_count,
        "column_count": column_count,
        "columns": columns_meta,
        "numeric_stats": numeric_stats,
        "categorical_stats": categorical_stats,
        "temporal_stats": temporal_stats,
        "trend": trend,
        "sample_rows": sample_rows_list,
    }

    return _serialize_value(profile)
