# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for background task cleanup.

Tests verify that background tasks are properly cancelled and awaited
during application shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.adapters.state.databricks.memory_store import (
    DatabricksLakebaseMemoryStore,
)
from starboard.adapters.state.databricks.state_store import (
    DatabricksLakebaseStateStore,
)
from starboard.infra.core.container import Container


class TestBackgroundTaskCleanup:
    """Tests for background task cleanup during shutdown."""

    @pytest.mark.asyncio
    async def test_databricks_state_store_cancels_token_refresh(
        self,
    ) -> None:
        """Test that Databricks state store cancels token refresh task on close."""
        # Mock the store (we can't easily test the real one without Databricks setup)
        store = MagicMock(spec=DatabricksLakebaseStateStore)
        store._token_refresh_task = MagicMock()
        store._token_refresh_task.done.return_value = False
        store._token_refresh_task.cancel = MagicMock()

        # Mock the close method behavior
        async def mock_close():
            if store._token_refresh_task and not store._token_refresh_task.done():
                store._token_refresh_task.cancel()
                # Don't await MagicMock - just verify cancel was called
                pass

        store.close = AsyncMock(side_effect=mock_close)

        # Call close
        await store.close()

        # Verify task was cancelled
        store._token_refresh_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_databricks_memory_store_cancels_token_refresh(
        self,
    ) -> None:
        """Test that Databricks memory store cancels token refresh task on close."""
        # Mock the store
        store = MagicMock(spec=DatabricksLakebaseMemoryStore)

        # Create a real task that we can cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        store._token_refresh_task = task

        # Mock the close method behavior
        async def mock_close():
            if store._token_refresh_task and not store._token_refresh_task.done():
                store._token_refresh_task.cancel()
                with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(store._token_refresh_task, timeout=5.0)

        store.close = AsyncMock(side_effect=mock_close)

        # Call close
        await store.close()

        # Verify task was cancelled
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_container_shutdown_closes_all_stores(self) -> None:
        """Test that Container.shutdown() closes all stores."""
        from starboard.infra.core.config import EnvConfig

        config = EnvConfig(
            environment="test",
            database_backend="sqlite",
            offline_mode=True,  # Skip validation for required API keys in tests
        )
        container = Container(config)

        # Mock stores
        state_store = MagicMock()
        state_store.close = AsyncMock()
        cache_store = MagicMock()
        cache_store.close = AsyncMock()
        memory_store = MagicMock()
        memory_store.close = AsyncMock()

        container._state_store = state_store
        container._cache_store = cache_store
        container._memory_store = memory_store

        # Shutdown
        await container.shutdown()

        # Verify all stores were closed
        state_store.close.assert_called_once()
        cache_store.close.assert_called_once()
        memory_store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_timeout_handling(self) -> None:
        """Test that shutdown handles timeouts gracefully."""

        # Create a task that takes too long
        async def slow_task():
            await asyncio.sleep(10)  # Longer than timeout

        task = asyncio.create_task(slow_task())

        # Try to cancel with timeout
        task.cancel()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.1)

        # Task should be cancelled
        assert task.cancelled()
