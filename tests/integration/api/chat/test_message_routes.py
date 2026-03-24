"""
Integration tests for message routes.

Tests message handling, input injection, solicitation responses, and checkpoints.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starboard_server.api.chat.message_routes import (
    get_checkpoints,
    inject_input,
    respond_to_solicitation,
    send_message,
)
from starboard_server.api.models import (
    CheckpointInfo,
    InjectInputRequest,
    MessageResponse,
    RespondToSolicitationRequest,
    SendMessageRequest,
)


@pytest.fixture
def mock_manager():
    """Mock MultiAgentConversationManager."""
    manager = AsyncMock()

    # Setup return values
    now = datetime.now(UTC)

    # get_conversation (used by ownership verification)
    manager.get_conversation.return_value = {
        "conversation_id": "conv_123",
        "user_id": "user_123",
        "exists": True,
    }

    # send_message response
    manager.enqueue_message.return_value = MessageResponse(
        message_id="msg_123",
        conversation_id="conv_123",
        trace_id="trace_123",
        status="pending",
    )

    # inject_input response
    mock_user_input = Mock()
    mock_user_input.input_id = "input_123"
    mock_user_input.checkpoint_id = "ckpt_123"
    manager.inject_input.return_value = mock_user_input

    # respond_to_solicitation response
    mock_solicitation_response = Mock()
    mock_solicitation_response.user_input = Mock()
    mock_solicitation_response.user_input.input_id = "resp_123"
    mock_solicitation_response.solicitation_id = "sol_123"
    mock_solicitation_response.response_time_seconds = 1.234
    manager.respond_to_solicitation.return_value = mock_solicitation_response

    # get_checkpoints response
    checkpoint_info = CheckpointInfo(
        checkpoint_id="ckpt_001",
        step_number=1,
        checkpoint_type="reasoning_step",
        timestamp=now,
        can_interrupt=True,
    )
    manager.get_checkpoints.return_value = [checkpoint_info]

    return manager


@pytest.fixture
def mock_http_request():
    """Mock FastAPI Request object."""
    request = Mock()
    request.client = Mock()
    request.client.host = "127.0.0.1"
    request.state = Mock()
    request.state.user = Mock()
    request.state.user.id = "user_123"
    return request


@pytest.fixture
def mock_container():
    """Mock Container object."""
    container = Mock()
    container.cache_factory = Mock()
    cache = AsyncMock()
    container.cache_factory.get_or_create.return_value = cache
    return container


class TestSendMessage:
    """Tests for send_message endpoint."""

    @pytest.mark.asyncio
    async def test_send_message_success(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test successful message send."""
        request = SendMessageRequest(
            content="What is the status of job 12345?",
            attachments=None,
            metadata={"source": "ui"},
        )

        result = await send_message(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
            container=mock_container,
        )

        assert result.message_id == "msg_123"
        assert result.conversation_id == "conv_123"
        assert result.trace_id == "trace_123"
        assert result.status == "pending"

        mock_manager.enqueue_message.assert_called_once_with(
            conversation_id="conv_123",
            content="What is the status of job 12345?",
            attachments=None,
            metadata={"source": "ui"},
        )

    @pytest.mark.asyncio
    async def test_send_message_with_attachments(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test sending message with attachments."""
        request = SendMessageRequest(
            content="Analyze this data",
            attachments=[
                {
                    "filename": "data.csv",
                    "size": 1024,
                    "content": "sample,data\n1,2\n3,4",
                }
            ],
            metadata={},
        )

        result = await send_message(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
            container=mock_container,
        )

        assert result is not None
        mock_manager.enqueue_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_conversation_not_found(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test sending message to non-existent conversation."""
        mock_manager.enqueue_message.side_effect = ValueError("Conversation not found")

        request = SendMessageRequest(
            content="Hello",
            attachments=None,
            metadata={},
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_message(
                conversation_id="nonexistent",
                http_request=mock_http_request,
                request=request,
                manager=mock_manager,
                container=mock_container,
            )

        assert exc_info.value.status_code == 404
        assert "Conversation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_send_message_manager_error(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test handling of manager errors."""
        mock_manager.enqueue_message.side_effect = Exception("Internal error")

        request = SendMessageRequest(
            content="Hello",
            attachments=None,
            metadata={},
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_message(
                conversation_id="conv_123",
                http_request=mock_http_request,
                request=request,
                manager=mock_manager,
                container=mock_container,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to enqueue message" in exc_info.value.detail


class TestInjectInput:
    """Tests for inject_input endpoint."""

    @pytest.mark.asyncio
    async def test_inject_input_success(self, mock_manager, mock_http_request):
        """Test successful input injection."""
        request = InjectInputRequest(
            input_type="context_injection",
            content="Focus on partition pruning",
            checkpoint_id="ckpt_123",
            metadata={},
        )

        result = await inject_input(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
        )

        assert result.input_id == "input_123"
        assert result.status == "accepted"
        assert result.checkpoint_id == "ckpt_123"
        assert "next checkpoint" in result.message

        mock_manager.inject_input.assert_called_once_with(
            conversation_id="conv_123",
            input_type="context_injection",
            content="Focus on partition pruning",
            checkpoint_id="ckpt_123",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_inject_input_without_checkpoint(
        self, mock_manager, mock_http_request
    ):
        """Test injecting input without specifying checkpoint."""
        request = InjectInputRequest(
            input_type="replan",
            content="Change strategy",
            checkpoint_id=None,
            metadata={},
        )

        result = await inject_input(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
        )

        assert result is not None
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_inject_input_conversation_not_processing(
        self, mock_manager, mock_http_request
    ):
        """Test injecting input when conversation not processing."""
        mock_manager.inject_input.side_effect = ValueError(
            "Conversation not actively processing"
        )

        request = InjectInputRequest(
            input_type="context_injection",
            content="Test",
            checkpoint_id=None,
            metadata={},
        )

        with pytest.raises(HTTPException) as exc_info:
            await inject_input(
                conversation_id="conv_123",
                http_request=mock_http_request,
                request=request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 400
        assert "not actively processing" in exc_info.value.detail


class TestRespondToSolicitation:
    """Tests for respond_to_solicitation endpoint."""

    @pytest.mark.asyncio
    async def test_respond_to_solicitation_success(
        self, mock_manager, mock_http_request
    ):
        """Test successful solicitation response."""
        request = RespondToSolicitationRequest(
            solicitation_id="sol_123",
            content="Service principal: sp-prod-databricks",
            metadata={},
        )

        result = await respond_to_solicitation(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
        )

        assert result.response_id == "resp_123"
        assert result.status == "accepted"
        assert result.solicitation_id == "sol_123"
        assert result.response_time_ms == 1234.0

        mock_manager.respond_to_solicitation.assert_called_once_with(
            conversation_id="conv_123",
            solicitation_id="sol_123",
            content="Service principal: sp-prod-databricks",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_respond_to_solicitation_with_metadata(
        self, mock_manager, mock_http_request
    ):
        """Test solicitation response with metadata."""
        request = RespondToSolicitationRequest(
            solicitation_id="sol_123",
            content="Answer",
            metadata={"confidence": 0.95},
        )

        result = await respond_to_solicitation(
            conversation_id="conv_123",
            http_request=mock_http_request,
            request=request,
            manager=mock_manager,
        )

        assert result is not None
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_respond_to_solicitation_not_found(
        self, mock_manager, mock_http_request
    ):
        """Test responding to non-existent solicitation."""
        mock_manager.respond_to_solicitation.side_effect = ValueError(
            "Solicitation not found or expired"
        )

        request = RespondToSolicitationRequest(
            solicitation_id="nonexistent",
            content="Answer",
            metadata={},
        )

        with pytest.raises(HTTPException) as exc_info:
            await respond_to_solicitation(
                conversation_id="conv_123",
                http_request=mock_http_request,
                request=request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 404
        assert "not found or expired" in exc_info.value.detail


class TestGetCheckpoints:
    """Tests for get_checkpoints endpoint."""

    @pytest.mark.asyncio
    async def test_get_checkpoints_success(self, mock_manager, mock_http_request):
        """Test successful checkpoint retrieval."""
        result = await get_checkpoints(
            conversation_id="conv_123",
            request=mock_http_request,
            manager=mock_manager,
            limit=10,
        )

        assert len(result.checkpoints) == 1
        assert result.checkpoints[0].checkpoint_id == "ckpt_001"
        assert result.checkpoints[0].step_number == 1
        assert result.checkpoints[0].checkpoint_type == "reasoning_step"
        assert result.checkpoints[0].can_interrupt is True
        assert result.active_checkpoint == "ckpt_001"

        mock_manager.get_checkpoints.assert_called_once_with(
            conversation_id="conv_123",
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_get_checkpoints_with_custom_limit(
        self, mock_manager, mock_http_request
    ):
        """Test checkpoint retrieval with custom limit."""
        result = await get_checkpoints(
            conversation_id="conv_123",
            request=mock_http_request,
            manager=mock_manager,
            limit=5,
        )

        assert result is not None
        mock_manager.get_checkpoints.assert_called_once_with(
            conversation_id="conv_123",
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_get_checkpoints_empty_result(self, mock_manager, mock_http_request):
        """Test checkpoint retrieval with no checkpoints."""
        mock_manager.get_checkpoints.return_value = []

        result = await get_checkpoints(
            conversation_id="conv_123",
            request=mock_http_request,
            manager=mock_manager,
            limit=10,
        )

        assert len(result.checkpoints) == 0
        assert result.active_checkpoint is None

    @pytest.mark.asyncio
    async def test_get_checkpoints_invalid_limit_too_low(
        self, mock_manager, mock_http_request
    ):
        """Test checkpoint retrieval with limit < 1."""
        with pytest.raises(HTTPException) as exc_info:
            await get_checkpoints(
                conversation_id="conv_123",
                request=mock_http_request,
                manager=mock_manager,
                limit=0,
            )

        assert exc_info.value.status_code == 400
        assert "limit must be between 1 and 50" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_checkpoints_invalid_limit_too_high(
        self, mock_manager, mock_http_request
    ):
        """Test checkpoint retrieval with limit > 50."""
        with pytest.raises(HTTPException) as exc_info:
            await get_checkpoints(
                conversation_id="conv_123",
                request=mock_http_request,
                manager=mock_manager,
                limit=100,
            )

        assert exc_info.value.status_code == 400
        assert "limit must be between 1 and 50" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_checkpoints_conversation_not_found(
        self, mock_manager, mock_http_request
    ):
        """Test checkpoint retrieval for non-existent conversation."""
        mock_manager.get_checkpoints.side_effect = ValueError("Conversation not found")

        with pytest.raises(HTTPException) as exc_info:
            await get_checkpoints(
                conversation_id="nonexistent",
                request=mock_http_request,
                manager=mock_manager,
                limit=10,
            )

        assert exc_info.value.status_code == 404
        assert "Conversation not found" in exc_info.value.detail


class TestMessageRoutesIntegration:
    """Integration tests spanning multiple message route operations."""

    @pytest.mark.asyncio
    async def test_message_injection_workflow(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test workflow: send message → inject input → respond to solicitation."""
        # Send message
        send_req = SendMessageRequest(
            content="Analyze job performance", attachments=None, metadata={}
        )
        msg_result = await send_message(
            "conv_123", mock_http_request, send_req, mock_manager, mock_container
        )
        assert msg_result.status == "pending"

        # Inject context mid-reasoning
        inject_req = InjectInputRequest(
            input_type="context_injection",
            content="Focus on memory usage",
            checkpoint_id=None,
            metadata={},
        )
        inject_result = await inject_input(
            "conv_123", mock_http_request, inject_req, mock_manager
        )
        assert inject_result.status == "accepted"

        # Respond to solicitation (agent asks question)
        sol_req = RespondToSolicitationRequest(
            solicitation_id="sol_123",
            content="Job ID: 987654",
            metadata={},
        )
        sol_result = await respond_to_solicitation(
            "conv_123", mock_http_request, sol_req, mock_manager
        )
        assert sol_result.status == "accepted"

    @pytest.mark.asyncio
    async def test_checkpoint_monitoring_workflow(
        self, mock_manager, mock_http_request, mock_container
    ):
        """Test workflow: send message → monitor checkpoints → inject at specific checkpoint."""
        # Send message
        send_req = SendMessageRequest(
            content="Start analysis", attachments=None, metadata={}
        )
        await send_message(
            "conv_123", mock_http_request, send_req, mock_manager, mock_container
        )

        # Monitor checkpoints
        ckpt_result = await get_checkpoints(
            "conv_123", mock_http_request, mock_manager, limit=10
        )
        assert len(ckpt_result.checkpoints) > 0

        # Inject at specific checkpoint
        target_checkpoint = ckpt_result.checkpoints[0].checkpoint_id
        inject_req = InjectInputRequest(
            input_type="replan",
            content="Change approach",
            checkpoint_id=target_checkpoint,
            metadata={},
        )
        inject_result = await inject_input(
            "conv_123", mock_http_request, inject_req, mock_manager
        )
        # Verify injection was successful (checkpoint_id may differ in mock)
        assert inject_result.status == "accepted"
        assert inject_result.checkpoint_id is not None
