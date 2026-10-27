# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Data transformers for large UC data sources.

Transformers condense raw API responses into compact summaries
suitable for LLM context windows while preserving key insights.

This module includes:
- Query fingerprinting with sqlglot
- Table fingerprint analysis
- Lineage graph transformation
- Schema history tracking
- Simple table metadata transforms
"""

from __future__ import annotations

import json
import logging
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from statistics import mean
from typing import Any

import sqlglot
from sqlglot import exp

from starboard_core.domain.models.databricks import LineageDependencyType

logger = logging.getLogger(__name__)


# =============================================================================
# Constants for data transformations
# =============================================================================

KILOBYTE = 1024
MEGABYTE = KILOBYTE * 1024
GIGABYTE = MEGABYTE * 1024
THOUSAND = 1000
KILOBYTE_THRESHOLD = 256 * KILOBYTE  # Small file threshold
ROUNDING_PRECISION = 2


# =============================================================================
# Query Classification (Hybrid sqlglot + pattern matching)
# =============================================================================


class QueryOperation(StrEnum):
    """Classified query operation type."""

    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    MERGE = "merge"
    CREATE = "create"
    ALTER = "alter"
    DROP = "drop"
    # Databricks-specific (not parseable by sqlglot)
    OPTIMIZE = "optimize"
    VACUUM = "vacuum"
    COPY_INTO = "copy_into"
    CLONE = "clone"
    RESTORE = "restore"
    ANALYZE = "analyze"
    # Fallback
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QueryFingerprint:
    """Rich query fingerprint from AST analysis.

    Attributes:
        operation: The primary SQL operation type
        is_read: Whether query reads data
        is_write: Whether query writes data
        is_maintenance: Whether query is maintenance (OPTIMIZE, VACUUM, etc.)
        join_count: Number of joins in the query
        join_types: List of join types (INNER, LEFT, etc.)
        subquery_count: Number of subqueries
        cte_count: Number of CTEs (WITH clauses)
        has_aggregation: Whether query uses aggregate functions
        agg_functions: List of aggregate function names used
        group_by_columns: Number of GROUP BY columns
        window_count: Number of window functions
        has_where: Whether query has a WHERE clause
        has_limit: Whether query has a LIMIT clause
        tables_referenced: List of table names referenced
        parse_confidence: Confidence level of parsing ("parsed", "pattern", "heuristic")
    """

    operation: QueryOperation
    is_read: bool
    is_write: bool
    is_maintenance: bool = False
    # Complexity metrics
    join_count: int = 0
    join_types: tuple[str, ...] = field(default_factory=tuple)
    subquery_count: int = 0
    cte_count: int = 0
    # Aggregation metrics
    has_aggregation: bool = False
    agg_functions: tuple[str, ...] = field(default_factory=tuple)
    group_by_columns: int = 0
    # Window function metrics
    window_count: int = 0
    # Selectivity hints
    has_where: bool = False
    has_limit: bool = False
    # Table references
    tables_referenced: tuple[str, ...] = field(default_factory=tuple)
    # Parsing metadata
    parse_confidence: str = "heuristic"


# Databricks commands that sqlglot can't parse - check these first
_DATABRICKS_PATTERNS: list[tuple[str, QueryOperation, bool, bool, bool]] = [
    # (pattern, operation, is_read, is_write, is_maintenance)
    ("OPTIMIZE", QueryOperation.OPTIMIZE, False, True, True),
    ("VACUUM", QueryOperation.VACUUM, False, True, True),
    ("COPY INTO", QueryOperation.COPY_INTO, False, True, False),
    ("CLONE", QueryOperation.CLONE, True, True, False),
    ("RESTORE", QueryOperation.RESTORE, False, True, False),
    ("ANALYZE TABLE", QueryOperation.ANALYZE, True, False, True),
    ("DESCRIBE HISTORY", QueryOperation.SELECT, True, False, False),
    ("DESCRIBE DETAIL", QueryOperation.SELECT, True, False, False),
    ("SHOW ", QueryOperation.SELECT, True, False, False),
]


def classify_query(sql: str, full_analysis: bool = True) -> QueryFingerprint:
    """
    Classify a SQL query using hybrid approach.

    Strategy:
    1. Check for Databricks-specific patterns first (fast, handles non-parseable)
    2. Try sqlglot parsing for standard SQL
    3. Fall back to simple string heuristics

    Args:
        sql: SQL query text
        full_analysis: If True, extract all metrics. If False, just operation type.

    Returns:
        QueryFingerprint with operation type and metrics
    """
    if not sql:
        return QueryFingerprint(
            operation=QueryOperation.UNKNOWN,
            is_read=False,
            is_write=False,
            parse_confidence="heuristic",
        )

    sql_stripped = sql.strip()
    sql_upper = sql_stripped.upper()

    # Step 1: Check Databricks-specific patterns (sqlglot can't parse these)
    for pattern, op, is_read, is_write, is_maint in _DATABRICKS_PATTERNS:
        if sql_upper.startswith(pattern) or f"\n{pattern}" in sql_upper:
            return QueryFingerprint(
                operation=op,
                is_read=is_read,
                is_write=is_write,
                is_maintenance=is_maint,
                parse_confidence="pattern",
            )

    # Step 2: Try sqlglot parsing
    if full_analysis:
        try:
            parsed = sqlglot.parse_one(sql_stripped, dialect="databricks")
            return _extract_full_fingerprint(parsed)
        except Exception as e:
            logger.debug("sqlglot parse failed, falling back to heuristics: %s", str(e))

    # Step 3: Fallback to string heuristics
    return _classify_from_heuristics(sql_upper)


def _extract_full_fingerprint(parsed: exp.Expression) -> QueryFingerprint:
    """Extract all metrics from parsed AST."""
    # Classify operation from AST type
    op, is_read, is_write = _classify_ast_operation(parsed)

    # Extract joins
    joins = list(parsed.find_all(exp.Join))
    join_types = tuple(j.kind or "INNER" for j in joins)

    # Extract aggregations
    agg_funcs = list(parsed.find_all(exp.AggFunc))
    agg_names = tuple(type(f).__name__ for f in agg_funcs)

    # Extract GROUP BY
    group = parsed.find(exp.Group)
    group_by_count = len(group.expressions) if group else 0

    # Extract windows
    windows = list(parsed.find_all(exp.Window))

    # Extract tables
    tables = _extract_tables(parsed)

    return QueryFingerprint(
        operation=op,
        is_read=is_read,
        is_write=is_write,
        is_maintenance=False,
        join_count=len(joins),
        join_types=join_types,
        subquery_count=len(list(parsed.find_all(exp.Subquery))),
        cte_count=len(list(parsed.find_all(exp.CTE))),
        has_aggregation=len(agg_funcs) > 0,
        agg_functions=agg_names,
        group_by_columns=group_by_count,
        window_count=len(windows),
        has_where=parsed.find(exp.Where) is not None,
        has_limit=parsed.find(exp.Limit) is not None,
        tables_referenced=tables,
        parse_confidence="parsed",
    )


def _classify_ast_operation(
    parsed: exp.Expression,
) -> tuple[QueryOperation, bool, bool]:
    """Classify operation from sqlglot AST node type."""
    # Map AST node types to operations (operation, is_read, is_write)
    ast_mapping: dict[type, tuple[QueryOperation, bool, bool]] = {
        exp.Select: (QueryOperation.SELECT, True, False),
        exp.Insert: (QueryOperation.INSERT, False, True),
        exp.Update: (QueryOperation.UPDATE, True, True),  # Reads WHERE clause
        exp.Delete: (QueryOperation.DELETE, True, True),  # Reads WHERE clause
        exp.Merge: (QueryOperation.MERGE, True, True),
        exp.Create: (QueryOperation.CREATE, False, True),
        exp.Alter: (QueryOperation.ALTER, False, True),
        exp.Drop: (QueryOperation.DROP, False, True),
    }

    for node_type, (op, is_read, is_write) in ast_mapping.items():
        if isinstance(parsed, node_type):
            # Special case: INSERT ... SELECT reads from source
            if isinstance(parsed, exp.Insert) and parsed.find(exp.Select):
                is_read = True
            return op, is_read, is_write

    # Check for CTAS (Create Table As Select)
    if isinstance(parsed, exp.Create) and parsed.find(exp.Select):
        return QueryOperation.CREATE, True, True

    return QueryOperation.UNKNOWN, False, False


def _extract_tables(parsed: exp.Expression) -> tuple[str, ...]:
    """Extract fully qualified table names from AST."""
    tables = []
    for table in parsed.find_all(exp.Table):
        parts = [table.catalog, table.db, table.name]
        full_name = ".".join(p for p in parts if p)
        if full_name:
            tables.append(full_name)
    return tuple(tables)


def _classify_from_heuristics(sql_upper: str) -> QueryFingerprint:
    """Last-resort string-based classification."""
    # Order matters - check more specific patterns first
    heuristics: list[tuple[list[str], QueryOperation, bool, bool]] = [
        (["MERGE INTO", "MERGE "], QueryOperation.MERGE, True, True),
        (["INSERT"], QueryOperation.INSERT, False, True),
        (["UPDATE "], QueryOperation.UPDATE, True, True),
        (["DELETE FROM", "DELETE "], QueryOperation.DELETE, True, True),
        (["CREATE "], QueryOperation.CREATE, False, True),
        (["ALTER "], QueryOperation.ALTER, False, True),
        (["DROP "], QueryOperation.DROP, False, True),
        (["SELECT"], QueryOperation.SELECT, True, False),
    ]

    for patterns, op, is_read, is_write in heuristics:
        if any(p in sql_upper for p in patterns):
            # Check for SELECT in write operations (reads source data)
            if is_write and "SELECT" in sql_upper:
                is_read = True
            return QueryFingerprint(
                operation=op,
                is_read=is_read,
                is_write=is_write,
                has_where="WHERE" in sql_upper,
                has_limit="LIMIT" in sql_upper,
                parse_confidence="heuristic",
            )

    return QueryFingerprint(
        operation=QueryOperation.UNKNOWN,
        is_read=False,
        is_write=False,
        parse_confidence="heuristic",
    )


# =============================================================================
# Transformers
# =============================================================================


@dataclass
class LineageGraphTransformer:
    """Transform raw lineage API response for LLM context.

    The Databricks lineage REST API returns only direct (1-hop) dependencies.
    This transformer condenses the response into a summary suitable for
    LLM context windows.

    Note: For transitive (multi-hop) lineage, query system.access.table_lineage
    system table directly, or recursively call the REST API.

    Example:
        >>> transformer = LineageGraphTransformer(max_items=5)
        >>> summary = transformer.transform(raw_lineage_response)
        >>> len(summary["upstream_summary"]) <= 5
        True
    """

    max_items: int = 10

    def transform(self, raw_lineage: dict[str, Any]) -> dict[str, Any]:
        """
        Transform raw lineage to condensed summary.

        Args:
            raw_lineage: Raw lineage API response with upstreams/downstreams

        Returns:
            Condensed lineage summary with table info, job counts, notebook counts
        """
        upstreams = raw_lineage.get("upstreams", [])
        downstreams = raw_lineage.get("downstreams", [])

        upstream_summary = self._summarize_nodes(upstreams)
        downstream_summary = self._summarize_nodes(downstreams)

        return {
            "upstream_count": len(upstreams),
            "downstream_count": len(downstreams),
            "upstream_summary": upstream_summary,
            "downstream_summary": downstream_summary,
            "truncated": (
                len(upstreams) > self.max_items or len(downstreams) > self.max_items
            ),
        }

    def _summarize_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Summarize lineage nodes to essential information.

        Extracts table info, job references, and notebook references from
        the raw API response.
        """
        summary = []
        for node in nodes[: self.max_items]:
            table_info = node.get("tableInfo", {})
            job_infos = node.get("jobInfos", [])
            notebook_infos = node.get("notebookInfos", [])

            # Extract table name
            catalog = table_info.get("catalog_name", "")
            schema = table_info.get("schema_name", "")
            name = table_info.get("name", "")
            full_name = (
                f"{catalog}.{schema}.{name}" if all((catalog, schema, name)) else name
            )

            # Extract job IDs for reference
            job_ids = [j.get("job_id") for j in job_infos if j.get("job_id")]
            notebook_ids = [
                n.get("notebook_id") for n in notebook_infos if n.get("notebook_id")
            ]

            summary.append(
                {
                    "table": full_name,
                    "table_type": table_info.get("table_type", "UNKNOWN"),
                    "job_count": len(job_infos),
                    "notebook_count": len(notebook_infos),
                    "job_ids": job_ids[:5],  # Limit to first 5 for context
                    "notebook_ids": notebook_ids[:5],
                    "last_updated": table_info.get("lineage_timestamp"),
                }
            )
        return summary


