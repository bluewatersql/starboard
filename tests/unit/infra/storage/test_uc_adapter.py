# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for UC storage adapter.

Tests cover:
- Configuration loading
- Read operations with filters
- Write operations (insert, upsert, delete)
- Batch operations
- SQL generation
- Column validation (P0.10)
- ORDER BY validation (P0.10)
- Async SDK wrapper (P0.10)
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard_server.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)
from starboard_server.infra.storage.uc_adapter import (
    InvalidColumnError,
    UCStorageAdapter,
    UCStorageConfig,
)


class TestUCStorageConfig:
    """Tests for UCStorageConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = UCStorageConfig()

        assert config.catalog == "starboard"
        assert config.schema == "agent_state"
        assert config.warehouse_id is None
        assert config.auto_create_catalog is True
        assert config.auto_create_schema is True
        assert config.auto_create_tables is True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = UCStorageConfig(
            catalog="custom_catalog",
            schema="custom_schema",
            warehouse_id="wh-123",
            auto_create_catalog=False,
        )

        assert config.catalog == "custom_catalog"
        assert config.schema == "custom_schema"
        assert config.warehouse_id == "wh-123"
        assert config.auto_create_catalog is False

    def test_from_env(self) -> None:
        """Test loading config from environment."""
        with patch.dict(
            "os.environ",
            {
                "STARBOARD_UC_CATALOG": "env_catalog",
                "STARBOARD_UC_SCHEMA": "env_schema",
                "STARBOARD_WAREHOUSE_ID": "env-wh-123",
            },
        ):
            config = UCStorageConfig.from_env()

            assert config.catalog == "env_catalog"
            assert config.schema == "env_schema"
            assert config.warehouse_id == "env-wh-123"


class TestUCStorageAdapter:
    """Tests for UCStorageAdapter."""

    @pytest.fixture
    def mock_registry(self) -> TableRegistry:
        """Create a registry with test tables."""
        registry = TableRegistry()
        registry.register(
            TableDef(
                table_id="test_table",
                table_name="test_data",
                columns=(
                    ColumnDef("id", "STRING", nullable=False),
                    ColumnDef("name", "STRING"),
                    ColumnDef("value", "INT"),
                    ColumnDef("created_at", "TIMESTAMP"),
                ),
                primary_key=("id",),
            )
        )
        return registry

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Databricks workspace client."""
        client = MagicMock()
        client.statement_execution = MagicMock()
        client.statement_execution.execute_statement = MagicMock()
        client.catalogs = MagicMock()
        client.schemas = MagicMock()
        return client

    @pytest.fixture
    def config(self) -> UCStorageConfig:
        """Create test configuration."""
        return UCStorageConfig(
            catalog="test_catalog",
            schema="test_schema",
            warehouse_id="test-wh-123",
        )

    @pytest.fixture
    def adapter(
        self,
        mock_client: MagicMock,
        config: UCStorageConfig,
        mock_registry: TableRegistry,
    ) -> UCStorageAdapter:
        """Create adapter with mocks."""
        return UCStorageAdapter(
            workspace_client=mock_client,
            config=config,
            registry=mock_registry,
        )

    def test_format_value_string(self, adapter: UCStorageAdapter) -> None:
        """Test formatting string values."""
        result = adapter._format_value("test")
        assert result == "'test'"

    def test_format_value_string_with_quotes(self, adapter: UCStorageAdapter) -> None:
        """Test formatting string with single quotes."""
        result = adapter._format_value("it's a test")
        assert result == "'it''s a test'"

    def test_format_value_none(self, adapter: UCStorageAdapter) -> None:
        """Test formatting None values."""
        result = adapter._format_value(None)
        assert result == "NULL"

    def test_format_value_bool(self, adapter: UCStorageAdapter) -> None:
        """Test formatting boolean values."""
        assert adapter._format_value(True) == "TRUE"
        assert adapter._format_value(False) == "FALSE"

    def test_format_value_number(self, adapter: UCStorageAdapter) -> None:
        """Test formatting numeric values."""
        assert adapter._format_value(42) == "42"
        assert adapter._format_value(3.14) == "3.14"

    def test_format_value_datetime(self, adapter: UCStorageAdapter) -> None:
        """Test formatting datetime values."""
        dt = datetime(2025, 12, 6, 10, 30, 0)
        result = adapter._format_value(dt)
        assert result == "TIMESTAMP'2025-12-06T10:30:00'"

    def test_format_value_dict(self, adapter: UCStorageAdapter) -> None:
        """Test formatting dict as JSON."""
        result = adapter._format_value({"key": "value"})
        assert result == '\'{"key": "value"}\''

    def test_build_read_query_simple(self, adapter: UCStorageAdapter) -> None:
        """Test building a simple read query."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters=None,
            order_by=None,
            limit=None,
        )

        assert "SELECT *" in query
        assert "FROM test_catalog.test_schema.test_data" in query
        assert "WHERE" not in query
        assert "ORDER BY" not in query
        assert "LIMIT" not in query

    def test_build_read_query_with_columns(self, adapter: UCStorageAdapter) -> None:
        """Test building read query with specific columns."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=["id", "name"],
            filters=None,
            order_by=None,
            limit=None,
        )

        assert "SELECT id, name" in query

    def test_build_read_query_with_filters(self, adapter: UCStorageAdapter) -> None:
        """Test building read query with filters."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters={"id": "abc123", "value": 42},
            order_by=None,
            limit=None,
        )

        assert "WHERE" in query
        assert "id = 'abc123'" in query
        assert "value = 42" in query
        assert "AND" in query

    def test_build_read_query_with_null_filter(self, adapter: UCStorageAdapter) -> None:
        """Test building read query with NULL filter."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters={"name": None},
            order_by=None,
            limit=None,
        )

        assert "name IS NULL" in query

    def test_build_read_query_with_order_and_limit(
        self, adapter: UCStorageAdapter
    ) -> None:
        """Test building read query with order and limit."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters=None,
            order_by="created_at DESC",
            limit=10,
        )

        assert "ORDER BY created_at DESC" in query
        assert "LIMIT 10" in query

    def test_build_insert_query(self, adapter: UCStorageAdapter) -> None:
        """Test building insert query."""
        query = adapter._build_insert_query(
            table_id="test_table",
            row={"id": "abc", "name": "Test", "value": 42},
        )

        assert "INSERT INTO test_catalog.test_schema.test_data" in query
        assert "id" in query
        assert "name" in query
        assert "value" in query
        assert "'abc'" in query
        assert "'Test'" in query
        assert "42" in query

    def test_build_upsert_query(self, adapter: UCStorageAdapter) -> None:
        """Test building upsert (MERGE) query."""
        query = adapter._build_upsert_query(
            table_id="test_table",
            row={"id": "abc", "name": "Updated", "value": 100},
        )

        assert "MERGE INTO test_catalog.test_schema.test_data" in query
        assert "target.id = source.id" in query
        assert "WHEN MATCHED THEN UPDATE SET" in query
        assert "WHEN NOT MATCHED THEN INSERT" in query

    def test_build_delete_query(self, adapter: UCStorageAdapter) -> None:
        """Test building delete query."""
        query = adapter._build_delete_query(
            table_id="test_table",
            filters={"id": "abc"},
        )

        assert "DELETE FROM test_catalog.test_schema.test_data" in query
        assert "WHERE id = 'abc'" in query

    def test_build_batch_insert_query(self, adapter: UCStorageAdapter) -> None:
        """Test building batch insert query."""
        rows = [
            {"id": "a", "name": "Row A"},
            {"id": "b", "name": "Row B"},
            {"id": "c", "name": "Row C"},
        ]

        query = adapter._build_batch_insert_query(
            table_id="test_table",
            rows=rows,
        )

        assert "INSERT INTO test_catalog.test_schema.test_data" in query
        assert "VALUES" in query
        # Should have 3 value sets
        assert query.count("'a'") == 1
        assert query.count("'b'") == 1
        assert query.count("'c'") == 1

    @pytest.mark.asyncio
    async def test_read_returns_empty_list(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test read returns empty list when no results."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = None
        mock_client.statement_execution.execute_statement.return_value = mock_response

        results = await adapter.read("test_table")

        assert results == []

    @pytest.mark.asyncio
    async def test_read_returns_rows(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test read returns rows as dicts."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = MagicMock()
        mock_response.result.data_array = [
            ["id1", "Name 1", "100"],
            ["id2", "Name 2", "200"],
        ]
        mock_response.manifest = MagicMock()
        mock_response.manifest.schema = MagicMock()
        # Create column mocks with name as attribute (not constructor param)
        col_id = MagicMock()
        col_id.name = "id"
        col_name = MagicMock()
        col_name.name = "name"
        col_value = MagicMock()
        col_value.name = "value"
        mock_response.manifest.schema.columns = [col_id, col_name, col_value]
        mock_client.statement_execution.execute_statement.return_value = mock_response

        results = await adapter.read("test_table")

        assert len(results) == 2
        assert results[0]["id"] == "id1"
        assert results[0]["name"] == "Name 1"
        assert results[1]["id"] == "id2"

    @pytest.mark.asyncio
    async def test_read_one_returns_single_row(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test read_one returns single row."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = MagicMock()
        mock_response.result.data_array = [["id1", "Name 1", "100"]]
        mock_response.manifest = MagicMock()
        mock_response.manifest.schema = MagicMock()
        # Create column mocks with name as attribute (not constructor param)
        col_id = MagicMock()
        col_id.name = "id"
        col_name = MagicMock()
        col_name.name = "name"
        col_value = MagicMock()
        col_value.name = "value"
        mock_response.manifest.schema.columns = [col_id, col_name, col_value]
        mock_client.statement_execution.execute_statement.return_value = mock_response

        result = await adapter.read_one("test_table", filters={"id": "id1"})

        assert result is not None
        assert result["id"] == "id1"

    @pytest.mark.asyncio
    async def test_read_one_returns_none_when_empty(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test read_one returns None when no results."""
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = None
        mock_client.statement_execution.execute_statement.return_value = mock_response

        result = await adapter.read_one("test_table", filters={"id": "nonexistent"})

        assert result is None

    @pytest.mark.asyncio
    async def test_exists_returns_true(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test exists returns True when row found."""
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = MagicMock()
        mock_response.result.data_array = [["id1"]]
        mock_response.manifest = MagicMock()
        mock_response.manifest.schema = MagicMock()
        col_id = MagicMock()
        col_id.name = "id"
        mock_response.manifest.schema.columns = [col_id]
        mock_client.statement_execution.execute_statement.return_value = mock_response

        result = await adapter.exists("test_table", filters={"id": "id1"})

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test exists returns False when no row found."""
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = None
        mock_client.statement_execution.execute_statement.return_value = mock_response

        result = await adapter.exists("test_table", filters={"id": "nonexistent"})

        assert result is False

    def test_unknown_table_raises_error(self, adapter: UCStorageAdapter) -> None:
        """Test that unknown table ID raises ValueError."""
        with pytest.raises(ValueError, match="Unknown table"):
            adapter._build_read_query(
                table_id="nonexistent_table",
                columns=None,
                filters=None,
                order_by=None,
                limit=None,
            )


class TestColumnValidation:
    """Tests for column name validation (P0.10 hardening)."""

    @pytest.fixture
    def mock_registry(self) -> TableRegistry:
        """Create a registry with test tables."""
        registry = TableRegistry()
        registry.register(
            TableDef(
                table_id="test_table",
                table_name="test_data",
                columns=(
                    ColumnDef("id", "STRING", nullable=False),
                    ColumnDef("name", "STRING"),
                    ColumnDef("value", "INT"),
                    ColumnDef("created_at", "TIMESTAMP"),
                ),
                primary_key=("id",),
            )
        )
        return registry

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Databricks workspace client."""
        return MagicMock()

    @pytest.fixture
    def config(self) -> UCStorageConfig:
        """Create test configuration."""
        return UCStorageConfig(
            catalog="test_catalog",
            schema="test_schema",
            warehouse_id="test-wh-123",
        )

    @pytest.fixture
    def adapter(
        self,
        mock_client: MagicMock,
        config: UCStorageConfig,
        mock_registry: TableRegistry,
    ) -> UCStorageAdapter:
        """Create adapter with mocks."""
        return UCStorageAdapter(
            workspace_client=mock_client,
            config=config,
            registry=mock_registry,
        )

    def test_invalid_filter_column_raises_error(
        self, adapter: UCStorageAdapter
    ) -> None:
        """Test that invalid column in filters raises InvalidColumnError."""
        with pytest.raises(InvalidColumnError, match="invalid_column"):
            adapter._build_read_query(
                table_id="test_table",
                columns=None,
                filters={"invalid_column": "value"},
                order_by=None,
                limit=None,
            )

    def test_invalid_select_column_raises_error(
        self, adapter: UCStorageAdapter
    ) -> None:
        """Test that invalid column in select raises InvalidColumnError."""
        with pytest.raises(InvalidColumnError, match="bad_col"):
            adapter._build_read_query(
                table_id="test_table",
                columns=["id", "bad_col"],
                filters=None,
                order_by=None,
                limit=None,
            )

    def test_invalid_order_by_column_raises_error(
        self, adapter: UCStorageAdapter
    ) -> None:
        """Test that invalid column in ORDER BY raises InvalidColumnError."""
        with pytest.raises(InvalidColumnError, match="unknown_col"):
            adapter._build_read_query(
                table_id="test_table",
                columns=None,
                filters=None,
                order_by="unknown_col DESC",
                limit=None,
            )

    def test_valid_columns_work(self, adapter: UCStorageAdapter) -> None:
        """Test that valid columns don't raise errors."""
        # This should not raise
        query = adapter._build_read_query(
            table_id="test_table",
            columns=["id", "name"],
            filters={"id": "123", "value": 42},
            order_by="created_at DESC",
            limit=10,
        )
        assert "SELECT id, name" in query
        assert "WHERE" in query
        assert "ORDER BY created_at DESC" in query

    def test_order_by_with_asc_desc(self, adapter: UCStorageAdapter) -> None:
        """Test ORDER BY validation handles ASC/DESC suffixes."""
        # These should not raise
        query1 = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters=None,
            order_by="name ASC",
            limit=None,
        )
        assert "ORDER BY name ASC" in query1

        query2 = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters=None,
            order_by="created_at DESC",
            limit=None,
        )
        assert "ORDER BY created_at DESC" in query2

    def test_order_by_multiple_columns(self, adapter: UCStorageAdapter) -> None:
        """Test ORDER BY validation handles multiple columns."""
        query = adapter._build_read_query(
            table_id="test_table",
            columns=None,
            filters=None,
            order_by="name ASC, created_at DESC",
            limit=None,
        )
        assert "ORDER BY name ASC, created_at DESC" in query

    def test_order_by_invalid_in_multi_column(self, adapter: UCStorageAdapter) -> None:
        """Test ORDER BY validation catches invalid column in multi-column order."""
        with pytest.raises(InvalidColumnError, match="bad_col"):
            adapter._build_read_query(
                table_id="test_table",
                columns=None,
                filters=None,
                order_by="name ASC, bad_col DESC",
                limit=None,
            )

    def test_insert_validates_columns(self, adapter: UCStorageAdapter) -> None:
        """Test that INSERT validates column names."""
        with pytest.raises(InvalidColumnError, match="bad_column"):
            adapter._build_insert_query(
                table_id="test_table",
                row={"id": "123", "bad_column": "value"},
            )

    def test_delete_validates_filter_columns(self, adapter: UCStorageAdapter) -> None:
        """Test that DELETE validates filter column names."""
        with pytest.raises(InvalidColumnError, match="invalid_col"):
            adapter._build_delete_query(
                table_id="test_table",
                filters={"invalid_col": "value"},
            )


