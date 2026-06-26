# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for SQLiteUserStore.

These tests use a real SQLite in-memory database.
"""

import aiosqlite
import pytest
from starboard_core.domain.models.auth import UserStatus
from starboard_server.adapters.state.sqlite.user_store import SQLiteUserStore
from starboard_server.domain.auth.exceptions import UserNotFoundError


@pytest.fixture
async def db_conn():
    """Create in-memory SQLite connection with schema."""
    conn = await aiosqlite.connect(":memory:")

    # Enable foreign keys
    await conn.execute("PRAGMA foreign_keys=ON")

    # Initialize schema (migration 006)
    await conn.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            external_id TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'databricks',
            username TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            login_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            metadata TEXT
        );

        CREATE UNIQUE INDEX idx_users_provider_external
            ON users(provider, external_id);

        CREATE UNIQUE INDEX idx_users_username
            ON users(username);
    """
    )
    await conn.commit()

    yield conn

    await conn.close()


@pytest.fixture
async def user_store(db_conn):
    """Create SQLiteUserStore with test database."""
    return SQLiteUserStore(db_conn)


@pytest.fixture
def sample_user_data() -> dict:
    """Sample user data for testing."""
    return {
        "external_id": "databricks_123",
        "username": "test@example.com",
        "display_name": "Test User",
        "provider": "databricks",
        "metadata": {"email_verified": True},
    }


class TestSQLiteUserStoreInit:
    """Test suite for SQLiteUserStore initialization."""

    def test_init_stores_connection(self, db_conn) -> None:
        """Test that __init__ stores connection."""
        store = SQLiteUserStore(db_conn)
        assert store._conn is db_conn


