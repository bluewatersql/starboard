"""
Unit tests for feedback domain models.

Tests cover:
- FeedbackRating enum
- FeedbackCategory enum
- FeedbackContext dataclass
- UserFeedback dataclass
- AgentPerformanceReport dataclass
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_core import ValidationError
from starboard_core.domain.models.feedback import (
    AgentPerformanceReport,
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)


class TestFeedbackRating:
    """Tests for FeedbackRating enum."""

    def test_rating_values(self) -> None:
        """Test that rating enum has expected values."""
        assert FeedbackRating.POSITIVE.value == "positive"
        assert FeedbackRating.NEGATIVE.value == "negative"

    def test_rating_from_string(self) -> None:
        """Test creating rating from string value."""
        rating = FeedbackRating("positive")
        assert rating == FeedbackRating.POSITIVE

        rating = FeedbackRating("negative")
        assert rating == FeedbackRating.NEGATIVE

    def test_rating_invalid_value(self) -> None:
        """Test that invalid rating value raises error."""
        with pytest.raises(ValueError):
            FeedbackRating("neutral")


class TestFeedbackCategory:
    """Tests for FeedbackCategory enum."""

    def test_category_values(self) -> None:
        """Test that category enum has all expected values."""
        assert FeedbackCategory.INACCURATE.value == "inaccurate"
        assert FeedbackCategory.MISSING_INFO.value == "missing_info"
        assert FeedbackCategory.TOO_VAGUE.value == "too_vague"
        assert FeedbackCategory.DIDNT_ANSWER.value == "didnt_answer"
        assert FeedbackCategory.TOO_LONG.value == "too_long"
        assert FeedbackCategory.WRONG_AGENT.value == "wrong_agent"
        assert FeedbackCategory.OTHER.value == "other"

    def test_category_from_string(self) -> None:
        """Test creating category from string value."""
        category = FeedbackCategory("inaccurate")
        assert category == FeedbackCategory.INACCURATE

    def test_all_categories_unique(self) -> None:
        """Test that all category values are unique."""
        values = [cat.value for cat in FeedbackCategory]
        assert len(values) == len(set(values))


class TestFeedbackContext:
    """Tests for FeedbackContext dataclass."""

    def test_context_creation(self) -> None:
        """Test creating a feedback context."""
        context = FeedbackContext(
            user_query="How do I optimize this query?",
            agent_response="You can add an index on the order_date column.",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v2",
            model_used="gpt-4",
            temperature=0.4,
            response_length=45,
            num_tool_calls=1,
            tool_names=("query_analyzer",),
            had_next_steps=True,
            response_time_ms=1200.5,
            token_count=150,
            cost_usd=0.002,
            user_session_length=3,
            is_repeat_query=False,
        )

        assert context.user_query == "How do I optimize this query?"
        assert (
            context.agent_response == "You can add an index on the order_date column."
        )
        assert context.model_used == "gpt-4"
        assert context.temperature == 0.4
        assert context.num_tool_calls == 1
        assert context.had_next_steps is True

    def test_context_immutable(self) -> None:
        """Test that feedback context is immutable."""
        context = FeedbackContext(
            user_query="Test query",
            agent_response="Test response",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=13,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=1,
            is_repeat_query=False,
        )

        with pytest.raises((ValidationError, AttributeError)):
            context.model_used = "gpt-3.5"  # type: ignore

    def test_context_with_conversation_history(self) -> None:
        """Test context with conversation history."""
        history = (
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
        )

        context = FeedbackContext(
            user_query="Second message",
            agent_response="Second response",
            conversation_history=history,
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=15,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=2,
            is_repeat_query=False,
        )

        assert len(context.conversation_history) == 2
        assert context.conversation_history[0]["role"] == "user"


class TestUserFeedback:
    """Tests for UserFeedback dataclass."""

    def test_feedback_creation_positive(self) -> None:
        """Test creating positive feedback."""
        now = datetime.now(UTC)
        context = FeedbackContext(
            user_query="Test query",
            agent_response="Test response",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=13,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=1,
            is_repeat_query=False,
        )

        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.POSITIVE,
            categories=None,
            comment="Very helpful!",
            timestamp=now,
            context_snapshot=context,
        )

        assert feedback.rating == FeedbackRating.POSITIVE
        assert feedback.comment == "Very helpful!"
        assert feedback.categories is None
        assert feedback.agent_name == "query_optimizer"

    def test_feedback_creation_negative_with_categories(self) -> None:
        """Test creating negative feedback with categories."""
        now = datetime.now(UTC)
        context = FeedbackContext(
            user_query="Test query",
            agent_response="Test response",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=13,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=1,
            is_repeat_query=False,
        )

        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.NEGATIVE,
            categories=(FeedbackCategory.TOO_VAGUE, FeedbackCategory.MISSING_INFO),
            comment="Needs more detail",
            timestamp=now,
            context_snapshot=context,
        )

        assert feedback.rating == FeedbackRating.NEGATIVE
        assert len(feedback.categories) == 2
        assert FeedbackCategory.TOO_VAGUE in feedback.categories
        assert FeedbackCategory.MISSING_INFO in feedback.categories

    def test_feedback_immutable(self) -> None:
        """Test that feedback is immutable."""
        now = datetime.now(UTC)
        context = FeedbackContext(
            user_query="Test query",
            agent_response="Test response",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=13,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=1,
            is_repeat_query=False,
        )

        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.POSITIVE,
            categories=None,
            comment="Good",
            timestamp=now,
            context_snapshot=context,
        )

        with pytest.raises((ValidationError, AttributeError)):
            feedback.rating = FeedbackRating.NEGATIVE  # type: ignore

    def test_feedback_without_comment(self) -> None:
        """Test feedback without optional comment."""
        now = datetime.now(UTC)
        context = FeedbackContext(
            user_query="Test query",
            agent_response="Test response",
            conversation_history=(),
            agent_version="1.0.0",
            prompt_version="v1",
            model_used="gpt-4",
            temperature=0.4,
            response_length=13,
            num_tool_calls=0,
            tool_names=(),
            had_next_steps=False,
            response_time_ms=1000.0,
            token_count=100,
            cost_usd=0.001,
            user_session_length=1,
            is_repeat_query=False,
        )

        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=uuid4(),
            message_id=uuid4(),
            user_id="user-123",
            agent_name="query_optimizer",
            rating=FeedbackRating.POSITIVE,
            categories=None,
            comment=None,
            timestamp=now,
            context_snapshot=context,
        )

        assert feedback.comment is None


class TestAgentPerformanceReport:
    """Tests for AgentPerformanceReport dataclass."""

    def test_report_creation(self) -> None:
        """Test creating a performance report."""
        now = datetime.now(UTC)
        report = AgentPerformanceReport(
            agent_name="query_optimizer",
            period_days=7,
            total_feedback=100,
            positive_count=70,
            negative_count=30,
            satisfaction_rate=0.7,
            negative_categories={"too_vague": 15, "missing_info": 10, "inaccurate": 5},
            generated_at=now,
        )

        assert report.agent_name == "query_optimizer"
        assert report.total_feedback == 100
        assert report.satisfaction_rate == 0.7
        assert report.negative_categories["too_vague"] == 15

    def test_report_immutable(self) -> None:
        """Test that report is immutable."""
        now = datetime.now(UTC)
        report = AgentPerformanceReport(
            agent_name="query_optimizer",
            period_days=7,
            total_feedback=100,
            positive_count=70,
            negative_count=30,
            satisfaction_rate=0.7,
            negative_categories={},
            generated_at=now,
        )

        with pytest.raises((ValidationError, AttributeError)):
            report.satisfaction_rate = 0.8  # type: ignore

    def test_report_empty_negative_categories(self) -> None:
        """Test report with no negative feedback categories."""
        now = datetime.now(UTC)
        report = AgentPerformanceReport(
            agent_name="query_optimizer",
            period_days=7,
            total_feedback=50,
            positive_count=50,
            negative_count=0,
            satisfaction_rate=1.0,
            negative_categories={},
            generated_at=now,
        )

        assert report.negative_count == 0
        assert len(report.negative_categories) == 0
        assert report.satisfaction_rate == 1.0

    def test_report_satisfaction_rate_calculation(self) -> None:
        """Test that satisfaction rate is correctly represented."""
        now = datetime.now(UTC)
        report = AgentPerformanceReport(
            agent_name="query_optimizer",
            period_days=7,
            total_feedback=100,
            positive_count=85,
            negative_count=15,
            satisfaction_rate=0.85,
            negative_categories={},
            generated_at=now,
        )

        # Verify satisfaction rate matches positive/total ratio
        expected_rate = report.positive_count / report.total_feedback
        assert report.satisfaction_rate == expected_rate
