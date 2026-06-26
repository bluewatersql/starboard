# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for UC service schema diff functionality.

Tests the generate_schema_diff method which uses DESCRIBE HISTORY
to track schema changes across Delta table versions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from starboard_server.tools.services.uc_service import UCService


class MockSQLProvider:
    """Mock SQL provider for testing."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def execute_query(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.results


class MockUCProvider:
    """Mock UC catalog provider."""

    def list_catalogs(self, limit: int = 100) -> list[dict]:
        return []

    def list_schemas(self, catalog_name: str, limit: int = 100) -> list[dict]:
        return []

    def list_tables(
        self, catalog_name: str, schema_name: str, limit: int = 100
    ) -> list[dict]:
        return []

    def list_volumes(
        self, catalog_name: str, schema_name: str, limit: int = 100
    ) -> list[dict]:
        return []

    def get_table(
        self, full_name: str, include_delta_metadata: bool = True
    ) -> dict | None:
        return None

    def get_grants(self, securable_type: Any, full_name: str) -> dict | None:
        return None

    def get_effective_grants(self, securable_type: Any, full_name: str) -> dict | None:
        return None


@pytest.fixture
def mock_uc_provider() -> MockUCProvider:
    return MockUCProvider()


class TestGenerateSchemaDiff:
    """Tests for generate_schema_diff method."""

    @pytest.mark.asyncio
    async def test_no_sql_provider_returns_none(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should return None when SQL provider is not configured."""
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=None,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_diff(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should return diff with empty changes when no schema changes found."""
        sql_provider = MockSQLProvider(results=[])
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert result.table_name == "catalog.schema.table"
        assert len(result.columns_added) == 0
        assert len(result.columns_removed) == 0
        assert len(result.columns_modified) == 0
        assert result.is_breaking_change is False

    @pytest.mark.asyncio
    async def test_add_columns_parsed_correctly(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should parse ADD COLUMNS operations correctly."""
        # Normalized JSON output from our SQL query
        schema_json = '[{"column":{"name":"new_col","type":"string","nullable":true}}]'
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 15, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": schema_json,
                }
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert len(result.columns_added) == 1
        assert result.columns_added[0].column_name == "new_col"
        assert result.columns_added[0].new_type == "string"
        assert result.columns_added[0].new_nullable is True
        assert result.is_breaking_change is False  # Nullable column is not breaking

    @pytest.mark.asyncio
    async def test_add_non_nullable_column_is_breaking(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should flag adding non-nullable column as breaking change."""
        schema_json = (
            '[{"column":{"name":"required_col","type":"int","nullable":false}}]'
        )
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 15, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": schema_json,
                }
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert result.is_breaking_change is True
        assert "non-nullable" in (result.breaking_reason or "").lower()

    @pytest.mark.asyncio
    async def test_drop_columns_parsed_correctly(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should parse DROP COLUMNS operations correctly."""
        # DROP COLUMNS has null type and nullable
        schema_json = '[{"column":{"name":"old_col","type":null,"nullable":null}}]'
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 10,
                    "timestamp": datetime(2024, 2, 1, 14, 30, 0),
                    "operation": "DROP COLUMNS",
                    "schema_json_normalized": schema_json,
                }
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert len(result.columns_removed) == 1
        assert result.columns_removed[0].column_name == "old_col"
        assert result.columns_removed[0].old_type is None
        assert result.is_breaking_change is True  # Dropping is always breaking
        assert "dropped" in (result.breaking_reason or "").lower()

    @pytest.mark.asyncio
    async def test_replace_columns_parsed_correctly(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should parse REPLACE COLUMNS operations correctly."""
        schema_json = '[{"column":{"name":"col1","type":"long","nullable":true}},{"column":{"name":"col2","type":"string","nullable":false}}]'
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 15,
                    "timestamp": datetime(2024, 3, 1, 9, 0, 0),
                    "operation": "REPLACE COLUMNS",
                    "schema_json_normalized": schema_json,
                }
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert len(result.columns_modified) == 2
        assert result.columns_modified[0].column_name == "col1"
        assert result.columns_modified[0].new_type == "long"
        assert result.columns_modified[1].column_name == "col2"
        assert result.is_breaking_change is True  # REPLACE is breaking
        assert "replace" in (result.breaking_reason or "").lower()

    @pytest.mark.asyncio
    async def test_multiple_operations_combined(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should combine multiple schema operations into single diff."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"col_a","type":"string","nullable":true}}]',
                },
                {
                    "version": 8,
                    "timestamp": datetime(2024, 1, 20, 14, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"col_b","type":"int","nullable":true}}]',
                },
                {
                    "version": 12,
                    "timestamp": datetime(2024, 2, 5, 9, 0, 0),
                    "operation": "DROP COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"col_a","type":null,"nullable":null}}]',
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0, version_to=20
        )

        assert result is not None
        assert len(result.columns_added) == 2
        assert len(result.columns_removed) == 1
        assert result.version_from == 0
        # version_to respects the passed parameter when provided
        assert result.version_to == 20

    @pytest.mark.asyncio
    async def test_version_filter_applied(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should apply version filter to query."""
        sql_provider = MockSQLProvider(results=[])
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        await service.generate_schema_diff(
            "catalog.schema.table", version_from=10, version_to=20
        )

        assert len(sql_provider.queries) == 1
        query = sql_provider.queries[0]
        assert "version >= 10" in query
        assert "version <= 20" in query

    @pytest.mark.asyncio
    async def test_timestamp_tracking(self, mock_uc_provider: MockUCProvider) -> None:
        """Should track first and last timestamps correctly."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"col1","type":"string","nullable":true}}]',
                },
                {
                    "version": 10,
                    "timestamp": datetime(2024, 3, 15, 16, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"col2","type":"int","nullable":true}}]',
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert result.timestamp_from == datetime(2024, 1, 10, 10, 0, 0)
        assert result.timestamp_to == datetime(2024, 3, 15, 16, 0, 0)

    @pytest.mark.asyncio
    async def test_migration_sql_hints_generated(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should generate migration SQL hints."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10, 10, 0, 0),
                    "operation": "DROP COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"old_col","type":null,"nullable":null}}]',
                },
                {
                    "version": 6,
                    "timestamp": datetime(2024, 1, 11, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"new_col","type":"string","nullable":false}}]',
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert result.migration_sql is not None
        assert "old_col" in result.migration_sql
        assert "new_col" in result.migration_sql

    @pytest.mark.asyncio
    async def test_malformed_json_handled_gracefully(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should handle malformed JSON gracefully."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10, 10, 0, 0),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": "not valid json",
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        # Should not raise, should return empty diff
        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert len(result.columns_added) == 0

    @pytest.mark.asyncio
    async def test_sql_execution_error_returns_none(
        self, mock_uc_provider: MockUCProvider
    ) -> None:
        """Should return None when SQL execution fails."""

        class FailingSQLProvider:
            async def execute_query(self, query: str) -> list[dict[str, Any]]:
                raise Exception("Database connection failed")

        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=FailingSQLProvider(),
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is None


class TestMigrationHints:
    """Tests for migration SQL hint generation."""

    @pytest.mark.asyncio
    async def test_drop_column_hints(self, mock_uc_provider: MockUCProvider) -> None:
        """Should generate hints for dropped columns."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10),
                    "operation": "DROP COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"dropped_col","type":null,"nullable":null}}]',
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert "Dropped columns" in (result.migration_sql or "")
        assert "dropped_col" in (result.migration_sql or "")

    @pytest.mark.asyncio
    async def test_add_column_hints(self, mock_uc_provider: MockUCProvider) -> None:
        """Should generate hints for added columns."""
        sql_provider = MockSQLProvider(
            results=[
                {
                    "version": 5,
                    "timestamp": datetime(2024, 1, 10),
                    "operation": "ADD COLUMNS",
                    "schema_json_normalized": '[{"column":{"name":"new_col","type":"bigint","nullable":false}}]',
                },
            ]
        )
        service = UCService(
            uc_provider=mock_uc_provider,
            sql_provider=sql_provider,
        )

        result = await service.generate_schema_diff(
            "catalog.schema.table", version_from=0
        )

        assert result is not None
        assert "new_col" in (result.migration_sql or "")
        assert "bigint" in (result.migration_sql or "")
        assert "NOT NULL" in (result.migration_sql or "")
