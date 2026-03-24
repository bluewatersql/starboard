"""Tests for memory consolidation service."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Message
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.core.container import Container
from starboard_server.services.memory.memory_consolidation import (
    MemoryConsolidationService,
)


@pytest.fixture
async def container():
    """Create test container with in-memory database for isolation."""
    config = EnvConfig(
        environment="test",
        database_backend="sqlite",
        sqlite_state_path=":memory:",
        sqlite_memory_path=":memory:",
        memory_consolidation_enabled=True,
        offline_mode=True,
    )
    container = Container(config)
    await container.initialize()
    yield container
    await container.shutdown()


@pytest.mark.asyncio
async def test_service_initialization(container):
    """Should initialize service with container."""
    service = MemoryConsolidationService(container)

    assert service.container == container
    assert service.config == container.config
    assert not service._running


@pytest.mark.asyncio
async def test_start_stop_service(container):
    """Should start and stop background task."""
    service = MemoryConsolidationService(container)

    # Start service
    await service.start()
    assert service._running
    assert service._task is not None

    # Stop service
    await service.stop()
    assert not service._running


@pytest.mark.asyncio
async def test_start_when_disabled(container):
    """Should not start when disabled in config."""
    # Create container with consolidation disabled
    config = EnvConfig(
        environment="test",
        database_backend="sqlite",
        sqlite_state_path=":memory:",
        sqlite_memory_path=":memory:",
        memory_consolidation_enabled=False,
        offline_mode=True,
    )
    container_disabled = Container(config)
    await container_disabled.initialize()

    service = MemoryConsolidationService(container_disabled)
    await service.start()

    # Should not start
    assert not service._running
    assert service._task is None

    await container_disabled.shutdown()


@pytest.mark.asyncio
async def test_consolidate_conversation(container):
    """Should consolidate conversation into memory."""
    # Create conversation with messages
    conv_repo = container.conversation_repo
    await conv_repo.get_or_create("conv-1", "user-1")

    timestamp = datetime.now(UTC)
    messages = [
        Message(role="user", content="I need help with Python", timestamp=timestamp),
        Message(role="assistant", content="I can help with that!", timestamp=timestamp),
        Message(role="user", content="How do I use async/await?", timestamp=timestamp),
    ]

    for msg in messages:
        await conv_repo.add_message("conv-1", msg)

    # Consolidate conversation
    service = MemoryConsolidationService(container)
    episode_id = await service.consolidate_conversation("conv-1")

    # Verify episode created
    assert episode_id is not None

    # Verify episode can be retrieved via get_relevant_context
    mem_repo = container.memory_repo
    context = await mem_repo.get_relevant_context("user-1", "Python", max_episodes=10)
    assert len(context["episodes"]) > 0


@pytest.mark.asyncio
async def test_consolidate_nonexistent_conversation(container):
    """Should raise error for non-existent conversation."""
    service = MemoryConsolidationService(container)

    with pytest.raises(ValueError, match="not found"):
        await service.consolidate_conversation("nonexistent")


@pytest.mark.asyncio
async def test_consolidate_empty_conversation(container):
    """Should raise error for empty conversation."""
    # Create empty conversation
    conv_repo = container.conversation_repo
    await conv_repo.get_or_create("empty-conv", "user-1")

    service = MemoryConsolidationService(container)

    with pytest.raises(ValueError, match="empty"):
        await service.consolidate_conversation("empty-conv")


@pytest.mark.asyncio
async def test_generate_summary(container):
    """Should generate summary from conversation."""
    # Create conversation
    conv_repo = container.conversation_repo
    conv = await conv_repo.get_or_create("conv-summary", "user-1")

    timestamp = datetime.now(UTC)
    await conv_repo.add_message(
        "conv-summary", Message(role="user", content="Test", timestamp=timestamp)
    )

    # Get updated conversation
    conv = await conv_repo.get("conv-summary")

    # Generate summary
    service = MemoryConsolidationService(container)
    summary = service._generate_summary(conv)

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "1 messages" in summary


@pytest.mark.asyncio
async def test_extract_key_points(container):
    """Should extract key points from conversation."""
    # Create conversation
    conv_repo = container.conversation_repo
    conv = await conv_repo.get_or_create("conv-points", "user-1")

    timestamp = datetime.now(UTC)
    messages = [
        Message(role="user", content="First important point", timestamp=timestamp),
        Message(role="user", content="Second important point", timestamp=timestamp),
        Message(role="user", content="Third important point", timestamp=timestamp),
    ]

    for msg in messages:
        await conv_repo.add_message("conv-points", msg)

    # Get updated conversation
    conv = await conv_repo.get("conv-points")

    # Extract key points
    service = MemoryConsolidationService(container)
    key_points = service._extract_key_points(conv)

    assert isinstance(key_points, list)
    assert len(key_points) == 3


@pytest.mark.asyncio
async def test_extract_facts(container):
    """Should extract facts from conversation."""
    # Create conversation
    conv_repo = container.conversation_repo
    conv = await conv_repo.get_or_create("conv-facts", "user-1")

    timestamp = datetime.now(UTC)
    messages = [
        Message(role="user", content="I prefer Python over Java", timestamp=timestamp),
        Message(role="assistant", content="Got it", timestamp=timestamp),
        Message(
            role="user",
            content="I work at Google in San Francisco",
            timestamp=timestamp,
        ),
    ]

    for msg in messages:
        await conv_repo.add_message("conv-facts", msg)

    # Get updated conversation
    conv = await conv_repo.get("conv-facts")

    # Extract facts
    service = MemoryConsolidationService(container)
    facts = service._extract_facts(conv)

    assert isinstance(facts, list)
    assert len(facts) == 2  # Two user messages > 20 chars

    for fact in facts:
        assert fact.user_id == "user-1"
        assert fact.category == "extracted"
        assert fact.confidence == 0.5
        assert not fact.verified
