# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for authentication domain models.

Tests follow Python AI Agent Engineering Standards:
- Test all public methods and properties
- Test edge cases and boundary conditions
- Test immutability of frozen dataclasses
- Clear test names describing expected behavior
"""

from datetime import UTC, datetime, timedelta

import pytest
from starboard_core.domain.models.auth import User, UserSession, UserStatus


def utc_now() -> datetime:
    """Get current UTC time (timezone-aware).

    Replacement for deprecated utc_now() per Python 3.12+.
    """
    return datetime.now(UTC)


class TestUserStatus:
    """Test suite for UserStatus enum."""

    def test_user_status_values(self) -> None:
        """Test that UserStatus has expected values."""
        assert UserStatus.ACTIVE == "active"
        assert UserStatus.DISABLED == "disabled"
        assert UserStatus.DELETED == "deleted"

    def test_user_status_comparison(self) -> None:
        """Test UserStatus enum comparison."""
        assert UserStatus.ACTIVE != UserStatus.DISABLED
        assert UserStatus.ACTIVE == UserStatus.ACTIVE


class TestUser:
    """Test suite for User domain model."""

    def test_user_creation_minimal(self) -> None:
        """Test creating user with minimal required fields."""
        now = utc_now()
        user = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="user@example.com",
            display_name="Test User",
            created_at=now,
        )

        assert user.id == "user_123"
        assert user.external_id == "ext_456"
        assert user.provider == "databricks"
        assert user.username == "user@example.com"
        assert user.display_name == "Test User"
        assert user.created_at == now
        assert user.status == UserStatus.ACTIVE
        assert user.last_login is None
        assert user.login_count == 0
        assert user.metadata == {}

    def test_user_creation_with_all_fields(self) -> None:
        """Test creating user with all fields populated."""
        created_at = utc_now()
        last_login = created_at + timedelta(hours=1)
        metadata = {"email_verified": True, "groups": ["admin", "users"]}

        user = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="admin@example.com",
            display_name="Admin User",
            created_at=created_at,
            status=UserStatus.ACTIVE,
            last_login=last_login,
            login_count=5,
            metadata=metadata,
        )

        assert user.id == "user_123"
        assert user.external_id == "ext_456"
        assert user.provider == "databricks"
        assert user.username == "admin@example.com"
        assert user.display_name == "Admin User"
        assert user.created_at == created_at
        assert user.status == UserStatus.ACTIVE
        assert user.last_login == last_login
        assert user.login_count == 5
        assert user.metadata == metadata
        assert user.metadata["email_verified"] is True
        assert user.metadata["groups"] == ["admin", "users"]

    def test_user_is_active(self) -> None:
        """Test User.is_active() method."""
        now = utc_now()

        active_user = User(
            id="user_1",
            external_id="ext_1",
            provider="databricks",
            username="user1@example.com",
            display_name="User 1",
            created_at=now,
            status=UserStatus.ACTIVE,
        )

        disabled_user = User(
            id="user_2",
            external_id="ext_2",
            provider="databricks",
            username="user2@example.com",
            display_name="User 2",
            created_at=now,
            status=UserStatus.DISABLED,
        )

        assert active_user.is_active() is True
        assert disabled_user.is_active() is False

    def test_user_is_disabled(self) -> None:
        """Test User.is_disabled() method."""
        now = utc_now()

        disabled_user = User(
            id="user_1",
            external_id="ext_1",
            provider="databricks",
            username="user1@example.com",
            display_name="User 1",
            created_at=now,
            status=UserStatus.DISABLED,
        )

        active_user = User(
            id="user_2",
            external_id="ext_2",
            provider="databricks",
            username="user2@example.com",
            display_name="User 2",
            created_at=now,
            status=UserStatus.ACTIVE,
        )

        assert disabled_user.is_disabled() is True
        assert active_user.is_disabled() is False

    def test_user_is_deleted(self) -> None:
        """Test User.is_deleted() method."""
        now = utc_now()

        deleted_user = User(
            id="user_1",
            external_id="ext_1",
            provider="databricks",
            username="user1@example.com",
            display_name="User 1",
            created_at=now,
            status=UserStatus.DELETED,
        )

        active_user = User(
            id="user_2",
            external_id="ext_2",
            provider="databricks",
            username="user2@example.com",
            display_name="User 2",
            created_at=now,
            status=UserStatus.ACTIVE,
        )

        assert deleted_user.is_deleted() is True
        assert active_user.is_deleted() is False

    def test_user_immutability(self) -> None:
        """Test that User is immutable (frozen dataclass)."""
        now = utc_now()
        user = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="user@example.com",
            display_name="Test User",
            created_at=now,
        )

        # Attempt to modify should raise exception
        with pytest.raises(AttributeError):
            user.username = "different@example.com"  # type: ignore

        with pytest.raises(AttributeError):
            user.login_count = 10  # type: ignore

    def test_user_metadata_default_is_not_shared(self) -> None:
        """Test that default metadata dict is not shared between instances."""
        now = utc_now()

        user1 = User(
            id="user_1",
            external_id="ext_1",
            provider="databricks",
            username="user1@example.com",
            display_name="User 1",
            created_at=now,
        )

        user2 = User(
            id="user_2",
            external_id="ext_2",
            provider="databricks",
            username="user2@example.com",
            display_name="User 2",
            created_at=now,
        )

        # Metadata should be separate instances
        assert user1.metadata is not user2.metadata


class TestUserSession:
    """Test suite for UserSession domain model."""

    def test_session_creation_minimal(self) -> None:
        """Test creating session with minimal required fields."""
        now = utc_now()
        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        assert session.session_id == "sess_123"
        assert session.user_id == "user_456"
        assert session.started_at == now
        assert session.last_activity == now
        assert session.source == "web"
        assert session.is_active is True
        assert session.context == {}

    def test_session_creation_with_all_fields(self) -> None:
        """Test creating session with all fields populated."""
        started_at = utc_now()
        last_activity = started_at + timedelta(minutes=30)
        context = {"ip_address": "192.168.1.1", "user_agent": "Mozilla/5.0"}

        session = UserSession(
            session_id="sess_789",
            user_id="user_101",
            started_at=started_at,
            last_activity=last_activity,
            source="cli",
            is_active=False,
            context=context,
        )

        assert session.session_id == "sess_789"
        assert session.user_id == "user_101"
        assert session.started_at == started_at
        assert session.last_activity == last_activity
        assert session.source == "cli"
        assert session.is_active is False
        assert session.context == context
        assert session.context["ip_address"] == "192.168.1.1"

    def test_session_duration_seconds_same_time(self) -> None:
        """Test duration_seconds when started_at equals last_activity."""
        now = utc_now()
        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        assert session.duration_seconds == 0.0

    def test_session_duration_seconds_with_activity(self) -> None:
        """Test duration_seconds with actual session activity."""
        started_at = utc_now()
        last_activity = started_at + timedelta(minutes=15, seconds=30)

        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=started_at,
            last_activity=last_activity,
            source="api",
        )

        expected_duration = 15 * 60 + 30  # 930 seconds
        assert session.duration_seconds == expected_duration

    def test_session_duration_seconds_long_session(self) -> None:
        """Test duration_seconds for a long-running session."""
        started_at = utc_now()
        last_activity = started_at + timedelta(hours=2, minutes=30, seconds=45)

        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=started_at,
            last_activity=last_activity,
            source="web",
        )

        expected_duration = (2 * 3600) + (30 * 60) + 45  # 9045 seconds
        assert session.duration_seconds == expected_duration

    def test_session_immutability(self) -> None:
        """Test that UserSession is immutable (frozen dataclass)."""
        now = utc_now()
        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        # Attempt to modify should raise exception
        with pytest.raises(AttributeError):
            session.source = "cli"  # type: ignore

        with pytest.raises(AttributeError):
            session.is_active = False  # type: ignore

    def test_session_context_default_is_not_shared(self) -> None:
        """Test that default context dict is not shared between instances."""
        now = utc_now()

        session1 = UserSession(
            session_id="sess_1",
            user_id="user_1",
            started_at=now,
            last_activity=now,
            source="web",
        )

        session2 = UserSession(
            session_id="sess_2",
            user_id="user_2",
            started_at=now,
            last_activity=now,
            source="cli",
        )

        # Context should be separate instances
        assert session1.context is not session2.context

    def test_session_source_values(self) -> None:
        """Test that session can be created with different source values."""
        now = utc_now()

        sources = ["web", "cli", "api"]
        for source in sources:
            session = UserSession(
                session_id=f"sess_{source}",
                user_id="user_123",
                started_at=now,
                last_activity=now,
                source=source,
            )
            assert session.source == source


class TestDataClassBehavior:
    """Test dataclass-specific behavior for auth models."""

    def test_user_equality(self) -> None:
        """Test that users with same data are equal."""
        now = utc_now()

        user1 = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="user@example.com",
            display_name="Test User",
            created_at=now,
        )

        user2 = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="user@example.com",
            display_name="Test User",
            created_at=now,
        )

        assert user1 == user2

    def test_user_inequality(self) -> None:
        """Test that users with different data are not equal."""
        now = utc_now()

        user1 = User(
            id="user_123",
            external_id="ext_456",
            provider="databricks",
            username="user1@example.com",
            display_name="User 1",
            created_at=now,
        )

        user2 = User(
            id="user_456",
            external_id="ext_789",
            provider="databricks",
            username="user2@example.com",
            display_name="User 2",
            created_at=now,
        )

        assert user1 != user2

    def test_session_equality(self) -> None:
        """Test that sessions with same data are equal."""
        now = utc_now()

        session1 = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        session2 = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        assert session1 == session2

    def test_session_inequality(self) -> None:
        """Test that sessions with different data are not equal."""
        now = utc_now()

        session1 = UserSession(
            session_id="sess_123",
            user_id="user_456",
            started_at=now,
            last_activity=now,
            source="web",
        )

        session2 = UserSession(
            session_id="sess_456",
            user_id="user_789",
            started_at=now,
            last_activity=now,
            source="cli",
        )

        assert session1 != session2
