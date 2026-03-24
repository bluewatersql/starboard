"""
Unit tests for ChunkingService.

Tests table chunking into semantic pieces for vector search.
"""

from starboard_core.rag.models import (
    ColumnMetadata,
    RelationshipCondition,
    RelationshipMetadata,
    TableMetadata,
)
from starboard_server.infra.rag.services.chunking_service import (
    ChunkingService,
    TableChunk,
)


class TestTableChunk:
    """Test TableChunk model."""

    def test_table_chunk_basic(self):
        """Should create chunk with required fields."""
        chunk = TableChunk(
            chunk_type="table_summary",
            base_id="system.billing.usage::table_summary",
            content="TABLE: system.billing.usage\nPurpose: Billing data",
            metadata={"table_name": "system.billing.usage"},
        )

        assert chunk.chunk_type == "table_summary"
        assert chunk.base_id == "system.billing.usage::table_summary"
        assert "Billing data" in chunk.content
        assert chunk.metadata["table_name"] == "system.billing.usage"
        assert chunk.column_name is None

    def test_table_chunk_with_column_name(self):
        """Should support column_name for column chunks."""
        chunk = TableChunk(
            chunk_type="column",
            base_id="system.billing.usage::column::usage_date",
            content="COLUMN: usage_date",
            metadata={"column_name": "usage_date"},
            column_name="usage_date",
        )

        assert chunk.chunk_type == "column"
        assert chunk.column_name == "usage_date"

    def test_table_chunk_immutable(self):
        """Should be immutable (frozen dataclass)."""
        chunk = TableChunk(
            chunk_type="table_summary",
            base_id="test",
            content="test",
            metadata={},
        )

        import pytest

        with pytest.raises(AttributeError):
            chunk.chunk_type = "use_cases"  # type: ignore


class TestChunkingService:
    """Test ChunkingService."""

    def test_init(self):
        """Should initialize service."""
        service = ChunkingService()
        assert service is not None

    def test_chunk_table_minimal(self):
        """Should chunk table with minimal metadata."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
        )

        chunks = service.chunk_table(table)

        # Should have 1 summary chunk (no use_cases, no relationships, no columns)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "table_summary"
        assert "system.billing.usage" in chunks[0].content

    def test_chunk_table_with_columns(self):
        """Should create chunk for each column."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                ),
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="sku_name",
                    data_type="STRING",
                ),
            ],
        )

        chunks = service.chunk_table(table)

        # 1 summary + 2 columns
        assert len(chunks) == 3
        assert chunks[0].chunk_type == "table_summary"
        assert chunks[1].chunk_type == "column"
        assert chunks[1].column_name == "usage_date"
        assert chunks[2].chunk_type == "column"
        assert chunks[2].column_name == "sku_name"

    def test_chunk_table_with_use_cases(self):
        """Should create use_cases chunk if table has use cases."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            common_use_cases=[
                "Daily cost analysis",
                "SKU utilization trends",
            ],
        )

        chunks = service.chunk_table(table)

        # 1 summary + 1 use_cases
        assert len(chunks) == 2
        assert chunks[0].chunk_type == "table_summary"
        assert chunks[1].chunk_type == "use_cases"
        assert "Daily cost analysis" in chunks[1].content
        assert "SKU utilization trends" in chunks[1].content

    def test_chunk_table_with_relationships(self):
        """Should create relationships chunk if table has relationships."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            relationships=[
                RelationshipMetadata(
                    from_table="system.billing.usage",
                    to_table="system.billing.list_prices",
                    join_types=["LEFT", "INNER"],
                    core_columns="usage.sku_name = list_prices.sku_name",
                    extended_conditions=[
                        RelationshipCondition(
                            condition="usage_date BETWEEN price_start_time AND price_end_time",
                            frequency="very_common",
                        ),
                    ],
                ),
            ],
        )

        chunks = service.chunk_table(table)

        # 1 summary + 1 relationships
        assert len(chunks) == 2
        assert chunks[0].chunk_type == "table_summary"
        assert chunks[1].chunk_type == "relationships"
        assert "system.billing.list_prices" in chunks[1].content
        assert "LEFT" in chunks[1].content

    def test_chunk_table_complete(self):
        """Should create all chunk types for complete table."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            comment="Billing usage data",
            business_context="Tracks resource consumption and costs",
            grain="One row per SKU per day",
            common_use_cases=["Daily cost analysis"],
            common_join_columns=["workspace_id", "sku_name"],
            relationships=[
                RelationshipMetadata(
                    from_table="system.billing.usage",
                    to_table="system.billing.list_prices",
                    join_types=["LEFT"],
                    core_columns="sku_name",
                    extended_conditions=[],
                ),
            ],
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                    comment="Date of usage",
                    business_meaning="The date when resources were consumed",
                    cardinality_estimate="high",
                ),
            ],
        )

        chunks = service.chunk_table(table)

        # 1 summary + 1 use_cases + 1 relationships + 1 column
        assert len(chunks) == 4
        assert chunks[0].chunk_type == "table_summary"
        assert chunks[1].chunk_type == "use_cases"
        assert chunks[2].chunk_type == "relationships"
        assert chunks[3].chunk_type == "column"


class TestSummaryChunk:
    """Test summary chunk generation."""

    def test_summary_chunk_basic(self):
        """Should include basic table info."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            comment="Billing usage",
        )

        chunks = service.chunk_table(table)
        summary = chunks[0]

        assert summary.chunk_type == "table_summary"
        assert "TABLE: system.billing.usage" in summary.content
        assert "DOC_TYPE: table_summary" in summary.content
        assert "Purpose: Billing usage" in summary.content
        assert summary.base_id == "system.billing.usage::table_summary"

    def test_summary_chunk_with_enrichment(self):
        """Should include enriched business context and grain."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            business_context="Tracks resource consumption",
            grain="One row per SKU per day",
        )

        chunks = service.chunk_table(table)
        summary = chunks[0]

        assert "Tracks resource consumption" in summary.content
        assert "Grain: One row per SKU per day" in summary.content

    def test_summary_chunk_with_use_cases_reference(self):
        """Should reference use cases in summary."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            common_use_cases=["Cost analysis", "Usage trends"],
        )

        chunks = service.chunk_table(table)
        summary = chunks[0]

        assert "Use Cases:" in summary.content
        assert "Cost analysis" in summary.content

    def test_summary_chunk_with_join_columns(self):
        """Should include common join columns."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            common_join_columns=["workspace_id", "sku_name"],
        )

        chunks = service.chunk_table(table)
        summary = chunks[0]

        assert "Common Join Columns:" in summary.content
        assert "workspace_id" in summary.content
        assert "sku_name" in summary.content

    def test_summary_chunk_metadata(self):
        """Should include correct metadata."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
        )

        chunks = service.chunk_table(table)
        summary = chunks[0]

        assert summary.metadata["table_name"] == "system.billing.usage"
        assert summary.metadata["doc_type"] == "table_summary"
        assert summary.metadata["table_catalog"] == "system"
        assert summary.metadata["table_schema"] == "billing"


