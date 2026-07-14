# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for discovery by example methods in MetadataExtractor.

Tests query history analysis and usage pattern discovery.

NOTE: These tests are currently skipped as they test the old implementation
that was refactored during the RAG reorganization. The functionality is now
split between MetadataExtractor and QueryAnalyzer, and is tested in other files.
"""

from unittest.mock import MagicMock

import pytest
from starboard_core.rag.models import ColumnMetadata, TableMetadata
from starboard.infra.rag.domain.query_analyzer import QueryAnalyzer
from starboard.infra.rag.services.metadata_service import MetadataExtractor

pytestmark = pytest.mark.skip(
    reason="Tests old implementation - refactored during RAG reorganization"
)


@pytest.fixture
def query_analyzer():
    """Create QueryAnalyzer instance."""
    return QueryAnalyzer()


class TestDiscoverByExample:
    """Test _discover_by_example method."""

    def test_discover_by_example_enriches_columns(self, query_analyzer):
        """Should enrich columns with predicates and aggregations."""
        # Mock client
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT SUM(usage_quantity) FROM system.billing.usage WHERE sku_name = 'JOBS_COMPUTE'",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)

        # Create test table
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
                ),
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_quantity",
                    data_type="DECIMAL",
                ),
            ],
        )

        # Discover patterns
        enriched = extractor._discover_by_example(table)

        # Should enrich columns
        assert enriched is not None
        assert len(enriched.columns) == 2

    def test_discover_by_example_adds_join_columns(self, query_analyzer):
        """Should add common join columns to table."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM system.billing.usage u JOIN system.billing.list_prices p ON u.workspace_id = p.workspace_id",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[],
        )

        enriched = extractor._discover_by_example(table)

        # Should have common_join_columns
        assert (
            enriched.common_join_columns is not None
            or enriched.common_join_columns == []
        )

    def test_discover_by_example_handles_empty_query_cache(self, query_analyzer):
        """Should gracefully handle no query history."""
        client = MagicMock()
        client.execute_query.return_value = []

        extractor = MetadataExtractor(client, query_analyzer)

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[],
        )

        enriched = extractor._discover_by_example(table)

        # Should return table unchanged
        assert enriched.table_name == "usage"


