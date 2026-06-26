# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Data models for RAG (Retrieval-Augmented Generation) in Analytics Agent.

These models represent table metadata extracted from Databricks system tables,
enriched with LLM-generated context, and real-world usage patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from starboard_core.foundations.models import ReflexionLearning

# =============================================================================
# RAG Context Models
# =============================================================================


class RAGNuanceContext(BaseModel):
    """RAG nuance context for domain-specific best practices.

    Attributes:
        topic: Topic of the nuance
        type: Type of the nuance (tip, warning, pattern, etc.)
        content: Content of the nuance
        domain: Domain of the nuance (billing, compute, etc.)
        relevance_score: Confidence score (0.0 to 1.0)

    Example:
        >>> nuance = RAGNuanceContext(
        ...     topic="Cost optimization",
        ...     type="tip",
        ...     content="Use list_prices table for cost analysis",
        ...     domain="billing",
        ...     relevance_score=0.95
        ... )
    """

    topic: str = Field(..., description="Topic of the nuance")
    type: str = Field(..., description="Type of the nuance")
    content: str = Field(..., description="Content of the nuance")
    domain: str = Field(..., description="Domain of the nuance")
    relevance_score: float = Field(..., description="Confidence score", ge=0.0, le=1.0)


class RAGFacetContext(BaseModel):
    """RAG facet context for categorical values.

    Attributes:
        code: Code or key of the facet
        values: List of valid values for this facet
        domain: Domain of the facet
        relevance_score: Confidence score (0.0 to 1.0)

    Example:
        >>> facet = RAGFacetContext(
        ...     code="warehouse_size",
        ...     values=["X_SMALL", "SMALL", "MEDIUM", "LARGE", "X_LARGE"],
        ...     domain="compute",
        ...     relevance_score=0.90
        ... )
    """

    code: str = Field(..., description="Code of the facet")
    values: list[str] = Field(default_factory=list, description="Values of the facet")
    domain: str = Field(..., description="Domain of the facet")
    relevance_score: float = Field(..., description="Confidence score", ge=0.0, le=1.0)


class RAGCodebookContext(BaseModel):
    """RAG codebook context for field definitions and value mappings.

    Attributes:
        code: Code identifier
        description: Description of the codebook
        sku_family: SKU family classification
        warehouse_type: Warehouse type classification
        time_validity: Time validity information
        involves_tags: Whether tags are involved
        domain: Domain of the codebook
        relevance_score: Confidence score (0.0 to 1.0)

    Example:
        >>> codebook = RAGCodebookContext(
        ...     code="usage_metadata.job_id",
        ...     description="Unique identifier for a job",
        ...     sku_family="N/A",
        ...     warehouse_type="ALL",
        ...     time_validity="Always",
        ...     involves_tags=False,
        ...     domain="billing",
        ...     relevance_score=0.92
        ... )
    """

    code: str = Field(..., description="Code of the codebook")
    description: str = Field(..., description="Description of the codebook")
    sku_family: str = Field(..., description="SKU family of the codebook")
    warehouse_type: str = Field(..., description="Warehouse type of the codebook")
    time_validity: str = Field(..., description="Time validity of the codebook")
    involves_tags: bool = Field(..., description="Whether the codebook involves tags")
    domain: str = Field(..., description="Domain of the codebook")
    relevance_score: float = Field(..., description="Confidence score", ge=0.0, le=1.0)


class RAGTableContext(BaseModel):
    """RAG table context for system table metadata.

    Attributes:
        table_name: Name of the table
        description: Description of the table
        table_columns: Description of table columns
        relationships: Table relationships
        use_cases: Common use cases
        domain: Domain of the table
        relevance_score: Confidence score (0.0 to 1.0)

    Example:
        >>> table = RAGTableContext(
        ...     table_name="system.billing.usage",
        ...     description="Databricks usage tracking",
        ...     table_columns="usage_date, sku_name, usage_quantity",
        ...     relationships="Joins with list_prices on sku_name",
        ...     use_cases="Cost analysis, usage trends",
        ...     domain="billing",
        ...     relevance_score=0.98
        ... )
    """

    table_name: str | None = Field(None, description="Name of the table")
    description: str | None = Field(None, description="Description of the table")
    table_columns: str | None = Field(None, description="Columns of the table")
    relationships: str | None = Field(None, description="Relationships of the table")
    use_cases: str | None = Field(None, description="Use cases of the table")
    domain: str | None = Field(None, description="Domain of the table")
    relevance_score: float | None = Field(
        None, description="Confidence score", ge=0.0, le=1.0
    )


class RAGContext(BaseModel):
    """Context gathered from RAG tools.

    This model contains all relevant information retrieved from the
    RAG vector store to inform query building.

    Attributes:
        tables: Relevant system tables discovered
        nuances: Best practices and domain knowledge
        codebook: Field definitions and value mappings
        facets: Valid categorical values
        learnings: Successful query patterns from past
    """

    tables: list[RAGTableContext] = Field(
        default_factory=list, description="Discovered tables"
    )
    nuance: list[RAGNuanceContext] = Field(
        default_factory=list, description="Best practices and knowledge"
    )
    codebook: list[RAGCodebookContext] = Field(
        default_factory=list, description="Field definitions"
    )
    facets: list[RAGFacetContext] = Field(
        default_factory=list, description="Categorical values"
    )
    learnings: list[ReflexionLearning] = Field(
        default_factory=list, description="Past successful patterns"
    )


# =============================================================================
# SQL Analysis Models (Discovery by Example)
# =============================================================================


class JoinRecord(BaseModel):
    """
    Record of a join pattern extracted from real query history.

    Represents a single join between two tables as observed in production SQL.
    """

    model_config = ConfigDict(frozen=True)

    from_table: str
    to_table: str
    join_type: str  # INNER, LEFT, RIGHT, FULL, CROSS
    join_pairs: tuple[tuple[str, str], ...]  # ((from_col, to_col), ...)
    join_condition: str  # Full condition text


