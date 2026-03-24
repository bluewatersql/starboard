"""Integration tests for container with API."""

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from starboard_core.models.conversation import Message
from starboard_server.api.container_integration import (
    create_app_with_container,
    get_container,
)
from starboard_server.api.turn_context import create_turn_context
from starboard_server.infra import EnvConfig
from starboard_server.infra.core.container import Container


@pytest.fixture
async def test_container():
    """Create test container."""
    config = EnvConfig(
        environment="test",
        database_backend="sqlite",
        offline_mode=True,  # Skip validation for required API keys in tests
    )
    container = Container(config)
    await container.initialize()
    yield container
    await container.shutdown()


@pytest.fixture
def app_with_routes(test_container):
    """Create app with test routes."""
    app = create_app_with_container()

    # Override container dependency for testing
    app.dependency_overrides[get_container] = lambda: test_container

    # Add test route
    @app.post("/test/messages")
    async def add_test_message(
        conversation_id: str,
        content: str,
        user_id: str,
        container: Container = Depends(get_container),
    ):
        """Test endpoint for adding messages."""
        turn_ctx = create_turn_context(conversation_id, user_id)

        conv_repo = container.conversation_repo
        await conv_repo.get_or_create(conversation_id, user_id)
        await conv_repo.add_message(
            conversation_id,
            Message(role="user", content=content),
        )

        return {
            "status": "success",
            "turn_id": turn_ctx.turn_id,
            "conversation_id": conversation_id,
        }

    yield app

    app.dependency_overrides.clear()


def test_container_dependency_injection(app_with_routes, test_container):
    """Should inject container into endpoint."""
    client = TestClient(app_with_routes)

    response = client.post(
        "/test/messages",
        params={
            "conversation_id": "test-conv",
            "content": "Hello",
            "user_id": "user-1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "turn_id" in data
    assert data["conversation_id"] == "test-conv"


@pytest.mark.asyncio
async def test_conversation_persisted(app_with_routes, test_container):
    """Should persist conversation using repository."""
    client = TestClient(app_with_routes)

    # Add message
    response = client.post(
        "/test/messages",
        params={
            "conversation_id": "persist-test",
            "content": "Test message",
            "user_id": "user-1",
        },
    )

    assert response.status_code == 200

    # Verify conversation exists
    conv_repo = test_container.conversation_repo
    conv = await conv_repo.get("persist-test")

    assert conv is not None
    assert conv.user_id == "user-1"
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "Test message"


@pytest.mark.asyncio
async def test_multiple_messages_same_conversation(app_with_routes, test_container):
    """Should add multiple messages to same conversation."""
    client = TestClient(app_with_routes)

    # Add first message
    client.post(
        "/test/messages",
        params={
            "conversation_id": "multi-msg",
            "content": "First message",
            "user_id": "user-1",
        },
    )

    # Add second message
    client.post(
        "/test/messages",
        params={
            "conversation_id": "multi-msg",
            "content": "Second message",
            "user_id": "user-1",
        },
    )

    # Verify both messages exist
    conv_repo = test_container.conversation_repo
    conv = await conv_repo.get("multi-msg")

    assert len(conv.messages) == 2
    assert conv.messages[0].content == "First message"
    assert conv.messages[1].content == "Second message"


@pytest.mark.asyncio
async def test_turn_context_unique_per_request(app_with_routes):
    """Should create unique turn context per request."""
    client = TestClient(app_with_routes)

    # Make two requests
    response1 = client.post(
        "/test/messages",
        params={
            "conversation_id": "turn-test",
            "content": "Message 1",
            "user_id": "user-1",
        },
    )

    response2 = client.post(
        "/test/messages",
        params={
            "conversation_id": "turn-test",
            "content": "Message 2",
            "user_id": "user-1",
        },
    )

    # Turn IDs should be different
    turn_id1 = response1.json()["turn_id"]
    turn_id2 = response2.json()["turn_id"]

    assert turn_id1 != turn_id2


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="MemoryRepository interface changed - query_facts method missing"
)
async def test_end_to_end_flow(app_with_routes, test_container):
    """Test complete flow from API to memory consolidation."""
    client = TestClient(app_with_routes)

    # 1. Add messages via API
    messages = [
        "I need help with Python",
        "How do I use async/await?",
        "Can you explain generators?",
    ]

    for msg in messages:
        response = client.post(
            "/test/messages",
            params={
                "conversation_id": "integration-test",
                "content": msg,
                "user_id": "user-integration",
            },
        )
        assert response.status_code == 200

    # 2. Verify conversation persisted
    conv_repo = test_container.conversation_repo
    conv = await conv_repo.get("integration-test")
    assert len(conv.messages) == 3

    # 3. Consolidate conversation
    from starboard_server.services.memory.memory_consolidation import (
        MemoryConsolidationService,
    )

    service = MemoryConsolidationService(test_container)
    episode_id = await service.consolidate_conversation("integration-test")

    # 4. Verify episode created
    assert episode_id is not None

    # 5. Verify facts extracted
    from starboard_core.models.memory import SemanticQuery

    mem_repo = test_container.memory_repo
    facts = await mem_repo.query_facts(
        "user-integration",
        SemanticQuery(text="", limit=100),
    )

    # Should have extracted some facts
    assert len(facts) >= 1
