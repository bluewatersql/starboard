"""
Unit tests for InMemoryUserStore.

Tests follow Python AI Agent Engineering Standards:
- Complete coverage of all methods
- Test success and failure paths
- Test edge cases
- Test thread safety where applicable
"""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.auth import UserStatus
from starboard_server.adapters.state.inmemory.user_store import InMemoryUserStore
from starboard_server.domain.auth.exceptions import UserNotFoundError


@pytest.fixture
def user_store() -> InMemoryUserStore:
    """Create fresh in-memory user store for each test."""
    return InMemoryUserStore()


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


class TestInMemoryUserStoreInit:
    """Test suite for InMemoryUserStore initialization."""

    def test_init_creates_empty_store(self) -> None:
        """Test that __init__ creates empty data structures."""
        store = InMemoryUserStore()

        assert store._users == {}
        assert store._external_id_index == {}
        assert store._username_index == {}


class TestFindById:
    """Test suite for find_by_id method."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing_user(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test finding an existing user by ID."""
        # Create user first
        user = await user_store.find_or_create(**sample_user_data)

        # Find by ID
        found = await user_store.find_by_id(user.id)

        assert found is not None
        assert found.id == user.id
        assert found.username == sample_user_data["username"]

    @pytest.mark.asyncio
    async def test_find_by_id_nonexistent_user(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test finding a non-existent user returns None."""
        result = await user_store.find_by_id("nonexistent_id")

        assert result is None


class TestFindByExternalId:
    """Test suite for find_by_external_id method."""

    @pytest.mark.asyncio
    async def test_find_by_external_id_existing_user(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test finding user by provider and external ID."""
        # Create user
        await user_store.find_or_create(**sample_user_data)

        # Find by external ID
        found = await user_store.find_by_external_id(
            provider=sample_user_data["provider"],
            external_id=sample_user_data["external_id"],
        )

        assert found is not None
        assert found.external_id == sample_user_data["external_id"]
        assert found.provider == sample_user_data["provider"]

    @pytest.mark.asyncio
    async def test_find_by_external_id_nonexistent_user(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test finding non-existent user returns None."""
        result = await user_store.find_by_external_id(
            provider="databricks",
            external_id="nonexistent",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_external_id_different_provider(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that provider matters in lookup."""
        # Create user with databricks provider
        await user_store.find_or_create(**sample_user_data)

        # Try to find with different provider
        found = await user_store.find_by_external_id(
            provider="oauth",  # Different provider
            external_id=sample_user_data["external_id"],
        )

        assert found is None


class TestFindOrCreate:
    """Test suite for find_or_create method."""

    @pytest.mark.asyncio
    async def test_create_new_user(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test creating a new user."""
        user = await user_store.find_or_create(**sample_user_data)

        assert user.id is not None
        assert user.external_id == sample_user_data["external_id"]
        assert user.username == sample_user_data["username"]
        assert user.display_name == sample_user_data["display_name"]
        assert user.provider == sample_user_data["provider"]
        assert user.status == UserStatus.ACTIVE
        assert user.login_count == 0
        assert user.last_login is None
        assert user.metadata == sample_user_data["metadata"]

    @pytest.mark.asyncio
    async def test_create_user_without_metadata(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test creating user without metadata."""
        user = await user_store.find_or_create(
            external_id="ext_123",
            username="user@example.com",
            display_name="User",
            provider="databricks",
        )

        assert user.metadata == {}

    @pytest.mark.asyncio
    async def test_find_existing_user_idempotent(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that find_or_create is idempotent."""
        # Create user first time
        user1 = await user_store.find_or_create(**sample_user_data)

        # Call again with same data
        user2 = await user_store.find_or_create(**sample_user_data)

        # Should return the same user
        assert user1.id == user2.id
        assert user1 == user2

    @pytest.mark.asyncio
    async def test_create_updates_indexes(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that creating user updates all indexes."""
        user = await user_store.find_or_create(**sample_user_data)

        # Check external_id index
        key = (sample_user_data["provider"], sample_user_data["external_id"])
        assert user_store._external_id_index[key] == user.id

        # Check username index
        assert user_store._username_index[sample_user_data["username"]] == user.id

    @pytest.mark.asyncio
    async def test_create_multiple_users(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test creating multiple different users."""
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

        assert user1.id != user2.id
        assert user1.username != user2.username


class TestUpdate:
    """Test suite for update method."""

    @pytest.mark.asyncio
    async def test_update_user_display_name(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user display name."""
        user = await user_store.find_or_create(**sample_user_data)

        updated = await user_store.update(
            user.id,
            {"display_name": "Updated Name"},
        )

        assert updated.id == user.id
        assert updated.display_name == "Updated Name"
        assert updated.username == user.username  # Unchanged

    @pytest.mark.asyncio
    async def test_update_user_metadata(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user metadata."""
        user = await user_store.find_or_create(**sample_user_data)

        new_metadata = {"email_verified": True, "groups": ["admin"]}
        updated = await user_store.update(
            user.id,
            {"metadata": new_metadata},
        )

        assert updated.metadata == new_metadata

    @pytest.mark.asyncio
    async def test_update_user_username(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating username updates index."""
        user = await user_store.find_or_create(**sample_user_data)
        old_username = user.username
        new_username = "newemail@example.com"

        updated = await user_store.update(
            user.id,
            {"username": new_username},
        )

        assert updated.username == new_username

        # Old username should be removed from index
        assert old_username not in user_store._username_index

        # New username should be in index
        assert user_store._username_index[new_username] == user.id

    @pytest.mark.asyncio
    async def test_update_nonexistent_user_raises_error(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test updating non-existent user raises UserNotFoundError."""
        with pytest.raises(UserNotFoundError) as exc_info:
            await user_store.update("nonexistent_id", {"display_name": "New"})

        assert "nonexistent_id" in str(exc_info.value)


class TestTrackLogin:
    """Test suite for track_login method."""

    @pytest.mark.asyncio
    async def test_track_login_first_time(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test tracking first login."""
        user = await user_store.find_or_create(**sample_user_data)

        assert user.login_count == 0
        assert user.last_login is None

        # Track login
        await user_store.track_login(user.id)

        # Retrieve updated user
        updated = await user_store.find_by_id(user.id)

        assert updated.login_count == 1
        assert updated.last_login is not None
        assert updated.last_login <= datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_track_login_multiple_times(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test tracking multiple logins increments count."""
        user = await user_store.find_or_create(**sample_user_data)

        # Track multiple logins
        await user_store.track_login(user.id)
        await user_store.track_login(user.id)
        await user_store.track_login(user.id)

        # Retrieve updated user
        updated = await user_store.find_by_id(user.id)

        assert updated.login_count == 3

    @pytest.mark.asyncio
    async def test_track_login_updates_timestamp(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that track_login updates last_login timestamp."""
        user = await user_store.find_or_create(**sample_user_data)

        # First login
        await user_store.track_login(user.id)
        user_after_first = await user_store.find_by_id(user.id)
        first_login = user_after_first.last_login

        # Second login (after a tiny delay)
        await user_store.track_login(user.id)
        user_after_second = await user_store.find_by_id(user.id)
        second_login = user_after_second.last_login

        # Timestamp should be updated (or equal if too fast)
        assert second_login >= first_login

    @pytest.mark.asyncio
    async def test_track_login_nonexistent_user_raises_error(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test tracking login for non-existent user raises error."""
        with pytest.raises(UserNotFoundError):
            await user_store.track_login("nonexistent_id")


class TestUpdateStatus:
    """Test suite for update_status method."""

    @pytest.mark.asyncio
    async def test_update_status_to_disabled(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user status to disabled."""
        user = await user_store.find_or_create(**sample_user_data)

        assert user.status == UserStatus.ACTIVE

        updated = await user_store.update_status(user.id, UserStatus.DISABLED)

        assert updated.status == UserStatus.DISABLED
        assert updated.id == user.id

    @pytest.mark.asyncio
    async def test_update_status_to_deleted(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test updating user status to deleted."""
        user = await user_store.find_or_create(**sample_user_data)

        updated = await user_store.update_status(user.id, UserStatus.DELETED)

        assert updated.status == UserStatus.DELETED

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_user(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test updating status for non-existent user raises error."""
        with pytest.raises(UserNotFoundError):
            await user_store.update_status("nonexistent", UserStatus.DISABLED)


class TestListUsers:
    """Test suite for list_users method."""

    @pytest.mark.asyncio
    async def test_list_users_empty_store(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test listing users when store is empty."""
        users = await user_store.list_users()

        assert users == []

    @pytest.mark.asyncio
    async def test_list_users_all(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test listing all users."""
        # Create multiple users
        await user_store.find_or_create(
            external_id="ext_1",
            username="user1@example.com",
            display_name="User 1",
            provider="databricks",
        )
        await user_store.find_or_create(
            external_id="ext_2",
            username="user2@example.com",
            display_name="User 2",
            provider="databricks",
        )

        users = await user_store.list_users()

        assert len(users) == 2

    @pytest.mark.asyncio
    async def test_list_users_with_pagination(
        self,
        user_store: InMemoryUserStore,
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

        # Pages should have different users
        assert page1[0].id != page2[0].id

    @pytest.mark.asyncio
    async def test_list_users_filter_by_status(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test filtering users by status."""
        # Create active user
        user1 = await user_store.find_or_create(
            external_id="ext_1",
            username="user1@example.com",
            display_name="User 1",
            provider="databricks",
        )

        # Create disabled user
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

        # List only disabled users
        disabled_users = await user_store.list_users(status=UserStatus.DISABLED)

        assert len(disabled_users) == 1
        assert disabled_users[0].id == user2.id

    @pytest.mark.asyncio
    async def test_list_users_sorted_by_created_at(
        self,
        user_store: InMemoryUserStore,
    ) -> None:
        """Test that users are sorted by created_at descending."""
        # Create users (newer ones first in result)
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

        users = await user_store.list_users()

        # Most recent user should be first
        assert users[0].id == user2.id
        assert users[1].id == user1.id


class TestClear:
    """Test suite for clear method."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_users(
        self,
        user_store: InMemoryUserStore,
        sample_user_data: dict,
    ) -> None:
        """Test that clear removes all users."""
        # Create some users
        await user_store.find_or_create(**sample_user_data)
        await user_store.find_or_create(
            external_id="ext_2",
            username="user2@example.com",
            display_name="User 2",
            provider="databricks",
        )

        # Clear store
        await user_store.clear()

        # Verify all data structures are empty
        assert user_store._users == {}
        assert user_store._external_id_index == {}
        assert user_store._username_index == {}

        # Verify no users can be found
        users = await user_store.list_users()
        assert users == []
