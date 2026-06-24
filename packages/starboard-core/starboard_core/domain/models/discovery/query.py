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
        output_columns: Expected column names in the result (for validation).
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
    output_columns: tuple[str, ...] | None = None
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
        data: Polars DataFrame with results, or None on failure.
        error: Error message if the query failed.
        execution_time_ms: Wall-clock time for query execution.
        row_count: Number of rows returned.
    """

    query_id: str
    domain: str
    data: pl.DataFrame | None
    error: str | None = None
    execution_time_ms: float = 0.0
    row_count: int = 0

    @property
    def succeeded(self) -> bool:
        """True if the query returned data without error."""
        return self.data is not None and self.error is None


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
    def failure_count(self) -> int:
        """Number of queries that failed."""
        return sum(1 for r in self.results if not r.succeeded)
