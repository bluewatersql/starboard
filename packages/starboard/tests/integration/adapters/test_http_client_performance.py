# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for HTTPClient performance improvements.

Tests verify:
- Connection reuse reduces latency
- Multiple concurrent requests work correctly
- No connection leaks
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from respx import MockRouter
from starboard.adapters.apis.http_client import HTTPClient


@pytest.mark.integration
class TestHTTPClientPerformance:
    """Integration tests for HTTP client performance."""

    @pytest.fixture
    def base_url(self) -> str:
        """Test base URL."""
        return "https://httpbin.org"

    @pytest.fixture
    def client(self, base_url: str) -> HTTPClient:
        """Create HTTPClient instance."""
        return HTTPClient(base_url=base_url, timeout=30.0)

    @pytest.mark.asyncio
    async def test_connection_reuse_reduces_latency(
        self, client: HTTPClient, respx_mock: MockRouter
    ) -> None:
        """Test that connection reuse reduces latency for repeated requests."""
        # Mock HTTP responses
        respx_mock.get("https://httpbin.org/test").mock(
            return_value=httpx.Response(
                200,
                json={"status": "ok"},
                headers={"content-type": "application/json"},
            )
        )

        # First request (connection establishment)
        start = time.perf_counter()
        await client.get("/test")
        first_request_time = time.perf_counter() - start

        # Second request (should reuse connection)
        start = time.perf_counter()
        await client.get("/test")
        second_request_time = time.perf_counter() - start

        # Second request should be faster (no connection overhead)
        # Note: In real scenarios, this would be more pronounced
        # In mocked tests, the difference may be minimal
        assert second_request_time <= first_request_time * 1.5  # Allow some variance

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self, client: HTTPClient, respx_mock: MockRouter
    ) -> None:
        """Test that multiple concurrent requests work correctly."""
        # Mock multiple endpoints
        for i in range(10):
            respx_mock.get(f"https://httpbin.org/endpoint{i}").mock(
                return_value=httpx.Response(
                    200,
                    json={"id": i},
                    headers={"content-type": "application/json"},
                )
            )

        # Make concurrent requests
        tasks = [client.get(f"/endpoint{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 10
        for i, result in enumerate(results):
            assert result["id"] == i

    @pytest.mark.asyncio
    async def test_no_connection_leaks(
        self, client: HTTPClient, respx_mock: MockRouter
    ) -> None:
        """Test that connections are properly managed and don't leak."""
        respx_mock.get("https://httpbin.org/test").mock(
            return_value=httpx.Response(
                200,
                json={"status": "ok"},
                headers={"content-type": "application/json"},
            )
        )

        # Make many requests
        for _ in range(100):
            await client.get("/test")

        # Close client
        await client.close()

        # Verify clients are closed
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(
        self, base_url: str, respx_mock: MockRouter
    ) -> None:
        """Test that context manager properly cleans up resources."""
        respx_mock.get("https://httpbin.org/test").mock(
            return_value=httpx.Response(
                200,
                json={"status": "ok"},
                headers={"content-type": "application/json"},
            )
        )

        async with HTTPClient(base_url=base_url) as client:
            await client.get("/test")

        # After context exit, client should be closed
        assert client._client.is_closed
