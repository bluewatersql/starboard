# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for Databricks authentication provider.

Tests follow Python AI Agent Engineering Standards:
- Mock all external dependencies (Databricks API, UserRepository)
- Test success and failure paths
- Test edge cases and error conditions
- 100% coverage target
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request
from starboard_core.domain.models.auth import User, UserStatus
from starboard_server.domain.auth.exceptions import (
    AuthenticationError,
    UserNotFoundError,
)
from starboard_server.infra.auth.providers.databricks import DatabricksAuthProvider


@pytest.fixture
def mock_databricks_api() -> Mock:
    """Create mock Databricks API."""
    api = Mock()
    api.users = Mock()
    api.users.get_current_user = AsyncMock()
    return api


@pytest.fixture
def mock_user_repository() -> AsyncMock:
    """Create mock UserRepository."""
    repo = AsyncMock()
    repo.find_or_create = AsyncMock()
    repo.track_login = AsyncMock()
    return repo


@pytest.fixture
def sample_databricks_user() -> dict:
    """Sample Databricks user data (as returned by SDK's as_dict())."""
    return {
        "id": "databricks_user_123",
        "userName": "user@company.com",  # camelCase from SDK
        "displayName": "Test User",  # camelCase from SDK
        "emails": [{"value": "user@company.com", "primary": True}],
        "groups": [{"display": "admins"}],
    }


@pytest.fixture
def sample_user() -> User:
    """Sample User domain model."""
    return User(
        id="user_uuid_456",
        external_id="databricks_user_123",
        provider="databricks",
        username="user@company.com",
        display_name="Test User",
        created_at=datetime.now(UTC),
        status=UserStatus.ACTIVE,
        login_count=1,
        metadata={"id": "databricks_user_123"},
    )


@pytest.fixture
def mock_request() -> Request:
    """Create mock FastAPI Request."""
    return Mock(spec=Request)


class TestDatabricksAuthProviderInit:
    """Test suite for DatabricksAuthProvider initialization."""

    def test_init_stores_dependencies(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
    ) -> None:
        """Test that __init__ stores dependencies correctly."""
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        assert provider.databricks is mock_databricks_api
        assert provider.users is mock_user_repository


