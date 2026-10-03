# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery query infrastructure types.

Pure domain types for representing system table queries, query packs,
and their execution results. No I/O or side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


class DiscoveryMode(StrEnum):
    """Controls which queries are included in a discovery run.

    Attributes:
        GENERAL: Standard profiling queries that run by default.
        DEEP_DIVE: Additional detailed queries that run only when
            the caller explicitly requests deeper analysis.
    """

    GENERAL = "GENERAL"
    DEEP_DIVE = "DEEP_DIVE"


class QueryCategory(StrEnum):
    """Classifies the analytical purpose of a discovery query.

    Attributes:
        PROFILE: Resource inventory and configuration snapshots.
        BILLING: DBU consumption, cost attribution, and trends.
        OPTIMIZATION: Performance bottlenecks and tuning opportunities.
        GOVERNANCE: Access patterns, lineage, compliance, and data health.
    """

    PROFILE = "PROFILE"
    BILLING = "BILLING"
    OPTIMIZATION = "OPTIMIZATION"
    GOVERNANCE = "GOVERNANCE"


@dataclass(frozen=True)
class QueryMetadata:
    """LLM-facing metadata that describes a query's intent and output.

    Attached to each SystemQuery so the agent can make informed
    decisions about which queries to inspect or cite in findings.

    Args:
        summary: One-sentence plain-English description of the insight
            this query produces.
        output_hint: Brief description of the result shape
            (e.g., "Top 50 jobs ranked by DBU per run").
        tags: Freeform tags for secondary filtering.
    """

    summary: str
    output_hint: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SystemQuery:
    """A single parameterized SQL query against Databricks system tables.

    Args:
        query_id: Unique identifier (e.g., "C-B01", "P-AUDIT01").
        name: Human-readable name.
        description: What this query measures and why.
        sql_template: SQL with ``{lookback_days}`` and optional ``{result_limit}`` placeholders.
        required_tables: System tables this query reads from.
        domain: Which domain this query belongs to.
        required: If True, query failure marks the domain as degraded.
        lookback_override: Per-query override of the global lookback_days.
        max_lookback_days: Upper bound on the effective lookback for this query,
            used to keep the window within the source table's retention (e.g.,
            ``system.compute.node_timeline`` and ``system.serving.endpoint_usage``
            retain 90 days). The executor clamps the effective lookback to
            ``min(effective_lookback, max_lookback_days)`` so a larger configured
            or overridden lookback never silently returns empty results. ``None``
            means no clamp.
        output_columns: Expected column names in the result (for validation).
        required_columns: Source columns this query reads from its
            ``required_tables``.  Used by the CI schema-validation guard
            (``tests/contract/test_preview_pack_schema.py``) to assert that
            every column referenced in the SQL exists in the recorded
            ``system_table_columns.json`` manifest.  An empty tuple means "no
            declared column requirements" (legacy packs).
        discovery_mode: Filter queries by run depth.
        category: Classify analytical purpose.
        metadata: LLM context metadata.
    """

    query_id: str
    name: str
    description: str
    sql_template: str
    required_tables: tuple[str, ...]
    domain: str
    required: bool = True
    lookback_override: int | None = None
    max_lookback_days: int | None = None
    output_columns: tuple[str, ...] | None = None
    required_columns: tuple[str, ...] = ()
    discovery_mode: DiscoveryMode = DiscoveryMode.GENERAL
    category: QueryCategory = QueryCategory.PROFILE
    metadata: QueryMetadata | None = None


@dataclass(frozen=True)
class QueryPack:
    """Collection of queries for a domain workload.

    Args:
        pack_id: Unique identifier (e.g., "billing", "jobs", "apps").
        domain: Domain this pack analyzes.
        name: Human-readable name.
        description: What this pack covers.
        queries: Ordered tuple of queries to execute.
        gating_products: ``billing_origin_product`` values that must be present
            in the audit to run this pack. Empty means always run.
    """

    pack_id: str
    domain: str
    name: str
    description: str
    queries: tuple[SystemQuery, ...]
    gating_products: frozenset[str] = frozenset()


@dataclass(frozen=True)
class QueryResult:
    """Result of executing a single SystemQuery.

    Args:
        query_id: ID of the query that produced this result.
        domain: Domain the query belongs to.
        data: Polars DataFrame with results, or None on failure/skip.
        error: Error message if the query failed, or the reason it was skipped.
        execution_time_ms: Wall-clock time for query execution.
        row_count: Number of rows returned.
        skipped: True when the query was deliberately not run (e.g. it is
            unavailable on the selected source) rather than attempted and failed.
            A skip is an expected coverage gap, NOT an error.
        result_limit: The SQL ``LIMIT`` this query ran with (its rendered
            ``{result_limit}``), or None when the query has no templated row
            limit. A result whose ``row_count`` reaches it was capped by the SQL.
        lookback_days: Effective lookback window this query ran with —
            ``query.lookback_override`` if the query has a per-query override,
            else the run-level default, clamped by ``max_lookback_days`` when
            set. ``None`` for skipped/unavailable queries that never ran.
        attempts: Number of times the statement was submitted (1 = no retry;
            >1 when a poll-deadline timeout was retried). 0 when never run.
        attempt_elapsed_ms: Wall-clock time of each submission, in order
            (back-off sleeps between attempts are excluded).
    """

    query_id: str
    domain: str
    data: pl.DataFrame | None
    error: str | None = None
    execution_time_ms: float = 0.0
    row_count: int = 0
    skipped: bool = False
    result_limit: int | None = None
    lookback_days: int | None = None
    attempts: int = 0
    attempt_elapsed_ms: tuple[float, ...] = ()

    @property
    def succeeded(self) -> bool:
        """True if the query returned data without error."""
        return self.data is not None and self.error is None

    @property
    def status(self) -> str:
        """Outcome as one of ``"succeeded"``, ``"skipped"``, or ``"failed"``.

        A skip (e.g. unavailable on the selected source) is distinct from a
        failure: it is an expected coverage gap, not an error.
        """
        if self.succeeded:
            return "succeeded"
        return "skipped" if self.skipped else "failed"


@dataclass(frozen=True)
class PackResult:
    """Aggregated results for a query pack.

    Args:
        pack_id: ID of the pack.
        domain: Domain this pack covers.
        results: Individual query results.
    """

    pack_id: str
    domain: str
    results: tuple[QueryResult, ...]

    @property
    def total_execution_time_ms(self) -> float:
        """Sum of all query execution times."""
        return sum(r.execution_time_ms for r in self.results)

    @property
    def success_count(self) -> int:
        """Number of queries that returned data."""
        return sum(1 for r in self.results if r.succeeded)

    @property
    def skipped_count(self) -> int:
        """Number of queries deliberately skipped (e.g. unavailable on source)."""
        return sum(1 for r in self.results if r.skipped and not r.succeeded)

    @property
    def failure_count(self) -> int:
        """Number of queries that were attempted and failed (excludes skips)."""
        return sum(1 for r in self.results if not r.succeeded and not r.skipped)
