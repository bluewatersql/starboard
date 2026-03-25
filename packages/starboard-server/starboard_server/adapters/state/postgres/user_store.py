"""
Postgres user repository implementation.

Provides persistent user storage using PostgreSQL with async support via asyncpg.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
from starboard_core.domain.models.auth import User, UserStatus

from starboard_server.domain.auth.exceptions import UserNotFoundError
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class PostgresUserStore:
    """
    PostgreSQL-backed user repository.

    Uses connection pool for high-performance concurrent access.
    Assumes schema is already initialized (migration 006).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Initialize Postgres user store.

        Args:
            pool: Active asyncpg connection pool (from PostgresStateStore)
        """
        self._pool = pool

    async def find_by_id(self, user_id: str) -> User | None:
        """
        Find user by internal ID.

        Args:
            user_id: Internal user ID

        Returns:
            User if found, None otherwise
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                WHERE id = $1
                """,
                user_id,
            )

        if row is None:
            return None

        return self._row_to_user(row)

    async def find_by_external_id(
        self,
        provider: str,
        external_id: str,
    ) -> User | None:
        """
        Find user by provider and external ID.

        Args:
            provider: Authentication provider
            external_id: Provider-specific user identifier

        Returns:
            User if found, None otherwise
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                WHERE provider = $1 AND external_id = $2
                """,
                provider,
                external_id,
            )

        if row is None:
            return None

        return self._row_to_user(row)

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

        Uses UPSERT (INSERT ... ON CONFLICT) for atomicity.

        Args:
            external_id: Provider-specific user identifier
            username: Username or email
            display_name: Human-readable name
            provider: Authentication provider
            metadata: Optional provider-specific metadata

        Returns:
            Existing or newly created User
        """
        # Try to find existing user first (optimization to avoid unnecessary insert attempts)
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

        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO users (
                        id, external_id, provider, username, display_name,
                        created_at, last_login, login_count, status, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    user_id,
                    external_id,
                    provider,
                    username,
                    display_name,
                    now,
                    None,
                    0,
                    UserStatus.ACTIVE.value,
                    json.dumps(metadata) if metadata else None,
                )

                logger.debug(
                    "user_created",
                    user_id=user_id,
                    username=username,
                    provider=provider,
                    external_id=external_id,
                )

                return User(
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

            except asyncpg.UniqueViolationError:
                # Race condition: user was created by another process
                # Fetch and return the existing user
                existing = await self.find_by_external_id(provider, external_id)
                if existing:
                    logger.debug(
                        "user_found_after_conflict",
                        user_id=existing.id,
                        provider=provider,
                        external_id=external_id,
                    )
                    return existing

                # Should never happen, but raise if it does
                raise

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
        # Build dynamic SET clause
        set_clauses = []
        params = []
        param_index = 1

        for key, value in updates.items():
            if key in ("id", "created_at"):
                continue  # Don't allow updating ID or creation timestamp

            if key == "status" and isinstance(value, UserStatus):
                value = value.value

            if key == "metadata" and isinstance(value, dict):
                value = json.dumps(value)

            set_clauses.append(f"{key} = ${param_index}")
            params.append(value)
            param_index += 1

        if not set_clauses:
            # No valid fields to update
            user = await self.find_by_id(user_id)
            if not user:
                raise UserNotFoundError(user_id, provider="postgres")
            return user

        params.append(user_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ${param_index}",
                *params,
            )

            # Check if any rows were updated
            if result == "UPDATE 0":
                raise UserNotFoundError(user_id, provider="postgres")

        # Fetch and return updated user
        user = await self.find_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="postgres")

        logger.debug(
            "user_updated",
            user_id=user_id,
            updated_fields=list(updates.keys()),
        )

        return user

    async def track_login(self, user_id: str) -> None:
        """
        Update last_login timestamp and increment login_count.

        Args:
            user_id: Internal user ID

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        now = datetime.now(UTC)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE users
                SET last_login = $1,
                    login_count = login_count + 1
                WHERE id = $2
                """,
                now,
                user_id,
            )

            if result == "UPDATE 0":
                raise UserNotFoundError(user_id, provider="postgres")

        logger.debug(
            "login_tracked",
            user_id=user_id,
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
        params: tuple[str, int, int] | tuple[int, int]
        if status:
            query = """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            params = (status.value, limit, offset)
        else:
            query = """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            params = (limit, offset)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_user(row) for row in rows]

    def _row_to_user(self, row: asyncpg.Record) -> User:
        """
        Convert database row to User domain model.

        Args:
            row: Database row

        Returns:
            User object
        """
        # Parse status
        status = UserStatus(row["status"])

        # Parse metadata (JSONB is already a dict in asyncpg)
        metadata = row["metadata"] if row["metadata"] else {}

        return User(
            id=row["id"],
            external_id=row["external_id"],
            provider=row["provider"],
            username=row["username"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            status=status,
            last_login=row["last_login"],
            login_count=row["login_count"],
            metadata=metadata,
        )

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, key: str, value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
