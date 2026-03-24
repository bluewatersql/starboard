"""Query workload service for UC table analysis.

Provides shared data fetching and processing for:
- fetch_table_fingerprint (tool #11)
- analyze_query_impact (tool #10)

Uses parallel SQL queries + Python-side sqlglot analysis for:
- Fast execution (simple queries, parallel fetch)
- Accurate parsing (sqlglot AST vs fragile SQL regex)
- Testability (mock-friendly, pure Python processing)
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import polars as pl
import sqlglot
from sqlglot import exp
from starboard_core.domain.transformers import (
    QueryFingerprint,
    classify_query,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class SQLExecutor(Protocol):
    """Protocol for async SQL execution returning Polars DataFrames."""

    async def execute_query_polars(self, query: str) -> pl.DataFrame:
        """Execute SQL and return Polars DataFrame."""
        ...


@dataclass
class QueryHistoryRow:
    """Single row from query.history with relevant attributes."""

    statement_id: str
    statement_text: str
    statement_type: str | None
    total_duration_ms: int
    read_bytes: int
    written_bytes: int
    executed_by: str
    start_time: datetime
    # Additional useful attributes
    client_application: str | None = None
    result_from_cache: bool = False
    warehouse_id: str | None = None
    compute_type: str | None = None  # SQL_WAREHOUSE, SERVERLESS, etc.
    query_source: str | None = None  # DASHBOARD, JOB, NOTEBOOK, etc.


@dataclass
class JoinKey:
    """Extracted join key from query analysis."""

    left_table: str
    right_table: str
    left_column: str
    right_column: str
    join_type: str  # INNER, LEFT, RIGHT, FULL, CROSS
    frequency: int = 1


@dataclass
class FilterColumn:
    """Extracted filter column from WHERE clauses."""

    column_name: str
    table_name: str | None  # May not always be determinable
    operators: tuple[str, ...]  # =, <, >, LIKE, IN, etc.
    frequency: int = 1


@dataclass
class AggregationPattern:
    """Aggregation pattern from query analysis."""

    function: str  # COUNT, SUM, AVG, etc.
    column_name: str | None
    frequency: int = 1


@dataclass
class WorkloadAnalysis:
    """Aggregated workload analysis from query history."""

    # Read metrics
    read_query_count: int = 0
    total_read_bytes: int = 0
    total_read_duration_ms: int = 0
    distinct_readers: int = 0
    last_read_time: datetime | None = None

    # Write metrics
    write_query_count: int = 0
    total_written_bytes: int = 0
    insert_count: int = 0
    merge_count: int = 0
    update_count: int = 0
    delete_count: int = 0

    # Query patterns (from sqlglot analysis)
    top_join_keys: tuple[JoinKey, ...] = field(default_factory=tuple)
    top_filter_columns: tuple[FilterColumn, ...] = field(default_factory=tuple)
    top_aggregations: tuple[AggregationPattern, ...] = field(default_factory=tuple)
    pct_queries_with_groupby: float = 0.0
    pct_queries_with_joins: float = 0.0

    # Query source breakdown
    queries_from_jobs: int = 0
    queries_from_dashboards: int = 0
    queries_from_notebooks: int = 0
    queries_from_other: int = 0

    # Cache stats
    cache_hit_count: int = 0
    cache_hit_pct: float = 0.0


class QueryPatternAnalyzer:
    """Analyze query patterns using sqlglot AST parsing.

    Extracts:
    - Join keys (which columns are joined on)
    - Filter columns (which columns appear in WHERE)
    - Aggregation patterns (which functions are used)
    - GROUP BY usage

    Handles parse failures gracefully since query.history contains
    non-SQL content (Python, shell commands, etc.).
    """

    def __init__(self) -> None:
        self._join_keys: Counter[tuple[str, str, str, str, str]] = Counter()
        self._filter_columns: Counter[tuple[str, str | None]] = Counter()
        self._aggregations: Counter[tuple[str, str | None]] = Counter()
        self._operators: dict[tuple[str, str | None], set[str]] = {}
        self._total_queries = 0
        self._queries_with_groupby = 0
        self._queries_with_joins = 0
        self._parse_failures = 0

    def analyze(self, statement_text: str) -> QueryFingerprint | None:
        """Analyze a single query statement.

        Args:
            statement_text: SQL query text (may contain non-SQL)

        Returns:
            QueryFingerprint if parseable, None if not
        """
        self._total_queries += 1

        if not statement_text or len(statement_text.strip()) < 5:
            return None

        # Use existing classify_query for basic fingerprint
        fingerprint = classify_query(statement_text, full_analysis=True)

        if fingerprint.parse_confidence == "heuristic":
            # Couldn't parse - skip deep analysis
            self._parse_failures += 1
            return fingerprint

        # Track GROUP BY and JOIN usage
        if fingerprint.group_by_columns > 0:
            self._queries_with_groupby += 1
        if fingerprint.join_count > 0:
            self._queries_with_joins += 1

        # Extract join keys (requires re-parsing for detailed analysis)
        if fingerprint.join_count > 0:
            self._extract_join_keys(statement_text)

        # Extract filter columns
        if fingerprint.has_where:
            self._extract_filter_columns(statement_text)

        # Track aggregations
        for agg_func in fingerprint.agg_functions:
            self._aggregations[(agg_func, None)] += 1

        return fingerprint

    def _extract_join_keys(self, sql: str) -> None:
        """Extract join conditions from SQL."""
        try:
            parsed = sqlglot.parse_one(sql, dialect="databricks")
            if not parsed:
                return

            for join in parsed.find_all(exp.Join):
                join_type = join.kind or "INNER"
                on_clause = join.args.get("on")

                if on_clause:
                    # Extract equality conditions from ON clause
                    for eq in on_clause.find_all(exp.EQ):
                        left = eq.left
                        right = eq.right

                        if isinstance(left, exp.Column) and isinstance(
                            right, exp.Column
                        ):
                            left_table = self._get_table_name(left)
                            right_table = self._get_table_name(right)
                            left_col = left.name
                            right_col = right.name

                            key = (
                                left_table,
                                right_table,
                                left_col,
                                right_col,
                                join_type,
                            )
                            self._join_keys[key] += 1

        except Exception:
            # sqlglot parse error - skip
            pass

    def _extract_filter_columns(self, sql: str) -> None:
        """Extract columns from WHERE clause."""
        try:
            parsed = sqlglot.parse_one(sql, dialect="databricks")
            if not parsed:
                return

            where = parsed.find(exp.Where)
            if not where:
                return

            # Find all column references in WHERE clause
            for col in where.find_all(exp.Column):
                table_name = self._get_table_name(col)
                col_key = (col.name, table_name)
                self._filter_columns[col_key] += 1

                # Track operators used with this column
                parent = col.parent
                if parent:
                    op_name = type(parent).__name__
                    if col_key not in self._operators:
                        self._operators[col_key] = set()
                    self._operators[col_key].add(op_name)

        except Exception:
            # sqlglot parse error - skip
            pass

    def _get_table_name(self, col: exp.Column) -> str:
        """Get table name from column reference."""
        if col.table:
            return col.table
        return "unknown"

    def get_results(self, top_n: int = 10) -> WorkloadAnalysis:
        """Get aggregated analysis results.

        Args:
            top_n: Number of top items to return for each category

        Returns:
            WorkloadAnalysis with top patterns
        """
        # Build top join keys
        top_joins = [
            JoinKey(
                left_table=k[0],
                right_table=k[1],
                left_column=k[2],
                right_column=k[3],
                join_type=k[4],
                frequency=count,
            )
            for k, count in self._join_keys.most_common(top_n)
        ]

        # Build top filter columns
        top_filters = [
            FilterColumn(
                column_name=k[0],
                table_name=k[1],
                operators=tuple(self._operators.get(k, set())),
                frequency=count,
            )
            for k, count in self._filter_columns.most_common(top_n)
        ]

        # Build top aggregations
        top_aggs = [
            AggregationPattern(
                function=k[0],
                column_name=k[1],
                frequency=count,
            )
            for k, count in self._aggregations.most_common(top_n)
        ]

        # Calculate percentages
        total = max(self._total_queries, 1)
        pct_groupby = (self._queries_with_groupby / total) * 100
        pct_joins = (self._queries_with_joins / total) * 100

        return WorkloadAnalysis(
            top_join_keys=tuple(top_joins),
            top_filter_columns=tuple(top_filters),
            top_aggregations=tuple(top_aggs),
            pct_queries_with_groupby=round(pct_groupby, 2),
            pct_queries_with_joins=round(pct_joins, 2),
        )


class QueryWorkloadService:
    """Shared service for fetching and analyzing query workload data.

    Provides efficient data access for UC analysis tools:
    - Parallel SQL queries using asyncio.gather
    - Polars DataFrames for efficient processing
    - sqlglot-based query pattern analysis

    Usage:
        service = QueryWorkloadService(sql_executor)
        data = await service.fetch_workload_data(["catalog.schema.table"], 30)
        analysis = service.analyze_workload(data)
    """

    def __init__(self, sql_executor: SQLExecutor) -> None:
        """Initialize service.

        Args:
            sql_executor: SQL executor that returns Polars DataFrames
        """
        self.sql_executor = sql_executor

    async def fetch_workload_data(
        self,
        table_names: list[str],
        window_days: int = 30,
        limit: int = 1000,
    ) -> pl.DataFrame:
        """Fetch query history for specified tables.

        Uses table_lineage to accurately tie queries to tables,
        then joins with query.history for full details.

        Args:
            table_names: List of fully qualified table names
            window_days: Analysis window in days
            limit: Max queries to fetch per table

        Returns:
            Polars DataFrame with query history and lineage data
        """
        if not table_names:
            return pl.DataFrame()

        # Build table list for SQL IN clause
        table_list = ", ".join(f"'{t}'" for t in table_names)

        # Single query that joins lineage with history
        # This uses lineage for accurate table attribution
        query = f"""
        WITH target_lineage AS (
            -- Get statement IDs for queries touching our tables
            SELECT DISTINCT
                tl.statement_id,
                tl.source_table_full_name AS table_name,
                'READ' AS access_type
            FROM system.access.table_lineage tl
            WHERE tl.source_table_full_name IN ({table_list})
              AND tl.event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS

            UNION ALL

            SELECT DISTINCT
                tl.statement_id,
                tl.target_table_full_name AS table_name,
                'WRITE' AS access_type
            FROM system.access.table_lineage tl
            WHERE tl.target_table_full_name IN ({table_list})
              AND tl.event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        )
        SELECT
            h.statement_id,
            h.statement_text,
            h.statement_type,
            h.total_duration_ms,
            COALESCE(h.read_bytes, 0) AS read_bytes,
            COALESCE(h.written_bytes, 0) AS written_bytes,
            h.executed_by,
            h.start_time,
            h.end_time,
            -- Additional useful attributes
            h.client_application,
            COALESCE(h.from_result_cache, false) AS result_from_cache,
            COALESCE(h.compute.warehouse_id, 'SERVERLESS') AS warehouse_id,
            -- Extract query source as string from STRUCT
            CASE
                WHEN h.query_source.job_info.job_id IS NOT NULL THEN 'JOB'
                WHEN h.query_source.dashboard_id IS NOT NULL OR h.query_source.legacy_dashboard_id IS NOT NULL THEN 'DASHBOARD'
                WHEN h.query_source.notebook_id IS NOT NULL THEN 'NOTEBOOK'
                WHEN h.query_source.sql_query_id IS NOT NULL THEN 'SQL_EDITOR'
                WHEN h.query_source.genie_space_id IS NOT NULL THEN 'GENIE'
                WHEN h.query_source.alert_id IS NOT NULL THEN 'ALERT'
                WHEN h.query_source.pipeline_info.pipeline_id IS NOT NULL THEN 'PIPELINE'
                ELSE 'OTHER'
            END AS query_source,
            -- Lineage info
            tl.table_name,
            tl.access_type
        FROM target_lineage tl
        INNER JOIN system.query.history h ON tl.statement_id = h.statement_id
        WHERE h.execution_status = 'FINISHED'
          AND h.start_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        ORDER BY h.start_time DESC
        LIMIT {limit}
        """

        logger.debug("fetching_workload_data", table_count=len(table_names))
        return await self.sql_executor.execute_query_polars(query)

    async def fetch_billing_data(
        self,
        window_days: int = 30,
    ) -> pl.DataFrame:
        """Fetch billing/DBU usage data.

        Args:
            window_days: Analysis window in days

        Returns:
            Polars DataFrame with hourly DBU usage by warehouse
        """
        query = f"""
        SELECT
            workspace_id,
            COALESCE(usage_metadata.warehouse_id, 'SERVERLESS') AS warehouse_id,
            DATE_TRUNC('hour', usage_start_time) AS usage_hour,
            SUM(COALESCE(usage_quantity, 0)) AS dbus
        FROM system.billing.usage
        WHERE usage_start_time >= CURRENT_DATE() - INTERVAL {window_days} DAYS
          AND usage_unit = 'DBU'
        GROUP BY ALL
        """
        return await self.sql_executor.execute_query_polars(query)

    async def fetch_all_data(
        self,
        table_names: list[str],
        window_days: int = 30,
        limit: int = 1000,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Fetch all workload data in parallel.

        Args:
            table_names: Tables to analyze
            window_days: Analysis window
            limit: Max queries per table

        Returns:
            Tuple of (query_history_df, billing_df)
        """
        async with asyncio.TaskGroup() as tg:
            t_history = tg.create_task(
                self.fetch_workload_data(table_names, window_days, limit)
            )
            t_billing = tg.create_task(self.fetch_billing_data(window_days))
        history_df, billing_df = t_history.result(), t_billing.result()
        return history_df, billing_df

    def analyze_workload(
        self,
        history_df: pl.DataFrame,
        billing_df: pl.DataFrame | None = None,  # noqa: ARG002 - reserved for future cost attribution
    ) -> WorkloadAnalysis:
        """Analyze query workload using Polars + sqlglot.

        Args:
            history_df: Query history DataFrame from fetch_workload_data
            billing_df: Optional billing DataFrame for cost attribution (reserved for future use)

        Returns:
            WorkloadAnalysis with metrics and patterns
        """
        if history_df.is_empty():
            return WorkloadAnalysis()

        # Parse queries with sqlglot
        analyzer = QueryPatternAnalyzer()
        for row in history_df.iter_rows(named=True):
            stmt_text = row.get("statement_text", "")
            if stmt_text:
                analyzer.analyze(stmt_text)

        # Get pattern analysis
        pattern_analysis = analyzer.get_results(top_n=10)

        # Calculate read metrics using Polars
        read_df = history_df.filter(pl.col("access_type") == "READ")
        write_df = history_df.filter(pl.col("access_type") == "WRITE")

        read_metrics = self._calculate_read_metrics(read_df)
        write_metrics = self._calculate_write_metrics(write_df)
        source_breakdown = self._calculate_source_breakdown(history_df)
        cache_stats = self._calculate_cache_stats(history_df)

        return WorkloadAnalysis(
            # Read metrics
            read_query_count=read_metrics["count"],
            total_read_bytes=read_metrics["total_bytes"],
            total_read_duration_ms=read_metrics["total_duration"],
            distinct_readers=read_metrics["distinct_users"],
            last_read_time=read_metrics["last_time"],
            # Write metrics
            write_query_count=write_metrics["count"],
            total_written_bytes=write_metrics["total_bytes"],
            insert_count=write_metrics["insert_count"],
            merge_count=write_metrics["merge_count"],
            update_count=write_metrics["update_count"],
            delete_count=write_metrics["delete_count"],
            # Patterns from sqlglot
            top_join_keys=pattern_analysis.top_join_keys,
            top_filter_columns=pattern_analysis.top_filter_columns,
            top_aggregations=pattern_analysis.top_aggregations,
            pct_queries_with_groupby=pattern_analysis.pct_queries_with_groupby,
            pct_queries_with_joins=pattern_analysis.pct_queries_with_joins,
            # Source breakdown
            queries_from_jobs=source_breakdown["jobs"],
            queries_from_dashboards=source_breakdown["dashboards"],
            queries_from_notebooks=source_breakdown["notebooks"],
            queries_from_other=source_breakdown["other"],
            # Cache stats
            cache_hit_count=cache_stats["hits"],
            cache_hit_pct=cache_stats["hit_pct"],
        )

    def _calculate_read_metrics(self, df: pl.DataFrame) -> dict[str, Any]:
        """Calculate read workload metrics using Polars."""
        if df.is_empty():
            return {
                "count": 0,
                "total_bytes": 0,
                "total_duration": 0,
                "distinct_users": 0,
                "last_time": None,
            }

        return {
            "count": len(df),
            "total_bytes": df["read_bytes"].sum() or 0,
            "total_duration": df["total_duration_ms"].sum() or 0,
            "distinct_users": df["executed_by"].n_unique(),
            "last_time": df["start_time"].max(),
        }

    def _calculate_write_metrics(self, df: pl.DataFrame) -> dict[str, Any]:
        """Calculate write workload metrics using Polars."""
        if df.is_empty():
            return {
                "count": 0,
                "total_bytes": 0,
                "insert_count": 0,
                "merge_count": 0,
                "update_count": 0,
                "delete_count": 0,
            }

        # Count by statement type
        type_counts = (
            df.group_by("statement_type")
            .agg(pl.count().alias("count"))
            .to_dict(as_series=False)
        )

        type_map = dict(
            zip(type_counts.get("statement_type", []), type_counts.get("count", []))
        )

        return {
            "count": len(df),
            "total_bytes": df["written_bytes"].sum() or 0,
            "insert_count": type_map.get("INSERT", 0),
            "merge_count": type_map.get("MERGE", 0),
            "update_count": type_map.get("UPDATE", 0),
            "delete_count": type_map.get("DELETE", 0),
        }

    def _calculate_source_breakdown(self, df: pl.DataFrame) -> dict[str, int]:
        """Calculate query source breakdown using Polars."""
        if df.is_empty():
            return {"jobs": 0, "dashboards": 0, "notebooks": 0, "other": 0}

        # Normalize query_source values
        source_counts = (
            df.with_columns(
                pl.when(pl.col("query_source").str.to_uppercase().str.contains("JOB"))
                .then(pl.lit("jobs"))
                .when(
                    pl.col("query_source").str.to_uppercase().str.contains("DASHBOARD")
                )
                .then(pl.lit("dashboards"))
                .when(
                    pl.col("query_source").str.to_uppercase().str.contains("NOTEBOOK")
                )
                .then(pl.lit("notebooks"))
                .otherwise(pl.lit("other"))
                .alias("source_category")
            )
            .group_by("source_category")
            .agg(pl.count().alias("count"))
            .to_dict(as_series=False)
        )

        category_map = dict(
            zip(
                source_counts.get("source_category", []),
                source_counts.get("count", []),
            )
        )

        return {
            "jobs": category_map.get("jobs", 0),
            "dashboards": category_map.get("dashboards", 0),
            "notebooks": category_map.get("notebooks", 0),
            "other": category_map.get("other", 0),
        }

    def _calculate_cache_stats(self, df: pl.DataFrame) -> dict[str, Any]:
        """Calculate cache hit statistics."""
        if df.is_empty():
            return {"hits": 0, "hit_pct": 0.0}

        total = len(df)
        hits = df.filter(pl.col("result_from_cache") == True).height  # noqa: E712

        return {
            "hits": hits,
            "hit_pct": round((hits / total) * 100, 2) if total > 0 else 0.0,
        }