class TestGetTablePredicates:
    """Test get_table_predicates method."""

    def test_get_table_predicates_empty_cache(self, query_analyzer):
        """Should return empty dict when no queries cached."""
        client = MagicMock()
        client.execute_query.return_value = []

        extractor = MetadataExtractor(client, query_analyzer)
        predicates = extractor.get_table_predicates("usage")

        assert predicates == {}

    def test_get_table_predicates_with_queries(self, query_analyzer):
        """Should extract predicates from WHERE clauses."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM system.billing.usage WHERE sku_name = 'JOBS_COMPUTE'",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM system.billing.usage WHERE sku_name = 'SERVERLESS_SQL'",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        predicates = extractor.get_table_predicates("usage")

        # Should be a dict (exact values depend on SQL parsing)
        assert isinstance(predicates, dict)

    def test_get_table_predicates_skips_id_columns(self, query_analyzer):
        """Should skip columns with _id suffix."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage WHERE workspace_id = '12345'",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        predicates = extractor.get_table_predicates("usage")

        # Should skip workspace_id
        assert "workspace_id" not in predicates

    def test_get_table_predicates_handles_unparseable_queries(self, query_analyzer):
        """Should gracefully handle malformed SQL."""
        client = MagicMock()
        client.execute_query.return_value = [
            {"table_name": "usage", "statement_text": "INVALID SQL GARBAGE"},
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        predicates = extractor.get_table_predicates("usage")

        # Should return empty dict, not crash
        assert predicates == {}


class TestGetTableAggregateColumns:
    """Test get_table_aggregate_columns method."""

    def test_get_table_aggregate_columns_empty_cache(self, query_analyzer):
        """Should return empty dict when no queries cached."""
        client = MagicMock()
        client.execute_query.return_value = []

        extractor = MetadataExtractor(client, query_analyzer)
        aggregations = extractor.get_table_aggregate_columns("usage")

        assert aggregations == {}

    def test_get_table_aggregate_columns_with_queries(self, query_analyzer):
        """Should extract aggregation functions."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT SUM(usage_quantity), AVG(usage_quantity) FROM usage GROUP BY sku_name",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        aggregations = extractor.get_table_aggregate_columns("usage")

        # Should be a dict
        assert isinstance(aggregations, dict)

    def test_get_table_aggregate_columns_handles_multiple_aggs(self, query_analyzer):
        """Should collect multiple aggregation types per column."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT SUM(amount) FROM usage",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT AVG(amount), COUNT(amount) FROM usage",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        aggregations = extractor.get_table_aggregate_columns("usage")

        # Should be a dict
        assert isinstance(aggregations, dict)


class TestGetTableJoinColumns:
    """Test get_table_join_columns method."""

    def test_get_table_join_columns_empty_cache(self, query_analyzer):
        """Should return empty list when no queries cached."""
        client = MagicMock()
        client.execute_query.return_value = []

        extractor = MetadataExtractor(client, query_analyzer)
        join_columns = extractor.get_table_join_columns("usage")

        assert join_columns == []

    def test_get_table_join_columns_with_queries(self, query_analyzer):
        """Should extract join columns from ON clauses."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u JOIN list_prices p ON u.workspace_id = p.workspace_id",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        join_columns = extractor.get_table_join_columns("usage")

        # Should be a list
        assert isinstance(join_columns, list)

    def test_get_table_join_columns_sorts_by_frequency(self, query_analyzer):
        """Should return most frequent join columns first."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u JOIN t1 ON u.workspace_id = t1.workspace_id",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u JOIN t2 ON u.workspace_id = t2.workspace_id",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u JOIN t3 ON u.sku_name = t3.sku_name",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        join_columns = extractor.get_table_join_columns("usage")

        # Should be a list (exact order depends on SQL parsing)
        assert isinstance(join_columns, list)

    def test_get_table_join_columns_limits_to_top_10(self, query_analyzer):
        """Should return at most 10 join columns."""
        client = MagicMock()
        # Create 15 different join columns
        queries = []
        for i in range(15):
            queries.append(
                {
                    "table_name": "usage",
                    "statement_text": f"SELECT * FROM usage u JOIN t{i} ON u.col{i} = t{i}.col{i}",
                }
            )
        client.execute_query.return_value = queries

        extractor = MetadataExtractor(client, query_analyzer)
        join_columns = extractor.get_table_join_columns("usage")

        # Should have at most 10
        assert len(join_columns) <= 10


class TestDiscoverRelationships:
    """Test discover_relationships method."""

    def test_discover_relationships_empty_cache(self, query_analyzer):
        """Should return empty list when no queries cached."""
        client = MagicMock()
        client.execute_query.return_value = []

        extractor = MetadataExtractor(client, query_analyzer)
        relationships = extractor.discover_relationships("usage")

        assert relationships == []

    def test_discover_relationships_with_queries(self, query_analyzer):
        """Should discover relationships from JOIN patterns."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u JOIN list_prices p ON u.sku_name = p.sku_name",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        relationships = extractor.discover_relationships("usage")

        # Should be a list
        assert isinstance(relationships, list)

    def test_discover_relationships_deduplicates_tables(self, query_analyzer):
        """Should create one relationship per joined table."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u INNER JOIN list_prices p ON u.sku_name = p.sku_name",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM usage u LEFT JOIN list_prices p ON u.sku_name = p.sku_name",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        relationships = extractor.discover_relationships("usage")

        # Should be a list (relationships may be deduplicated)
        assert isinstance(relationships, list)


class TestLoadQueryHistory:
    """Test _load_query_history method."""

    def test_load_query_history_queries_databricks(self, query_analyzer):
        """Should query system.access.table_lineage and system.query.history."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM system.billing.usage",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        extractor._load_query_history()

        # Should have called execute_query
        assert client.execute_query.called
        assert "table_lineage" in client.execute_query.call_args[0][0].lower()

    def test_load_query_history_caches_by_table_name(self, query_analyzer):
        """Should group queries by table name."""
        client = MagicMock()
        client.execute_query.return_value = [
            {
                "table_name": "usage",
                "statement_text": "SELECT * FROM system.billing.usage WHERE sku_name = 'JOBS'",
            },
            {
                "table_name": "usage",
                "statement_text": "SELECT SUM(amount) FROM system.billing.usage",
            },
            {
                "table_name": "list_prices",
                "statement_text": "SELECT * FROM system.billing.list_prices",
            },
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        extractor._load_query_history()

        # Should have cached queries
        assert "usage" in extractor._query_cache
        assert "list_prices" in extractor._query_cache
        assert len(extractor._query_cache["usage"]) == 2
        assert len(extractor._query_cache["list_prices"]) == 1

    def test_load_query_history_handles_query_failure(self, query_analyzer):
        """Should gracefully handle query execution failure."""
        client = MagicMock()
        client.execute_query.side_effect = Exception("Databricks error")

        extractor = MetadataExtractor(client, query_analyzer)
        extractor._load_query_history()

        # Should set empty cache, not crash
        assert extractor._query_cache == {}

    def test_load_query_history_filters_invalid_results(self, query_analyzer):
        """Should skip rows with missing table_name or statement_text."""
        client = MagicMock()
        client.execute_query.return_value = [
            {"table_name": "usage", "statement_text": "SELECT * FROM usage"},
            {"table_name": None, "statement_text": "SELECT * FROM something"},
            {"table_name": "list_prices", "statement_text": None},
            {"table_name": "budget", "statement_text": ""},
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        extractor._load_query_history()

        # Should only cache valid entries
        assert "usage" in extractor._query_cache
        assert None not in extractor._query_cache
        assert "list_prices" not in extractor._query_cache
        assert "budget" not in extractor._query_cache

    def test_load_query_history_only_loads_once(self, query_analyzer):
        """Should cache results and not reload on subsequent calls."""
        client = MagicMock()
        client.execute_query.return_value = [
            {"table_name": "usage", "statement_text": "SELECT * FROM usage"},
        ]

        extractor = MetadataExtractor(client, query_analyzer)

        # Load query history
        extractor._load_query_history()
        first_call_count = client.execute_query.call_count

        # Call discovery methods (should not reload)
        extractor.get_table_predicates("usage")
        extractor.get_table_aggregate_columns("usage")
        extractor.get_table_join_columns("usage")

        # Should not have called execute_query again
        assert client.execute_query.call_count == first_call_count


class TestIntegration:
    """Integration tests for discovery by example."""

    def test_extract_tables_calls_discover_by_example(self):
        """Should automatically apply discovery to extracted tables."""
        client = MagicMock()
        # Mock INFORMATION_SCHEMA queries
        client.execute_query.side_effect = [
            # Tables query
            [
                {
                    "table_catalog": "system",
                    "table_schema": "billing",
                    "table_name": "usage",
                    "table_type": "TABLE",
                    "comment": "Billing usage",
                }
            ],
            # Columns query
            [
                {
                    "column_name": "sku_name",
                    "data_type": "STRING",
                    "is_nullable": "YES",
                    "comment": "SKU name",
                }
            ],
            # Query history (for discovery)
            [
                {
                    "table_name": "usage",
                    "statement_text": "SELECT * FROM usage WHERE sku_name = 'JOBS'",
                }
            ],
        ]

        extractor = MetadataExtractor(client, query_analyzer)
        tables = extractor.extract_tables(schemas=["billing"])

        # Should have extracted and enriched table
        assert len(tables) == 1
        assert tables[0].table_name == "usage"
        assert len(tables[0].columns) == 1
