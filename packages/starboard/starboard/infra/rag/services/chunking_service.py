# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Table chunking service for semantic retrieval.

Breaks table metadata into semantic chunks for better vector search:
- table_summary: Overview, grain, join columns
- use_cases: Concrete analytics scenarios
- relationships: Join patterns with other tables
- column: Individual column with semantics (one per column)

Pattern:
    service = ChunkingService()
    chunks = service.chunk_table(table_metadata)
    # Returns list of TableChunk objects
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from starboard_core.rag.models import ColumnMetadata, TableMetadata

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TableChunk:
    """
    Semantic chunk from table metadata.

    Represents one piece of table information optimized for vector search.

    Attributes:
        chunk_type: Type of chunk ("table_summary" | "use_cases" | "relationships" | "column")
        base_id: Canonical ID (e.g., "system.billing.usage::table_summary")
        content: Text content for embedding
        metadata: Additional metadata (table_name, domain, doc_type, etc.)
        column_name: Column name (for column chunks only)
    """

    chunk_type: str
    base_id: str
    content: str
    metadata: dict[str, str]
    column_name: str | None = None


class ChunkingService:
    """
    Service for chunking table metadata into semantic pieces.

    Breaks tables into 4 chunk types for optimized retrieval:
    1. table_summary - Overview, purpose, grain
    2. use_cases - Common analytics scenarios
    3. relationships - Join patterns with other tables
    4. column - Individual column metadata (one chunk per column)
    """

    def chunk_table(self, table: TableMetadata) -> list[TableChunk]:
        """
        Chunk table metadata into semantic pieces.

        Args:
            table: Table metadata to chunk

        Returns:
            List of table chunks (1 summary + optional use_cases + optional relationships + N columns)

        Example:
            >>> service = ChunkingService()
            >>> chunks = service.chunk_table(table_metadata)
            >>> print(f"Generated {len(chunks)} chunks")
            >>> summary_chunks = [c for c in chunks if c.chunk_type == "table_summary"]
        """
        chunks: list[TableChunk] = []

        # Create short summary chunk
        chunks.append(self._build_summary_chunk(table))

        # Create detailed summary chunk (distinct chunk_type: table_detailed_summary)
        chunks.append(self._build_summary_chunk(table, detailed=True))

        # Create use_cases chunk if table has use cases
        if table.common_use_cases:
            chunks.append(self._build_use_cases_chunk(table))

        # Create relationships chunk if table has relationships
        if table.relationships:
            chunks.append(self._build_relationships_chunk(table))

        # Create short table columns chunk
        chunks.append(
            self._build_table_columns_chunk(table, table.columns, detailed=False)
        )

        # Create detailed table columns chunk
        chunks.append(
            self._build_table_columns_chunk(table, table.columns, detailed=True)
        )

        # Create columns detail chunk
        chunks.extend(self._build_columns_chunk(table, table.columns))

        logger.debug(
            "table_chunked",
            table=table.full_name,
            chunks=len(chunks),
            summary=1,
            use_cases=1 if table.common_use_cases else 0,
            relationships=1 if table.relationships else 0,
            columns=len(table.columns),
        )

        return chunks

    def _build_summary_chunk(
        self, table: TableMetadata, detailed: bool = False
    ) -> TableChunk:
        """
        Build summary chunk with table overview.

        Includes: purpose, grain, common join columns.
        """
        lines = [
            f"TABLE: {table.full_name}",
            f"DOC_TYPE: {'table_summary' if not detailed else 'table_detailed_summary'}",
            f"Purpose: {table.business_context or table.comment or 'No description'}",
            f"Grain: {table.grain or 'Unknown'}",
        ]

        if detailed:
            if table.columns:
                lines.append(
                    "Columns:\n"
                    + "\n    - ".join(
                        [f"{c.column_name} ({c.data_type})" for c in table.columns]
                    )
                )

            if table.common_use_cases:
                lines.append("Use Cases:\n- " + "\n- ".join(table.common_use_cases))

            if table.common_join_columns:
                lines.append(
                    "Common Join Columns:\n"
                    + ",".join(
                        [
                            col.replace(f"{table.table_schema}.{table.table_name}.", "")
                            for col in table.common_join_columns
                        ]
                    )
                )

        content = "\n".join(lines)
        base_id = self._make_base_id(
            table.full_name,
            "table_summary" if not detailed else "table_detailed_summary",
        )

        return TableChunk(
            chunk_type="table_summary" if not detailed else "table_detailed_summary",
            base_id=base_id,
            content=content,
            metadata={
                "table_name": table.full_name,
                "doc_type": "table_summary"
                if not detailed
                else "table_detailed_summary",
                "table_catalog": table.table_catalog,
                "table_schema": table.table_schema,
            },
        )

    def _build_use_cases_chunk(self, table: TableMetadata) -> TableChunk:
        """
        Build use_cases chunk with concrete analytics scenarios.

        Only called if table has use cases.
        """
        lines = [
            f"TABLE: {table.full_name}",
            "DOC_TYPE: use_cases",
            "Use Cases:",
            "- " + "\n- ".join(table.common_use_cases),
        ]

        content = "\n".join(lines)
        base_id = self._make_base_id(table.full_name, "use_cases")

        return TableChunk(
            chunk_type="use_cases",
            base_id=base_id,
            content=content,
            metadata={
                "table_name": table.full_name,
                "doc_type": "use_cases",
                "table_catalog": table.table_catalog,
                "table_schema": table.table_schema,
            },
        )

    def _build_relationships_chunk(self, table: TableMetadata) -> TableChunk:
        """
        Build relationships chunk with join patterns.

        Only called if table has relationships.
        """
        lines = [
            f"TABLE: {table.full_name}",
            "DOC_TYPE: relationships",
            "Relationships:",
        ]

        for rel in table.relationships[:5]:
            rel_lines = [f" - {rel.to_table}"]

            if rel.join_types:
                rel_lines.append(f"   Join Types: {', '.join(rel.join_types)}")

            if rel.core_columns:
                rel_lines.append(f"   Join on: {rel.core_columns}")

            if rel.extended_conditions:
                conditions = [cond.condition for cond in rel.extended_conditions]
                rel_lines.append(f"   Extended Conditions: {', '.join(conditions)}")

            lines.extend(rel_lines)

        content = "\n".join(lines)
        base_id = self._make_base_id(table.full_name, "relationships")

        return TableChunk(
            chunk_type="relationships",
            base_id=base_id,
            content=content,
            metadata={
                "table_name": table.full_name,
                "doc_type": "relationships",
                "table_catalog": table.table_catalog,
                "table_schema": table.table_schema,
            },
        )

    def _build_table_columns_chunk(
        self,
        table: TableMetadata,
        columns: list[ColumnMetadata],
        detailed: bool = False,
    ) -> TableChunk:
        """
        Build table columns chunk for all columns in the table.

        Includes: column name, type, business meaning, cardinality, aggregations, filters.
        """
        parts = [
            f"TABLE: {table.full_name}",
            f"DOC_TYPE: {'table_columns' if not detailed else 'table_column_details'}",
            "Columns:",
        ]

        # Add column details
        for column in columns[:60]:
            col_details = [f" - {column.column_name} ({column.data_type})"]

            if detailed:
                if column.cardinality_estimate:
                    col_details.append(f"   Cardinality: {column.cardinality_estimate}")

                if column.common_aggregations:
                    col_details.append(
                        f"   Common Aggregations: {', '.join(column.common_aggregations)}"
                    )

            parts.extend(col_details)

        content = "\n".join(parts)
        base_id = self._make_base_id(
            table.full_name, "table_columns" if not detailed else "table_column_details"
        )

        return TableChunk(
            chunk_type="table_columns" if not detailed else "table_column_details",
            base_id=base_id,
            content=content,
            metadata={
                "table_name": table.full_name,
                "doc_type": "table_columns" if not detailed else "table_column_details",
                "table_catalog": table.table_catalog,
                "table_schema": table.table_schema,
            },
        )

    def _build_columns_chunk(
        self, table: TableMetadata, columns: list[ColumnMetadata]
    ) -> list[TableChunk]:
        """
        Build column chunk for individual column.

        Includes: column name, type, business meaning, cardinality, aggregations, filters.
        """
        chunks: list[TableChunk] = []
        parts = [
            f"TABLE: {table.full_name}",
            f"DOC_TYPE: {'column'}",
            "Columns:",
        ]

        # Add column details
        for column in columns:
            col_details = [f" - {column.column_name} ({column.data_type})"]

            if column.comment:
                col_details.append(f"   Comment: {column.comment}")

            if column.business_meaning:
                col_details.append(f"   Definition: {column.business_meaning}")

            if column.cardinality_estimate:
                col_details.append(f"   Cardinality: {column.cardinality_estimate}")

            if column.common_aggregations:
                col_details.append(
                    f"   Common Aggregations: {', '.join(column.common_aggregations)}"
                )

            if column.example_filters:
                examples_str = ", ".join(str(v) for v in column.example_filters[:5])
                col_details.append(f"   Example Filters: {examples_str}")

            parts.extend(col_details)

            content = "\n".join(parts)
            base_id = self._make_base_id(column.full_name, "column")

            chunks.append(
                TableChunk(
                    chunk_type="column",
                    base_id=base_id,
                    content=content,
                    metadata={
                        "table_name": table.full_name,
                        "doc_type": "column",
                        "table_catalog": table.table_catalog,
                        "table_schema": table.table_schema,
                        "column_name": column.column_name,
                        "fq_column_name": column.full_name,
                    },
                )
            )

        return chunks

    def _make_base_id(self, table_full_name: str, doc_type: str) -> str:
        """
        Generate base ID for chunk.

        Format:
        - Table chunks: "system.billing.usage::table_summary"
        """
        return f"{table_full_name}::{doc_type}"
