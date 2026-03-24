"""Unit tests for conversation patterns repository.

Tests repository methods for storing and retrieving:
- NextStepOptions in messages
- Agent handoffs
- User feedback
- Suggestion interactions

Part of Phase 1: Foundation
"""

from uuid import uuid4

import pytest
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard_server.repositories.conversation_patterns_repository import (
    ConversationPatternsRepository,
)


# Mock database client for testing
class MockDatabaseClient:
    """Mock database client for unit tests."""

    def __init__(self):
        self.handoffs = {}
        self.feedback = {}
        self.suggestions = {}
        self.execute_calls = []
        self.fetch_calls = []

    async def execute(self, query: str, *params):
        """Mock execute."""
        self.execute_calls.append((query, params))
        return "INSERT 0 1"  # Mock response

    async def fetch_one(self, query: str, *params):
        """Mock fetch_one."""
        self.fetch_calls.append((query, params))
        return None

    async def fetch_all(self, query: str, *params):
        """Mock fetch_all."""
        self.fetch_calls.append((query, params))
        return []


@pytest.fixture
def mock_db():
    """Create mock database client."""
    return MockDatabaseClient()


@pytest.fixture
def repository(mock_db):
    """Create repository with mock database."""
    return ConversationPatternsRepository(mock_db)


@pytest.fixture
def sample_next_steps() -> tuple[NextStepOption, ...]:
    """Create sample next step options."""
    return (
        NextStepOption(
            id="opt1",
            number=1,
            title="Optimize query",
            description="Improve performance",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="optimize",
            parameters={"mode": "fast"},
        ),
        NextStepOption(
            id="opt2",
            number=2,
            title="Route to specialist",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="specialist_agent",
            tool_name=None,
            parameters=None,
        ),
    )


class TestAgentHandoffs:
    """Test agent handoff operations."""

    @pytest.mark.asyncio
    async def test_save_handoff(self, repository, mock_db):
        """Test saving an agent handoff."""
        handoff_id = str(uuid4())
        conversation_id = "conv-123"

        await repository.save_handoff(
            handoff_id=handoff_id,
            conversation_id=conversation_id,
            source_agent_id="agent_a",
            target_agent_id="agent_b",
            capability_id="analyze_performance",
            handoff_context={"warehouse_id": "prod"},
            status="initiated",
        )

        # Verify execute was called
        assert len(mock_db.execute_calls) == 1
        query, params = mock_db.execute_calls[0]

        # Verify INSERT query
        assert "INSERT INTO agent_handoffs" in query
        assert params[0] == handoff_id
        assert params[1] == conversation_id
        assert params[2] == "agent_a"
        assert params[3] == "agent_b"

    @pytest.mark.asyncio
    async def test_complete_handoff(self, repository, mock_db):
        """Test marking handoff as complete."""
        handoff_id = str(uuid4())

        await repository.complete_handoff(
            handoff_id=handoff_id,
            success=True,
        )

        # Verify UPDATE was called
        assert len(mock_db.execute_calls) == 1
        query, params = mock_db.execute_calls[0]

        assert "UPDATE agent_handoffs" in query
        assert "status = " in query
        assert params[0] == handoff_id

    @pytest.mark.asyncio
    async def test_complete_handoff_with_error(self, repository, mock_db):
        """Test marking handoff as failed with error message."""
        handoff_id = str(uuid4())
        error_msg = "Agent unavailable"

        await repository.complete_handoff(
            handoff_id=handoff_id,
            success=False,
            error_message=error_msg,
        )

        # Verify error message stored
        query, params = mock_db.execute_calls[0]
        assert "error_message" in query
        assert error_msg in params

    @pytest.mark.asyncio
    async def test_get_conversation_handoffs(self, repository, mock_db):
        """Test retrieving handoffs for a conversation."""
        conversation_id = "conv-123"

        await repository.get_conversation_handoffs(conversation_id)

        # Verify SELECT was called
        assert len(mock_db.fetch_calls) == 1
        query, params = mock_db.fetch_calls[0]

        assert "SELECT" in query
        assert "FROM agent_handoffs" in query
        assert params[0] == conversation_id