class TestGetCurrentUser:
    """Test suite for get_current_user method."""

    @pytest.mark.asyncio
    async def test_get_current_user_success(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
        sample_databricks_user: dict,
        sample_user: User,
    ) -> None:
        """Test successful user authentication and auto-provisioning."""
        # Setup mocks
        mock_databricks_api.users.get_current_user.return_value = sample_databricks_user
        mock_user_repository.find_or_create.return_value = sample_user
        mock_user_repository.track_login.return_value = None

        # Create provider and authenticate
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        user = await provider.get_current_user(mock_request)

        # Verify result
        assert user == sample_user
        assert user.username == "user@company.com"
        assert user.external_id == "databricks_user_123"

        # Verify Databricks API was called
        mock_databricks_api.users.get_current_user.assert_called_once()

        # Verify user was provisioned
        mock_user_repository.find_or_create.assert_called_once_with(
            external_id="databricks_user_123",
            username="user@company.com",
            display_name="Test User",
            provider="databricks",
            metadata=sample_databricks_user,
        )

        # Verify login was tracked
        mock_user_repository.track_login.assert_called_once_with("user_uuid_456")

    @pytest.mark.asyncio
    async def test_get_current_user_no_databricks_user(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
    ) -> None:
        """Test authentication fails when Databricks returns no user."""
        # Setup mock to return None
        mock_databricks_api.users.get_current_user.return_value = None

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert "No authenticated Databricks user found" in str(exc_info.value)
        assert exc_info.value.provider == "databricks"

        # User repository should not be called
        mock_user_repository.find_or_create.assert_not_called()
        mock_user_repository.track_login.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_user_missing_external_id(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
    ) -> None:
        """Test authentication fails when user data missing external ID."""
        # Setup mock with incomplete data
        mock_databricks_api.users.get_current_user.return_value = {
            "userName": "user@company.com",
            "displayName": "Test User",
            # Missing 'id' field
        }

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert "Invalid user data from Databricks API" in str(exc_info.value)
        assert exc_info.value.provider == "databricks"

    @pytest.mark.asyncio
    async def test_get_current_user_missing_username(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
    ) -> None:
        """Test authentication fails when user data missing username."""
        # Setup mock with incomplete data
        mock_databricks_api.users.get_current_user.return_value = {
            "id": "databricks_user_123",
            "displayName": "Test User",
            # Missing 'userName' field
        }

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert "Invalid user data from Databricks API" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_current_user_display_name_fallback(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
        sample_user: User,
    ) -> None:
        """Test display_name falls back to username when displayName is missing."""
        # Setup mock with no 'displayName' field
        databricks_user = {
            "id": "databricks_user_123",
            "userName": "user@company.com",
            # No 'displayName' field
        }
        mock_databricks_api.users.get_current_user.return_value = databricks_user
        mock_user_repository.find_or_create.return_value = sample_user

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        await provider.get_current_user(mock_request)

        # Verify find_or_create was called with username as display_name
        mock_user_repository.find_or_create.assert_called_once()
        call_kwargs = mock_user_repository.find_or_create.call_args.kwargs
        assert call_kwargs["display_name"] == "user@company.com"

    @pytest.mark.asyncio
    async def test_get_current_user_databricks_api_error(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
    ) -> None:
        """Test authentication fails when Databricks API raises exception."""
        # Setup mock to raise exception
        mock_databricks_api.users.get_current_user.side_effect = Exception(
            "Databricks API unavailable"
        )

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert "Failed to authenticate with Databricks" in str(exc_info.value)
        assert exc_info.value.provider == "databricks"
        assert "original_error" in exc_info.value.details

    @pytest.mark.asyncio
    async def test_get_current_user_repository_error_propagates(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
        sample_databricks_user: dict,
    ) -> None:
        """Test that repository errors are wrapped in AuthenticationError."""
        # Setup mocks
        mock_databricks_api.users.get_current_user.return_value = sample_databricks_user
        mock_user_repository.find_or_create.side_effect = Exception("Database error")

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert "Failed to authenticate with Databricks" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_current_user_auth_error_propagates(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
        sample_databricks_user: dict,
    ) -> None:
        """Test that AuthenticationError is re-raised without wrapping."""
        # Setup mocks
        mock_databricks_api.users.get_current_user.return_value = sample_databricks_user
        auth_error = AuthenticationError("Custom auth error", provider="test")
        mock_user_repository.find_or_create.side_effect = auth_error

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should re-raise the same error
        with pytest.raises(AuthenticationError) as exc_info:
            await provider.get_current_user(mock_request)

        assert exc_info.value is auth_error

    @pytest.mark.asyncio
    async def test_get_current_user_user_not_found_error_propagates(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
        mock_request: Request,
        sample_databricks_user: dict,
    ) -> None:
        """Test that UserNotFoundError is re-raised without wrapping."""
        # Setup mocks
        mock_databricks_api.users.get_current_user.return_value = sample_databricks_user
        not_found_error = UserNotFoundError("user@test.com", provider="test")
        mock_user_repository.find_or_create.side_effect = not_found_error

        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should re-raise the same error
        with pytest.raises(UserNotFoundError) as exc_info:
            await provider.get_current_user(mock_request)

        assert exc_info.value is not_found_error


class TestValidateSession:
    """Test suite for validate_session method."""

    @pytest.mark.asyncio
    async def test_validate_session_returns_true(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
    ) -> None:
        """Test that validate_session always returns True for Databricks."""
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # Should always return True (platform handles sessions)
        result = await provider.validate_session("any_session_id")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_session_different_ids(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
    ) -> None:
        """Test validate_session with different session IDs."""
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        # All should return True
        assert await provider.validate_session("sess_123") is True
        assert await provider.validate_session("sess_456") is True
        assert await provider.validate_session("") is True


class TestProtocolCompliance:
    """Test that DatabricksAuthProvider implements AuthenticationService protocol."""

    def test_has_get_current_user_method(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
    ) -> None:
        """Test provider has get_current_user method."""
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        assert hasattr(provider, "get_current_user")
        assert callable(provider.get_current_user)

    def test_has_validate_session_method(
        self,
        mock_databricks_api: Mock,
        mock_user_repository: AsyncMock,
    ) -> None:
        """Test provider has validate_session method."""
        provider = DatabricksAuthProvider(
            databricks_api=mock_databricks_api,
            user_repository=mock_user_repository,
        )

        assert hasattr(provider, "validate_session")
        assert callable(provider.validate_session)
