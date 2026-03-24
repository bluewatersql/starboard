"""
User repository protocol.

Defines the interface for user data persistence following the Repository pattern.
"""

from typing import Any, Protocol

from starboard_core.domain.models.auth import User, UserStatus


class UserRepository(Protocol):
    """
    Repository protocol for user management.

    This protocol defines the interface for user persistence operations.
    Implementations can use any storage backend (SQLite, Postgres, etc.).
    """

    async def find_by_id(self, user_id: str) -> User | None:
        """
        Find user by internal ID.

        Args:
            user_id: Internal user ID

        Returns:
            User if found, None otherwise
        """
        ...

    async def find_by_external_id(
        self,
        provider: str,
        external_id: str,
    ) -> User | None:
        """
        Find user by provider and external ID.

        Args:
            provider: Authentication provider ('databricks', 'oauth', etc.)
            external_id: Provider-specific user identifier

        Returns:
            User if found, None otherwise
        """
        ...

    async def find_or_create(
        self,
        external_id: str,
        username: str,
        display_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        """
        Find existing user or create new one (auto-provisioning).

        This is the primary method for user provisioning. It's idempotent
        and thread-safe.

        Args:
            external_id: Provider-specific user identifier
            username: Username or email
            display_name: Human-readable name
            provider: Authentication provider
            metadata: Optional provider-specific metadata

        Returns:
            Existing or newly created User

        Raises:
            Exception: If user creation fails
        """
        ...

    async def update(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> User:
        """
        Update user attributes.

        Args:
            user_id: Internal user ID
            updates: Dictionary of fields to update

        Returns:
            Updated User

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        ...

    async def track_login(self, user_id: str) -> None:
        """
        Update last_login timestamp and increment login_count.

        Args:
            user_id: Internal user ID

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        ...

    async def update_status(
        self,
        user_id: str,
        status: UserStatus,
    ) -> User:
        """
        Update user status.

        Args:
            user_id: Internal user ID
            status: New user status

        Returns:
            Updated User

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        ...

    async def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
        status: UserStatus | None = None,
    ) -> list[User]:
        """
        List users with pagination and optional filtering.

        Args:
            limit: Maximum number of users to return
            offset: Number of users to skip
            status: Optional status filter

        Returns:
            List of users
        """
        ...
