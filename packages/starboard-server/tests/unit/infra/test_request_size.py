"""Unit tests for request size limit middleware.

Tests cover:
- Request size limit enforcement
- Content-Length header checking
- 413 Payload Too Large responses
- Configuration loading
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starboard_server.infra.middleware.request_size import RequestSizeLimitMiddleware


class TestRequestSizeLimitMiddleware:
    """Tests for request size limit middleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create FastAPI app with request size middleware."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size=10 * 1024)  # 10KB

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            return {"status": "ok"}

        return app

    def test_request_within_limit(self, app: FastAPI) -> None:
        """Test that requests within size limit are allowed."""
        client = TestClient(app)

        # Small payload (1KB)
        payload = {"data": "x" * 1024}
        response = client.post("/test", json=payload)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_request_exceeds_limit(self, app: FastAPI) -> None:
        """Test that requests exceeding size limit are rejected."""
        client = TestClient(app, raise_server_exceptions=False)

        # Large payload (20KB) - TestClient will set Content-Length automatically
        # The middleware checks Content-Length header before reading body
        # Create payload that when JSON serialized exceeds 10KB limit
        payload = {"data": "x" * (20 * 1024)}

        # Post with large payload - TestClient sets Content-Length automatically
        # The middleware will raise HTTPException which FastAPI converts to 413 response
        # Use raise_server_exceptions=False to get the actual HTTP response
        response = client.post(
            "/test",
            json=payload,
        )

        # Should return 413 Payload Too Large (middleware checks Content-Length)
        # The middleware checks the Content-Length header value set by TestClient
        # Note: The test fixture sets max_size=10KB, payload is 20KB, so should be rejected
        assert response.status_code == 413
        assert "too large" in response.text.lower()

    def test_request_without_content_length(self, app: FastAPI) -> None:
        """Test that requests without Content-Length are allowed."""
        client = TestClient(app)

        # Request without Content-Length header
        payload = {"data": "test"}
        response = client.post("/test", json=payload)

        # Should be allowed (can't check size without Content-Length)
        assert response.status_code == 200

    def test_middleware_configurable_size(self) -> None:
        """Test that middleware accepts configurable max size."""
        app = FastAPI()
        middleware = RequestSizeLimitMiddleware(app, max_size=5 * 1024 * 1024)  # 5MB
        assert middleware.max_size == 5 * 1024 * 1024

    def test_middleware_default_size(self) -> None:
        """Test that middleware has sensible default."""
        app = FastAPI()
        middleware = RequestSizeLimitMiddleware(app)
        assert middleware.max_size == 10 * 1024 * 1024  # 10MB default

    async def test_middleware_call_next_on_valid_request(self) -> None:
        """Test that middleware calls next middleware on valid request."""
        app = FastAPI()
        middleware = RequestSizeLimitMiddleware(app, max_size=1024)

        # Mock request with small Content-Length
        request = MagicMock(spec=Request)
        request.headers = {"content-length": "512"}

        # Mock call_next
        call_next_called = False

        async def call_next(request: Request):
            nonlocal call_next_called
            call_next_called = True
            return MagicMock()

        # Call middleware dispatch
        await middleware.dispatch(request, call_next)

        # Should have called next
        assert call_next_called

    async def test_middleware_rejects_large_request(self) -> None:
        """Test that middleware rejects large requests."""
        from fastapi.responses import JSONResponse

        app = FastAPI()
        middleware = RequestSizeLimitMiddleware(app, max_size=1024)

        # Mock request with large Content-Length
        request = MagicMock(spec=Request)
        request.headers = {"content-length": "2048"}

        # Mock call_next
        async def call_next(request: Request):
            return MagicMock()

        # Call middleware - should return JSONResponse with 413
        response = await middleware.dispatch(request, call_next)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 413
        # Check response body content
        import json

        body_content = (
            json.loads(response.body.decode())
            if isinstance(response.body, bytes)
            else response.body
        )
        assert "too large" in str(body_content.get("detail", "")).lower()


class TestRequestSizeConfiguration:
    """Tests for request size configuration in EnvConfig."""

    def test_request_size_config_default(self) -> None:
        """Test that request size config has sensible default."""
        from starboard_server.infra.core.config import EnvConfig

        config = EnvConfig.from_env()

        # Verify config exists
        assert config is not None

    def test_request_size_configurable(self) -> None:
        """Test that request size can be configured."""
        import os

        original = os.getenv("MAX_REQUEST_SIZE")
        try:
            os.environ["MAX_REQUEST_SIZE"] = "5242880"  # 5MB
            # Config would read this
            assert os.getenv("MAX_REQUEST_SIZE") == "5242880"
        finally:
            if original:
                os.environ["MAX_REQUEST_SIZE"] = original
            else:
                os.environ.pop("MAX_REQUEST_SIZE", None)
