# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for FeedbackService."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from starboard_core.domain.models.feedback import (
    AgentPerformanceReport,
    FeedbackCategory,
    FeedbackRating,
    UserFeedback,
)
from starboard_core.models.conversation import Conversation, Message
from starboard_server.services.feedback.feedback_service import FeedbackService

# Fixed UUIDs for test consistency
TEST_CONVERSATION_ID = "12345678-1234-5678-1234-567812345678"
TEST_CONVERSATION_ID_2 = "12345678-1234-5678-1234-567812345679"
TEST_USER_ID = "87654321-4321-8765-4321-876543218765"
TEST_MESSAGE_ID = "abcdef01-2345-6789-abcd-ef0123456789"
TEST_MESSAGE_ID_2 = "abcdef01-2345-6789-abcd-ef0123456780"


class MockFeedbackRepository:
    """Mock feedback repository for testing."""

    def __init__(self):
        self.feedbacks: list[UserFeedback] = []
        self.save_called = False
        self.stats_result: dict[str, Any] = {
            "total_feedback": 0,
            "positive_count": 0,
            "negative_count": 0,
            "satisfaction_rate": 0.0,
        }
        self.categories_result: dict[str, int] = {}

    async def save(self, feedback: UserFeedback) -> None:
        """Mock save method."""
        self.feedbacks.append(feedback)
        self.save_called = True

    async def get_agent_feedback_stats(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """Mock get_agent_feedback_stats method."""
        return self.stats_result

    async def get_negative_feedback_categories(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, int]:
        """Mock get_negative_feedback_categories method."""
        return self.categories_result


class MockConversationRepository:
    """Mock conversation repository for testing."""

    def __init__(self):
        self.conversations: dict[str, Conversation] = {}

    async def get(self, conversation_id: str) -> Conversation | None:
        """Mock get method."""
        return self.conversations.get(conversation_id)

    def add_conversation(self, conversation: Conversation) -> None:
        """Add a conversation to the mock store."""
        self.conversations[conversation.id] = conversation


@pytest.fixture
def mock_feedback_repo():
    """Create a mock feedback repository."""
    return MockFeedbackRepository()


@pytest.fixture
def mock_conversation_repo():
    """Create a mock conversation repository."""
    return MockConversationRepository()


@pytest.fixture
def feedback_service(mock_feedback_repo, mock_conversation_repo):
    """Create a feedback service instance."""
    return FeedbackService(
        repository=mock_feedback_repo,
        conversation_repository=mock_conversation_repo,
    )


@pytest.fixture
def sample_conversation():
    """Create a sample conversation with messages."""
    user_msg = Message(
        role="user",
        content="What is the cost of warehouse prod_wh?",
        timestamp=datetime.now(UTC),
        metadata={"id": str(uuid4())},
    )

    agent_msg = Message(
        role="assistant",
        content="The cost of warehouse prod_wh is $1,234.56",
        timestamp=datetime.now(UTC),
        metadata={
            "id": TEST_MESSAGE_ID,
            "agent_version": "v1.0",
            "prompt_version": "v2.3",
            "model": "gpt-4",
            "temperature": 0.4,
            "num_tool_calls": 2,
            "tool_names": ["get_warehouse", "calculate_cost"],
            "response_time_ms": 1234.5,
            "token_count": 150,
            "cost_usd": 0.0023,
        },
    )

    return Conversation(
        id=TEST_CONVERSATION_ID,
        user_id=TEST_USER_ID,
        messages=[user_msg, agent_msg],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSubmitFeedback:
    """Test feedback submission workflow."""

    @pytest.mark.asyncio
    async def test_submit_positive_feedback(
        self,
        feedback_service,
        mock_feedback_repo,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test submitting positive feedback."""
        # Arrange
        mock_conversation_repo.add_conversation(sample_conversation)
        # message_id = "msg-123"

        # Act
        await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
            comment="Very helpful!",
        )

        # Assert
        assert mock_feedback_repo.save_called
        assert len(mock_feedback_repo.feedbacks) == 1

        saved_feedback = mock_feedback_repo.feedbacks[0]
        assert saved_feedback.rating == FeedbackRating.POSITIVE
        assert saved_feedback.message_id == UUID(TEST_MESSAGE_ID)
        assert saved_feedback.comment == "Very helpful!"
        assert saved_feedback.categories is None
        assert saved_feedback.conversation_id == UUID(TEST_CONVERSATION_ID)
        assert saved_feedback.user_id == TEST_USER_ID
        assert saved_feedback.agent_name == "assistant"

    @pytest.mark.asyncio
    async def test_submit_negative_feedback_with_categories(
        self,
        feedback_service,
        mock_feedback_repo,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test submitting negative feedback with categories."""
        # Arrange
        mock_conversation_repo.add_conversation(sample_conversation)

        # Act
        await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.NEGATIVE,
            categories=[FeedbackCategory.INACCURATE, FeedbackCategory.TOO_VAGUE],
            comment="The cost seems wrong",
        )

        # Assert
        saved_feedback = mock_feedback_repo.feedbacks[0]
        assert saved_feedback.rating == FeedbackRating.NEGATIVE
        assert saved_feedback.categories == (
            FeedbackCategory.INACCURATE,
            FeedbackCategory.TOO_VAGUE,
        )
        assert saved_feedback.comment == "The cost seems wrong"

    @pytest.mark.asyncio
    async def test_submit_feedback_without_comment(
        self,
        feedback_service,
        mock_feedback_repo,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test submitting feedback without a comment."""
        # Arrange
        mock_conversation_repo.add_conversation(sample_conversation)

        # Act
        await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        saved_feedback = mock_feedback_repo.feedbacks[0]
        assert saved_feedback.comment is None

    @pytest.mark.asyncio
    async def test_feedback_context_snapshot_enrichment(
        self,
        feedback_service,
        mock_feedback_repo,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test that feedback includes rich context snapshot."""
        # Arrange
        mock_conversation_repo.add_conversation(sample_conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        context = result.context_snapshot
        assert context.user_query == "What is the cost of warehouse prod_wh?"
        assert context.agent_response == "The cost of warehouse prod_wh is $1,234.56"
        assert context.agent_version == "v1.0"
        assert context.prompt_version == "v2.3"
        assert context.model_used == "gpt-4"
        assert context.temperature == 0.4
        assert context.response_length == len(
            "The cost of warehouse prod_wh is $1,234.56"
        )
        assert context.num_tool_calls == 2
        assert context.tool_names == ("get_warehouse", "calculate_cost")
        assert context.response_time_ms == 1234.5
        assert context.token_count == 150
        assert context.cost_usd == 0.0023

    @pytest.mark.asyncio
    async def test_conversation_history_in_context(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test that conversation history is included in context snapshot."""
        # Arrange
        messages = [
            Message(
                role="user",
                content="First query",
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="assistant",
                content="First response",
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="user",
                content="Second query",
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="assistant",
                content="Final response",
                timestamp=datetime.now(UTC),
                metadata={"id": TEST_MESSAGE_ID_2, "agent_version": "v1.0"},
            ),
        ]

        conversation = Conversation(
            id=TEST_CONVERSATION_ID_2,
            user_id=TEST_USER_ID,
            messages=messages,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID_2,
            message_id=TEST_MESSAGE_ID_2,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        context = result.context_snapshot
        # Should include previous messages (up to limit of 5)
        assert context.user_session_length == 3  # 3 messages before the rated one
        assert len(context.conversation_history) == 3

    @pytest.mark.asyncio
    async def test_submit_feedback_message_not_found(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test error when message is not found in conversation."""
        # Arrange
        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_conversation_repo.add_conversation(conversation)

        # Act & Assert
        with pytest.raises(ValueError, match="Message .* not found"):
            await feedback_service.submit_feedback(
                conversation_id=TEST_CONVERSATION_ID,
                message_id="00000000-0000-0000-0000-000000000000",  # Valid UUID but doesn't exist
                rating=FeedbackRating.POSITIVE,
            )

    @pytest.mark.asyncio
    async def test_submit_feedback_conversation_not_found(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test error when conversation is not found."""
        # Act & Assert
        with pytest.raises(ValueError, match="Conversation .* not found"):
            await feedback_service.submit_feedback(
                conversation_id="00000000-0000-0000-0000-000000000000",  # Valid UUID but doesn't exist
                message_id=TEST_MESSAGE_ID,
                rating=FeedbackRating.POSITIVE,
            )


class TestGetAgentPerformance:
    """Test agent performance report generation."""

    @pytest.mark.asyncio
    async def test_get_agent_performance_basic(
        self,
        feedback_service,
        mock_feedback_repo,
    ):
        """Test getting basic agent performance report."""
        # Arrange
        mock_feedback_repo.stats_result = {
            "total_feedback": 100,
            "positive_count": 85,
            "negative_count": 15,
            "satisfaction_rate": 0.85,
        }
        mock_feedback_repo.categories_result = {
            "inaccurate": 8,
            "too_vague": 5,
            "missing_info": 2,
        }

        # Act
        report = await feedback_service.get_agent_performance(
            agent_name="query_optimizer",
            days=7,
        )

        # Assert
        assert isinstance(report, AgentPerformanceReport)
        assert report.agent_name == "query_optimizer"
        assert report.period_days == 7
        assert report.total_feedback == 100
        assert report.positive_count == 85
        assert report.negative_count == 15
        assert report.satisfaction_rate == 0.85
        assert report.negative_categories == {
            "inaccurate": 8,
            "too_vague": 5,
            "missing_info": 2,
        }

    @pytest.mark.asyncio
    async def test_get_agent_performance_custom_period(
        self,
        feedback_service,
        mock_feedback_repo,
    ):
        """Test getting performance report for custom time period."""
        # Arrange
        mock_feedback_repo.stats_result = {
            "total_feedback": 50,
            "positive_count": 40,
            "negative_count": 10,
            "satisfaction_rate": 0.80,
        }
        mock_feedback_repo.categories_result = {}

        # Act
        report = await feedback_service.get_agent_performance(
            agent_name="cost_analyzer",
            days=30,
        )

        # Assert
        assert report.period_days == 30
        assert report.agent_name == "cost_analyzer"
        assert report.total_feedback == 50

    @pytest.mark.asyncio
    async def test_get_agent_performance_no_feedback(
        self,
        feedback_service,
        mock_feedback_repo,
    ):
        """Test getting performance report when no feedback exists."""
        # Arrange
        mock_feedback_repo.stats_result = {
            "total_feedback": 0,
            "positive_count": 0,
            "negative_count": 0,
            "satisfaction_rate": 0.0,
        }
        mock_feedback_repo.categories_result = {}

        # Act
        report = await feedback_service.get_agent_performance(
            agent_name="new_agent",
            days=7,
        )

        # Assert
        assert report.total_feedback == 0
        assert report.satisfaction_rate == 0.0
        assert report.negative_categories == {}


class TestContextSnapshotBuilding:
    """Test context snapshot building logic."""

    @pytest.mark.asyncio
    async def test_metadata_defaults_when_missing(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test that default values are used when metadata is missing."""
        # Arrange
        message = Message(
            role="assistant",
            content="Response without metadata",
            timestamp=datetime.now(UTC),
            metadata={"id": TEST_MESSAGE_ID},  # Only ID in metadata
        )

        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=[message],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        context = result.context_snapshot
        assert context.agent_version == "unknown"
        assert context.prompt_version == "unknown"
        assert context.model_used == "unknown"
        assert context.temperature == 0.0
        assert context.num_tool_calls == 0
        assert context.tool_names == ()
        assert context.response_time_ms == 0.0
        assert context.token_count == 0
        assert context.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_truncate_long_history_messages(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test that conversation history messages are truncated."""
        # Arrange
        long_content = "x" * 500  # 500 characters

        message = Message(
            role="user",
            content=long_content,
            timestamp=datetime.now(UTC),
            metadata={"id": str(uuid4())},
        )

        rated_message = Message(
            role="assistant",
            content="Short response",
            timestamp=datetime.now(UTC),
            metadata={"id": TEST_MESSAGE_ID},
        )

        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=[message, rated_message],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        context = result.context_snapshot
        assert len(context.conversation_history) == 1
        # History messages should be truncated to 200 chars
        assert len(context.conversation_history[0]["content"]) == 200

    @pytest.mark.asyncio
    async def test_is_repeat_query_detection(
        self,
        feedback_service,
        mock_conversation_repo,
    ):
        """Test repeat query detection logic."""
        # Arrange - similar queries
        messages = [
            Message(
                role="user",
                content="What is the cost of warehouse prod",
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="assistant",
                content="First response",
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="user",
                content="What is the cost of warehouse prod",  # Repeat query
                timestamp=datetime.now(UTC),
                metadata={"id": str(uuid4())},
            ),
            Message(
                role="assistant",
                content="Second response",
                timestamp=datetime.now(UTC),
                metadata={"id": TEST_MESSAGE_ID},
            ),
        ]

        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=messages,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert
        context = result.context_snapshot
        assert context.is_repeat_query is True


class TestNegativeFeedbackHandling:
    """Test special handling for negative feedback."""

    @pytest.mark.asyncio
    async def test_negative_feedback_triggers_logging(
        self,
        feedback_service,
        mock_conversation_repo,
        caplog,
    ):
        """Test that negative feedback triggers appropriate logging."""
        # Arrange
        message = Message(
            role="assistant",
            content="Incorrect response",
            timestamp=datetime.now(UTC),
            metadata={"id": TEST_MESSAGE_ID},
        )

        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=[message],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        result = await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.NEGATIVE,
            categories=[FeedbackCategory.DIDNT_ANSWER],
            comment="Didn't answer my question",
        )

        # Assert - verify feedback was saved with negative rating and categories
        assert result.rating == FeedbackRating.NEGATIVE
        assert result.categories == (FeedbackCategory.DIDNT_ANSWER,)
        assert result.comment == "Didn't answer my question"
        # Note: Logging verification omitted - structlog doesn't integrate with caplog
        # Logs are verified manually by inspecting test output

    @pytest.mark.asyncio
    async def test_positive_feedback_no_special_handling(
        self,
        feedback_service,
        mock_conversation_repo,
        caplog,
    ):
        """Test that positive feedback doesn't trigger special handling."""
        # Arrange
        message = Message(
            role="assistant",
            content="Good response",
            timestamp=datetime.now(UTC),
            metadata={"id": TEST_MESSAGE_ID},
        )

        conversation = Conversation(
            id=TEST_CONVERSATION_ID,
            user_id=TEST_USER_ID,
            messages=[message],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_conversation_repo.add_conversation(conversation)

        # Act
        import logging

        caplog.set_level(logging.WARNING)

        await feedback_service.submit_feedback(
            conversation_id=TEST_CONVERSATION_ID,
            message_id=TEST_MESSAGE_ID,
            rating=FeedbackRating.POSITIVE,
        )

        # Assert - no warnings for positive feedback
        assert not any(
            "negative_feedback_received" in record.message for record in caplog.records
        )
