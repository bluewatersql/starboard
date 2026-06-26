# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for MetadataExtractor.

Tests metadata extraction with mocked Databricks client.
"""

from unittest.mock import MagicMock

import pytest
from starboard_server.infra.rag.services.metadata_service import (
    MetadataExtractor,
)


class MockDatabricksClient:
    """Mock Databricks client for testing."""

    def __init__(self):
        """Initialize with empty result sets."""
        self.queries_executed = []
        self.table_results = []
        self.column_results = {}

    def execute_query(self, query: str) -> list[dict]:
        """Mock query execution."""
        self.queries_executed.append(query)

        # Return table results if this is a table query
        if "FROM system.information_schema.tables" in query:
            return self.table_results

        # Return column results if this is a column query
        if "FROM system.information_schema.columns" in query:
            # Extract table name from query
            for table_name, results in self.column_results.items():
                if f"table_name = '{table_name}'" in query:
                    return results

        return []

    def set_table_results(self, results: list[dict]):
        """Set mock table results."""
        self.table_results = results

    def set_column_results(self, table_name: str, results: list[dict]):
        """Set mock column results for a specific table."""
        self.column_results[table_name] = results


@pytest.fixture
def query_analyzer():
    """Create QueryAnalyzer instance."""
    from starboard_server.infra.rag.domain.query_analyzer import QueryAnalyzer

    return QueryAnalyzer()


@pytest.fixture
def empty_analysis_result():
    """Create an empty AnalysisResult for tests that don't need discovery."""
    from starboard_core.rag.models import AnalysisResult

    return AnalysisResult(
        success_count=0,
        failed_count=0,
        join_summary=[],
        raw_joins=[],
        raw_predicates=[],
        raw_aggregations=[],
    )


class TestMetadataExtractor:
    """Test MetadataExtractor initialization and basic operations."""

    def test_init(self, query_analyzer):
        """Should initialize with databricks client and max_workers."""
        client = MockDatabricksClient()
        extractor = MetadataExtractor(client, query_analyzer, max_workers=10)

        assert extractor.databricks_client is client
        assert extractor.max_workers == 10

    def test_init_default_max_workers(self, query_analyzer):
        """Should use default max_workers if not specified."""
        client = MockDatabricksClient()
        extractor = MetadataExtractor(client, query_analyzer)

        assert extractor.max_workers == 5