class TestUserFeedback:
    """Test user feedback operations."""

    @pytest.mark.asyncio
    async def test_save_feedback(self, repository, mock_db):
        """Test saving user feedback."""
        feedback_id = str(uuid4())
        message_id = str(uuid4())

        context_snapshot = {
            "user_query": "Why is my query slow?",
            "agent_response": "Your query has full table scans",
            "model_used": "gpt-4",
            "token_count": 150,
        }

        await repository.save_feedback(
            feedback_id=feedback_id,
            conversation_id="conv-123",
            message_id=message_id,
            user_id="user-456",
            agent_name="query_optimizer",
            rating="positive",
            categories=None,
            comment="Very helpful!",
            context_snapshot=context_snapshot,
        )

        # Verify INSERT was called
        assert len(mock_db.execute_calls) == 1
        query, params = mock_db.execute_calls[0]

        assert "INSERT INTO user_feedback" in query
        assert params[0] == feedback_id
        assert params[4] == "query_optimizer"
        assert params[5] == "positive"

    @pytest.mark.asyncio
    async def test_save_negative_feedback_with_categories(self, repository, mock_db):
        """Test saving negative feedback with categories."""
        feedback_id = str(uuid4())

        await repository.save_feedback(
            feedback_id=feedback_id,
            conversation_id="conv-123",
            message_id=str(uuid4()),
            user_id="user-456",
            agent_name="test_agent",
            rating="negative",
            categories=["too_vague", "missing_info"],
            comment=None,
            context_snapshot={},
        )

        # Verify categories stored
        query, params = mock_db.execute_calls[0]
        assert ["too_vague", "missing_info"] in params

    @pytest.mark.asyncio
    async def test_get_feedback_by_message(self, repository, mock_db):
        """Test retrieving feedback for a specific message."""
        message_id = str(uuid4())

        await repository.get_feedback_by_message(message_id)

        # Verify SELECT was called
        assert len(mock_db.fetch_calls) == 1
        query, params = mock_db.fetch_calls[0]

        assert "SELECT" in query
        assert "FROM user_feedback" in query
        assert "WHERE message_id" in query
        assert params[0] == message_id

    @pytest.mark.asyncio
    async def test_get_agent_feedback_stats(self, repository, mock_db):
        """Test getting aggregate feedback stats for an agent."""
        agent_name = "query_optimizer"
        days = 7

        await repository.get_agent_feedback_stats(
            agent_name=agent_name,
            days=days,
        )

        # Verify aggregate query was called
        assert len(mock_db.fetch_calls) == 1
        query, params = mock_db.fetch_calls[0]

        assert "COUNT(*)" in query
        assert "GROUP BY" in query or "agent_name" in query
        assert params[0] == agent_name


class TestSuggestionInteractions:
    """Test suggestion interaction operations."""

    @pytest.mark.asyncio
    async def test_record_suggestion_presented(self, repository, mock_db):
        """Test recording suggestion presentation."""
        interaction_id = str(uuid4())

        await repository.record_suggestion_interaction(
            interaction_id=interaction_id,
            suggestion_id="sug-123",
            user_id="user-456",
            conversation_id="conv-789",
            target_agent_id="cost_analyzer",
            action="presented",
        )

        # Verify INSERT was called
        assert len(mock_db.execute_calls) == 1
        query, params = mock_db.execute_calls[0]

        assert "INSERT INTO suggestion_interactions" in query
        assert params[0] == interaction_id
        assert params[1] == "sug-123"
        assert params[5] == "presented"

    @pytest.mark.asyncio
    async def test_record_suggestion_clicked(self, repository, mock_db):
        """Test recording suggestion click."""
        interaction_id = str(uuid4())

        await repository.record_suggestion_interaction(
            interaction_id=interaction_id,
            suggestion_id="sug-123",
            user_id="user-456",
            conversation_id="conv-789",
            target_agent_id="cost_analyzer",
            action="clicked",
        )

        # Verify action stored
        query, params = mock_db.execute_calls[0]
        assert params[5] == "clicked"

    @pytest.mark.asyncio
    async def test_get_suggestion_metrics(self, repository, mock_db):
        """Test getting suggestion metrics for an agent."""
        target_agent_id = "cost_analyzer"
        days = 7

        await repository.get_suggestion_metrics(
            target_agent_id=target_agent_id,
            days=days,
        )

        # Verify aggregate query was called
        assert len(mock_db.fetch_calls) == 1
        query, params = mock_db.fetch_calls[0]

        assert "SELECT" in query
        assert "FROM suggestion_interactions" in query
        assert params[0] == target_agent_id


