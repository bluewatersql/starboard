# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
SQLite user repository implementation.

Provides persistent user storage using SQLite with async support.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite
from starboard_core.domain.models.auth import User, UserStatus

from starboard_server.domain.auth.exceptions import UserNotFoundError
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class SQLiteUserStore:
    """
    SQLite-backed user repository.

    Uses the same connection as SQLiteStateStore for consistency.
    Assumes schema is already initialized (migration 006).
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        """
        Initialize SQLite user store.

        Args:
            conn: Active aiosqlite connection (from SQLiteStateStore)
        """
        self._conn = conn

    async def find_by_id(self, user_id: str) -> User | None:
        """
        Find user by internal ID.

        Args:
            user_id: Internal user ID

        Returns:
            User if found, None otherwise
        """
        async with self._conn.execute(
            """
            SELECT id, external_id, provider, username, display_name,
                   created_at, last_login, login_count, status, metadata
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_user(tuple(row))

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
        async with self._conn.execute(
            """
            SELECT id, external_id, provider, username, display_name,
                   created_at, last_login, login_count, status, metadata
            FROM users
            WHERE provider = ? AND external_id = ?
            """,
            (provider, external_id),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_user(tuple(row))

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

        Idempotent and thread-safe via database unique constraints.

        Args:
            external_id: Provider-specific user identifier
            username: Username or email
            display_name: Human-readable name
            provider: Authentication provider
            metadata: Optional provider-specific metadata

        Returns:
            Existing or newly created User
        """
        # Try to find existing user
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
        metadata_json = json.dumps(metadata) if metadata else None

        try:
            await self._conn.execute(
                """
                INSERT INTO users (
                    id, external_id, provider, username, display_name,
                    created_at, last_login, login_count, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    external_id,
                    provider,
                    username,
                    display_name,
                    now.isoformat(),
                    None,
                    0,
                    UserStatus.ACTIVE.value,
                    metadata_json,
                ),
            )
            await self._conn.commit()

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

        except aiosqlite.IntegrityError:
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

        for key, value in updates.items():
            if key in ("id", "created_at"):
                continue  # Don't allow updating ID or creation timestamp

            if key == "status" and isinstance(value, UserStatus):
                value = value.value

            if key == "metadata" and isinstance(value, dict):
                value = json.dumps(value)

            if key == "last_login" and isinstance(value, datetime):
                value = value.isoformat()

            set_clauses.append(f"{key} = ?")
            params.append(value)

        if not set_clauses:
            # No valid fields to update
            user = await self.find_by_id(user_id)
            if not user:
                raise UserNotFoundError(user_id, provider="sqlite")
            return user

        params.append(user_id)

        await self._conn.execute(
            f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )
        await self._conn.commit()

        # Fetch and return updated user
        user = await self.find_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="sqlite")

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

        cursor = await self._conn.execute(
            """
            UPDATE users
            SET last_login = ?,
                login_count = login_count + 1
            WHERE id = ?
            """,
            (now.isoformat(), user_id),
        )

        if cursor.rowcount == 0:
            raise UserNotFoundError(user_id, provider="sqlite")

        await self._conn.commit()

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
        params: tuple[Any, ...]
        if status:
            query = """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            params = (status.value, limit, offset)
        else:
            query = """
                SELECT id, external_id, provider, username, display_name,
                       created_at, last_login, login_count, status, metadata
                FROM users
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            params = (limit, offset)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_user(tuple(row)) for row in rows]

    def _row_to_user(self, row: tuple[Any, ...]) -> User:
        """
        Convert database row to User domain model.

        Args:
            row: Database row tuple

        Returns:
            User object
        """
        (
            user_id,
            external_id,
            provider,
            username,
            display_name,
            created_at_str,
            last_login_str,
            login_count,
            status_str,
            metadata_json,
        ) = row

        # Parse timestamps
        created_at = datetime.fromisoformat(created_at_str)
        last_login = datetime.fromisoformat(last_login_str) if last_login_str else None

        # Parse status
        status = UserStatus(status_str)

        # Parse metadata
        metadata = json.loads(metadata_json) if metadata_json else {}

        return User(
            id=user_id,
            external_id=external_id,
            provider=provider,
            username=username,
            display_name=display_name,
            created_at=created_at,
            status=status,
            last_login=last_login,
            login_count=login_count,
            metadata=metadata,
        )

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
