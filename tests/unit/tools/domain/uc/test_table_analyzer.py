# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for TableAnalyzer domain logic (table discovery and categorization)."""

from starboard_core.domain.analyzers import TableAnalyzer
from starboard_core.domain.models.databricks import TableReference


class TestTableAnalyzer:
    """Test suite for TableAnalyzer pure functions."""

    def test_deduplicate_tables_removes_duplicates(self):
        """Test that deduplicate_tables removes duplicate table references."""
        # Arrange
        tables = [
            TableReference(
                raw="table1",
                table="table1",
                resolved_3part="catalog.schema.table1",
                type="table",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="table1",
                table="table1",
                resolved_3part="catalog.schema.table1",
                type="table",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="table2",
                table="table2",
                resolved_3part="catalog.schema.table2",
                type="table",
                is_source=False,
                is_destination=True,
            ),
        ]

        # Act
        result = TableAnalyzer.deduplicate_tables(tables)

        # Assert
        assert len(result) == 2
        assert result[0].resolved_3part == "catalog.schema.table1"
        assert result[1].resolved_3part == "catalog.schema.table2"

    def test_deduplicate_tables_preserves_order(self):
        """Test that deduplicate_tables preserves first occurrence order."""
        # Arrange
        tables = [
            TableReference(
                raw="table2",
                table="table2",
                resolved_3part="catalog.schema.table2",
                type="table",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="table1",
                table="table1",
                resolved_3part="catalog.schema.table1",
                type="table",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="table2",
                table="table2",
                resolved_3part="catalog.schema.table2",
                type="table",
                is_source=True,
                is_destination=False,
            ),
        ]

        # Act
        result = TableAnalyzer.deduplicate_tables(tables)

        # Assert
        assert len(result) == 2
        assert result[0].resolved_3part == "catalog.schema.table2"
        assert result[1].resolved_3part == "catalog.schema.table1"

    def test_categorize_tables_all_types(self):
        """Test that categorize_tables correctly categorizes all table types."""
        # Arrange
        tables = [
            TableReference(
                raw="source_table",
                table="source_table",
                resolved_3part="catalog.schema.source_table",
                type="table",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="target_table",
                table="target_table",
                resolved_3part="catalog.schema.target_table",
                type="table",
                is_source=False,
                is_destination=True,
            ),
            TableReference(
                raw="view1",
                table="view1",
                resolved_3part="catalog.schema.view1",
                type="view",
                is_source=True,
                is_destination=False,
            ),
            TableReference(
                raw="temp_table",
                table="temp_table",
                resolved_3part="temp.temp_table",
                type="temp_table",
                is_source=False,
                is_destination=False,
            ),
        ]

        # Act
        result = TableAnalyzer.categorize_tables(tables)

        # Assert
        assert len(result.all_tables) == 4
        assert len(result.source_tables) == 2
        assert len(result.target_tables) == 1
        assert len(result.tables_and_views) == 3  # Excludes temp_table
        assert "catalog.schema.source_table" in result.source_tables
        assert "catalog.schema.target_table" in result.target_tables
        assert "temp.temp_table" not in result.tables_and_views

    def test_categorize_tables_empty_list(self):
        """Test that categorize_tables handles empty list."""
        # Arrange
        tables = []

        # Act
        result = TableAnalyzer.categorize_tables(tables)

        # Assert
        assert len(result.all_tables) == 0
        assert len(result.source_tables) == 0
        assert len(result.target_tables) == 0
        assert len(result.tables_and_views) == 0

    def test_convert_table_reference_dicts(self):
        """Test that convert_table_reference_dicts converts dicts to TableReference objects."""
        # Arrange
        data = [
            {
                "raw": "table1",
                "table": "table1",
                "resolved_3part": "catalog.schema.table1",
                "type": "table",
                "is_source": True,
                "is_destination": False,
            },
            {
                "raw": "table2",
                "table": "table2",
                "resolved_3part": "catalog.schema.table2",
                "catalog": "catalog",
                "schema": "schema",
                "type": "view",
                "is_source": False,
                "is_destination": True,
            },
        ]

        # Act
        result = TableAnalyzer.convert_table_reference_dicts(data)

        # Assert
        assert len(result) == 2
        assert all(isinstance(t, TableReference) for t in result)
        assert result[0].resolved_3part == "catalog.schema.table1"
        assert result[0].is_source is True
        assert result[1].type == "view"
        assert result[1].is_destination is True

    def test_convert_table_reference_dicts_mixed_input(self):
        """Test that convert_table_reference_dicts handles mixed dict and TableReference input."""
        # Arrange
        ref = TableReference(
            raw="table1",
            table="table1",
            resolved_3part="catalog.schema.table1",
            type="table",
            is_source=True,
            is_destination=False,
        )
        data = [
            ref,
            {
                "raw": "table2",
                "table": "table2",
                "resolved_3part": "catalog.schema.table2",
                "type": "view",
                "is_source": False,
                "is_destination": True,
            },
        ]

        # Act
        result = TableAnalyzer.convert_table_reference_dicts(data)

        # Assert
        assert len(result) == 2
        assert result[0] is ref  # Same object
        assert isinstance(result[1], TableReference)
        assert result[1].resolved_3part == "catalog.schema.table2"
