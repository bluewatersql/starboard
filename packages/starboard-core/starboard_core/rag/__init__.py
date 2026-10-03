# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""RAG (Retrieval-Augmented Generation) data models for Analytics Agent."""

from starboard_core.rag.models import (
    AggregationRecord,
    AnalysisResult,
    ColumnMetadata,
    FacetRow,
    JoinRecord,
    PredicateRecord,
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
    RelationshipCondition,
    RelationshipMetadata,
    TableMetadata,
)
from starboard_core.rag.resource_domains import (
    RagResourceDomain,
    TableDomainMapping,
    map_many_system_tables,
    map_system_table_to_rag_resource_domains,
)

__all__ = [
    "AggregationRecord",
    "AnalysisResult",
    "ColumnMetadata",
    "FacetRow",
    "JoinRecord",
    "PredicateRecord",
    "RAGCodebookContext",
    "RAGContext",
    "RAGFacetContext",
    "RAGNuanceContext",
    "RAGTableContext",
    "RagResourceDomain",
    "RelationshipCondition",
    "RelationshipMetadata",
    "TableDomainMapping",
    "TableMetadata",
    "map_many_system_tables",
    "map_system_table_to_rag_resource_domains",
]