@dataclass
class TableFingerprintTransformer:
    """Transform query history into workload fingerprint.

    Aggregates potentially thousands of query history rows into
    a compact fingerprint summary for LLM analysis. Uses sqlglot
    for accurate query classification when possible, with fallback
    to pattern matching for Databricks-specific commands.

    Attributes:
        sample_size: Max queries to analyze with full sqlglot parsing.
            Larger samples are randomly sampled to limit overhead.
        full_analysis: Whether to extract complexity metrics via sqlglot.

    Example:
        >>> transformer = TableFingerprintTransformer()
        >>> fingerprint = transformer.transform(query_rows)
        >>> "access_pattern" in fingerprint
        True
    """

    sample_size: int = 100
    full_analysis: bool = True

    def transform(self, query_rows: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregate query history into fingerprint.

        Args:
            query_rows: Query history rows (potentially thousands)

        Returns:
            Compact fingerprint summary with read/write profiles,
            complexity metrics, and access pattern classification.
        """
        if not query_rows:
            return self._empty_fingerprint()

        # Sample for deep analysis if large volume
        if len(query_rows) > self.sample_size:
            sample = random.sample(query_rows, self.sample_size)
            sampled = True
        else:
            sample = query_rows
            sampled = False

        # Classify all queries in sample
        fingerprints: list[tuple[dict[str, Any], QueryFingerprint]] = []
        for row in sample:
            sql = row.get("query_text", "") or ""
            fp = classify_query(sql, full_analysis=self.full_analysis)
            fingerprints.append((row, fp))

        # Separate by read/write/maintenance
        read_queries = [(r, f) for r, f in fingerprints if f.is_read]
        write_queries = [(r, f) for r, f in fingerprints if f.is_write]
        maintenance_queries = [(r, f) for r, f in fingerprints if f.is_maintenance]

        # Count operations by type
        op_counts: Counter[str] = Counter(f.operation.value for _, f in fingerprints)

        # Calculate read metrics
        total_read_bytes = sum(r.get("bytes_scanned", 0) or 0 for r, _ in read_queries)
        distinct_users = len(
            {r.get("user_id") or r.get("user_name", "") for r, _ in read_queries}
        )

        # Build result
        result: dict[str, Any] = {
            "read_profile": {
                "query_count": len(read_queries),
                "total_bytes": total_read_bytes,
                "total_gb": round(total_read_bytes / 1e9, 2),
                "distinct_users": distinct_users,
            },
            "write_profile": {
                "operation_count": len(write_queries),
                "by_operation": {
                    k: v
                    for k, v in op_counts.items()
                    if k in ("insert", "update", "delete", "merge")
                },
            },
            "maintenance_profile": {
                "operation_count": len(maintenance_queries),
                "optimize_count": op_counts.get("optimize", 0),
                "vacuum_count": op_counts.get("vacuum", 0),
                "analyze_count": op_counts.get("analyze", 0),
            },
            "access_pattern": self._classify_pattern(
                len(read_queries), len(write_queries)
            ),
            "sample_info": {
                "total_queries": len(query_rows),
                "analyzed_queries": len(sample),
                "sampled": sampled,
            },
        }

        # Add complexity profile if we did full analysis
        if self.full_analysis and fingerprints:
            result["complexity_profile"] = self._compute_complexity_profile(
                fingerprints
            )

        return result

    def _compute_complexity_profile(
        self, fingerprints: list[tuple[dict[str, Any], QueryFingerprint]]
    ) -> dict[str, Any]:
        """Compute complexity metrics from fingerprints."""
        fps = [f for _, f in fingerprints]

        # Only compute stats for parsed queries
        parsed_fps = [f for f in fps if f.parse_confidence == "parsed"]
        if not parsed_fps:
            return {"parse_success_rate": 0.0}

        join_counts = [f.join_count for f in parsed_fps]
        subquery_counts = [f.subquery_count for f in parsed_fps]

        # Count aggregate functions across all queries
        all_agg_funcs: list[str] = []
        for f in parsed_fps:
            all_agg_funcs.extend(f.agg_functions)
        agg_func_counts = Counter(all_agg_funcs)

        return {
            "parse_success_rate": round(len(parsed_fps) / len(fps), 2),
            "join_stats": {
                "avg_joins": round(mean(join_counts), 2) if join_counts else 0,
                "max_joins": max(join_counts) if join_counts else 0,
                "queries_with_joins": sum(1 for c in join_counts if c > 0),
            },
            "subquery_stats": {
                "avg_subqueries": round(mean(subquery_counts), 2)
                if subquery_counts
                else 0,
                "max_subqueries": max(subquery_counts) if subquery_counts else 0,
                "queries_with_subqueries": sum(1 for c in subquery_counts if c > 0),
            },
            "queries_with_ctes": sum(1 for f in parsed_fps if f.cte_count > 0),
            "queries_with_aggregation": sum(1 for f in parsed_fps if f.has_aggregation),
            "queries_with_windows": sum(1 for f in parsed_fps if f.window_count > 0),
            "common_agg_functions": dict(agg_func_counts.most_common(5)),
            "queries_with_filters": sum(1 for f in parsed_fps if f.has_where),
            "queries_with_limits": sum(1 for f in parsed_fps if f.has_limit),
        }

    def _classify_pattern(self, reads: int, writes: int) -> str:
        """Classify access pattern based on read/write ratio."""
        if reads == 0 and writes == 0:
            return "inactive"
        if writes == 0:
            return "high_read_low_write"
        ratio = reads / max(writes, 1)
        if ratio > 10:
            return "high_read_low_write"
        if ratio < 0.1:
            return "high_write_low_read"
        if reads + writes < 10:
            return "inactive"
        return "balanced"

    def _empty_fingerprint(self) -> dict[str, Any]:
        """Return empty fingerprint structure."""
        return {
            "read_profile": {
                "query_count": 0,
                "total_bytes": 0,
                "total_gb": 0.0,
                "distinct_users": 0,
            },
            "write_profile": {
                "operation_count": 0,
                "by_operation": {},
            },
            "maintenance_profile": {
                "operation_count": 0,
                "optimize_count": 0,
                "vacuum_count": 0,
                "analyze_count": 0,
            },
            "access_pattern": "unknown",
            "sample_info": {
                "total_queries": 0,
                "analyzed_queries": 0,
                "sampled": False,
            },
        }


@dataclass
class AccessPatternTransformer:
    """Summarize audit log access patterns.

    Transforms potentially millions of audit log rows into
    a compact access pattern summary.

    Example:
        >>> transformer = AccessPatternTransformer(top_users_limit=5)
        >>> summary = transformer.transform(audit_rows)
        >>> len(summary["top_users"]) <= 5
        True
    """

    top_users_limit: int = 10
    daily_trend_limit: int = 30

    def transform(self, audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Aggregate audit log into access pattern summary.

        Args:
            audit_rows: Audit log rows

        Returns:
            Access pattern summary
        """
        if not audit_rows:
            return self._empty_summary()

        # Count by user
        user_counts: dict[str, int] = {}
        for row in audit_rows:
            user = row.get("user_email", "") or row.get("user_identity", {}).get(
                "email", "unknown"
            )
            user_counts[user] = user_counts.get(user, 0) + 1

        # Top users
        sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        top_users = [
            {"email": email, "count": count}
            for email, count in sorted_users[: self.top_users_limit]
        ]

        # Count by action
        action_counts: dict[str, int] = {}
        for row in audit_rows:
            action = row.get("action_name", "unknown")
            action_counts[action] = action_counts.get(action, 0) + 1

        # Daily trend
        daily_counts: dict[str, int] = {}
        for row in audit_rows:
            # Try different date field names
            date_str = (
                row.get("event_date")
                or row.get("event_time", "")[:10]  # Extract date from datetime
                or "unknown"
            )
            daily_counts[date_str] = daily_counts.get(date_str, 0) + 1

        sorted_days = sorted(daily_counts.items(), key=lambda x: x[0], reverse=True)
        daily_trend = [
            {"date": date, "count": count}
            for date, count in sorted_days[: self.daily_trend_limit]
        ]

        return {
            "total_accesses": len(audit_rows),
            "top_users": top_users,
            "access_by_action": action_counts,
            "daily_trend": daily_trend,
            "distinct_users": len(user_counts),
        }

    def _empty_summary(self) -> dict[str, Any]:
        """Return empty summary structure."""
        return {
            "total_accesses": 0,
            "top_users": [],
            "access_by_action": {},
            "daily_trend": [],
            "distinct_users": 0,
        }


@dataclass
class SchemaHistoryTransformer:
    """Summarize schema evolution from Delta history.

    Extracts schema changes from Delta history entries
    to track schema evolution over time.

    Example:
        >>> transformer = SchemaHistoryTransformer()
        >>> summary = transformer.transform(history_entries)
        >>> "schema_changes" in summary
        True
    """

    max_changes: int = 20

    def transform(self, history_entries: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Extract schema changes from Delta history.

        Args:
            history_entries: Delta history entries

        Returns:
            Schema evolution summary
        """
        schema_changes: list[dict[str, Any]] = []
        current_version = 0

        for entry in history_entries:
            version = entry.get("version", 0)
            current_version = max(current_version, version)

            # Check for schema change indicators
            operation = entry.get("operation", "")
            op_params = entry.get("operationParameters", {}) or {}

            is_schema_change = (
                "SET TBLPROPERTIES" in operation
                or "ALTER" in operation
                or "schema" in str(op_params).lower()
                or entry.get("userMetadata", {}).get("schemaChange", False)
            )

            if is_schema_change and len(schema_changes) < self.max_changes:
                # Try to extract change details
                change_type = self._detect_change_type(operation, op_params)
                timestamp_ms = entry.get("timestamp", 0)
                timestamp = (
                    datetime.fromtimestamp(timestamp_ms / 1000)
                    if timestamp_ms
                    else None
                )

                schema_changes.append(
                    {
                        "version": version,
                        "timestamp": timestamp.isoformat() if timestamp else None,
                        "change_type": change_type,
                        "operation": operation,
                        "user": entry.get("userId", entry.get("userName", "unknown")),
                    }
                )

        return {
            "current_version": current_version,
            "schema_changes": schema_changes,
            "total_schema_changes": len(schema_changes),
            "last_schema_change": (
                schema_changes[0]["timestamp"] if schema_changes else None
            ),
        }

    def _detect_change_type(self, operation: str, op_params: dict[str, Any]) -> str:
        """Detect the type of schema change."""
        op_lower = operation.lower()
        params_str = str(op_params).lower()

        if "add" in op_lower or "add" in params_str:
            return "ADD_COLUMN"
        if "drop" in op_lower or "drop" in params_str:
            return "DROP_COLUMN"
        if "alter" in op_lower or "type" in params_str:
            return "TYPE_CHANGE"
        if "rename" in op_lower or "rename" in params_str:
            return "RENAME"
        return "UNKNOWN"


# =============================================================================
# Simple Transform Functions (LLM-optimized output)
# =============================================================================


def _safe_int(value: Any, default: int | None = 0) -> int | None:
    """Safely convert value to int, handling NaN and various formats."""
    if value is None:
        return default
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if math.isnan(value):
                return default
            return int(value)
        string_val = str(value).strip()
        if not string_val or string_val.lower() == "nan":
            return default
        return int(float(string_val))
    except (TypeError, ValueError):
        return default


def _round_float(value: Any, precision: int = ROUNDING_PRECISION) -> float:
    """Round a value to specified precision."""
    try:
        return round(float(value), precision)
    except (TypeError, ValueError):
        return 0.0


def _as_list(value: Any) -> list[Any]:
    """Ensure value is a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _try_json_load(value: Any, return_none: bool = False) -> Any:
    """Try to parse a JSON string, returning original value on failure."""
    if value is None:
        return None if return_none else value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None if return_none else value
    return value


def _parse_json_list(value: Any) -> list[str]:
    """Parse a JSON string as list, or return empty list."""
    parsed = _try_json_load(value, return_none=True)
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return []


def _parse_json_dict(value: Any) -> dict[str, Any]:
    """Parse a JSON string as dict, or return empty dict."""
    parsed = _try_json_load(value, return_none=True)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _to_iso_string(timestamp: Any) -> str | None:
    """Convert timestamp to ISO string format."""
    if timestamp is None:
        return None
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    if isinstance(timestamp, str):
        return timestamp
    if isinstance(timestamp, (int, float)):
        try:
            return datetime.fromtimestamp(timestamp / 1000).isoformat()
        except Exception:
            return None
    if hasattr(timestamp, "isoformat"):
        try:
            return timestamp.isoformat()
        except Exception:
            return None
    return str(timestamp)


def _strip_nulls(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively strip None values and empty dicts from a dictionary."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _strip_nulls(value)
            if nested:  # Only include if non-empty
                result[key] = nested
        elif isinstance(value, list):
            # Filter out None values in lists
            filtered = [v for v in value if v is not None]
            if filtered:
                result[key] = filtered
        else:
            result[key] = value
    return result


def transform_table_metadata(
    describe_json: str | dict[str, Any],
    *,
    include_schema: bool = False,
    max_schema_cols: int = 50,
    include_properties_subset: bool = True,
    property_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Transform Unity Catalog table metadata into compact LLM-optimized format.

    Processes JSON output from DESCRIBE EXTENDED <catalog>.<schema>.<table> AS JSON
    and extracts key metadata for optimization analysis.

    Args:
        describe_json: Dictionary or JSON string from DESCRIBE EXTENDED AS JSON
        include_schema: Whether to include schema block (possibly truncated)
        max_schema_cols: Maximum number of columns to keep in schema block
        include_properties_subset: Whether to include filtered subset of table properties
        property_allowlist: Case-insensitive property keys to keep; if None, uses defaults

    Returns:
        Compact dictionary with table metadata, stats, partitioning, and clustering info
    """
    data = (
        json.loads(describe_json)
        if isinstance(describe_json, str)
        else dict(describe_json)
    )

    # Coalesce common fields (names vary slightly across engines/versions)
    catalog = data.get("catalog_name") or data.get("catalog") or data.get("catalogName")
    schema = (
        data.get("schema_name")
        or data.get("namespace")
        or data.get("database")
        or data.get("schema")
    )
    # Some variants use "namespace" as a list like ["bakehouse"]
    if isinstance(schema, list) and schema:
        schema = schema[-1]

    table = data.get("table_name") or data.get("name") or data.get("table")
    provider = (
        data.get("provider") or data.get("format") or data.get("type") or ""
    ).lower()

    # Stats (shape can vary)
    stats = data.get("statistics", {}) or {}
    size_bytes = (
        stats.get("sizeInBytes") or stats.get("total_size") or stats.get("totalSize")
    )
    num_files = stats.get("numFiles")
    num_rows = (
        stats.get("numRows")
        or stats.get("row_count")
        or stats.get("Statistics Num Rows")
    )

    # Schema
    raw_cols = data.get("columns") or []
    schema_cols: list[dict[str, Any]] = []
    for c in raw_cols:
        t = c.get("type")
        if isinstance(t, dict):
            tname = t.get("text") or t.get("name") or str(t)
        else:
            tname = str(t) if t is not None else None
        schema_cols.append({"name": c.get("name"), "type": tname})

    # Partitioning and clustering
    partitions = _as_list(
        data.get("partition_columns")
        or data.get("partitioning")
        or data.get("partitionProvider")
    )
    partition_provider = data.get("partition_provider") or data.get("partitionProvider")

    # Delta/feature properties
    props: dict[str, Any] = (
        data.get("table_properties") or data.get("properties") or {}
    ) or {}
    predictive_opt = data.get("predictive_optimization") or data.get(
        "predictiveOptimization"
    )

    out: dict[str, Any] = {
        "table": f"{catalog}.{schema}.{table}"
        if catalog and schema and table
        else (table or None),
        "catalog": catalog,
        "database": schema,
        "format": provider,
        "stats": {
            "numFiles": num_files,
            "sizeInBytes": size_bytes,
            "numRows": num_rows,
        },
        "partitions": partitions or None,
        "partition_provider": partition_provider,
        "clustering": {
            "liquid_enabled": props.get("delta.liquidClustering.enabled"),
            "liquid_columns": (
                [
                    s.strip()
                    for s in props.get("delta.liquidClustering.columns", "").split(",")
                ]
                if props.get("delta.liquidClustering.columns")
                else None
            ),
            "zorder_columns": (
                [
                    s.strip().strip("[]")
                    for s in (
                        props.get("delta.zorderColumns")
                        or props.get("delta.lastZOrderBy")
                        or ""
                    ).split(",")
                ]
                if (props.get("delta.zorderColumns") or props.get("delta.lastZOrderBy"))
                else None
            ),
        },
        "skipping": {"dataSkippingStatsColumns": stats.get("data_skipping_columns")},
        "features": {
            "predictive_optimization": predictive_opt,
            "is_managed": bool(data.get("is_managed_location"))
            if "is_managed_location" in data
            else None,
            "table_type": data.get("type"),
            "collation": data.get("collation"),
        },
    }

    # Include schema (possibly truncated)
    if include_schema:
        if len(schema_cols) > max_schema_cols:
            out["schema"] = {
                "columns": schema_cols[:max_schema_cols],
                "total_columns": len(schema_cols),
                "truncated": True,
            }
        else:
            out["schema"] = {"columns": schema_cols, "total_columns": len(schema_cols)}

    # Optional subset of high-signal properties
    if include_properties_subset:
        default_allow = [
            "delta.appendOnly",
            "delta.enableChangeDataFeed",
            "delta.minReaderVersion",
            "delta.minWriterVersion",
            "delta.columnMapping.mode",
            "delta.constraints",
            "delta.dataSkippingStatsColumns",
            "delta.liquidClustering.enabled",
            "delta.liquidClustering.columns",
            "delta.lastOptimizedTimestamp",
            "delta.zorderColumns",
            "delta.lastZOrderBy",
            "delta.parquet.compression.codec",
            "delta.enableDeletionVectors",
            "delta.feature.appendOnly",
            "delta.feature.deletionVectors",
            "delta.feature.invariants",
        ]
        allow = {k.lower() for k in (property_allowlist or default_allow)}
        if out.get("properties"):
            filtered = {
                k: v for k, v in out["properties"].items() if k.lower() in allow
            }
            out["properties_subset"] = filtered or None

    return _strip_nulls(out)


def resolve_3part(
    name: str, default_catalog: str, default_schema: str
) -> tuple[str, str, str, str]:
    """Resolve a table name to a 3-part namespace (catalog.schema.table).

    Args:
        name: Table name (may be 1, 2, or 3 parts)
        default_catalog: Default catalog to use if not specified
        default_schema: Default schema to use if not specified

    Returns:
        Tuple of (catalog, schema, table, fully_qualified_name)
    """
    ident = name.replace("`", "").strip()
    parts = [part for part in ident.split(".") if part]

    if len(parts) == 3:
        catalog, schema, table = parts
        return catalog, schema, table, f"{catalog}.{schema}.{table}"

    if len(parts) == 2:
        schema, table = parts
        return default_catalog, schema, table, f"{default_catalog}.{schema}.{table}"

    table = parts[0] if parts else name
    return (
        default_catalog,
        default_schema,
        table,
        f"{default_catalog}.{default_schema}.{table}",
    )


def transform_delta_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize Delta table history for LLM usage optimization.

    Features:
    - Aggregates by operation
    - Summarizes operation metrics (summing numeric fields)
    - Extracts partitioning/cluster/z-order info and table properties
    - Captures last OPTIMIZE and VACUUM END details
    - Detects small-file WRITE pattern

    Args:
        history: List of Delta table history records

    Returns:
        Summarized history dictionary
    """
    last_optimize: dict[str, Any] | None = None
    last_vacuum_end: dict[str, Any] | None = None

    schema_layout: dict[str, list[str]] = {
        "partitionBy": [],
        "clusterBy": [],
        "zOrderBy": [],
    }
    table_properties: dict[str, Any] = {}

    by_operation: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "metrics_sum": defaultdict(int), "params_observed": set()}
    )

    write_files: list[int] = []
    write_rows: list[int] = []
    write_bytes: list[int] = []

    for event in history:
        operation = event.get("operation") or "UNKNOWN"
        by_operation[operation]["count"] += 1

        event_ts = _to_iso_string(event.get("timestamp")) or ""
        if operation == "OPTIMIZE" and (
            (last_optimize is None)
            or (event_ts > (_to_iso_string(last_optimize.get("timestamp")) or ""))
        ):
            last_optimize = event

        if operation == "VACUUM END" and (
            (last_vacuum_end is None)
            or (event_ts > (_to_iso_string(last_vacuum_end.get("timestamp")) or ""))
        ):
            last_vacuum_end = event

        params = event.get("operationParameters")
        params = _try_json_load(params, return_none=True) or {}

        if params:
            for key in (
                "partitionBy",
                "clusterBy",
                "zOrderBy",
                "statsOnLoad",
                "mode",
                "retentionCheckEnabled",
                "defaultRetentionMillis",
                "predicate",
                "auto",
            ):
                if key in params:
                    by_operation[operation]["params_observed"].add(
                        f"{key}={params[key]}"
                    )

        if operation in ("CREATE TABLE", "CREATE OR REPLACE TABLE", "REPLACE TABLE"):
            schema_layout["partitionBy"] = _parse_json_list(params.get("partitionBy"))
            schema_layout["clusterBy"] = _parse_json_list(params.get("clusterBy"))
            z_from_create = _parse_json_list(params.get("zOrderBy"))
            if z_from_create:
                schema_layout["zOrderBy"] = z_from_create
            props = _parse_json_dict(params.get("properties"))
            if props:
                table_properties.update(props)

        if operation == "OPTIMIZE":
            cluster_by = _parse_json_list(params.get("clusterBy"))
            z_order_by = _parse_json_list(params.get("zOrderBy"))
            if cluster_by and not schema_layout["clusterBy"]:
                schema_layout["clusterBy"] = cluster_by
            if z_order_by and not schema_layout["zOrderBy"]:
                schema_layout["zOrderBy"] = z_order_by

        metrics = event.get("operationMetrics")
        metrics = _try_json_load(metrics, return_none=True) or {}

        for key, value in metrics.items():
            int_val = _safe_int(value, None)
            if int_val is not None:
                by_operation[operation]["metrics_sum"][key] += int_val

        if operation == "WRITE":
            num_files = _safe_int(metrics.get("numFiles"), None)
            num_rows = _safe_int(metrics.get("numOutputRows"), None)
            num_bytes = _safe_int(metrics.get("numOutputBytes"), None)
            if num_files is not None:
                write_files.append(num_files)
            if num_rows is not None:
                write_rows.append(num_rows)
            if num_bytes is not None:
                write_bytes.append(num_bytes)

    table_info: dict[str, Any] = {
        "schema_layout": {
            "partitionBy": schema_layout.get("partitionBy"),
            "clusterBy": schema_layout.get("clusterBy"),
            "zOrderBy": schema_layout.get("zOrderBy"),
        }
    }

    if last_optimize:
        opt_metrics = last_optimize.get("operationMetrics")
        opt_metrics = _try_json_load(opt_metrics, return_none=True) or {}

        def get_metric_int(key: str) -> int:
            value = _safe_int(opt_metrics.get(key), None)
            return value if value is not None else 0

        def get_metric_mb(key: str) -> float:
            value = _safe_int(opt_metrics.get(key), None)
            return _round_float((value or 0) / MEGABYTE)

        table_info["last_optimize"] = {
            "version": last_optimize.get("version"),
            "timestamp": _to_iso_string(last_optimize.get("timestamp")),
            "num_removed_files": get_metric_int("numRemovedFiles"),
            "removed_mb": get_metric_mb("numRemovedBytes"),
            "num_added_files": get_metric_int("numAddedFiles"),
            "added_mb": get_metric_mb("numAddedBytes"),
            "file_size_stats_mb": {
                "min": get_metric_mb("minFileSize"),
                "p25": get_metric_mb("p25FileSize"),
                "p50": get_metric_mb("p50FileSize"),
                "p75": get_metric_mb("p75FileSize"),
                "max": get_metric_mb("maxFileSize"),
            },
        }

    if last_vacuum_end:
        vacuum_metrics = last_vacuum_end.get("operationMetrics")
        vacuum_metrics = _try_json_load(vacuum_metrics, return_none=True) or {}
        table_info["last_vacuum"] = {
            "version": last_vacuum_end.get("version"),
            "timestamp": _to_iso_string(last_vacuum_end.get("timestamp")),
            "num_deleted_files": _safe_int(vacuum_metrics.get("numDeletedFiles"), None)
            or 0,
            "num_vacuumed_directories": _safe_int(
                vacuum_metrics.get("numVacuumedDirectories"), None
            )
            or 0,
        }

    out_by_operation: dict[str, Any] = {}
    for operation, agg in by_operation.items():
        entry: dict[str, Any] = {"count": agg["count"]}

        if agg["params_observed"]:
            entry["params_observed"] = sorted(agg["params_observed"])

        if agg["metrics_sum"]:
            scaled_metrics: dict[str, Any] = {}
            for key, value in agg["metrics_sum"].items():
                if int(value) == 0:
                    continue
                if "Bytes" in key or "bytes" in key:
                    new_key = key.replace("Bytes", "MB").replace("bytes", "mb")
                    scaled_metrics[new_key] = _round_float(value / MEGABYTE)
                elif "Rows" in key or "rows" in key:
                    new_key = key.replace("Rows", "RowsK").replace("rows", "rows_k")
                    scaled_metrics[new_key] = _round_float(value / THOUSAND)
                else:
                    scaled_metrics[key] = int(value)
            if scaled_metrics:
                entry["metrics_sum"] = scaled_metrics

        if operation == "WRITE" and (write_files or write_rows or write_bytes):
            per_write: dict[str, Any] = {}
            if write_files and all(num_files == 1 for num_files in write_files):
                per_write["num_files"] = 1
            if write_rows:
                avg_rows_k = _round_float(sum(write_rows) / len(write_rows) / THOUSAND)
                per_write["output_rows_k_avg"] = avg_rows_k
            if write_bytes:
                avg_mb = _round_float(sum(write_bytes) / len(write_bytes) / MEGABYTE)
                per_write["output_mb_avg"] = avg_mb
                avg_bytes = sum(write_bytes) / len(write_bytes)
                entry["small_files"] = avg_bytes < KILOBYTE_THRESHOLD
            if per_write:
                entry["metrics_pattern"] = {"per_write": per_write}

        out_by_operation[operation] = entry

    return {"table_info": table_info, "by_operation": out_by_operation}


def _flatten_dependencies(lineage: dict[str, Any], dep_type: str) -> dict[str, int]:
    """Flatten lineage dependencies into counts by type."""
    dependencies: dict[str, int] = {}
    for item in lineage.get(dep_type, []):
        for k, v in item.items():
            if k.lower() == "tableinfo":
                dependencies[k] = dependencies.get(k, 0) + 1
            else:
                dependencies[k] = dependencies.get(k, 0) + len(v)
    return {LineageDependencyType(k.upper()).name: v for k, v in dependencies.items()}


def transform_table_lineage(tbl: str, lineage: dict[str, Any]) -> dict[str, Any]:
    """Transform table lineage into a compact LLM-optimized format.

    Args:
        tbl: Table name
        lineage: Table lineage dictionary

    Returns:
        Compact dictionary with table lineage information
    """
    return {
        "table": tbl,
        "downstreams": _flatten_dependencies(lineage, "downstreams"),
        "upstreams": _flatten_dependencies(lineage, "upstreams"),
    }
