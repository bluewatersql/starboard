# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog native user store (Phase 2 C2).

``UCUserStore`` mirrors :class:`SQLiteUserStore` / :class:`InMemoryUserStore`
over the UC ``users`` Delta table, backed by :class:`UCStorageAdapter`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.auth import User, UserStatus

from starboard.adapters.state.uc import _serde
from starboard.adapters.state.uc.tables import USERS
from starboard.domain.auth.exceptions import UserNotFoundError
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.storage.uc_adapter import UCStorageAdapter

logger = get_logger(__name__)


def _user_to_row(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "external_id": user.external_id,
        "provider": user.provider,
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status.value,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "login_count": user.login_count,
        "metadata": _serde.dumps(user.metadata),
    }


def _row_to_user(row: dict[str, Any]) -> User:
    return User(
        id=row["id"],
        external_id=row["external_id"],
        provider=row["provider"],
        username=row["username"],
        display_name=row.get("display_name") or "",
        created_at=_serde.parse_dt(row["created_at"]),
        status=UserStatus(row.get("status") or "active"),
        last_login=_serde.parse_dt_opt(row.get("last_login")),
        login_count=_serde.parse_int(row.get("login_count")),
        metadata=_serde.loads(row.get("metadata"), {}),
    )


class UCUserStore:
    """User identities persisted to a Unity Catalog ``users`` Delta table.

    Args:
        adapter: A configured :class:`UCStorageAdapter`.
    """

    def __init__(self, adapter: UCStorageAdapter) -> None:
        self._adapter = adapter

    async def connect(self) -> None:
        """Ensure catalog/schema/tables exist."""
        await self._adapter.initialize()

    async def close(self) -> None:
        """Release resources (no-op)."""

    async def find_by_id(self, user_id: str) -> User | None:
        """Find a user by internal id."""
        row = await self._adapter.read_one(USERS, {"id": user_id})
        return _row_to_user(row) if row else None

    async def find_by_external_id(
        self,
        provider: str,
        external_id: str,
    ) -> User | None:
        """Find a user by provider + external id."""
        row = await self._adapter.read_one(
            USERS, {"provider": provider, "external_id": external_id}
        )
        return _row_to_user(row) if row else None

    async def find_or_create(
        self,
        external_id: str,
        username: str,
        display_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        """Find an existing user or auto-provision a new one (idempotent)."""
        existing = await self.find_by_external_id(provider, external_id)
        if existing:
            return existing
        now = datetime.now(UTC)
        user = User(
            id=str(uuid.uuid4()),
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
        await self._adapter.upsert(USERS, _user_to_row(user))
        logger.debug("uc_user_created", user_id=user.id, provider=provider)
        return user

    async def update(self, user_id: str, updates: dict[str, Any]) -> User:
        """Update user attributes and persist."""
        user = await self.find_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="uc")
        updated = User(
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
        await self._adapter.upsert(USERS, _user_to_row(updated))
        return updated

    async def track_login(self, user_id: str) -> None:
        """Bump ``last_login`` and increment ``login_count``."""
        user = await self.find_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id, provider="uc")
        await self.update(
            user_id,
            {"last_login": datetime.now(UTC), "login_count": user.login_count + 1},
        )

    async def update_status(self, user_id: str, status: UserStatus) -> User:
        """Update a user's account status."""
        return await self.update(user_id, {"status": status})

    async def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
        status: UserStatus | None = None,
    ) -> list[User]:
        """List users, most-recent first, with optional status filter."""
        rows = await self._adapter.read(
            USERS, order_by="created_at DESC", limit=limit + offset if limit else None
        )
        users = [_row_to_user(r) for r in rows]
        if status:
            users = [u for u in users if u.status == status]
        return users[offset : offset + limit] if limit else users[offset:]

    # -- generic KV (Protocol parity with the other user stores) -----------
    async def get(self, _key: str) -> object | None:
        return None

    async def set(self, _key: str, _value: object) -> None:
        return None

    async def delete(self, _key: str) -> bool:
        return False