class TestAsyncWrappers:
    """Tests for async SDK call wrappers (P0.10 hardening)."""

    @pytest.fixture
    def mock_registry(self) -> TableRegistry:
        """Create a registry with test tables."""
        registry = TableRegistry()
        registry.register(
            TableDef(
                table_id="test_table",
                table_name="test_data",
                columns=(ColumnDef("id", "STRING", nullable=False),),
                primary_key=("id",),
            )
        )
        return registry

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Databricks workspace client."""
        client = MagicMock()
        client.statement_execution = MagicMock()
        client.catalogs = MagicMock()
        client.schemas = MagicMock()
        return client

    @pytest.fixture
    def config(self) -> UCStorageConfig:
        """Create test configuration."""
        return UCStorageConfig(
            catalog="test_catalog",
            schema="test_schema",
            warehouse_id="test-wh-123",
        )

    @pytest.fixture
    def adapter(
        self,
        mock_client: MagicMock,
        config: UCStorageConfig,
        mock_registry: TableRegistry,
    ) -> UCStorageAdapter:
        """Create adapter with mocks."""
        return UCStorageAdapter(
            workspace_client=mock_client,
            config=config,
            registry=mock_registry,
        )

    @pytest.mark.asyncio
    async def test_ensure_catalog_uses_async_wrapper(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test that catalog check uses run_databricks_sync for sync SDK call."""
        # Mock catalog exists
        mock_client.catalogs.get.return_value = MagicMock()

        with patch(
            "starboard_server.infra.storage.uc_adapter.run_databricks_sync",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = MagicMock()
            await adapter._ensure_catalog_exists()
            # Should have called run_databricks_sync for the sync SDK call
            mock_run.assert_called()

    @pytest.mark.asyncio
    async def test_ensure_schema_uses_async_wrapper(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test that schema check uses run_databricks_sync for sync SDK call."""
        # Mock schema exists
        mock_client.schemas.get.return_value = MagicMock()

        with patch(
            "starboard_server.infra.storage.uc_adapter.run_databricks_sync",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = MagicMock()
            await adapter._ensure_schema_exists()
            mock_run.assert_called()

    @pytest.mark.asyncio
    async def test_execute_query_uses_async_wrapper(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test that query execution uses run_databricks_sync for sync SDK call."""
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"
        mock_response.result = None

        with patch(
            "starboard_server.infra.storage.uc_adapter.run_databricks_sync",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = mock_response
            await adapter._execute_query("SELECT 1")
            mock_run.assert_called()

    @pytest.mark.asyncio
    async def test_execute_statement_uses_async_wrapper(
        self,
        adapter: UCStorageAdapter,
        mock_client: MagicMock,
    ) -> None:
        """Test that statement execution uses run_databricks_sync for sync SDK call."""
        mock_response = MagicMock()
        mock_response.status.state = "SUCCEEDED"

        with patch(
            "starboard_server.infra.storage.uc_adapter.run_databricks_sync",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = mock_response
            await adapter._execute_statement("CREATE TABLE test")
            mock_run.assert_called()