class TestNextStepsStorage:
    """Test next steps storage in messages."""

    def test_serialize_next_steps_for_storage(self, sample_next_steps):
        """Test serializing next steps for database storage."""
        # Next steps should be stored as JSONB in message metadata
        serialized = [opt.to_dict() for opt in sample_next_steps]

        assert len(serialized) == 2
        assert serialized[0]["id"] == "opt1"
        assert serialized[0]["action_type"] == "tool_call"
        assert serialized[1]["action_type"] == "route"

    def test_deserialize_next_steps_from_storage(self, sample_next_steps):
        """Test deserializing next steps from database."""
        # Simulate retrieving from database
        serialized = [opt.to_dict() for opt in sample_next_steps]

        # Deserialize
        deserialized = tuple(NextStepOption.from_dict(opt) for opt in serialized)

        assert len(deserialized) == 2
        assert deserialized[0].id == "opt1"
        assert deserialized[0].action_type == ActionType.TOOL_CALL
        assert deserialized[1].action_type == ActionType.ROUTE


class TestRepositoryEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_save_handoff_with_null_capability(self, repository, mock_db):
        """Test saving handoff without capability_id."""
        await repository.save_handoff(
            handoff_id=str(uuid4()),
            conversation_id="conv-123",
            source_agent_id="agent_a",
            target_agent_id="agent_b",
            capability_id=None,
            handoff_context={},
            status="initiated",
        )

        # Should not raise error
        assert len(mock_db.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_save_feedback_with_empty_context(self, repository, mock_db):
        """Test saving feedback with minimal context."""
        await repository.save_feedback(
            feedback_id=str(uuid4()),
            conversation_id="conv-123",
            message_id=str(uuid4()),
            user_id="user-456",
            agent_name="test_agent",
            rating="positive",
            categories=None,
            comment=None,
            context_snapshot={},
        )

        # Should not raise error
        assert len(mock_db.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_get_stats_with_no_data(self, repository, mock_db):
        """Test getting stats when no data exists."""
        # Mock empty result
        await repository.get_agent_feedback_stats(
            agent_name="nonexistent_agent",
            days=7,
        )

        # Should not raise error
        assert len(mock_db.fetch_calls) == 1


class TestParameterValidation:
    """Test parameter validation."""

    @pytest.mark.asyncio
    async def test_handoff_status_values(self, repository, mock_db):
        """Test that valid status values are accepted."""
        valid_statuses = ["initiated", "completed", "failed"]

        for status in valid_statuses:
            mock_db.execute_calls.clear()
            await repository.save_handoff(
                handoff_id=str(uuid4()),
                conversation_id="conv-123",
                source_agent_id="agent_a",
                target_agent_id="agent_b",
                capability_id=None,
                handoff_context={},
                status=status,
            )
            assert len(mock_db.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_feedback_rating_values(self, repository, mock_db):
        """Test that valid rating values are accepted."""
        valid_ratings = ["positive", "negative"]

        for rating in valid_ratings:
            mock_db.execute_calls.clear()
            await repository.save_feedback(
                feedback_id=str(uuid4()),
                conversation_id="conv-123",
                message_id=str(uuid4()),
                user_id="user-456",
                agent_name="test_agent",
                rating=rating,
                categories=None,
                comment=None,
                context_snapshot={},
            )
            assert len(mock_db.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_suggestion_action_values(self, repository, mock_db):
        """Test that valid action values are accepted."""
        valid_actions = ["presented", "clicked", "dismissed", "converted"]

        for action in valid_actions:
            mock_db.execute_calls.clear()
            await repository.record_suggestion_interaction(
                interaction_id=str(uuid4()),
                suggestion_id="sug-123",
                user_id="user-456",
                conversation_id="conv-789",
                target_agent_id="test_agent",
                action=action,
            )
            assert len(mock_db.execute_calls) == 1
