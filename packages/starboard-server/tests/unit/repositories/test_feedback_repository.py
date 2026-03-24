"""
Unit tests for FeedbackRepository.

Tests cover:
- Saving feedback
- Retrieving feedback by message
- Retrieving feedback by conversation
- Aggregate feedback statistics
- Negative feedback category analysis
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starboard_core.domain.models.feedback import (
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)
from starboard_server.repositories.feedback_repository import PostgresFeedbackRepository


@pytest.fixture
def mock_db_client():
    """Mock database client."""
    mock_client = AsyncMock()
    return mock_client


@pytest.fixture
def feedback_repository(mock_db_client):
    """Create a FeedbackRepository with mocked dependencies."""
    return PostgresFeedbackRepository(db_client=mock_db_client)


@pytest.fixture
def sample_feedback_context():
    """Create a sample feedback context for testing."""
    return FeedbackContext(
        user_query="How do I optimize this query?",
        agent_response="Add an index on order_date",
        conversation_history=(),
        agent_version="1.0.0",
        prompt_version="v2",
        model_used="gpt-4",
        temperature=0.4,
        response_length=30,
        num_tool_calls=1,
        tool_names=("query_analyzer",),
        had_next_steps=True,
        response_time_ms=1200.5,
        token_count=150,
        cost_usd=0.002,
        user_session_length=3,
        is_repeat_query=False,
    )


@pytest.fixture
def sample_feedback(sample_feedback_context):
    """Create a sample UserFeedback for testing."""
    return UserFeedback(
        feedback_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        user_id="user-123",
        agent_name="query_optimizer",
        rating=FeedbackRating.POSITIVE,
        categories=None,
        comment="Very helpful!",
        timestamp=datetime.now(UTC),
        context_snapshot=sample_feedback_context,
    )


class TestSaveFeedback:
    """Tests for saving feedback."""

    @pytest.mark.asyncio
    async def test_save_positive_feedback(
        self, feedback_repository, mock_db_client, sample_feedback
    ):
        """Test saving positive feedback."""
        mock_db_client.execute = AsyncMock()

        await feedback_repository.save(sample_feedback)

        # Verify database was called
        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args

        # Verify SQL query structure
        assert "INSERT INTO user_feedback" in call_args[0][0]

        # Verify feedback_id was passed
        assert str(sample_feedback.feedback_id) in str(call_args[0])

    @pytest.mark.asyncio
    async def test_save_negative_feedback_with_categories(
        self, feedback_repository, mock_db_client, sample_feedback_context
    ):
        """Test saving negative feedback with categories."""
        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.NEGATIVE,
            categories=(FeedbackCategory.TOO_VAGUE, FeedbackCategory.MISSING_INFO),
            comment="Needs more detail",
            timestamp=datetime.now(UTC),
            context_snapshot=sample_feedback_context,
        )

        mock_db_client.execute = AsyncMock()

        await feedback_repository.save(feedback)

        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args

        # Verify categories are passed as list
        assert "categories" in str(call_args)

    @pytest.mark.asyncio
    async def test_save_feedback_without_comment(
        self, feedback_repository, mock_db_client, sample_feedback_context
    ):
        """Test saving feedback without optional comment."""
        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.POSITIVE,
            categories=None,
            comment=None,
            timestamp=datetime.now(UTC),
            context_snapshot=sample_feedback_context,
        )

        mock_db_client.execute = AsyncMock()

        await feedback_repository.save(feedback)

        mock_db_client.execute.assert_called_once()


class TestGetFeedback:
    """Tests for retrieving feedback."""

    @pytest.mark.asyncio
    async def test_get_by_message_found(
        self, feedback_repository, mock_db_client, sample_feedback
    ):
        """Test retrieving feedback by message ID when it exists."""
        mock_row = {
            "feedback_id": str(sample_feedback.feedback_id),
            "conversation_id": str(sample_feedback.conversation_id),
            "message_id": str(sample_feedback.message_id),
            "user_id": sample_feedback.user_id,
            "agent_name": sample_feedback.agent_name,
            "rating": sample_feedback.rating.value,
            "categories": None,
            "comment": sample_feedback.comment,
            "created_at": sample_feedback.timestamp,
            "context_snapshot": {
                "user_query": sample_feedback.context_snapshot.user_query,
                "agent_response": sample_feedback.context_snapshot.agent_response,
                "conversation_history": [],
                "agent_version": sample_feedback.context_snapshot.agent_version,
                "prompt_version": sample_feedback.context_snapshot.prompt_version,
                "model_used": sample_feedback.context_snapshot.model_used,
                "temperature": sample_feedback.context_snapshot.temperature,
                "response_length": sample_feedback.context_snapshot.response_length,
                "num_tool_calls": sample_feedback.context_snapshot.num_tool_calls,
                "tool_names": list(sample_feedback.context_snapshot.tool_names),
                "had_next_steps": sample_feedback.context_snapshot.had_next_steps,
                "response_time_ms": sample_feedback.context_snapshot.response_time_ms,
                "token_count": sample_feedback.context_snapshot.token_count,
                "cost_usd": sample_feedback.context_snapshot.cost_usd,
                "user_session_length": sample_feedback.context_snapshot.user_session_length,
                "is_repeat_query": sample_feedback.context_snapshot.is_repeat_query,
            },
        }

        mock_db_client.fetch_one = AsyncMock(return_value=mock_row)

        result = await feedback_repository.get_by_message(
            str(sample_feedback.message_id)
        )

        assert result is not None
        assert result.feedback_id == sample_feedback.feedback_id
        assert result.rating == sample_feedback.rating
        mock_db_client.fetch_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_message_not_found(self, feedback_repository, mock_db_client):
        """Test retrieving feedback when none exists for message."""
        mock_db_client.fetch_one = AsyncMock(return_value=None)

        result = await feedback_repository.get_by_message("nonexistent-message")

        assert result is None
        mock_db_client.fetch_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_conversation(
        self, feedback_repository, mock_db_client, sample_feedback
    ):
        """Test retrieving all feedback for a conversation."""
        mock_rows = [
            {
                "feedback_id": str(uuid4()),
                "conversation_id": str(sample_feedback.conversation_id),
                "message_id": str(uuid4()),
                "user_id": "user-123",
                "agent_name": "query_optimizer",
                "rating": "positive",
                "categories": None,
                "comment": "Great!",
                "created_at": datetime.now(UTC),
                "context_snapshot": {
                    "user_query": "Test query",
                    "agent_response": "Test response",
                    "conversation_history": [],
                    "agent_version": "1.0.0",
                    "prompt_version": "v1",
                    "model_used": "gpt-4",
                    "temperature": 0.4,
                    "response_length": 13,
                    "num_tool_calls": 0,
                    "tool_names": [],
                    "had_next_steps": False,
                    "response_time_ms": 1000.0,
                    "token_count": 100,
                    "cost_usd": 0.001,
                    "user_session_length": 1,
                    "is_repeat_query": False,
                },
            },
            {
                "feedback_id": str(uuid4()),
                "conversation_id": str(sample_feedback.conversation_id),
                "message_id": str(uuid4()),
                "user_id": "user-123",
                "agent_name": "query_optimizer",
                "rating": "negative",
                "categories": ["too_vague"],
                "comment": "Too vague",
                "created_at": datetime.now(UTC),
                "context_snapshot": {
                    "user_query": "Test query 2",
                    "agent_response": "Test response 2",
                    "conversation_history": [],
                    "agent_version": "1.0.0",
                    "prompt_version": "v1",
                    "model_used": "gpt-4",
                    "temperature": 0.4,
                    "response_length": 15,
                    "num_tool_calls": 0,
                    "tool_names": [],
                    "had_next_steps": False,
                    "response_time_ms": 1000.0,
                    "token_count": 100,
                    "cost_usd": 0.001,
                    "user_session_length": 2,
                    "is_repeat_query": False,
                },
            },
        ]

        mock_db_client.fetch_all = AsyncMock(return_value=mock_rows)

        result = await feedback_repository.get_by_conversation(
            str(sample_feedback.conversation_id)
        )

        assert len(result) == 2
        assert result[0].rating == FeedbackRating.POSITIVE
        assert result[1].rating == FeedbackRating.NEGATIVE
        mock_db_client.fetch_all.assert_called_once()


class TestFeedbackStats:
    """Tests for feedback statistics and analytics."""

    @pytest.mark.asyncio
    async def test_get_agent_feedback_stats(self, feedback_repository, mock_db_client):
        """Test retrieving aggregate feedback statistics for an agent."""
        mock_row = {
            "total_feedback": 100,
            "positive_count": 70,
            "negative_count": 30,
            "satisfaction_rate": 0.7,
        }

        mock_db_client.fetch_one = AsyncMock(return_value=mock_row)

        start_date = datetime.now(UTC) - timedelta(days=7)
        end_date = datetime.now(UTC)

        result = await feedback_repository.get_agent_feedback_stats(
            agent_name="query_optimizer",
            start_date=start_date,
            end_date=end_date,
        )

        assert result["total_feedback"] == 100
        assert result["positive_count"] == 70
        assert result["negative_count"] == 30
        assert result["satisfaction_rate"] == 0.7
        mock_db_client.fetch_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_negative_feedback_categories(
        self, feedback_repository, mock_db_client
    ):
        """Test retrieving breakdown of negative feedback categories."""
        mock_rows = [
            {"category": "too_vague", "count": 15},
            {"category": "missing_info", "count": 10},
            {"category": "inaccurate", "count": 5},
        ]

        mock_db_client.fetch_all = AsyncMock(return_value=mock_rows)

        start_date = datetime.now(UTC) - timedelta(days=7)
        end_date = datetime.now(UTC)

        result = await feedback_repository.get_negative_feedback_categories(
            agent_name="query_optimizer",
            start_date=start_date,
            end_date=end_date,
        )

        assert result["too_vague"] == 15
        assert result["missing_info"] == 10
        assert result["inaccurate"] == 5
        mock_db_client.fetch_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_agent_feedback_stats_no_feedback(
        self, feedback_repository, mock_db_client
    ):
        """Test getting stats when agent has no feedback."""
        mock_row = {
            "total_feedback": 0,
            "positive_count": 0,
            "negative_count": 0,
            "satisfaction_rate": 0.0,
        }

        mock_db_client.fetch_one = AsyncMock(return_value=mock_row)

        start_date = datetime.now(UTC) - timedelta(days=7)
        end_date = datetime.now(UTC)

        result = await feedback_repository.get_agent_feedback_stats(
            agent_name="nonexistent_agent",
            start_date=start_date,
            end_date=end_date,
        )

        assert result["total_feedback"] == 0
        assert result["satisfaction_rate"] == 0.0
