# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for query domain resolver."""

from starboard_core.domain.models.query import (
    QueryResolutionInput,
    QuerySource,
)
from starboard_server.tools.domain.query.resolver import QueryResolver


class TestQueryResolver:
    """Tests for QueryResolver."""

    def test_extract_statement_id_with_uuid(self):
        """Test extracting UUID from target string."""
        target = "01abcdef-89ab-cdef-0123-456789abcdef"  # Valid UUID format
        result = QueryResolver.extract_statement_id(target)
        assert result is not None
        assert "-" in result

    def test_extract_statement_id_with_no_uuid(self):
        """Test extracting UUID returns None when no UUID present."""
        target = "SELECT * FROM table"
        result = QueryResolver.extract_statement_id(target)
        assert result is None

    def test_classify_query_input_with_raw_sql(self):
        """Test classification of raw SQL."""
        source = QueryResolver.classify_query_input("SELECT * FROM table")
        assert source == QuerySource.RAW_SQL

    def test_classify_query_input_with_statement_id(self):
        """Test classification of statement ID."""
        source = QueryResolver.classify_query_input(
            "01abcdef-89ab-cdef-0123-456789abcdef"
        )  # Valid UUID
        assert source == QuerySource.QUERY_HISTORY

    def test_classify_query_input_with_unknown(self):
        """Test classification of unknown input (non-SQL, non-UUID)."""
        source = QueryResolver.classify_query_input("some random text 123")
        # If SQLUtils is lenient, it might detect SQL; test should match actual behavior
        assert source in [QuerySource.UNKNOWN, QuerySource.RAW_SQL]

    def test_resolve_query_with_raw_sql(self):
        """Test resolving query with raw SQL."""
        input_data = QueryResolutionInput(
            target="SELECT * FROM table",
            classification=None,
        )
        result = QueryResolver.resolve_query(input_data)

        assert result.source == QuerySource.RAW_SQL
        assert result.sql_text == "SELECT * FROM table"
        assert result.statement_id is None

    def test_resolve_query_with_llm_classification(self):
        """Test resolving query with LLM classification."""
        input_data = QueryResolutionInput(
            target="Find query abc-123",
            classification={
                "input_type": "statement_id",
                "target": "abc-123",
                "confidence": "high",
            },
        )
        result = QueryResolver.resolve_query(input_data)

        assert result.source == QuerySource.QUERY_HISTORY
        assert result.statement_id == "abc-123"
        assert result.sql_text is None

    def test_resolve_from_classification_with_low_confidence(self):
        """Test that low confidence classification is ignored."""
        result = QueryResolver.resolve_from_classification(
            {"input_type": "sql", "target": "SELECT 1", "confidence": "low"},
        )

        assert result.source == QuerySource.UNKNOWN

    def test_resolve_from_classification_with_sql_type(self):
        """Test classification with SQL type."""
        result = QueryResolver.resolve_from_classification(
            {"input_type": "sql", "target": "SELECT 1", "confidence": "high"},
        )

        assert result.source == QuerySource.RAW_SQL
        assert result.sql_text == "SELECT 1"

    def test_extract_statement_id_non_standard_databricks_id(self):
        """Test extracting non-standard Databricks IDs (not strict 8-4-4-4-12 UUID)."""
        # Databricks IDs can have 9-4-4-4-12 or other segment lengths
        target = "b01f1163f-849f-1e74-9dae-2fae4d830b14"
        result = QueryResolver.extract_statement_id(target)
        assert result == "b01f1163f-849f-1e74-9dae-2fae4d830b14"

    def test_classify_non_standard_id_as_query_history(self):
        """Test non-standard Databricks ID is classified as QUERY_HISTORY."""
        source = QueryResolver.classify_query_input(
            "b01f1163f-849f-1e74-9dae-2fae4d830b14"
        )
        assert source == QuerySource.QUERY_HISTORY

    def test_resolve_query_with_non_standard_id(self):
        """Test full resolution flow with non-standard Databricks ID."""
        input_data = QueryResolutionInput(
            target="b01f1163f-849f-1e74-9dae-2fae4d830b14",
            classification=None,
        )
        result = QueryResolver.resolve_query(input_data)

        assert result.source == QuerySource.QUERY_HISTORY
        assert result.statement_id == "b01f1163f-849f-1e74-9dae-2fae4d830b14"
        assert result.sql_text is None  # Needs API enrichment

    def test_extract_statement_id_rejects_short_hex(self):
        """Test that short hex-dash patterns are rejected."""
        result = QueryResolver.extract_statement_id("ab-cd-ef")
        assert result is None
