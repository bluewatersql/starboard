"""
Authentication domain models.

These are immutable, pure data structures with no I/O dependencies.
Following Python AI Agent Engineering Standards:
- Frozen dataclasses for immutability
- Complete type hints
- Google-style docstrings
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class UserStatus(str, Enum):
    """User account status."""

    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


@dataclass(frozen=True)
class User:
    """
    Domain model for an authenticated user.

    Immutable record of user identity and metadata.

    Attributes:
        id: Internal user ID (UUID format)
        external_id: Provider-specific user ID (e.g., Databricks user ID)
        provider: Authentication provider ('databricks', 'oauth', etc.)
        username: Username or email address
        display_name: Human-readable name
        created_at: Account creation timestamp
        last_login: Last successful login timestamp (None if never logged in)
        login_count: Total number of successful logins
        status: Account status
        metadata: Provider-specific metadata (e.g., groups, permissions)

    Examples:
        >>> user = User(
        ...     id="user_123",
        ...     external_id="databricks_456",
        ...     provider="databricks",
        ...     username="user@company.com",
        ...     display_name="John Doe",
        ...     created_at=datetime.now(timezone.utc),
        ...     status=UserStatus.ACTIVE,
        ... )
        >>> user.is_active()
        True
    """

    id: str
    external_id: str
    provider: str
    username: str
    display_name: str
    created_at: datetime
    status: UserStatus = UserStatus.ACTIVE
    last_login: datetime | None = None
    login_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Check if user account is active."""
        return self.status == UserStatus.ACTIVE

    def is_disabled(self) -> bool:
        """Check if user account is disabled."""
        return self.status == UserStatus.DISABLED

    def is_deleted(self) -> bool:
        """Check if user account is deleted."""
        return self.status == UserStatus.DELETED


@dataclass(frozen=True)
class UserSession:
    """
    User session context.

    Tracks active user session with metadata and activity.

    Attributes:
        session_id: Unique session identifier
        user_id: User ID this session belongs to
        started_at: Session start timestamp
        last_activity: Last activity timestamp
        source: Session source ('web', 'cli', 'api')
        is_active: Whether session is currently active
        context: Flexible session metadata (e.g., IP address, user agent)

    Examples:
        >>> session = UserSession(
        ...     session_id="sess_789",
        ...     user_id="user_123",
        ...     started_at=datetime.now(timezone.utc),
        ...     last_activity=datetime.now(timezone.utc),
        ...     source="web",
        ... )
        >>> session.duration_seconds
        0.0
    """

    session_id: str
    user_id: str
    started_at: datetime
    last_activity: datetime
    source: str  # 'web', 'cli', 'api'
    is_active: bool = True
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """
        Calculate session duration in seconds.

        Returns:
            Duration from start to last activity in seconds
        """
        return (self.last_activity - self.started_at).total_seconds()