class TestFindById:
    """Test suite for find_by_id method."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing_user(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test finding an existing user by ID."""
        user = await user_store.find_or_create(**sample_user_data)

        found = await user_store.find_by_id(user.id)

        assert found is not None
        assert found.id == user.id
        assert found.username == sample_user_data["username"]

    @pytest.mark.asyncio
    async def test_find_by_id_nonexistent_user(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test finding a non-existent user returns None."""
        result = await user_store.find_by_id("nonexistent_id")
        assert result is None


class TestFindByExternalId:
    """Test suite for find_by_external_id method."""

    @pytest.mark.asyncio
    async def test_find_by_external_id_existing_user(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test finding user by provider and external ID."""
        await user_store.find_or_create(**sample_user_data)

        found = await user_store.find_by_external_id(
            provider=sample_user_data["provider"],
            external_id=sample_user_data["external_id"],
        )

        assert found is not None
        assert found.external_id == sample_user_data["external_id"]

    @pytest.mark.asyncio
    async def test_find_by_external_id_nonexistent_user(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test finding non-existent user returns None."""
        result = await user_store.find_by_external_id(
            provider="databricks",
            external_id="nonexistent",
        )
        assert result is None


class TestFindOrCreate:
    """Test suite for find_or_create method."""

    @pytest.mark.asyncio
    async def test_create_new_user(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test creating a new user."""
        user = await user_store.find_or_create(**sample_user_data)

        assert user.id is not None
        assert user.external_id == sample_user_data["external_id"]
        assert user.username == sample_user_data["username"]
        assert user.status == UserStatus.ACTIVE
        assert user.login_count == 0

    @pytest.mark.asyncio
    async def test_find_existing_user_idempotent(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that find_or_create is idempotent."""
        user1 = await user_store.find_or_create(**sample_user_data)
        user2 = await user_store.find_or_create(**sample_user_data)

        assert user1.id == user2.id

    @pytest.mark.asyncio
    async def test_create_user_persisted_to_database(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
        db_conn,
    ) -> None:
        """Test that created user is actually persisted."""
        user = await user_store.find_or_create(**sample_user_data)

        # Query database directly
        async with db_conn.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user.id,),
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == user.id
        assert row[1] == sample_user_data["username"]


class TestUpdate:
    """Test suite for update method."""

    @pytest.mark.asyncio
    async def test_update_user_display_name(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user display name."""
        user = await user_store.find_or_create(**sample_user_data)

        updated = await user_store.update(
            user.id,
            {"display_name": "Updated Name"},
        )

        assert updated.display_name == "Updated Name"
        assert updated.id == user.id

    @pytest.mark.asyncio
    async def test_update_nonexistent_user_raises_error(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test updating non-existent user raises error."""
        with pytest.raises(UserNotFoundError):
            await user_store.update("nonexistent_id", {"display_name": "New"})


class TestTrackLogin:
    """Test suite for track_login method."""

    @pytest.mark.asyncio
    async def test_track_login_first_time(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test tracking first login."""
        user = await user_store.find_or_create(**sample_user_data)

        await user_store.track_login(user.id)

        updated = await user_store.find_by_id(user.id)
        assert updated.login_count == 1
        assert updated.last_login is not None

    @pytest.mark.asyncio
    async def test_track_login_multiple_times(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test tracking multiple logins."""
        user = await user_store.find_or_create(**sample_user_data)

        await user_store.track_login(user.id)
        await user_store.track_login(user.id)
        await user_store.track_login(user.id)

        updated = await user_store.find_by_id(user.id)
        assert updated.login_count == 3

    @pytest.mark.asyncio
    async def test_track_login_nonexistent_user_raises_error(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test tracking login for non-existent user raises error."""
        with pytest.raises(UserNotFoundError):
            await user_store.track_login("nonexistent_id")


class TestUpdateStatus:
    """Test suite for update_status method."""

    @pytest.mark.asyncio
    async def test_update_status_to_disabled(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user status to disabled."""
        user = await user_store.find_or_create(**sample_user_data)

        updated = await user_store.update_status(user.id, UserStatus.DISABLED)

        assert updated.status == UserStatus.DISABLED


class TestListUsers:
    """Test suite for list_users method."""

    @pytest.mark.asyncio
    async def test_list_users_empty_store(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test listing users when store is empty."""
        users = await user_store.list_users()
        assert users == []

    @pytest.mark.asyncio
    async def test_list_users_with_pagination(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test pagination works correctly."""
        # Create 5 users
        for i in range(5):
            await user_store.find_or_create(
                external_id=f"ext_{i}",
                username=f"user{i}@example.com",
                display_name=f"User {i}",
                provider="databricks",
            )

        # Get first 2 users
        page1 = await user_store.list_users(limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2 users
        page2 = await user_store.list_users(limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_list_users_filter_by_status(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test filtering users by status."""
        user1 = await user_store.find_or_create(
            external_id="ext_1",
            username="user1@example.com",
            display_name="User 1",
            provider="databricks",
        )

        user2 = await user_store.find_or_create(
            external_id="ext_2",
            username="user2@example.com",
            display_name="User 2",
            provider="databricks",
        )
        await user_store.update_status(user2.id, UserStatus.DISABLED)

        # List only active users
        active_users = await user_store.list_users(status=UserStatus.ACTIVE)
        assert len(active_users) == 1
        assert active_users[0].id == user1.id


class TestMetadataPersistence:
    """Test suite for metadata handling."""

    @pytest.mark.asyncio
    async def test_metadata_persisted_correctly(
        self,
        user_store: SQLiteUserStore,
    ) -> None:
        """Test that metadata is stored and retrieved correctly."""
        metadata = {
            "email_verified": True,
            "groups": ["admin", "users"],
            "preferences": {"theme": "dark"},
        }

        user = await user_store.find_or_create(
            external_id="ext_123",
            username="test@example.com",
            display_name="Test User",
            provider="databricks",
            metadata=metadata,
        )

        # Retrieve user
        found = await user_store.find_by_id(user.id)

        assert found.metadata == metadata
        assert found.metadata["email_verified"] is True
        assert found.metadata["groups"] == ["admin", "users"]

    @pytest.mark.asyncio
    async def test_update_metadata(
        self,
        user_store: SQLiteUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user metadata."""
        user = await user_store.find_or_create(**sample_user_data)

        new_metadata = {"updated": True, "version": 2}
        updated = await user_store.update(user.id, {"metadata": new_metadata})

        assert updated.metadata == new_metadata
