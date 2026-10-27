# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SupportModeInitializer."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.adapters.databricks.support_mode import (
    _SUPPORT_ENV_KEY,
    SupportModeInitializer,
)
from starboard.exceptions import DatabricksAPIError, PermissionDeniedError


@pytest.fixture
def mock_sql_service() -> MagicMock:
    """Create a mock SQLService."""
    service = MagicMock()
    service.execute_polars = AsyncMock(return_value=None)
    return service


@pytest.fixture
def initializer(mock_sql_service: MagicMock) -> SupportModeInitializer:
    """Create a SupportModeInitializer with mock SQL service."""
    return SupportModeInitializer(sql_service=mock_sql_service)


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure env var is clean before and after each test."""
    os.environ.pop(_SUPPORT_ENV_KEY, None)
    yield
    os.environ.pop(_SUPPORT_ENV_KEY, None)


class TestInitialize:
    """Tests for SupportModeInitializer.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_executes_all_grants(
        self, initializer: SupportModeInitializer, mock_sql_service: MagicMock
    ) -> None:
        """Execute all 3 GRANT statements and set env var."""
        await initializer.initialize()

        assert mock_sql_service.execute_polars.call_count == 3
        assert os.environ.get(_SUPPORT_ENV_KEY) == "TRUE"

        # Verify grant order
        calls = mock_sql_service.execute_polars.call_args_list
        assert "USE_CATALOG" in calls[0].args[0]
        assert "USE_SCHEMA" in calls[1].args[0]
        assert "SELECT" in calls[2].args[0]

    @pytest.mark.asyncio
    async def test_initialize_idempotent_when_env_set(
        self, initializer: SupportModeInitializer, mock_sql_service: MagicMock
    ) -> None:
        """Skip grants when env var is already set."""
        os.environ[_SUPPORT_ENV_KEY] = "TRUE"

        await initializer.initialize()

        mock_sql_service.execute_polars.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_fails_fast_on_grant_error(
        self, initializer: SupportModeInitializer, mock_sql_service: MagicMock
    ) -> None:
        """Fail on first grant error and don't set env var."""
        mock_sql_service.execute_polars.side_effect = [
            None,  # First grant succeeds
            Exception("SQL execution failed"),  # Second grant fails
        ]

        with pytest.raises(DatabricksAPIError):
            await initializer.initialize()

        assert os.environ.get(_SUPPORT_ENV_KEY) is None
        assert mock_sql_service.execute_polars.call_count == 2

    @pytest.mark.asyncio
    async def test_initialize_raises_on_permission_denied(
        self, initializer: SupportModeInitializer, mock_sql_service: MagicMock
    ) -> None:
        """Raise PermissionDeniedError on 403."""
        mock_sql_service.execute_polars.side_effect = Exception(
            "403 permission denied"
        )

        with pytest.raises(PermissionDeniedError):
            await initializer.initialize()

        assert os.environ.get(_SUPPORT_ENV_KEY) is None

    @pytest.mark.asyncio
    async def test_initialize_does_not_set_env_on_partial_failure(
        self, initializer: SupportModeInitializer, mock_sql_service: MagicMock
    ) -> None:
        """Don't set env var when third grant fails."""
        mock_sql_service.execute_polars.side_effect = [
            None,  # First grant succeeds
            None,  # Second grant succeeds
            Exception("Network timeout"),  # Third grant fails
        ]

        with pytest.raises(DatabricksAPIError):
            await initializer.initialize()

        assert os.environ.get(_SUPPORT_ENV_KEY) is None
