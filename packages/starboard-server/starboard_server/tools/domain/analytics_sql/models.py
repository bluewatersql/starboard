"""Analytics SQL - Query Context Models.

Pydantic models for representing query building context and intent classification.
These models flow through the query building pipeline.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field
from starboard_core.rag.models import RAGContext


class QueryIntent(str, Enum):
    """Classification of user's analytical intent.

    Attributes:
        COST_ANALYSIS: Analyze costs and spending patterns
        PERFORMANCE_ANALYSIS: Analyze query or job performance
        RESOURCE_UTILIZATION: Analyze resource usage (warehouses, clusters)
        USER_ACTIVITY: Analyze user behavior and access patterns
        TREND_ANALYSIS: Analyze trends over time
        COMPARISON: Compare metrics across dimensions
        TROUBLESHOOTING: Investigate failures or issues
        UNKNOWN: Intent could not be classified
    """

    COST_ANALYSIS = "cost_analysis"
    PERFORMANCE_ANALYSIS = "performance_analysis"
    RESOURCE_UTILIZATION = "resource_utilization"
    USER_ACTIVITY = "user_activity"
    TREND_ANALYSIS = "trend_analysis"
    COMPARISON = "comparison"
    TROUBLESHOOTING = "troubleshooting"
    UNKNOWN = "unknown"


class QueryDomain(str, Enum):
    """Databricks domain for the query.

    Attributes:
        BILLING: system.billing.* tables
        COMPUTE: system.compute.* tables
        QUERY: system.query.* tables
        LAKEFLOW: system.lakeflow.* tables (jobs, pipelines)
        CATALOG: system.catalog.* tables (Unity Catalog)
        MIXED: Multiple domains
        UNKNOWN: Domain could not be determined
    """

    BILLING = "finops_billing"
    COMPUTE = "compute_warehouses"
    CLUSTER = "compute_clusters"
    QUERY = "query_performance"
    LAKEFLOW = "job_workflows"
    CATALOG = "unity_catalog"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AggregationType(str, Enum):
    """Type of aggregation requested.

    Attributes:
        SUM: Sum of values
        AVG: Average of values
        COUNT: Count of rows
        MAX: Maximum value
        MIN: Minimum value
        TOP_N: Top N items by metric
        BOTTOM_N: Bottom N items by metric
        DISTINCT_COUNT: Count of distinct values
        NONE: No aggregation (raw data)
    """

    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MAX = "max"
    MIN = "min"
    TOP_N = "top_n"
    BOTTOM_N = "bottom_n"
    DISTINCT_COUNT = "distinct_count"
    NONE = "none"


class TimeGranularity(str, Enum):
    """Time granularity for grouping.

    Attributes:
        HOUR: Group by hour
        DAY: Group by day
        WEEK: Group by week
        MONTH: Group by month
        QUARTER: Group by quarter
        YEAR: Group by year
        NONE: No time grouping
    """

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    NONE = "none"


class QueryIntentContext(BaseModel):
    """Classified intent and extracted query parameters.

    This model represents the LLM's understanding of the user's query,
    including intent, domain, requested metrics, and filters.

    Attributes:
        intent: Primary analytical intent
        domain: Databricks domain (billing, compute, etc.)
        metrics: Requested metrics (e.g., ["cost", "dbu_usage"])
        dimensions: Grouping dimensions (e.g., ["workspace", "job"])
        aggregation: Type of aggregation requested
        time_range_days: Number of days to analyze (e.g., 30, 90)
        time_granularity: Time grouping granularity
        filters: Additional filters (e.g., {"usage_type": "WAREHOUSES"})
        limit: Maximum number of results (for TOP_N queries)
        sort_by: Sort column and direction
        requires_join: Whether query needs to join multiple tables
        confidence: Confidence score (0.0-1.0)
        reasoning: LLM's reasoning for classification
    """

    intent: QueryIntent = Field(..., description="Primary analytical intent")
    domain: QueryDomain = Field(..., description="Databricks domain")
    metrics: list[str] = Field(
        default_factory=list, description="Requested metrics to calculate"
    )
    dimensions: list[str] = Field(
        default_factory=list, description="Grouping dimensions"
    )
    rag_resource_domains: list[str] = Field(
        default_factory=list,
        description="RAG resource domains to drive context retrieval",
    )
    aggregation: AggregationType = Field(
        default=AggregationType.SUM, description="Aggregation type"
    )
    time_range_days: int | None = Field(
        None, description="Number of days to analyze", ge=1, le=365
    )
    time_granularity: TimeGranularity = Field(
        default=TimeGranularity.NONE, description="Time grouping granularity"
    )
    filters: dict[str, str | int | float | list[str]] = Field(
        default_factory=dict, description="Additional filters"
    )
    limit: int | None = Field(None, description="Result limit", ge=1, le=1000)
    sort_by: str | None = Field(None, description="Sort column")
    sort_desc: bool = Field(True, description="Sort descending")
    requires_join: bool = Field(False, description="Needs multi-table join")
    confidence: float = Field(..., description="Confidence score", ge=0.0, le=1.0)
    reasoning: str = Field(..., description="LLM reasoning for classification")


class QueryBuildContext(BaseModel):
    """Complete context for building a SQL query.

    This model combines intent classification and RAG context to provide
    all information needed for SQL generation.

    Attributes:
        user_query: Original natural language query
        intent_context: Classified intent and parameters
        rag_context: RAG-retrieved context
        validation_mode: Whether to validate SQL (online vs offline)
    """

    user_query: str = Field(..., description="Original NL query", min_length=1)
    intent_context: QueryIntentContext = Field(..., description="Classified intent")
    rag_context: RAGContext = Field(..., description="RAG-retrieved context")
    validation_mode: str = Field(
        default="online", description="Validation mode (online/offline)"
    )


class ValidationResult(BaseModel):
    """Result of SQL validation.

    Attributes:
        is_valid: Whether SQL passed validation
        errors: List of validation errors (if any)
        warnings: List of warnings (non-fatal issues)
        sql_normalized: Normalized SQL (formatted, comments removed)
        validation_method: Method used (sqlglot, explain, both)
    """

    is_valid: bool = Field(..., description="Whether SQL is valid")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    validation_method: str = Field(..., description="Validation method used")


class AnalyticsResult(BaseModel):
    """Complete analytics query result from pipeline.

    This is the final output of the query orchestrator, containing:
    - Generated SQL
    - Query results (rows)
    - Formatted profile for LLM consumption
    - Visualization configuration
    - Intent classification context
    - RAG discovery context
    - Execution metadata

    Attributes:
        sql: Generated SQL query string
        results: Query results (list of row dicts)
        metadata: Execution metadata (row count, timing, etc.)
        formatted_results: LLM-friendly data profile with statistics and summaries
        visualization: Visualization recommendation and chart config
        intent_context: Classified intent and domain
        rag_context: RAG-retrieved context (tables, nuances, etc.)
        iterations: Number of Reflexion iterations used
        cached: Whether result came from semantic cache
        execution_time_ms: Total orchestration time in milliseconds
    """

    sql: str = Field(..., description="Generated SQL query", min_length=1)
    results: list[dict] = Field(
        default_factory=list, description="Query results (rows as dicts)"
    )
    metadata: dict = Field(default_factory=dict, description="Execution metadata")
    formatted_results: dict = Field(
        default_factory=dict,
        description="LLM-friendly data profile with statistics and summaries",
    )
    visualization: dict = Field(
        default_factory=dict,
        description="Visualization recommendation and chart configuration",
    )
    intent_context: QueryIntentContext = Field(..., description="Intent classification")
    rag_context: RAGContext = Field(..., description="RAG context")
    iterations: int = Field(default=1, description="Reflexion iterations used", ge=1)
    cached: bool = Field(default=False, description="Result from cache")
    execution_time_ms: int = Field(
        default=0, description="Total execution time (ms)", ge=0
    )