class TestColumnChunk:
    """Test column chunk generation."""

    def test_column_chunk_basic(self):
        """Should include column name and type."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert column_chunk.chunk_type == "column"
        assert "COLUMN: usage_date (DATE)" in column_chunk.content
        assert column_chunk.column_name == "usage_date"
        assert column_chunk.base_id == "system.billing.usage::column::usage_date"

    def test_column_chunk_with_comment(self):
        """Should include column comment."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                    comment="Date of usage",
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert "Comment: Date of usage" in column_chunk.content

    def test_column_chunk_with_enrichment(self):
        """Should include enriched business meaning and cardinality."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="workspace_id",
                    data_type="STRING",
                    business_meaning="Unique identifier for workspace",
                    cardinality_estimate="high",
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert "Definition: Unique identifier for workspace" in column_chunk.content
        assert "Cardinality: high" in column_chunk.content

    def test_column_chunk_with_aggregations(self):
        """Should include common aggregations."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_quantity",
                    data_type="DECIMAL",
                    common_aggregations=["SUM", "AVG", "COUNT"],
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert "Common Aggregations: SUM, AVG, COUNT" in column_chunk.content

    def test_column_chunk_with_filters(self):
        """Should include example filter values."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="sku_name",
                    data_type="STRING",
                    example_filters=["STANDARD_ALL_PURPOSE_COMPUTE", "JOBS_COMPUTE"],
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert "Example Filters:" in column_chunk.content
        assert "STANDARD_ALL_PURPOSE_COMPUTE" in column_chunk.content

    def test_column_chunk_metadata(self):
        """Should include correct metadata."""
        service = ChunkingService()

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                ),
            ],
        )

        chunks = service.chunk_table(table)
        column_chunk = chunks[1]

        assert column_chunk.metadata["table_name"] == "system.billing.usage"
        assert column_chunk.metadata["doc_type"] == "column"
        assert column_chunk.metadata["column_name"] == "usage_date"


class TestBaseIdGeneration:
    """Test base ID generation."""

    def test_base_id_summary(self):
        """Should generate correct base ID for summary."""
        service = ChunkingService()
        base_id = service._make_base_id("system.billing.usage", "table_summary")
        assert base_id == "system.billing.usage::table_summary"

    def test_base_id_use_cases(self):
        """Should generate correct base ID for use cases."""
        service = ChunkingService()
        base_id = service._make_base_id("system.billing.usage", "use_cases")
        assert base_id == "system.billing.usage::use_cases"

    def test_base_id_relationships(self):
        """Should generate correct base ID for relationships."""
        service = ChunkingService()
        base_id = service._make_base_id("system.billing.usage", "relationships")
        assert base_id == "system.billing.usage::relationships"

    def test_base_id_column(self):
        """Should generate correct base ID for column."""
        service = ChunkingService()
        base_id = service._make_base_id(
            "system.billing.usage", "column", column_name="usage_date"
        )
        assert base_id == "system.billing.usage::column::usage_date"
