# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for SQL validation guard in execute_sql_query().

Verifies that execute_sql_query() blocks dangerous SQL before execution,
even if validate_sql_query() was bypassed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard_server.tools.domain.analytics_sql.sql_validator import SQLValidator


@pytest.fixture
def tools() -> AnalyticsSQLTools:
    """Create AnalyticsSQLTools with mock dependencies but real SQLValidator."""
    sql_validator = SQLValidator(sql_executor=None)
    return AnalyticsSQLTools(
        llm_client=MagicMock(),
        sql_executor=AsyncMock(),
        sql_validator=sql_validator,
        result_cache=None,
    )


class TestExecuteSQLQueryValidationGate:
    """Test the pre-execution syntax validation gate."""

    @pytest.mark.asyncio
    async def test_select_passes_gate(self, tools: AnalyticsSQLTools) -> None:
        """Valid SELECT statements should pass the syntax gate."""
        # Mock the sql_executor to return a simple DataFrame
        import polars as pl

        tools.sql_executor.execute_sql = AsyncMock(
            return_value=pl.DataFrame({"col": [1]})
        )

        result = await tools.execute_sql_query("SELECT 1 AS col")
        assert result["row_count"] == 1

    @pytest.mark.asyncio
    async def test_drop_blocked(self, tools: AnalyticsSQLTools) -> None:
        """DROP TABLE should be blocked by the gate."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("DROP TABLE users")

    @pytest.mark.asyncio
    async def test_delete_blocked(self, tools: AnalyticsSQLTools) -> None:
        """DELETE should be blocked by the gate."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("DELETE FROM users WHERE 1=1")

    @pytest.mark.asyncio
    async def test_insert_blocked(self, tools: AnalyticsSQLTools) -> None:
        """INSERT should be blocked by the gate."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("INSERT INTO users VALUES (1, 'admin')")

    @pytest.mark.asyncio
    async def test_update_blocked(self, tools: AnalyticsSQLTools) -> None:
        """UPDATE should be blocked by the gate."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("UPDATE users SET role='admin'")

    @pytest.mark.asyncio
    async def test_multi_statement_blocked(self, tools: AnalyticsSQLTools) -> None:
        """Multiple statements (SQL injection pattern) should be blocked."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("SELECT 1; DROP TABLE users")

    @pytest.mark.asyncio
    async def test_empty_sql_blocked(self, tools: AnalyticsSQLTools) -> None:
        """Empty SQL should be blocked by the gate."""
        with pytest.raises(ValueError, match="SQL blocked by pre-execution validation"):
            await tools.execute_sql_query("")

    @pytest.mark.asyncio
    async def test_executor_not_called_when_blocked(
        self, tools: AnalyticsSQLTools
    ) -> None:
        """SQL executor should never be called for blocked queries."""
        with pytest.raises(ValueError):
            await tools.execute_sql_query("DROP TABLE users")

        tools.sql_executor.execute_sql.assert_not_called()
