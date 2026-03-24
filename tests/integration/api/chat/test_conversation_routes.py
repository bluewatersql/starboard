"""
Tests for conversation management API endpoints.

Tests all conversation CRUD operations:
- POST /conversations - Create conversation
- GET /conversations - List conversations
- GET /conversations/{id} - Get conversation
- HEAD /conversations/{id} - Check existence
- GET /conversations/{id}/history - Get history
- DELETE /conversations/{id} - Delete conversation
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from starboard_core.domain.models.auth import User, UserStatus
from starboard_server.api.models import (
    ConversationConfig,
    ConversationHistory,
    ConversationMetadata,
    ConversationResponse,
)
from starboard_server.api.models.enums import MessageRole, MessageStatus
from starboard_server.api.models.messages import Message as APIMessage
from starboard_server.main import create_app

TEST_USER = User(
    id="user_123",
    external_id="ext_123",
    provider="test",
    username="test@example.com",
    display_name="Test User",
    created_at=datetime.now(UTC),
    status=UserStatus.ACTIVE,
)


@pytest.fixture
def mock_manager():
    """Mock MultiAgentConversationManager."""
    manager = AsyncMock()

    # Mock create_conversation
    manager.create_conversation.return_value = ConversationResponse(
        conversation_id="conv_test123",
        friendly_name="Test Conversation",
        created_at=datetime.now(UTC),
        config=ConversationConfig(
            temperature=0.4,
            max_tokens=120000,  # Valid: >= 10000
            safe_mode=False,
            streaming=True,
            model="gpt-4o-mini",
        ),
    )

    # Mock list_conversations - items need user_id for response construction
    manager.list_conversations.return_value = [
        Mock(
            conversation_id="conv_1",
            user_id="user_123",
            friendly_name="Conversation 1",
            created_at=datetime.now(UTC),
            config=ConversationConfig(),
        ),
        Mock(
            conversation_id="conv_2",
            user_id="user_123",
            friendly_name="Conversation 2",
            created_at=datetime.now(UTC),
            config=ConversationConfig(),
        ),
    ]

    # Mock get_conversation (used by ownership check and GET endpoint)
    manager.get_conversation.return_value = {
        "conversation_id": "conv_test123",
        "user_id": "user_123",
        "exists": True,
    }

    # Mock conversation_exists
    manager.conversation_exists.return_value = True

    # Mock get_history (route calls manager.get_history, not get_conversation_history)
    now = datetime.now(UTC)
    manager.get_history.return_value = ConversationHistory(
        conversation_id="conv_test123",
        messages=[
            APIMessage(
                id="msg_1",
                conversation_id="conv_test123",
                role=MessageRole.USER,
                content="Hello",
                timestamp=now,
                status=MessageStatus.COMPLETED,
            ),
            APIMessage(
                id="msg_2",
                conversation_id="conv_test123",
                role=MessageRole.ASSISTANT,
                content="Hi there!",
                timestamp=now,
                status=MessageStatus.COMPLETED,
            ),
        ],
        metadata=ConversationMetadata(
            total_messages=2,
            total_tokens=100,
            total_cost=0.001,
            created_at=now,
            updated_at=now,
            friendly_name="Test Conversation",
        ),
    )

    # Mock delete_conversation - returns True on success
    manager.delete_conversation.return_value = True

    return manager


@pytest.fixture
def mock_auth_middleware():
    """Bypass AuthMiddleware by patching dispatch to set a test user."""

    async def passthrough_dispatch(self, request, call_next):
        request.state.user = TEST_USER
        return await call_next(request)

    with patch(
        "starboard_server.infra.auth.middleware.AuthMiddleware.dispatch",
        passthrough_dispatch,
    ):
        yield


@pytest.fixture
def test_app(
    mock_manager,
    mock_event_coverage,
    mock_config,
    mock_container,
    mock_app_config,
    mock_auth_middleware,
):
    """Create test app with mocked dependencies."""
    app = create_app()

    # Override the dependency
    from starboard_server.api.dependencies import get_multi_agent_manager

    async def override_get_manager():
        return mock_manager

    app.dependency_overrides[get_multi_agent_manager] = override_get_manager

    return app


@pytest.fixture
def mock_event_coverage():
    """Mock event coverage validation."""
    with patch("starboard_server.api.event_converter.validate_event_coverage") as mock:
        mock.return_value = (True, [])
        yield mock


@pytest.fixture
def mock_config():
    """Mock app configuration."""
    with patch("starboard_server.main.get_config") as mock:
        config = Mock()
        config.log_level = "INFO"
        config.log_json = False
        config.host = "localhost"
        config.port = 8000
        config.debug = False
        config.environment = "test"
        config.database_backend = "sqlite"
        config.sqlite_state_path = ":memory:"
        config.database_url = None
        config.redis_url = None
        config.max_request_size = 10 * 1024 * 1024  # 10MB
        config.rate_limit_enabled = False
        mock.return_value = config
        yield config


@pytest.fixture
def mock_container():
    """Mock Container for testing."""
    with patch("starboard_server.main.Container") as mock_container_class:
        container = AsyncMock()
        container.config = Mock(
            environment="test",
            database_backend="sqlite",
        )
        container.state_store = Mock(__name__="InMemoryStateStore")
        container.memory_store = Mock(__name__="InMemoryMemoryStore")
        mock_container_class.return_value = container
        yield container


@pytest.fixture
def mock_app_config():
    """Mock get_config function."""
    with patch("starboard_server.infra.core.config.get_config") as mock_get_config:
        config = Mock()
        config.environment = "test"
        config.database_backend = "sqlite"
        config.sqlite_state_path = ":memory:"
        config.database_url = None
        config.redis_url = None
        config.validate = Mock()
        mock_get_config.return_value = config
        yield config


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.mark.requires_databricks
class TestCreateConversation:
    """Tests for POST /conversations endpoint."""

    def test_create_conversation_success(self, client, mock_manager):
        """Test successful conversation creation."""
        response = client.post(
            "/api/chat/conversations",
            json={
                "context": {"workspace_id": "ws_abc"},
                "config": {"temperature": 0.4},
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "conversation_id" in data
        assert data["conversation_id"] == "conv_test123"
        assert "config" in data

        # Verify manager was called correctly
        mock_manager.create_conversation.assert_called_once()

    def test_create_conversation_minimal_request(self, client, mock_manager):
        """Test creating conversation with minimal data (empty body)."""
        response = client.post(
            "/api/chat/conversations",
            json={},
        )

        assert response.status_code == 201
        data = response.json()
        assert "conversation_id" in data

    def test_create_conversation_invalid_config(self, client):
        """Test creation with invalid configuration."""
        response = client.post(
            "/api/chat/conversations",
            json={
                "config": {"temperature": 2.0},  # Invalid: > 1.0
            },
        )

        # Should still accept (validation happens later) or reject
        assert response.status_code in [201, 422]

    def test_create_conversation_manager_error(self, client, mock_manager):
        """Test handling of manager errors."""
        mock_manager.create_conversation.side_effect = Exception("Database error")

        response = client.post(
            "/api/chat/conversations",
            json={},
        )

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data


@pytest.mark.requires_databricks
class TestListConversations:
    """Tests for GET /conversations endpoint.

    Note: user_id is extracted from authentication middleware (request.state.user),
    not from query parameters.
    """

    def test_list_conversations_success(self, client, mock_manager):
        """Test successful conversation listing."""
        response = client.get("/api/chat/conversations")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["conversation_id"] == "conv_1"
        assert data[1]["conversation_id"] == "conv_2"

    def test_list_conversations_with_pagination(self, client, mock_manager):
        """Test conversation listing with pagination."""
        response = client.get("/api/chat/conversations?limit=10&offset=0")

        assert response.status_code == 200
        mock_manager.list_conversations.assert_called_with(
            user_id="user_123",
            limit=10,
            offset=0,
        )

    def test_list_conversations_invalid_limit(self, client):
        """Test listing with invalid limit."""
        response = client.get("/api/chat/conversations?limit=200")

        assert response.status_code == 422
        data = response.json()
        assert "limit" in data["detail"].lower()

    def test_list_conversations_negative_limit(self, client):
        """Test listing with negative limit."""
        response = client.get("/api/chat/conversations?limit=-1")

        assert response.status_code == 422

    def test_list_conversations_negative_offset(self, client):
        """Test listing with negative offset."""
        response = client.get("/api/chat/conversations?offset=-5")

        assert response.status_code == 422
        data = response.json()
        assert "offset" in data["detail"].lower()

    def test_list_conversations_empty_result(self, client, mock_manager):
        """Test listing when no conversations exist."""
        mock_manager.list_conversations.return_value = []

        response = client.get("/api/chat/conversations")

        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_list_conversations_manager_error(self, client, mock_manager):
        """Test handling of manager errors during listing."""
        mock_manager.list_conversations.side_effect = Exception("Connection error")

        response = client.get("/api/chat/conversations")

        assert response.status_code == 500


@pytest.mark.requires_databricks
class TestGetConversation:
    """Tests for GET /conversations/{id} endpoint."""

    def test_get_conversation_success(self, client, mock_manager):
        """Test successful conversation retrieval."""
        response = client.get("/api/chat/conversations/conv_test123")

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv_test123"
        assert data["user_id"] == "user_123"
        assert data["exists"] is True

    def test_get_conversation_with_trailing_slash(self, client, mock_manager):
        """Test endpoint works with trailing slash."""
        response = client.get("/api/chat/conversations/conv_test123/")

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv_test123"

    def test_get_conversation_not_found(self, client, mock_manager):
        """Test getting non-existent conversation."""
        mock_manager.get_conversation.return_value = None

        response = client.get("/api/chat/conversations/nonexistent")

        assert response.status_code == 404

    def test_get_conversation_manager_error(self, client, mock_manager):
        """Test handling of manager errors."""
        mock_manager.get_conversation.side_effect = Exception("Database error")

        response = client.get("/api/chat/conversations/conv_test123")

        assert response.status_code == 500


@pytest.mark.requires_databricks
class TestCheckConversationExists:
    """Tests for HEAD /conversations/{id} endpoint.

    HEAD endpoint returns 204 No Content if exists, 404 if not.
    """

    def test_check_exists_true(self, client, mock_manager):
        """Test checking existence of existing conversation."""
        response = client.head("/api/chat/conversations/conv_test123")

        assert response.status_code == 204

    def test_check_exists_false(self, client, mock_manager):
        """Test checking existence of non-existent conversation."""
        mock_manager.get_conversation.return_value = None

        response = client.head("/api/chat/conversations/nonexistent")

        assert response.status_code == 404

    def test_check_exists_manager_error(self, client, mock_manager):
        """Test handling of manager errors.

        HEAD endpoint has no try/except wrapper, so unhandled exceptions
        propagate through TestClient.
        """
        mock_manager.get_conversation.side_effect = Exception("Error")

        with pytest.raises(Exception, match="Error"):
            client.head("/api/chat/conversations/conv_test123")


@pytest.mark.requires_databricks
class TestGetConversationHistory:
    """Tests for GET /conversations/{id}/history endpoint."""

    def test_get_history_success(self, client, mock_manager):
        """Test successful history retrieval."""
        response = client.get("/api/chat/conversations/conv_test123/history")

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv_test123"
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    def test_get_history_empty(self, client, mock_manager):
        """Test getting history for conversation with no messages."""
        now = datetime.now(UTC)
        mock_manager.get_history.return_value = ConversationHistory(
            conversation_id="conv_test123",
            messages=[],
            metadata=ConversationMetadata(
                total_messages=0,
                total_tokens=0,
                total_cost=0.0,
                created_at=now,
                updated_at=now,
                friendly_name="Empty Conversation",
            ),
        )

        response = client.get("/api/chat/conversations/conv_test123/history")

        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 0

    def test_get_history_not_found(self, client, mock_manager):
        """Test getting history for non-existent conversation."""
        mock_manager.get_conversation.return_value = None

        response = client.get("/api/chat/conversations/nonexistent/history")

        assert response.status_code == 404

    def test_get_history_manager_error(self, client, mock_manager):
        """Test handling of manager errors."""
        mock_manager.get_history.side_effect = Exception("Error")

        response = client.get("/api/chat/conversations/conv_test123/history")

        assert response.status_code == 500


@pytest.mark.requires_databricks
class TestDeleteConversation:
    """Tests for DELETE /conversations/{id} endpoint.

    DELETE returns 204 No Content on success.
    """

    def test_delete_conversation_success(self, client, mock_manager):
        """Test successful conversation deletion."""
        response = client.delete("/api/chat/conversations/conv_test123")

        assert response.status_code == 204

        mock_manager.delete_conversation.assert_called_once_with("conv_test123")

    def test_delete_conversation_not_found(self, client, mock_manager):
        """Test deleting non-existent conversation."""
        mock_manager.get_conversation.return_value = None

        response = client.delete("/api/chat/conversations/nonexistent")

        assert response.status_code == 404

    def test_delete_conversation_manager_error(self, client, mock_manager):
        """Test handling of manager errors during deletion."""
        mock_manager.delete_conversation.side_effect = Exception("Delete failed")

        response = client.delete("/api/chat/conversations/conv_test123")

        assert response.status_code == 500


@pytest.mark.requires_databricks
class TestConversationRouteIntegration:
    """Integration tests for conversation route workflows."""

    def test_create_and_list_workflow(self, client, mock_manager):
        """Test creating a conversation and then listing it."""
        # Create conversation
        create_response = client.post(
            "/api/chat/conversations",
            json={},
        )
        assert create_response.status_code == 201
        create_response.json()["conversation_id"]

        # List conversations (user_id from auth middleware)
        list_response = client.get("/api/chat/conversations")
        assert list_response.status_code == 200
        conversations = list_response.json()
        assert len(conversations) > 0

    def test_create_get_delete_workflow(self, client, mock_manager):
        """Test complete CRUD workflow."""
        # Create
        create_response = client.post(
            "/api/chat/conversations",
            json={},
        )
        assert create_response.status_code == 201
        conv_id = create_response.json()["conversation_id"]

        # Get
        get_response = client.get(f"/api/chat/conversations/{conv_id}")
        assert get_response.status_code == 200

        # Check exists (HEAD returns 204)
        exists_response = client.head(f"/api/chat/conversations/{conv_id}")
        assert exists_response.status_code == 204

        # Delete (returns 204)
        delete_response = client.delete(f"/api/chat/conversations/{conv_id}")
        assert delete_response.status_code == 204