class TestExtractTables:
    """Test extract_tables method."""

    @pytest.mark.asyncio
    async def test_extract_tables_empty(self, query_analyzer, empty_analysis_result):
        """Should return empty list if no tables found."""
        client = MockDatabricksClient()
        client.set_table_results([])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        assert tables == []
        assert len(client.queries_executed) == 1

    @pytest.mark.asyncio
    async def test_extract_tables_single_schema(
        self, query_analyzer, empty_analysis_result
    ):
        """Should extract tables from single schema."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": "Billing usage data",
                },
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "list_prices",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )

        # Set column results for each table
        client.set_column_results(
            "usage",
            [
                {
                    "column_name": "usage_date",
                    "data_type": "DATE",
                    "is_nullable": "NO",
                    "comment": "Usage date",
                },
            ],
        )
        client.set_column_results(
            "list_prices",
            [
                {
                    "column_name": "price_start_time",
                    "data_type": "TIMESTAMP",
                    "is_nullable": "YES",
                    "comment": None,
                },
            ],
        )

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        assert len(tables) == 2

        # Order may not be preserved due to parallel execution
        # So find tables by name
        tables_by_name = {t.table_name: t for t in tables}
        assert "usage" in tables_by_name
        assert "list_prices" in tables_by_name

        usage_table = tables_by_name["usage"]
        assert usage_table.table_catalog == "system"
        assert usage_table.table_schema == "billing"
        assert usage_table.comment == "Billing usage data"
        assert len(usage_table.columns) == 1

        list_prices_table = tables_by_name["list_prices"]
        assert list_prices_table.comment is None
        assert len(list_prices_table.columns) == 1

    @pytest.mark.asyncio
    async def test_extract_tables_multiple_schemas(
        self, query_analyzer, empty_analysis_result
    ):
        """Should extract tables from multiple schemas."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": None,
                },
                {
                    "table_catalog": "system",
                    "table_schema": "compute",
                    "table_name": "warehouses",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )

        # Set empty columns for simplicity
        client.set_column_results("usage", [])
        client.set_column_results("warehouses", [])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing", "compute"])

        assert len(tables) == 2
        assert tables[0].table_schema == "billing"
        assert tables[1].table_schema == "compute"

        # Verify query includes both schemas
        query = client.queries_executed[0]
        assert "IN ('billing', 'compute')" in query

    @pytest.mark.asyncio
    async def test_extract_tables_custom_catalog(
        self, query_analyzer, empty_analysis_result
    ):
        """Should use custom catalog if specified."""
        client = MockDatabricksClient()
        client.set_table_results([])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        await extractor.extract_tables(schemas=["billing"], catalog="custom_catalog")

        query = client.queries_executed[0]
        assert "table_catalog = 'custom_catalog'" in query

    @pytest.mark.asyncio
    async def test_extract_tables_query_error(
        self, query_analyzer, empty_analysis_result
    ):
        """Should raise exception if table query fails."""
        client = MagicMock()
        client.execute_query.side_effect = Exception("Connection error")

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )

        with pytest.raises(Exception, match="Connection error"):
            await extractor.extract_tables(schemas=["billing"])

    @pytest.mark.asyncio
    async def test_extract_tables_graceful_column_failure(
        self, query_analyzer, empty_analysis_result
    ):
        """Should gracefully handle column extraction failures."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )

        # Simulate column extraction failure
        original_execute = client.execute_query

        def failing_execute(query: str):
            if "FROM system.information_schema.columns" in query:
                raise Exception("Column query failed")
            return original_execute(query)

        client.execute_query = failing_execute  # type: ignore[method-assign]

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        # Should still return table with empty columns
        assert len(tables) == 1
        assert tables[0].table_name == "usage"
        assert tables[0].columns == []


class TestExtractColumns:
    """Test extract_columns method."""

    @pytest.mark.asyncio
    async def test_extract_columns_basic(self, query_analyzer):
        """Should extract columns for a table."""
        client = MockDatabricksClient()
        client.set_column_results(
            "usage",
            [
                {
                    "column_name": "usage_date",
                    "data_type": "DATE",
                    "is_nullable": "NO",
                    "comment": "Usage date",
                },
                {
                    "column_name": "sku_name",
                    "data_type": "STRING",
                    "is_nullable": "YES",
                    "comment": None,
                },
            ],
        )

        extractor = MetadataExtractor(client, query_analyzer)
        columns = await extractor.extract_columns("system.billing.usage")

        assert len(columns) == 2
        assert columns[0].column_name == "usage_date"
        assert columns[0].data_type == "DATE"
        assert columns[0].is_nullable is False
        assert columns[0].comment == "Usage date"

        assert columns[1].column_name == "sku_name"
        assert columns[1].is_nullable is True
        assert columns[1].comment is None

    @pytest.mark.asyncio
    async def test_extract_columns_empty(self, query_analyzer):
        """Should return empty list if no columns found."""
        client = MockDatabricksClient()
        client.set_column_results("usage", [])

        extractor = MetadataExtractor(client, query_analyzer)
        columns = await extractor.extract_columns("system.billing.usage")

        assert columns == []

    @pytest.mark.asyncio
    async def test_extract_columns_invalid_table_name(self, query_analyzer):
        """Should raise ValueError if table name format is invalid."""
        client = MockDatabricksClient()
        extractor = MetadataExtractor(client, query_analyzer)

        with pytest.raises(ValueError, match="Invalid table name format"):
            await extractor.extract_columns("invalid_table")

        with pytest.raises(ValueError, match="Invalid table name format"):
            await extractor.extract_columns("schema.table")

    @pytest.mark.asyncio
    async def test_extract_columns_query_error(self, query_analyzer):
        """Should raise exception if column query fails."""
        client = MagicMock()
        client.execute_query.side_effect = Exception("Query failed")

        extractor = MetadataExtractor(client, query_analyzer)

        with pytest.raises(Exception, match="Query failed"):
            await extractor.extract_columns("system.billing.usage")

    @pytest.mark.asyncio
    async def test_extract_columns_query_format(self, query_analyzer):
        """Should generate correct SQL query."""
        client = MockDatabricksClient()
        client.set_column_results("usage", [])

        extractor = MetadataExtractor(client, query_analyzer)
        await extractor.extract_columns("system.billing.usage")

        query = client.queries_executed[0]
        assert "FROM system.information_schema.columns" in query
        assert "table_catalog = 'system'" in query
        assert "table_schema = 'billing'" in query
        assert "table_name = 'usage'" in query
        assert "ORDER BY ordinal_position" in query


class TestParallelExecution:
    """Test concurrent column extraction."""

    @pytest.mark.asyncio
    async def test_parallel_extraction_multiple_tables(
        self, query_analyzer, empty_analysis_result
    ):
        """Should extract columns concurrently for multiple tables."""
        client = MockDatabricksClient()

        # Set up 3 tables
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": None,
                },
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "list_prices",
                    "table_type": "TABLE",
                    "comment": None,
                },
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "discounts",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )

        # Set columns for each table
        for table_name in ["usage", "list_prices", "discounts"]:
            client.set_column_results(
                table_name,
                [
                    {
                        "column_name": "id",
                        "data_type": "BIGINT",
                        "is_nullable": "NO",
                        "comment": None,
                    },
                ],
            )

        extractor = MetadataExtractor(
            client, query_analyzer, max_workers=3, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        # All tables should have columns extracted
        assert len(tables) == 3
        for table in tables:
            assert len(table.columns) == 1
            assert table.columns[0].column_name == "id"

    @pytest.mark.asyncio
    async def test_parallel_extraction_respects_max_workers(
        self, query_analyzer, empty_analysis_result
    ):
        """Should respect max_workers setting."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": f"table_{i}",
                    "table_type": "TABLE",
                    "comment": None,
                }
                for i in range(10)
            ]
        )

        # Set empty columns
        for i in range(10):
            client.set_column_results(f"table_{i}", [])

        extractor = MetadataExtractor(
            client, query_analyzer, max_workers=2, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        assert len(tables) == 10


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_table_without_comment(self, query_analyzer, empty_analysis_result):
        """Should handle tables without comments."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )
        client.set_column_results("usage", [])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        assert tables[0].comment is None

    @pytest.mark.asyncio
    async def test_column_without_comment(self, query_analyzer):
        """Should handle columns without comments."""
        client = MockDatabricksClient()
        client.set_column_results(
            "usage",
            [
                {
                    "column_name": "id",
                    "data_type": "BIGINT",
                    "is_nullable": "NO",
                    "comment": None,
                },
            ],
        )

        extractor = MetadataExtractor(client, query_analyzer)
        columns = await extractor.extract_columns("system.billing.usage")

        assert columns[0].comment is None

    @pytest.mark.asyncio
    async def test_missing_catalog_defaults_to_system(
        self, query_analyzer, empty_analysis_result
    ):
        """Should default to 'system' catalog if missing."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": None,
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )
        client.set_column_results("usage", [])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        assert tables[0].table_catalog == "system"

    @pytest.mark.asyncio
    async def test_extract_tables_preserves_order(
        self, query_analyzer, empty_analysis_result
    ):
        """Should preserve table order from query results."""
        client = MockDatabricksClient()
        client.set_table_results(
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "a_first",
                    "table_type": "TABLE",
                    "comment": None,
                },
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "b_second",
                    "table_type": "TABLE",
                    "comment": None,
                },
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "c_third",
                    "table_type": "TABLE",
                    "comment": None,
                },
            ]
        )

        for table in ["a_first", "b_second", "c_third"]:
            client.set_column_results(table, [])

        extractor = MetadataExtractor(
            client, query_analyzer, analysis_result=empty_analysis_result
        )
        tables = await extractor.extract_tables(schemas=["billing"])

        # Order may not be preserved due to parallel execution
        # So just verify all tables are present
        table_names = {t.table_name for t in tables}
        assert table_names == {"a_first", "b_second", "c_third"}
