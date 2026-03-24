"""Tests for SQLService streaming and collected execution.

Tests cover:
- Streaming execution (execute_polars_streaming)
- Collected execution with max_rows (execute_polars)
- RowLimitExceededError behavior
- Edge cases (empty results, single batch, multiple batches)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pyarrow as pa
import pytest
from starboard_server.adapters.databricks.services.sql import (
    DEFAULT_MAX_ROWS,
    RowLimitExceededError,
    SQLService,
)

if TYPE_CHECKING:
    pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    """Create a mock WorkspaceClient."""
    client = MagicMock()
    client.statement_execution = MagicMock()
    return client


@pytest.fixture
def sql_service(mock_workspace_client: MagicMock) -> SQLService:
    """Create SQLService with mock client."""
    return SQLService(mock_workspace_client, warehouse_id="test-warehouse-123")


def create_arrow_bytes(df: pl.DataFrame) -> bytes:
    """Convert Polars DataFrame to Arrow IPC bytes."""
    arrow_table = df.to_arrow()
    sink = pa.BufferOutputStream()
    writer = pa.ipc.new_stream(sink, arrow_table.schema)
    writer.write_table(arrow_table)
    writer.close()
    return sink.getvalue().to_pybytes()


def create_mock_statement_response(
    external_links: list[str] | None = None,
    state: str = "SUCCEEDED",
    statement_id: str = "stmt-123",
) -> MagicMock:
    """Create a mock StatementResponse."""
    from databricks.sdk.service.sql import StatementState

    response = MagicMock()
    response.statement_id = statement_id
    response.status = MagicMock()
    response.status.state = getattr(StatementState, state)
    response.status.error = None

    if external_links:
        response.result = MagicMock()
        response.result.external_links = []
        for url in external_links:
            link = MagicMock()
            link.external_link = url
            response.result.external_links.append(link)
    else:
        response.result = None

    return response


# ============================================================================
# Test: RowLimitExceededError
# ============================================================================


class TestRowLimitExceededError:
    """Tests for RowLimitExceededError exception."""

    def test_error_message(self) -> None:
        """Test error message formatting."""
        error = RowLimitExceededError(row_count=150_000, max_rows=100_000)

        assert error.row_count == 150_000
        assert error.max_rows == 100_000
        assert "150,000" in str(error)
        assert "100,000" in str(error)
        assert "execute_polars_streaming()" in str(error)

    def test_error_attributes(self) -> None:
        """Test error attributes are set correctly."""
        error = RowLimitExceededError(row_count=500, max_rows=100)

        assert error.row_count == 500
        assert error.max_rows == 100


# ============================================================================
# Test: Streaming Execution
# ============================================================================


class TestExecutePolarsStreaming:
    """Tests for execute_polars_streaming method."""

    @pytest.mark.asyncio
    async def test_streaming_yields_batches(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test that streaming yields DataFrame batches."""
        # Create test data
        batch1 = pl.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
        batch2 = pl.DataFrame({"id": [4, 5, 6], "value": ["d", "e", "f"]})

        # Mock statement execution
        mock_response = create_mock_statement_response(
            external_links=["http://link1", "http://link2"]
        )
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        # Mock HTTP responses
        mock_http_response1 = MagicMock()
        mock_http_response1.content = create_arrow_bytes(batch1)
        mock_http_response1.raise_for_status = MagicMock()

        mock_http_response2 = MagicMock()
        mock_http_response2.content = create_arrow_bytes(batch2)
        mock_http_response2.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(
                side_effect=[mock_http_response1, mock_http_response2]
            )
            mock_client_class.return_value = mock_client

            # Collect batches
            batches: list[pl.DataFrame] = []
            async for batch in sql_service.execute_polars_streaming("SELECT 1"):
                batches.append(batch)

        assert len(batches) == 2
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert batches[0]["id"].to_list() == [1, 2, 3]
        assert batches[1]["id"].to_list() == [4, 5, 6]

    @pytest.mark.asyncio
    async def test_streaming_empty_results(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test streaming with no results."""
        mock_response = create_mock_statement_response(external_links=None)
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        batches: list[pl.DataFrame] = []
        async for batch in sql_service.execute_polars_streaming("SELECT 1 WHERE 1=0"):
            batches.append(batch)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_streaming_single_batch(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test streaming with single batch."""
        batch = pl.DataFrame({"x": [1, 2, 3]})
        mock_response = create_mock_statement_response(external_links=["http://link1"])
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        mock_http_response = MagicMock()
        mock_http_response.content = create_arrow_bytes(batch)
        mock_http_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_http_response)
            mock_client_class.return_value = mock_client

            batches: list[pl.DataFrame] = []
            async for b in sql_service.execute_polars_streaming("SELECT 1"):
                batches.append(b)

        assert len(batches) == 1
        assert batches[0]["x"].to_list() == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_streaming_query_failure(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test streaming handles query failure."""
        mock_response = create_mock_statement_response(state="FAILED")
        mock_response.status.error = MagicMock()
        mock_response.status.error.message = "Syntax error"
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        with pytest.raises(RuntimeError, match="Query failed: Syntax error"):
            async for _ in sql_service.execute_polars_streaming("INVALID SQL"):
                pass


# ============================================================================
# Test: Collected Execution
# ============================================================================


class TestExecutePolars:
    """Tests for execute_polars method (collected with max_rows)."""

    @pytest.mark.asyncio
    async def test_collected_combines_batches(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test that collected execution combines all batches."""
        batch1 = pl.DataFrame({"id": [1, 2]})
        batch2 = pl.DataFrame({"id": [3, 4]})

        mock_response = create_mock_statement_response(
            external_links=["http://link1", "http://link2"]
        )
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        mock_http_response1 = MagicMock()
        mock_http_response1.content = create_arrow_bytes(batch1)
        mock_http_response1.raise_for_status = MagicMock()

        mock_http_response2 = MagicMock()
        mock_http_response2.content = create_arrow_bytes(batch2)
        mock_http_response2.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(
                side_effect=[mock_http_response1, mock_http_response2]
            )
            mock_client_class.return_value = mock_client

            df = await sql_service.execute_polars("SELECT 1", max_rows=None)

        assert len(df) == 4
        assert df["id"].to_list() == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_collected_empty_results(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test collected execution with empty results."""
        mock_response = create_mock_statement_response(external_links=None)
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        df = await sql_service.execute_polars("SELECT 1 WHERE 1=0")

        assert len(df) == 0
        assert isinstance(df, pl.DataFrame)

    @pytest.mark.asyncio
    async def test_max_rows_enforcement(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test that max_rows raises error when exceeded."""
        # Create batches that exceed limit
        batch1 = pl.DataFrame({"id": list(range(60))})
        batch2 = pl.DataFrame({"id": list(range(60, 120))})

        mock_response = create_mock_statement_response(
            external_links=["http://link1", "http://link2"]
        )
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        mock_http_response1 = MagicMock()
        mock_http_response1.content = create_arrow_bytes(batch1)
        mock_http_response1.raise_for_status = MagicMock()

        mock_http_response2 = MagicMock()
        mock_http_response2.content = create_arrow_bytes(batch2)
        mock_http_response2.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(
                side_effect=[mock_http_response1, mock_http_response2]
            )
            mock_client_class.return_value = mock_client

            with pytest.raises(RowLimitExceededError) as exc_info:
                await sql_service.execute_polars("SELECT 1", max_rows=100)

            assert exc_info.value.row_count == 120
            assert exc_info.value.max_rows == 100

    @pytest.mark.asyncio
    async def test_max_rows_none_allows_unlimited(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test that max_rows=None allows unlimited rows."""
        # Create large batch
        large_batch = pl.DataFrame({"id": list(range(200_000))})

        mock_response = create_mock_statement_response(external_links=["http://link1"])
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        mock_http_response = MagicMock()
        mock_http_response.content = create_arrow_bytes(large_batch)
        mock_http_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_http_response)
            mock_client_class.return_value = mock_client

            # No error with max_rows=None
            df = await sql_service.execute_polars("SELECT 1", max_rows=None)

        assert len(df) == 200_000

    @pytest.mark.asyncio
    async def test_default_max_rows(self, sql_service: SQLService) -> None:
        """Test default max_rows value."""
        assert DEFAULT_MAX_ROWS == 100_000

    @pytest.mark.asyncio
    async def test_max_rows_boundary(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test max_rows at exact boundary."""
        # Create batch exactly at limit
        batch = pl.DataFrame({"id": list(range(100))})

        mock_response = create_mock_statement_response(external_links=["http://link1"])
        mock_workspace_client.statement_execution.execute_statement.return_value = (
            mock_response
        )

        mock_http_response = MagicMock()
        mock_http_response.content = create_arrow_bytes(batch)
        mock_http_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_http_response)
            mock_client_class.return_value = mock_client

            # Should succeed at exactly max_rows
            df = await sql_service.execute_polars("SELECT 1", max_rows=100)

        assert len(df) == 100


# ============================================================================
# Test: Query History
# ============================================================================


class TestGetQueryHistory:
    """Tests for get_query_history method."""

    @pytest.mark.asyncio
    async def test_get_history_with_statement_id(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test getting query history by statement ID."""
        mock_history = MagicMock()
        mock_history.as_dict.return_value = {
            "res": [{"query_id": "q1", "status": "FINISHED"}]
        }
        mock_workspace_client.query_history.list.return_value = mock_history

        result = await sql_service.get_query_history(statement_id="stmt-123")

        assert result is not None
        assert len(result) == 1
        assert result[0]["query_id"] == "q1"

    @pytest.mark.asyncio
    async def test_get_history_not_found(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test handling not found."""
        from databricks.sdk.errors import NotFound

        mock_workspace_client.query_history.list.side_effect = NotFound("Not found")

        result = await sql_service.get_query_history(statement_id="nonexistent")

        assert result is None


# ============================================================================
# Test: Service Properties
# ============================================================================


class TestSQLServiceProperties:
    """Tests for SQLService properties."""

    def test_warehouse_id_property(self, sql_service: SQLService) -> None:
        """Test warehouse_id property."""
        assert sql_service.warehouse_id == "test-warehouse-123"

    def test_warehouse_id_override(
        self, sql_service: SQLService, mock_workspace_client: MagicMock
    ) -> None:
        """Test warehouse_id can be overridden in execute methods."""
        # This would be tested in integration, but we verify the parameter exists
        # The execute methods accept warehouse_id parameter
        import inspect

        sig = inspect.signature(sql_service.execute_polars)
        assert "warehouse_id" in sig.parameters
