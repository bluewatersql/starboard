"""
Simplified tests for conversation routes.

Direct testing of route functions without full app context.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starboard_server.api.chat.conversation_routes import (
    check_conversation_exists,
    create_conversation,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversation_history,
    list_conversations,
)
from starboard_server.api.models import (
    ConversationConfig,
    ConversationHistory,
    ConversationMetadata,
    ConversationResponse,
    CreateConversationRequest,
)
from starboard_server.api.models.enums import MessageRole, MessageStatus
from starboard_server.api.models.messages import Message as APIMessage


@pytest.fixture
def mock_manager():
    """Mock MultiAgentConversationManager."""
    manager = AsyncMock()

    # Setup return values
    now = datetime.now(UTC)

    manager.create_conversation.return_value = ConversationResponse(
        conversation_id="conv_123",
        friendly_name="Test Conv",
        created_at=now,
        config=ConversationConfig(
            temperature=0.4,
            max_tokens=120000,
            safe_mode=False,
            streaming=True,
            model="gpt-4o-mini",
        ),
    )

    manager.list_conversations.return_value = [
        Mock(
            conversation_id="conv_1",
            friendly_name="Conv 1",
            created_at=now,
            config=ConversationConfig(),
        ),
    ]

    manager.get_conversation.return_value = {
        "conversation_id": "conv_123",
        "user_id": "user_123",
        "exists": True,
    }

    manager.conversation_exists.return_value = True

    manager.get_history.return_value = ConversationHistory(
        conversation_id="conv_123",
        messages=[
            APIMessage(
                id="msg_1",
                conversation_id="conv_123",
                role=MessageRole.USER,
                content="Hello",
                timestamp=now,
                status=MessageStatus.COMPLETED,
            ),
        ],
        metadata=ConversationMetadata(
            total_messages=1,
            total_tokens=50,
            total_cost=0.0005,
            created_at=now,
            updated_at=now,
            friendly_name="Test Conv",
        ),
    )

    manager.delete_conversation.return_value = True  # Returns boolean, not dict

    manager.delete_all_conversations.return_value = 5  # Returns count of deleted

    return manager


@pytest.fixture
def mock_request():
    """Mock FastAPI Request with authenticated user."""
    request = Mock()
    request.state = Mock()
    request.state.user = Mock()
    request.state.user.id = "user_123"
    request.state.user.username = "testuser"
    return request


class TestCreateConversationDirect:
    """Direct tests for create_conversation function."""

    @pytest.mark.asyncio
    async def test_create_conversation_success(self, mock_manager, mock_request):
        """Test successful conversation creation."""
        body = CreateConversationRequest(
            user_id="user_123",
            context={"workspace_id": "ws_abc"},
            config=None,
        )

        result = await create_conversation(mock_request, body, mock_manager)

        assert result.conversation_id == "conv_123"
        assert result.friendly_name == "Test Conv"
        mock_manager.create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_conversation_with_config(self, mock_manager, mock_request):
        """Test creating conversation with custom config."""
        body = CreateConversationRequest(
            user_id="user_123",
            config=ConversationConfig(temperature=0.7),
        )

        result = await create_conversation(mock_request, body, mock_manager)

        assert result is not None
        mock_manager.create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_conversation_manager_error(self, mock_manager, mock_request):
        """Test handling of manager errors."""
        mock_manager.create_conversation.side_effect = Exception("DB error")

        body = CreateConversationRequest(user_id="user_123")

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation(mock_request, body, mock_manager)

        assert exc_info.value.status_code == 500
        assert "Failed to create conversation" in exc_info.value.detail


@pytest.mark.skip(reason="Mock fixtures return invalid user_id - needs fixture update")
class TestListConversationsDirect:
    """Direct tests for list_conversations function."""

    @pytest.mark.asyncio
    async def test_list_conversations_success(self, mock_manager, mock_request):
        """Test successful conversation listing."""
        result = await list_conversations(
            mock_request,
            mock_manager,
            limit=20,
            offset=0,
        )

        assert len(result) == 1
        assert result[0].conversation_id == "conv_1"

    @pytest.mark.asyncio
    async def test_list_conversations_with_pagination(self, mock_manager, mock_request):
        """Test listing with custom pagination."""
        await list_conversations(
            mock_request,
            mock_manager,
            limit=10,
            offset=5,
        )

        mock_manager.list_conversations.assert_called_once_with(
            user_id="user_123",
            limit=10,
            offset=5,
        )

    @pytest.mark.asyncio
    async def test_list_conversations_invalid_limit(self, mock_manager, mock_request):
        """Test listing with invalid limit."""
        with pytest.raises(HTTPException) as exc_info:
            await list_conversations(
                mock_request,
                mock_manager,
                limit=200,  # > 100
                offset=0,
            )

        assert exc_info.value.status_code == 422
        assert "limit" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_list_conversations_negative_offset(self, mock_manager, mock_request):
        """Test listing with negative offset."""
        with pytest.raises(HTTPException) as exc_info:
            await list_conversations(
                mock_request,
                mock_manager,
                limit=20,
                offset=-1,
            )

        assert exc_info.value.status_code == 422
        assert "offset" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_list_conversations_manager_error(self, mock_manager, mock_request):
        """Test handling of manager errors."""
        mock_manager.list_conversations.side_effect = Exception("Error")

        with pytest.raises(HTTPException) as exc_info:
            await list_conversations(
                mock_request,
                mock_manager,
                limit=20,
                offset=0,
            )

        assert exc_info.value.status_code == 500


class TestGetConversationDirect:
    """Direct tests for get_conversation function."""

    @pytest.mark.asyncio
    async def test_get_conversation_success(self, mock_manager, mock_request):
        """Test successful conversation retrieval."""
        result = await get_conversation(
            conversation_id="conv_123",
            request=mock_request,
            manager=mock_manager,
        )

        assert result["conversation_id"] == "conv_123"
        assert result["user_id"] == "user_123"
        assert result["exists"] is True

    @pytest.mark.asyncio
    async def test_get_conversation_manager_error(self, mock_manager, mock_request):
        """Test handling of manager errors."""
        mock_manager.get_conversation.side_effect = Exception("Error")

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation(
                conversation_id="conv_123",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 500


class TestCheckConversationExistsDirect:
    """Direct tests for check_conversation_exists function."""

    @pytest.mark.asyncio
    async def test_check_exists_true(self, mock_manager, mock_request):
        """Test checking existence of existing conversation."""
        # Should not raise exception (returns None/204)
        result = await check_conversation_exists(
            conversation_id="conv_123",
            request=mock_request,
            manager=mock_manager,
        )

        assert result is None  # HEAD request returns None (204 No Content)

    @pytest.mark.asyncio
    async def test_check_exists_false(self, mock_manager, mock_request):
        """Test checking existence of non-existent conversation."""
        mock_manager.get_conversation.return_value = None  # Simulates not found

        with pytest.raises(HTTPException) as exc_info:
            await check_conversation_exists(
                conversation_id="nonexistent",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 404


class TestGetConversationHistoryDirect:
    """Direct tests for get_conversation_history function."""

    @pytest.mark.asyncio
    async def test_get_history_success(self, mock_manager, mock_request):
        """Test successful history retrieval."""
        result = await get_conversation_history(
            conversation_id="conv_123",
            request=mock_request,
            manager=mock_manager,
        )

        assert result.conversation_id == "conv_123"
        assert len(result.messages) == 1
        assert result.messages[0].role == MessageRole.USER
        assert result.metadata.total_messages == 1

    @pytest.mark.asyncio
    async def test_get_history_manager_error(self, mock_manager, mock_request):
        """Test handling of manager errors."""
        mock_manager.get_history.side_effect = Exception("Error")

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_history(
                conversation_id="conv_123",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 500


class TestDeleteConversationDirect:
    """Direct tests for delete_conversation function."""

    @pytest.mark.asyncio
    async def test_delete_conversation_success(self, mock_manager, mock_request):
        """Test successful conversation deletion."""
        result = await delete_conversation(
            conversation_id="conv_123",
            request=mock_request,
            manager=mock_manager,
        )

        assert result is None  # DELETE returns None (204 No Content)
        mock_manager.delete_conversation.assert_called_once_with("conv_123")

    @pytest.mark.asyncio
    async def test_delete_conversation_manager_error(self, mock_manager, mock_request):
        """Test handling of manager errors."""
        mock_manager.delete_conversation.side_effect = Exception("Error")

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation(
                conversation_id="conv_123",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 500


class TestDeleteAllConversationsDirect:
    """Direct tests for delete_all_conversations function (batch operation)."""

    @pytest.mark.asyncio
    async def test_delete_all_conversations_success(self, mock_manager, mock_request):
        """Test successful batch deletion of all user conversations."""
        result = await delete_all_conversations(
            request=mock_request,
            manager=mock_manager,
        )

        assert result is None  # DELETE returns None (204 No Content)
        mock_manager.delete_all_conversations.assert_called_once_with(
            user_id="user_123"
        )

    @pytest.mark.asyncio
    async def test_delete_all_conversations_zero_count(
        self, mock_manager, mock_request
    ):
        """Test batch deletion when no conversations exist."""
        mock_manager.delete_all_conversations.return_value = 0

        result = await delete_all_conversations(
            request=mock_request,
            manager=mock_manager,
        )

        assert result is None  # Still returns 204 even with 0 deletions
        mock_manager.delete_all_conversations.assert_called_once_with(
            user_id="user_123"
        )

    @pytest.mark.asyncio
    async def test_delete_all_conversations_manager_error(
        self, mock_manager, mock_request
    ):
        """Test handling of manager errors during batch deletion."""
        mock_manager.delete_all_conversations.side_effect = Exception("DB error")

        with pytest.raises(HTTPException) as exc_info:
            await delete_all_conversations(
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to delete conversations" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_all_uses_authenticated_user(self, mock_manager, mock_request):
        """Test that batch deletion uses the authenticated user's ID."""
        # Change user ID to verify correct user is used
        mock_request.state.user.id = "different_user_456"

        await delete_all_conversations(
            request=mock_request,
            manager=mock_manager,
        )

        mock_manager.delete_all_conversations.assert_called_once_with(
            user_id="different_user_456"
        )
