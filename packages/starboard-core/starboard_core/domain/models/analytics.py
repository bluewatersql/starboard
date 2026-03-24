"""Domain models for analytics queries.

This module defines immutable data structures for the system query catalog,
query parameters, results, and indexes. All models are frozen dataclasses
following the pure domain pattern (no I/O, no side effects).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueryMetadata:
    """Metadata for a system query from the catalog.

    Represents a single pre-built query with all its associated metadata
    including domains, scenarios, parameters, and the SQL text itself.

    Attributes:
        id: Unique UUID for the query
        name: Short human-readable name
        description: Brief summary of what the query does
        long_description: Detailed explanation of the query's purpose
        descriptive_name: Alternative descriptive name
        domains: List of applicable domains (e.g., ["FinOps", "Job"])
        scenarios: List of use case scenarios (e.g., ["cost optimization"])
        constraints: List of constraints (e.g., ["serverless_only"])
        parameters: List of parameter names (e.g., ["start_date", "end_date"])
        dependencies: List of related query IDs
        tables: List of system tables accessed by the query
        query: The SQL text of the query
        required_parameters: Enhanced parameter metadata from query_map.json
        chart_metadata: Chart/visualization metadata for UI rendering
        override_row_limit: When True, disables automatic LIMIT enforcement

    Example:
        >>> query = QueryMetadata(
        ...     id="b733352d-a70c-452b-9890-16488d4a8ca6",
        ...     name="Top 10 Most Expensive Jobs",
        ...     description="Analyzes job costs over configurable time period",
        ...     long_description="Detailed cost analysis...",
        ...     descriptive_name="Cost Analysis - Top Expensive Jobs",
        ...     domains=["FinOps", "Job"],
        ...     scenarios=["cost optimization", "capacity planning"],
        ...     constraints=["serverless_only"],
        ...     parameters=["start_date", "end_date"],
        ...     dependencies=[],
        ...     tables=["system.billing.usage", "system.lakeflow.jobs"],
        ...     query="WITH usage_raw AS (...) SELECT ...",
        ...     chart_metadata={"default_family": "time-series", ...}
        ... )
    """

    id: str
    name: str
    description: str
    long_description: str
    descriptive_name: str
    domains: list[str]
    scenarios: list[str]
    constraints: list[str]
    parameters: list[str]
    dependencies: list[str]
    tables: list[str]
    query: str
    required_parameters: list[dict[str, Any]] = field(default_factory=list)
    result_columns: list[dict[str, Any]] = field(default_factory=list)
    chart_metadata: dict[str, Any] = field(default_factory=dict)
    override_row_limit: bool = False


@dataclass(frozen=True)
class QueryParameter:
    """Specification for a query parameter.

    Defines a single parameter that a query accepts, including its type,
    whether it's required, default value, and description.

    Attributes:
        name: Parameter name (e.g., "start_date")
        type: Parameter type ("string", "date", "integer", "float")
        required: Whether this parameter must be provided
        default: Default value if parameter is optional (None if required)
        description: Human-readable description of the parameter

    Example:
        >>> param = QueryParameter(
        ...     name="start_date",
        ...     type="date",
        ...     required=False,
        ...     default="30 days ago",
        ...     description="Start date for cost analysis"
        ... )
    """

    name: str
    type: str  # "string", "date", "integer", "float"
    required: bool
    default: Any | None
    description: str


@dataclass(frozen=True)
class SystemQueryResult:
    """Results from executing a system query.

    Contains the query results along with execution metadata and a
    summary suitable for LLM consumption.

    Attributes:
        query_id: UUID of the executed query
        query_name: Human-readable name of the query
        execution_time_ms: Query execution time in milliseconds
        row_count: Number of rows returned
        results: List of result rows (each row is a dict)
        summary: Query-specific summary statistics

    Example:
        >>> result = SystemQueryResult(
        ...     query_id="b733352d-...",
        ...     query_name="Top 10 Most Expensive Jobs",
        ...     execution_time_ms=1234,
        ...     row_count=10,
        ...     results=[
        ...         {"job_id": "123", "job_name": "ETL Pipeline", "total_cost": 456.78},
        ...         # ... more rows
        ...     ],
        ...     summary={
        ...         "total_jobs": 10,
        ...         "total_cost": 1234.56,
        ...         "avg_cost": 123.46,
        ...         "date_range": "2025-11-01 to 2025-11-30"
        ...     }
        ... )
    """

    query_id: str
    query_name: str
    execution_time_ms: int
    row_count: int
    results: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass
class QueryCatalogIndex:
    """Index structures for fast query lookup.

    Provides multiple indexes for efficient searching of the query catalog
    by ID, domain, scenario, table, and keywords.

    Note: This is mutable (not frozen) because it's built incrementally
    during catalog loading. After building, it should be treated as immutable.

    Attributes:
        by_id: Maps query ID to QueryMetadata
        by_domain: Maps domain name to list of queries
        by_scenario: Maps scenario name to list of queries
        by_table: Maps table name to list of queries
        by_keywords: Maps keyword to list of queries

    Example:
        >>> index = QueryCatalogIndex(
        ...     by_id={"query-id-1": query1, "query-id-2": query2},
        ...     by_domain={"FinOps": [query1, query2], "Job": [query1]},
        ...     by_scenario={"cost optimization": [query1, query2]},
        ...     by_table={"system.billing.usage": [query1]},
        ...     by_keywords={"expensive": [query1], "cost": [query1, query2]}
        ... )
    """

    by_id: dict[str, QueryMetadata]
    by_domain: dict[str, list[QueryMetadata]]
    by_scenario: dict[str, list[QueryMetadata]]
    by_table: dict[str, list[QueryMetadata]]
    by_keywords: dict[str, list[QueryMetadata]]
