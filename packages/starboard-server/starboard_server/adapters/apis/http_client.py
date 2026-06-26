# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Generic HTTP REST client wrapper using httpx.

This module provides a reusable async HTTP client class that supports
standard REST methods with connection pooling.

The client uses a persistent async connection pool to improve performance
by reusing TCP connections across multiple requests.
"""

from typing import Any

import httpx

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class HTTPClient:
    """Generic async HTTP REST client.

    This client provides a simple interface for making async HTTP requests
    with automatic status checking and content extraction. Uses a persistent
    async connection pool to improve performance.

    Attributes:
        base_url: The base URL for all requests.
        headers: Default headers to include in all requests.
        timeout: Request timeout in seconds.
        _client: Persistent async HTTP client instance.

    Example:
        >>> # Using async context manager (recommended)
        >>> async with HTTPClient(base_url="https://api.example.com") as client:
        ...     result = await client.get("/endpoint")
        ...
        >>> # Manual cleanup
        >>> client = HTTPClient(base_url="https://api.example.com")
        >>> result = await client.get("/endpoint")
        >>> await client.close()
    """

    def __init__(
        self,
        base_url: str,
        auth_header: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the HTTP client.

        Creates a persistent httpx.AsyncClient with connection pooling
        configured for optimal performance.

        Args:
            base_url: Base URL/URI for all requests. Should not end with a slash.
            auth_header: Optional authentication header dictionary (e.g.,
                {"Authorization": "Bearer token"}).
            timeout: Request timeout in seconds. Defaults to 30.0.
        """
        self.base_url = base_url.rstrip("/")
        self.headers = auth_header or {}
        self.timeout = timeout

        # Create persistent async client with connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
        )
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=limits,
            headers=self.headers,
        )

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from base URL and endpoint.

        Args:
            endpoint: API endpoint path.

        Returns:
            Full URL string.
        """
        endpoint = endpoint.lstrip("/")
        return f"{self.base_url}/{endpoint}"

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Make an asynchronous GET request.

        Uses the persistent async client instance for connection reuse.

        Args:
            endpoint: API endpoint path.
            params: Optional query parameters.
            headers: Optional additional headers to merge with default headers.

        Returns:
            Response content (JSON parsed if content-type is application/json).

        Raises:
            httpx.HTTPStatusError: If response status indicates an error.
        """
        url = self._build_url(endpoint)
        merged_headers = {**self.headers, **(headers or {})}

        response = await self._client.get(url, params=params, headers=merged_headers)
        response.raise_for_status()
        return self._extract_content(response)

    async def post(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Make an asynchronous POST request.

        Uses the persistent async client instance for connection reuse.

        Args:
            endpoint: API endpoint path.
            json: Optional JSON body data.
            data: Optional form data.
            headers: Optional additional headers to merge with default headers.

        Returns:
            Response content (JSON parsed if content-type is application/json).

        Raises:
            httpx.HTTPStatusError: If response status indicates an error.
        """
        url = self._build_url(endpoint)
        merged_headers = {**self.headers, **(headers or {})}

        response = await self._client.post(
            url, json=json, data=data, headers=merged_headers
        )
        response.raise_for_status()
        return self._extract_content(response)

    async def patch(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Make an asynchronous PATCH request.

        Uses the persistent async client instance for connection reuse.

        Args:
            endpoint: API endpoint path.
            json: Optional JSON body data.
            data: Optional form data.
            headers: Optional additional headers to merge with default headers.

        Returns:
            Response content (JSON parsed if content-type is application/json).

        Raises:
            httpx.HTTPStatusError: If response status indicates an error.
        """
        url = self._build_url(endpoint)
        merged_headers = {**self.headers, **(headers or {})}

        response = await self._client.patch(
            url, json=json, data=data, headers=merged_headers
        )
        response.raise_for_status()
        return self._extract_content(response)

    async def close(self) -> None:
        """Close the HTTP client and release resources.

        Should be called when the client is no longer needed to properly
        clean up connections. Alternatively, use the async context manager.

        Example:
            >>> client = HTTPClient(base_url="https://api.example.com")
            >>> await client.get("/endpoint")
            >>> await client.close()
        """
        await self._client.aclose()

    async def __aenter__(self) -> "HTTPClient":
        """Async context manager entry.

        Returns:
            Self for use in async with statement.
        """
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit.

        Automatically closes the client when exiting context.
        """
        await self.close()

    @staticmethod
    def _extract_content(response: httpx.Response) -> Any:
        """Extract content from response based on content type.

        Args:
            response: The HTTP response object.

        Returns:
            Parsed JSON if content-type is application/json, otherwise text.
        """
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            return response.json()

        return response.text
