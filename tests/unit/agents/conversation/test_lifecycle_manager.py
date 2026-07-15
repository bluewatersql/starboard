# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for ConversationLifecycleManager.

Tests cover:
- Creating new conversations
- Retrieving conversation info
- Listing user's conversations
- Deleting conversations
- Generating friendly names
- Error handling and edge cases
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.models.conversation import ConversationMetadata
from starboard.agents.conversation import ConversationLifecycleManager
from starboard.agents.state.shared_context import SharedAgentContext
from starboard.domain.conversation.api_types import ConversationConfig, ConversationResponse


@pytest.fixture
def mock_state_manager():
    """Mock conversation state manager."""
    manager = AsyncMock()
    manager.save_context = AsyncMock()
    manager.load_context = AsyncMock()
    manager.delete_context = AsyncMock()

    # Add _store attribute for list_conversations
    manager._store = MagicMock()
    manager._store.list_conversations = AsyncMock(return_value=[])
    manager._store.delete_conversation = AsyncMock()

    return manager


@pytest.fixture
def mock_config_generator():
    """Mock domain model config generator."""
    generator = MagicMock()
    generator.generate = MagicMock(
        return_value=[
            {
                "domain": "Query Optimization",
                "domain_key": "query",
                "model": "gpt-4",
                "temperature": 0.3,
            },
            {
                "domain": "Job Analysis",
                "domain_key": "job",
                "model": "gpt-4",
                "temperature": 0.3,
            },
        ]
    )
    return generator


@pytest.fixture
def lifecycle_manager(mock_state_manager, mock_config_generator):
    """ConversationLifecycleManager instance for testing."""
    return ConversationLifecycleManager(
        state_manager=mock_state_manager,
        config_generator=mock_config_generator,
    )


@pytest.mark.asyncio
async def test_create_conversation(
    lifecycle_manager, mock_state_manager, mock_config_generator
):
    """Test creating a new conversation."""
    user_id = "user_123"
    context = {"workspace_id": "ws_abc"}
    config = ConversationConfig(temperature=0.4)

    response = await lifecycle_manager.create(
        user_id=user_id,
        context=context,
        config=config,
    )

    # Verify response
    assert isinstance(response, ConversationResponse)
    assert response.conversation_id.startswith("conv_")
    assert response.user_id == user_id
    assert response.config.temperature == 0.4
    assert len(response.domain_models) == 2

    # Verify state manager was called
    mock_state_manager.save_context.assert_called_once()
    saved_context = mock_state_manager.save_context.call_args[0][0]
    assert isinstance(saved_context, SharedAgentContext)
    assert saved_context.user_id == user_id
    assert saved_context.conversation_id == response.conversation_id


@pytest.mark.asyncio
async def test_create_conversation_with_defaults(lifecycle_manager, mock_state_manager):
    """Test creating conversation with default config and no context."""
    user_id = "user_456"

    response = await lifecycle_manager.create(user_id=user_id)

    # Should use default config
    assert response.config is not None
    assert isinstance(response.config, ConversationConfig)

    # Should have conversation_id
    assert response.conversation_id.startswith("conv_")

    # Should save context
    mock_state_manager.save_context.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_found(lifecycle_manager, mock_state_manager):
    """Test retrieving an existing conversation."""
    conversation_id = "conv_abc123"

    # Mock context exists
    mock_context = MagicMock()
    mock_context.user_id = "user_123"
    mock_state_manager.load_context.return_value = mock_context

    result = await lifecycle_manager.get(conversation_id)

    # Verify result
    assert result is not None
    assert result["conversation_id"] == conversation_id
    assert result["user_id"] == "user_123"
    assert result["exists"] is True

    # Verify load was called
    mock_state_manager.load_context.assert_called_once_with(conversation_id)


@pytest.mark.asyncio
async def test_get_conversation_not_found(lifecycle_manager, mock_state_manager):
    """Test retrieving a non-existent conversation."""
    conversation_id = "conv_nonexistent"

    # Mock context doesn't exist
    mock_state_manager.load_context.return_value = None

    result = await lifecycle_manager.get(conversation_id)

    # Should return None
    assert result is None


