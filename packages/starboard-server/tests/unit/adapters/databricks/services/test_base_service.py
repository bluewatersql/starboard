# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for BaseService async patterns.

Tests cover:
- Async wrapping of sync SDK calls
- Retry with exponential backoff
- Error handling
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from starboard_server.adapters.databricks.services.base import BaseService


class TestBaseServiceAsyncWrapping:
    """Tests for async wrapping of sync SDK calls."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock WorkspaceClient."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_client: MagicMock) -> BaseService:
        """Create BaseService instance."""
        return BaseService(mock_client)

    @pytest.mark.asyncio
    async def test_run_sync_executes_callable(self, service: BaseService) -> None:
        """Test _run_sync executes the provided callable."""
        result = await service._run_sync(lambda: "test_result")
        assert result == "test_result"

    @pytest.mark.asyncio
    async def test_run_sync_with_sdk_mock(
        self, service: BaseService, mock_client: MagicMock
    ) -> None:
        """Test _run_sync with mocked SDK call."""
        mock_client.jobs.get.return_value = MagicMock(
            as_dict=lambda: {"job_id": 123, "name": "Test"}
        )

        result = await service._run_sync(lambda: mock_client.jobs.get(123).as_dict())

        assert result["job_id"] == 123
        mock_client.jobs.get.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_run_sync_propagates_exceptions(self, service: BaseService) -> None:
        """Test _run_sync propagates exceptions from callable."""

        def failing_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await service._run_sync(failing_func)

    @pytest.mark.asyncio
    async def test_run_sync_doesnt_block_event_loop(self, service: BaseService) -> None:
        """Test _run_sync doesn't block the event loop."""
        import time

        # Simulate a blocking operation
        def slow_operation():
            time.sleep(0.1)
            return "done"

        # Run multiple operations concurrently
        start = time.time()
        results = await asyncio.gather(
            service._run_sync(slow_operation),
            service._run_sync(slow_operation),
            service._run_sync(slow_operation),
        )
        elapsed = time.time() - start

        # If truly parallel in thread pool, should take ~0.1s, not ~0.3s
        assert all(r == "done" for r in results)
        # Allow some overhead, but should be significantly less than 0.3s
        assert elapsed < 0.25


class TestBaseServiceRetry:
    """Tests for retry with exponential backoff."""

    @pytest.fixture
    def service(self) -> BaseService:
        """Create BaseService instance."""
        return BaseService(MagicMock())

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self, service: BaseService) -> None:
        """Test successful execution on first attempt."""
        call_count = 0

        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await service._run_with_retry(successful_func, max_retries=3)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self, service: BaseService) -> None:
        """Test success after initial failures."""
        call_count = 0

        def sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Temporary failure")
            return "success"

        result = await service._run_with_retry(
            sometimes_fails,
            max_retries=3,
            retry_delay=0.01,  # Fast for testing
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_last_error(
        self, service: BaseService
    ) -> None:
        """Test that last error is raised after all retries exhausted."""
        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"Failure #{call_count}")

        with pytest.raises(RuntimeError, match="Failure #3"):
            await service._run_with_retry(
                always_fails,
                max_retries=3,
                retry_delay=0.01,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff(self, service: BaseService) -> None:
        """Test exponential backoff between retries."""
        import time

        call_times: list[float] = []

        def track_and_fail():
            call_times.append(time.time())
            raise RuntimeError("Always fails")

        with pytest.raises(RuntimeError):
            await service._run_with_retry(
                track_and_fail,
                max_retries=3,
                retry_delay=0.05,  # 50ms base delay
            )

        # Should have 3 calls
        assert len(call_times) == 3

        # Check delays increase exponentially
        # First retry: ~0.05s, Second retry: ~0.1s
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]

        # Second delay should be roughly 2x the first (with some tolerance)
        assert delay1 >= 0.04  # At least 40ms
        assert delay2 >= delay1 * 1.5  # Second delay should be longer


class TestBaseServiceProperties:
    """Tests for BaseService properties."""

    def test_client_property(self) -> None:
        """Test client property returns the SDK client."""
        mock_client = MagicMock()
        service = BaseService(mock_client)

        assert service.client is mock_client

    def test_subclass_can_access_client(self) -> None:
        """Test subclass can access protected _client."""

        class TestService(BaseService):
            def get_something(self):
                return self._client.something.get()

        mock_client = MagicMock()
        mock_client.something.get.return_value = "result"

        service = TestService(mock_client)
        result = service.get_something()

        assert result == "result"
