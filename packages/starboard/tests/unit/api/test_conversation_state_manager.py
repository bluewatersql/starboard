# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for InMemoryConversationStateManager.

**Phase 3, Task 3.3**: API Layer Integration
"""

import pytest
from starboard.agents.state.agent_state import Message, WorkingMemory
from starboard.agents.state.shared_context import SharedAgentContext
from starboard.api.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def manager():
    """Create InMemoryConversationStateManager instance."""
    return InMemoryConversationStateManager()


@pytest.fixture
def sample_context():
    """Create sample SharedAgentContext for testing."""
    return SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[Message(role="user", content="Hello")],
        working_memory=WorkingMemory(facts=["fact1"]),
    )


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
async def test_load_nonexistent_context(manager):
    """Loading a nonexistent context returns None."""
    context = await manager.load_context("nonexistent")
    assert context is None


@pytest.mark.asyncio
async def test_save_and_load_context(manager, sample_context):
    """Save and load a context successfully."""
    await manager.save_context(sample_context)
    loaded = await manager.load_context("conv_123")
    assert loaded == sample_context
    assert loaded.conversation_id == "conv_123"
    assert loaded.user_id == "user_456"
    assert len(loaded.conversation_history) == 1
    assert loaded.conversation_history[0].content == "Hello"


@pytest.mark.asyncio
async def test_save_overwrites_existing_context(manager, sample_context):
    """Saving a context with the same ID overwrites the previous one."""
    await manager.save_context(sample_context)

    # Update context (add_message modifies in place)
    sample_context.add_message(Message(role="assistant", content="World"))
    await manager.save_context(sample_context)

    loaded = await manager.load_context("conv_123")
    assert len(loaded.conversation_history) == 2
    assert loaded.conversation_history[1].content == "World"


@pytest.mark.asyncio
async def test_save_empty_conversation_id_raises_error(manager):
    """Creating a context with empty conversation_id raises ValueError."""
    # Error happens during __post_init__, not during save
    with pytest.raises(ValueError, match="conversation_id cannot be empty"):
        SharedAgentContext(
            conversation_id="",
            user_id="user_456",
            conversation_history=[],
            working_memory=WorkingMemory(),
        )


async def test_clear_context(manager, sample_context):
    """Clear a specific context."""
    await manager.save_context(sample_context)
    manager.clear_context("conv_123")

    loaded = await manager.load_context("conv_123")
    assert loaded is None


def test_clear_nonexistent_context_no_error(manager):
    """Clearing a nonexistent context does not raise an error."""
    manager.clear_context("nonexistent")  # Should not raise


async def test_clear_all(manager):
    """Clear all contexts."""
    context1 = SharedAgentContext(
        conversation_id="conv_1",
        user_id="user_1",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )
    context2 = SharedAgentContext(
        conversation_id="conv_2",
        user_id="user_2",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )
    await manager.save_context(context1)
    await manager.save_context(context2)

    manager.clear_all()

    loaded1 = await manager.load_context("conv_1")
    loaded2 = await manager.load_context("conv_2")
    assert loaded1 is None
    assert loaded2 is None


@pytest.mark.asyncio
async def test_multiple_conversations(manager):
    """Manager can handle multiple conversations independently."""
    context1 = SharedAgentContext(
        conversation_id="conv_1",
        user_id="user_1",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )
    context2 = SharedAgentContext(
        conversation_id="conv_2",
        user_id="user_2",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )

    await manager.save_context(context1)
    await manager.save_context(context2)

    loaded1 = await manager.load_context("conv_1")
    loaded2 = await manager.load_context("conv_2")

    assert loaded1.conversation_id == "conv_1"
    assert loaded2.conversation_id == "conv_2"
    assert loaded1.user_id == "user_1"
    assert loaded2.user_id == "user_2"


@pytest.mark.asyncio
async def test_phase3_task33_acceptance_criteria_conversation_state_manager():
    """
    Comprehensive test for Phase 3, Task 3.3 acceptance criteria:
    ConversationStateManager implementation.
    """
    manager = InMemoryConversationStateManager()

    # 1. ConversationStateManager implementation
    assert hasattr(manager, "load_context")
    assert hasattr(manager, "save_context")

    # 2. Load/save context
    context = SharedAgentContext(
        conversation_id="test_conv",
        user_id="test_user",
        conversation_history=[Message(role="user", content="Test")],
        working_memory=WorkingMemory(),
    )
    await manager.save_context(context)
    loaded = await manager.load_context("test_conv")
    assert loaded == context

    # 3. Multiple conversations
    context2 = SharedAgentContext(
        conversation_id="conv_2",
        user_id="user_2",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )
    await manager.save_context(context2)
    loaded1 = await manager.load_context("test_conv")
    loaded2 = await manager.load_context("conv_2")
    assert loaded1.conversation_id == "test_conv"
    assert loaded2.conversation_id == "conv_2"

    # 4. Overwrite existing context
    context.add_message(Message(role="assistant", content="Response"))
    await manager.save_context(context)
    reloaded = await manager.load_context("test_conv")
    assert len(reloaded.conversation_history) == 2

    # 5. Load nonexistent context returns None
    nonexistent = await manager.load_context("does_not_exist")
    assert nonexistent is None