@pytest.mark.asyncio
async def test_get_conversation_with_dict_context(
    lifecycle_manager, mock_state_manager
):
    """Test retrieving conversation when context is a dict (compatibility)."""
    conversation_id = "conv_abc123"

    # Mock context as dict (legacy format)
    mock_state_manager.load_context.return_value = {
        "conversation_id": conversation_id,
        "user_id": "user_456",
    }

    result = await lifecycle_manager.get(conversation_id)

    # Should handle dict format
    assert result is not None
    assert result["user_id"] == "user_456"


@pytest.mark.asyncio
async def test_list_for_user_success(lifecycle_manager, mock_state_manager):
    """Test listing conversations for a user."""
    user_id = "user_123"

    # Mock conversation metadata
    from datetime import UTC

    mock_metadata = [
        ConversationMetadata(
            id="conv_1",
            user_id=user_id,
            title="Query Optimization",
            message_count=5,
            last_message_preview="How do I optimize this query?",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        ConversationMetadata(
            id="conv_2",
            user_id=user_id,
            title="Job Analysis",
            message_count=3,
            last_message_preview="What's the status of job 123?",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    mock_state_manager._store.list_conversations.return_value = mock_metadata

    conversations = await lifecycle_manager.list_for_user(
        user_id=user_id,
        limit=20,
        offset=0,
    )

    # Verify results
    assert len(conversations) == 2
    assert conversations[0].conversation_id == "conv_1"
    assert conversations[0].friendly_name == "Query Optimization"
    assert conversations[1].conversation_id == "conv_2"

    # Verify store was called
    mock_state_manager._store.list_conversations.assert_called_once_with(
        user_id=user_id,
        limit=20,
        offset=0,
    )


@pytest.mark.asyncio
async def test_list_for_user_empty(lifecycle_manager, mock_state_manager):
    """Test listing conversations when user has none."""
    user_id = "user_new"

    # Mock empty list
    mock_state_manager._store.list_conversations.return_value = []

    conversations = await lifecycle_manager.list_for_user(user_id=user_id)

    # Should return empty list
    assert conversations == []


@pytest.mark.asyncio
async def test_list_for_user_no_store(lifecycle_manager, mock_state_manager):
    """Test listing conversations when state manager has no _store."""
    user_id = "user_123"

    # Remove _store attribute
    del mock_state_manager._store

    conversations = await lifecycle_manager.list_for_user(user_id=user_id)

    # Should return empty list with warning
    assert conversations == []


@pytest.mark.asyncio
async def test_list_for_user_error(lifecycle_manager, mock_state_manager):
    """Test listing conversations when store raises error."""
    user_id = "user_123"

    # Mock error
    mock_state_manager._store.list_conversations.side_effect = Exception(
        "Database error"
    )

    conversations = await lifecycle_manager.list_for_user(user_id=user_id)

    # Should return empty list and log error
    assert conversations == []


@pytest.mark.asyncio
async def test_delete_conversation_success(lifecycle_manager, mock_state_manager):
    """Test deleting a conversation."""
    conversation_id = "conv_abc123"

    # Mock context exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    result = await lifecycle_manager.delete(conversation_id)

    # Should succeed
    assert result is True

    # Verify delete_context was called (implementation checks for this method first)
    mock_state_manager.delete_context.assert_called_once_with(conversation_id)


@pytest.mark.asyncio
async def test_delete_conversation_not_found(lifecycle_manager, mock_state_manager):
    """Test deleting a non-existent conversation."""
    conversation_id = "conv_nonexistent"

    # Mock context doesn't exist
    mock_state_manager.load_context.return_value = None

    result = await lifecycle_manager.delete(conversation_id)

    # Should return False
    assert result is False


@pytest.mark.asyncio
async def test_delete_conversation_with_delete_method(
    lifecycle_manager, mock_state_manager
):
    """Test deleting conversation when state manager has delete_context method."""
    conversation_id = "conv_abc123"

    # Mock context exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Add delete_context method
    mock_state_manager.delete_context = AsyncMock()

    result = await lifecycle_manager.delete(conversation_id)

    # Should use delete_context method
    assert result is True
    mock_state_manager.delete_context.assert_called_once_with(conversation_id)


@pytest.mark.asyncio
async def test_delete_conversation_error(lifecycle_manager, mock_state_manager):
    """Test deleting conversation when error occurs."""
    conversation_id = "conv_abc123"

    # Mock context exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Mock delete error (implementation checks delete_context first)
    mock_state_manager.delete_context.side_effect = Exception("Delete failed")

    result = await lifecycle_manager.delete(conversation_id)

    # Should return False
    assert result is False


def test_generate_friendly_name_query_domain(lifecycle_manager):
    """Test generating friendly name for query domain."""
    name = lifecycle_manager.generate_friendly_name(
        domain="query",
        extracted_ids={"query_id": "q123"},
    )

    assert name == "Query Optimization: q123"


def test_generate_friendly_name_job_domain(lifecycle_manager):
    """Test generating friendly name for job domain."""
    name = lifecycle_manager.generate_friendly_name(
        domain="job",
        extracted_ids={"job_id": "job_456"},
    )

    assert name == "Job Analysis: job_456"


def test_generate_friendly_name_uc_domain(lifecycle_manager):
    """Test generating friendly name for UC domain."""
    name = lifecycle_manager.generate_friendly_name(
        domain="uc",
        extracted_ids={"table_name": "users"},
    )

    assert name == "Unity Catalog: users"


def test_generate_friendly_name_no_ids(lifecycle_manager):
    """Test generating friendly name without extracted IDs."""
    name = lifecycle_manager.generate_friendly_name(
        domain="diagnostic",
        extracted_ids={},
    )

    assert name == "Diagnostics"


def test_generate_friendly_name_unknown_domain(lifecycle_manager):
    """Test generating friendly name for unknown domain."""
    name = lifecycle_manager.generate_friendly_name(
        domain="unknown",
        extracted_ids={},
    )

    assert name == "Conversation"


def test_generate_friendly_name_multiple_ids(lifecycle_manager):
    """Test generating friendly name with multiple IDs (uses first match)."""
    name = lifecycle_manager.generate_friendly_name(
        domain="query",
        extracted_ids={
            "query_id": "q123",
            "statement_id": "stmt_456",
        },
    )

    # Should use query_id (first in priority list)
    assert name == "Query Optimization: q123"


def test_initialization(mock_state_manager, mock_config_generator):
    """Test ConversationLifecycleManager initialization."""
    manager = ConversationLifecycleManager(
        state_manager=mock_state_manager,
        config_generator=mock_config_generator,
    )

    assert manager.state_manager == mock_state_manager
    assert manager.config_generator == mock_config_generator


@pytest.mark.asyncio
async def test_list_for_user_with_pagination(lifecycle_manager, mock_state_manager):
    """Test listing conversations with pagination parameters."""
    user_id = "user_123"

    # Mock metadata
    from datetime import UTC

    mock_metadata = [
        ConversationMetadata(
            id=f"conv_{i}",
            user_id=user_id,
            title=f"Conversation {i}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            message_count=i + 1,
            last_message_preview=f"Preview {i}",
        )
        for i in range(5)
    ]
    mock_state_manager._store.list_conversations.return_value = mock_metadata

    conversations = await lifecycle_manager.list_for_user(
        user_id=user_id,
        limit=5,
        offset=10,
    )

    # Verify pagination params passed through
    mock_state_manager._store.list_conversations.assert_called_once_with(
        user_id=user_id,
        limit=5,
        offset=10,
    )

    assert len(conversations) == 5


@pytest.mark.asyncio
async def test_create_saves_metadata_in_context(lifecycle_manager, mock_state_manager):
    """Test that create() saves initial metadata in context."""
    context = {"workspace_id": "ws_abc", "custom_field": "value"}
    config = ConversationConfig(temperature=0.5)

    await lifecycle_manager.create(
        user_id="user_123",
        context=context,
        config=config,
    )

    # Verify metadata includes both context and config
    saved_context = mock_state_manager.save_context.call_args[0][0]
    assert saved_context.metadata["workspace_id"] == "ws_abc"
    assert saved_context.metadata["custom_field"] == "value"
    assert "conversation_config" in saved_context.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