class PredicateRecord(BaseModel):
    """
    Record of a predicate (WHERE clause condition) from real query history.

    Captures common filter patterns and values used in production queries.
    """

    model_config = ConfigDict(frozen=True)

    scope: str  # WHERE, HAVING, ON, etc.
    op: str  # =, >, <, LIKE, IN, etc.
    lhs: str  # Left-hand side (column reference)
    rhs_kind: str  # literal, column, expression
    rhs: str  # Right-hand side value
    negated: bool = False
    values: tuple[str, ...] = ()  # Actual values observed


class AggregationRecord(BaseModel):
    """
    Record of an aggregation function from real query history.

    Tracks which aggregations are commonly used on which columns.
    """

    model_config = ConfigDict(frozen=True)

    agg: str  # COUNT, SUM, AVG, MIN, MAX, etc.
    arg_kind: str  # column, expression, star
    arg: str  # Column or expression being aggregated
    alias: str | None = None
    distinct: bool = False


class AnalysisResult(BaseModel):
    """
    Complete analysis results from discovery by example.

    Contains both raw records (joins, predicates, aggregations) and
    higher-level summaries for use in metadata enrichment.
    """

    success_count: int
    failed_count: int

    # Summaries (for quick reference)
    join_summary: list[dict[str, Any]]

    # Raw records (for detailed analysis)
    raw_joins: list[JoinRecord] | None = None
    raw_predicates: list[PredicateRecord] | None = None
    raw_aggregations: list[AggregationRecord] | None = None


# =============================================================================
# Relationship Models
# =============================================================================


class RelationshipCondition(BaseModel):
    """
    A single condition in a table relationship.

    Captures extended join conditions beyond simple column equality.
    """

    condition: str  # e.g., "usage_date BETWEEN pricing_start_time AND pricing_end_time"
    frequency: str  # very_common, common, occasional, rare


class RelationshipMetadata(BaseModel):
    """
    Metadata describing a relationship between two tables.

    Derived from real-world join patterns in production queries.
    """

    from_table: str  # system.billing.usage
    to_table: str  # system.billing.list_prices
    join_types: list[str]  # [INNER, LEFT]
    core_columns: str  # sku_name = sku_name
    extended_conditions: list[RelationshipCondition]  # Temporal joins, etc.

    @property
    def full_name(self) -> str:
        """Fully qualified relationship name."""
        return f"{self.from_table} -> {self.to_table}"


# =============================================================================
# Column & Table Models
# =============================================================================


class ColumnMetadata(BaseModel):
    """
    Metadata for a single column.

    Combines schema information from information_schema with:
    - Real-world usage patterns (aggregations, filters)
    - LLM-generated business context
    """

    table_name: str  # Full table name (catalog.schema.table)
    column_name: str
    data_type: str  # BIGINT, STRING, TIMESTAMP, etc.
    is_nullable: bool = True
    comment: str | None = None

    # Real-world usage patterns (from discovery by example)
    common_aggregations: list[str] = Field(default_factory=list)  # [SUM, AVG]
    example_filters: list[str] = Field(default_factory=list)  # Example WHERE values

    # LLM-enriched fields
    column_type: str | None = (
        None  # identifier, temporal, dimension, metric, flag, other
    )
    business_meaning: str | None = None  # What this column represents in business terms
    cardinality_estimate: str | None = (
        None  # unique, near-unique, high, medium, low, unknown
    )

    @property
    def full_name(self) -> str:
        """Fully qualified column name."""
        return f"{self.table_name}.{self.column_name}"


class TableMetadata(BaseModel):
    """
    Comprehensive metadata for a single table.

    Combines:
    - Schema information from information_schema
    - Real-world usage patterns from query history
    - LLM-generated business context and use cases
    """

    table_catalog: str  # system
    table_schema: str  # billing, compute, query, etc.
    table_name: str  # usage, list_prices, warehouses, etc.
    table_type: str  # TABLE, VIEW
    comment: str | None = None

    # Real-world usage patterns (from discovery by example)
    common_join_columns: list[str] = Field(default_factory=list)
    relationships: list[RelationshipMetadata] = Field(default_factory=list)

    # LLM-enriched fields
    business_context: str | None = None  # 2-3 sentences on what this table is used for
    grain: str | None = None  # One row represents...
    common_use_cases: list[str] = Field(default_factory=list)  # 3-5 typical queries

    # Columns
    columns: list[ColumnMetadata] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        """Fully qualified table name."""
        return f"{self.table_catalog}.{self.table_schema}.{self.table_name}"


# =============================================================================
# Facet Models (for categorical value explosion)
# =============================================================================


@dataclass(frozen=True)
class FacetRow:
    """
    One exploded facet value from a codebook/code-pack record.

    Designed for re-ingestion into a vector DB for semantic matching
    of categorical values.

    Example:
        facet_key: "system.compute.warehouses.warehouse_size"
        facet_value: "X_LARGE"
        facet_norm: "x large"  # For fuzzy matching
        domain: "compute_warehouses"
    """

    facet_key: str  # Column path (e.g., "system.compute.warehouses.warehouse_size")
    facet_value: str  # Canonical value (e.g., "X_LARGE")
    facet_norm: str  # Normalized for matching (e.g., "x large")
    domain: str  # Domain this facet belongs to
    parent_id: str  # Codebook topic ID
    base_id: str  # Unique ID for this facet
    source_record_id: str  # Original codebook record ID
    doc_set_version: int  # Version of the document set
    is_active: bool  # Whether this facet is currently active
    hint: str  # Optional SQL hint or semantic note
