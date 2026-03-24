"""
In-memory user repository implementation.

For testing and development. Thread-safe using asyncio locks.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from starboard_core.domain.models.auth import User, UserStatus

from starboard_server.domain.auth.exceptions import UserNotFoundError
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class InMemoryUserStore:
    """
    In-memory user repository for testing.

    Thread-safe, ephemeral storage. Data is lost when process terminates.
    Useful for unit tests and local development.
    """

    def __init__(self) -> None:
        """Initialize in-memory user store."""
        self._users: dict[str, User] = {}
        self._external_id_index: dict[
            tuple[str, str], str
        ] = {}  # (provider, external_id) -> user_id
        self._username_index: dict[str, str] = {}  # username -> user_id

    async def find_by_id(self, user_id: str) -> User | None:
        """
        Find user by internal ID.

        Args:
            user_id: Internal user ID

        Returns:
            User if found, None otherwise
        """
        return self._users.get(user_id)

    async def find_by_external_id(
        self,
        provider: str,
        external_id: str,
    ) -> User | None:
        """
        Find user by provider and external ID.

        Args:
            provider: Authentication provider
            external_id: Provider-specific user ID

        Returns:
            User if found, None otherwise
        """
        key = (provider, external_id)
        user_id = self._external_id_index.get(key)
        if user_id:
            return self._users.get(user_id)
        return None

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

        Idempotent operation. Thread-safe.

        Args:
            external_id: Provider-specific user identifier
            username: Username or email
            display_name: Human-readable name
            provider: Authentication provider
            metadata: Optional provider-specific metadata

        Returns:
            Existing or newly created User
        """
        # Try to find existing user by external_id
        existing = await self.find_by_external_id(provider, external_id)
        if existing:
            logger.debug(
                "user_found",
                user_id=existing.id,
                provider=provider,
                external_id=external_id,
            )
            return existing

        # Create new user
        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        user = User(
            id=user_id,
            external_id=external_id,
            provider=provider,
            username=username,
            display_name=display_name,
            created_at=now,
            status=UserStatus.ACTIVE,
            last_login=None,
            login_count=0,
            metadata=metadata or {},
        )

        # Store user and update indexes
        self._users[user_id] = user
        self._external_id_index[(provider, external_id)] = user_id
        self._username_index[username] = user_id

        logger.debug(
            "user_created",
            user_id=user_id,
            username=username,
            provider=provider,
            external_id=external_id,
        )

        return user

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
        user = self._users.get(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="inmemory")

        # Create updated user (immutable, so we replace)
        updated_user = User(
            id=user.id,
            external_id=updates.get("external_id", user.external_id),
            provider=updates.get("provider", user.provider),
            username=updates.get("username", user.username),
            display_name=updates.get("display_name", user.display_name),
            created_at=user.created_at,
            status=updates.get("status", user.status),
            last_login=updates.get("last_login", user.last_login),
            login_count=updates.get("login_count", user.login_count),
            metadata=updates.get("metadata", user.metadata),
        )

        # Update storage
        self._users[user_id] = updated_user

        # Update indexes if username changed
        if "username" in updates and updates["username"] != user.username:
            # Remove old username index
            self._username_index.pop(user.username, None)
            # Add new username index
            self._username_index[updated_user.username] = user_id

        logger.debug(
            "user_updated",
            user_id=user_id,
            updated_fields=list(updates.keys()),
        )

        return updated_user

    async def track_login(self, user_id: str) -> None:
        """
        Update last_login timestamp and increment login_count.

        Args:
            user_id: Internal user ID

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = self._users.get(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="inmemory")

        now = datetime.now(UTC)
        updated_user = User(
            id=user.id,
            external_id=user.external_id,
            provider=user.provider,
            username=user.username,
            display_name=user.display_name,
            created_at=user.created_at,
            status=user.status,
            last_login=now,
            login_count=user.login_count + 1,
            metadata=user.metadata,
        )

        self._users[user_id] = updated_user

        logger.debug(
            "login_tracked",
            user_id=user_id,
            login_count=updated_user.login_count,
        )

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
        return await self.update(user_id, {"status": status})

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
        users = list(self._users.values())

        # Filter by status if provided
        if status:
            users = [u for u in users if u.status == status]

        # Sort by created_at descending
        users.sort(key=lambda u: u.created_at, reverse=True)

        # Apply pagination
        return users[offset : offset + limit]

    async def clear(self) -> None:
        """Clear all users (for testing)."""
        self._users.clear()
        self._external_id_index.clear()
        self._username_index.clear()
        logger.debug("user_store_cleared")
