# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for AuthMiddleware.

Tests follow Python AI Agent Engineering Standards:
- Mock all external dependencies
- Test success and failure paths
- Test edge cases
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starboard_core.domain.models.auth import User, UserStatus
from starboard.domain.auth.exceptions import AuthenticationError
from starboard.infra.auth.middleware import AuthMiddleware, get_current_user


@pytest.fixture
def sample_user() -> User:
    """Create sample user for testing."""
    return User(
        id="user_123",
        external_id="ext_456",
        provider="databricks",
        username="test@example.com",
        display_name="Test User",
        created_at=datetime.now(UTC),
        status=UserStatus.ACTIVE,
    )


@pytest.fixture
def mock_auth_service(sample_user: User) -> AsyncMock:
    """Create mock authentication service."""
    service = AsyncMock()
    service.get_current_user = AsyncMock(return_value=sample_user)
    return service


@pytest.fixture
def app_with_auth(mock_auth_service: AsyncMock) -> FastAPI:
    """Create FastAPI app with auth middleware."""
    app = FastAPI()

    # Add middleware
    app.add_middleware(
        AuthMiddleware,
        auth_service=mock_auth_service,
        exclude_paths=["/health", "/public"],
    )

    # Test endpoints
    @app.get("/protected")
    async def protected_endpoint(request: Request):
        user = get_current_user(request)
        return {"user_id": user.id, "username": user.username}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "ok"}

    @app.get("/public")
    async def public_endpoint():
        return {"message": "public"}

    return app


class TestAuthMiddlewareSuccess:
    """Test suite for successful authentication."""

    def test_authenticated_request_success(
        self,
        app_with_auth: FastAPI,
        mock_auth_service: AsyncMock,
        sample_user: User,
    ) -> None:
        """Test that authenticated requests succeed."""
        client = TestClient(app_with_auth)

        response = client.get("/protected")

        assert response.status_code == 200
        assert response.json() == {
            "user_id": "user_123",
            "username": "test@example.com",
        }

        # Verify auth service was called
        mock_auth_service.get_current_user.assert_called_once()

    def test_user_stored_in_request_state(
        self,
        app_with_auth: FastAPI,
        sample_user: User,
    ) -> None:
        """Test that user is stored in request.state."""
        client = TestClient(app_with_auth)

        response = client.get("/protected")

        assert response.status_code == 200
        # User was accessible in endpoint (proven by successful response)

    def test_multiple_requests_authenticated(
        self,
        app_with_auth: FastAPI,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that each request is authenticated."""
        client = TestClient(app_with_auth)

        # Make multiple requests
        for _ in range(3):
            response = client.get("/protected")
            assert response.status_code == 200

        # Auth service should be called for each request
        assert mock_auth_service.get_current_user.call_count == 3


class TestAuthMiddlewareExcludedPaths:
    """Test suite for excluded paths (no auth required)."""

    def test_health_endpoint_not_authenticated(
        self,
        app_with_auth: FastAPI,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that /health endpoint skips authentication."""
        client = TestClient(app_with_auth)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Auth service should not be called
        mock_auth_service.get_current_user.assert_not_called()

    def test_public_endpoint_not_authenticated(
        self,
        app_with_auth: FastAPI,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that explicitly excluded paths skip auth."""
        client = TestClient(app_with_auth)

        response = client.get("/public")

        assert response.status_code == 200
        assert response.json() == {"message": "public"}

        # Auth service should not be called
        mock_auth_service.get_current_user.assert_not_called()


class TestAuthMiddlewareAuthenticationErrors:
    """Test suite for authentication failures."""

    def test_authentication_error_returns_401(
        self,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that AuthenticationError returns 401."""
        # Configure service to raise AuthenticationError
        mock_auth_service.get_current_user = AsyncMock(
            side_effect=AuthenticationError(
                "Invalid credentials",
                provider="databricks",
            )
        )

        app = FastAPI()
        app.add_middleware(AuthMiddleware, auth_service=mock_auth_service)

        @app.get("/protected")
        async def protected_endpoint(request: Request):
            return {"ok": True}

        client = TestClient(app)

        response = client.get("/protected")

        assert response.status_code == 401
        assert response.json()["error"] == "Unauthorized"
        assert response.json()["message"] == "Authentication failed"
        assert "Invalid credentials" in response.json()["details"]

    def test_unexpected_error_returns_500(
        self,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that unexpected errors return 500."""
        # Configure service to raise unexpected error
        mock_auth_service.get_current_user = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        app = FastAPI()
        app.add_middleware(AuthMiddleware, auth_service=mock_auth_service)

        @app.get("/protected")
        async def protected_endpoint(request: Request):
            return {"ok": True}

        client = TestClient(app)

        response = client.get("/protected")

        assert response.status_code == 500
        assert response.json()["error"] == "Internal Server Error"


class TestGetCurrentUser:
    """Test suite for get_current_user helper function."""

    def test_get_current_user_success(
        self,
        sample_user: User,
    ) -> None:
        """Test getting user from request.state."""
        # Mock request with user in state
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.user = sample_user

        user = get_current_user(request)

        assert user == sample_user
        assert user.id == "user_123"

    def test_get_current_user_raises_if_no_user(
        self,
    ) -> None:
        """Test that AttributeError is raised if no user in state."""
        # Mock request without user in state
        request = Mock(spec=Request)
        request.state = Mock(spec=[])  # Empty state

        with pytest.raises(AttributeError):
            get_current_user(request)


class TestAuthMiddlewareInitialization:
    """Test suite for middleware initialization."""

    def test_init_with_default_exclude_paths(
        self,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that middleware has default excluded paths."""
        app = FastAPI()
        middleware = AuthMiddleware(app, auth_service=mock_auth_service)

        assert "/health" in middleware.exclude_paths
        assert "/health/live" in middleware.exclude_paths
        assert "/health/ready" in middleware.exclude_paths

    def test_init_with_custom_exclude_paths(
        self,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that custom exclude paths can be provided."""
        app = FastAPI()
        custom_paths = ["/public", "/docs"]
        middleware = AuthMiddleware(
            app,
            auth_service=mock_auth_service,
            exclude_paths=custom_paths,
        )

        assert "/public" in middleware.exclude_paths
        assert "/docs" in middleware.exclude_paths

    def test_init_with_none_exclude_paths(
        self,
        mock_auth_service: AsyncMock,
    ) -> None:
        """Test that exclude_paths defaults work with None."""
        app = FastAPI()
        middleware = AuthMiddleware(
            app,
            auth_service=mock_auth_service,
            exclude_paths=None,
        )

        # Should have default paths
        assert "/health" in middleware.exclude_paths
