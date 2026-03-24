"""Integration tests for streaming tool positions (Phase 2).

Tests verify that tool positions are calculated during streaming
and sent with ToolStartEvent, not calculated after streaming completes.

See: /changes/ui_20251202/IMPLEMENTATION_PLAN_STREAMING_POSITIONS.md
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.conversation.multi_agent_manager import (
    MultiAgentConversationManager,
)
from starboard_server.agents.events import (
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.routing.routing_models import RouteDecision
from starboard_server.agents.tools import ToolRegistry
from starboard_server.api.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for testing."""
    client = Mock()
    client.json_response = AsyncMock(
        return_value={
            "domain": "query",
            "confidence": 0.9,
            "reasoning": "User provided query to analyze",
        }
    )
    client.text_response = AsyncMock(return_value="Mock LLM response")
    return client


@pytest.fixture
def mock_tool_registry():
    """Create a mock ToolRegistry for testing."""
    return ToolRegistry()


@pytest.fixture
def agent_factory(mock_llm_client, mock_tool_registry):
    """Create AgentFactory with mocked dependencies."""
    base_config = AgentConfig(
        model="gpt-4o",
        temperature=0.5,
        max_tokens=10000,
    )

    factory = AgentFactory(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        base_config=base_config,
        events=None,
    )
    return factory


@pytest.fixture
def intent_router(mock_llm_client):
    """Create IntentRouter with mocked LLM client."""
    return IntentRouter(llm_client=mock_llm_client)


@pytest.fixture
def state_manager():
    """Create InMemoryConversationStateManager for testing."""
    return InMemoryConversationStateManager()


@pytest.fixture
def multi_agent_manager(agent_factory, intent_router, state_manager):
    """Create MultiAgentConversationManager with all dependencies."""
    return MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router,
        state_manager=state_manager,
    )


# =============================================================================
# Integration Tests for Streaming Positions
# =============================================================================


class TestStreamingPositions:
    """Tests for streaming tool positions during message handling."""

    @pytest.mark.asyncio
    async def test_tool_start_event_has_positions(
        self, multi_agent_manager: MultiAgentConversationManager
    ):
        """Test that ToolStartEvent includes tool_positions during streaming."""

        # Create conversation
        response = await multi_agent_manager.create_conversation(
            user_id="test_user",
            context={"workspace_id": "test_workspace"},
        )
        conversation_id = response.conversation_id

        # Create mock events that simulate a real agent stream
        async def mock_agent_events():
            # Simulate thinking
            yield ThinkingEvent(step=1, content="Analyzing ")
            yield ThinkingEvent(step=1, content="the query ")
            yield ThinkingEvent(step=1, content="structure. ")

            # Simulate tool start
            yield ToolStartEvent(
                step=1,
                tool_name="fetch_query",
                friendly_name="Fetching Query Details",
                tool_call_id="call_123",
                arguments={"query_id": "q1"},
            )

            # Simulate tool end
            yield ToolEndEvent(
                step=1,
                tool_name="fetch_query",
                friendly_name="Fetching Query Details",
                tool_call_id="call_123",
                success=True,
                result_summary="Query fetched successfully",
                duration_seconds=0.5,
            )

            yield ThinkingEvent(step=1, content="Analysis complete.")

        # Mock the specialist agent's run_stream method
        mock_specialist = Mock()
        mock_specialist.run_stream = Mock(return_value=mock_agent_events())

        # Mock routing and agent creation
        mock_route_decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test query analysis",
        )

        with (
            patch.object(
                multi_agent_manager.handoff,
                "classify_and_route",
                new_callable=AsyncMock,
                return_value=mock_route_decision,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "should_request_clarification",
                return_value=False,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "get_specialist",
                return_value=mock_specialist,
            ),
        ):
            events = []
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Analyze query q1",
                mode=OptimizationMode.ONLINE,
            ):
                events.append(event)

        # Find ToolStartEvents
        tool_start_events = [e for e in events if isinstance(e, ToolStartEvent)]

        # Should have at least one tool start event
        assert len(tool_start_events) >= 1, "Expected at least one ToolStartEvent"

        # Check that the ToolStartEvent has positions
        tool_event = tool_start_events[0]
        assert tool_event.tool_positions is not None, (
            "ToolStartEvent should have tool_positions"
        )
        assert len(tool_event.tool_positions) > 0, "tool_positions should not be empty"

        # Check position structure
        pos = tool_event.tool_positions[0]
        assert "tool_call_id" in pos
        assert "position" in pos
        assert "display" in pos
        assert isinstance(pos["position"], int)
        assert pos["position"] >= 0
        assert pos["tool_call_id"] == "call_123"

    @pytest.mark.asyncio
    async def test_positions_increase_with_content(
        self, multi_agent_manager: MultiAgentConversationManager
    ):
        """Test that tool positions increase as content grows."""

        response = await multi_agent_manager.create_conversation(
            user_id="test_user",
            context={"workspace_id": "test_workspace"},
        )
        conversation_id = response.conversation_id

        # Create mock events with multiple tools
        async def mock_agent_events():
            # First chunk of thinking
            yield ThinkingEvent(step=1, content="First analysis. ")  # 16 chars

            # First tool
            yield ToolStartEvent(
                step=1,
                tool_name="tool_1",
                friendly_name="Tool 1",
                tool_call_id="call_1",
                arguments={},
            )
            yield ToolEndEvent(
                step=1,
                tool_name="tool_1",
                friendly_name="Tool 1",
                tool_call_id="call_1",
                success=True,
                result_summary="Done",
                duration_seconds=0.1,
            )

            # More thinking
            yield ThinkingEvent(step=1, content="Second analysis. ")  # +17 = 33

            # Second tool
            yield ToolStartEvent(
                step=1,
                tool_name="tool_2",
                friendly_name="Tool 2",
                tool_call_id="call_2",
                arguments={},
            )
            yield ToolEndEvent(
                step=1,
                tool_name="tool_2",
                friendly_name="Tool 2",
                tool_call_id="call_2",
                success=True,
                result_summary="Done",
                duration_seconds=0.1,
            )

        mock_specialist = Mock()
        mock_specialist.run_stream = Mock(return_value=mock_agent_events())

        mock_route_decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        with (
            patch.object(
                multi_agent_manager.handoff,
                "classify_and_route",
                new_callable=AsyncMock,
                return_value=mock_route_decision,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "should_request_clarification",
                return_value=False,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "get_specialist",
                return_value=mock_specialist,
            ),
        ):
            events = []
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Analyze",
                mode=OptimizationMode.ONLINE,
            ):
                events.append(event)

        # Find ToolStartEvents and their positions
        tool_start_events = [e for e in events if isinstance(e, ToolStartEvent)]

        assert len(tool_start_events) >= 2, "Expected at least two ToolStartEvents"

        pos1 = tool_start_events[0].tool_positions[0]["position"]
        pos2 = tool_start_events[1].tool_positions[0]["position"]

        # Second position should be greater (content grew)
        assert pos2 > pos1, (
            f"Position 2 ({pos2}) should be greater than position 1 ({pos1})"
        )

        # First position should be after "First analysis. " (16 chars)
        assert pos1 == 16, f"Position 1 should be 16, got {pos1}"

        # Second position should be after "First analysis. \nSecond analysis. " (34 chars)
        # Note: After each tool starts, "\n" is added for spacing
        # (Reduced from \n\n to \n since InlineToolSummary handles visual spacing)
        assert pos2 == 34, f"Position 2 should be 34, got {pos2}"

    @pytest.mark.asyncio
    async def test_no_markers_in_content(
        self, multi_agent_manager: MultiAgentConversationManager
    ):
        """Test that content does not contain {{TOOL:...}} markers."""

        response = await multi_agent_manager.create_conversation(
            user_id="test_user",
            context={"workspace_id": "test_workspace"},
        )
        conversation_id = response.conversation_id

        async def mock_agent_events():
            yield ThinkingEvent(step=1, content="Analyzing query. ")
            yield ToolStartEvent(
                step=1,
                tool_name="fetch_query",
                friendly_name="Fetching Query",
                tool_call_id="call_123",
                arguments={},
            )
            yield ToolEndEvent(
                step=1,
                tool_name="fetch_query",
                friendly_name="Fetching Query",
                tool_call_id="call_123",
                success=True,
                result_summary="Done",
                duration_seconds=0.1,
            )
            yield ThinkingEvent(step=1, content="Analysis complete.")

        mock_specialist = Mock()
        mock_specialist.run_stream = Mock(return_value=mock_agent_events())

        mock_route_decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        with (
            patch.object(
                multi_agent_manager.handoff,
                "classify_and_route",
                new_callable=AsyncMock,
                return_value=mock_route_decision,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "should_request_clarification",
                return_value=False,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "get_specialist",
                return_value=mock_specialist,
            ),
        ):
            content_parts = []
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Analyze query",
                mode=OptimizationMode.ONLINE,
            ):
                if hasattr(event, "content") and event.content:
                    content_parts.append(event.content)

        # Join all content
        full_content = "".join(content_parts)

        # Should not contain any markers
        assert "{{TOOL:" not in full_content, (
            "Content should not contain {{TOOL:...}} markers"
        )
        assert "}}" not in full_content or "{{" not in full_content, (
            "Content should not contain marker syntax"
        )


class TestToolPositionDataStructure:
    """Tests for the structure of tool position data."""

    @pytest.mark.asyncio
    async def test_position_dict_has_required_fields(
        self, multi_agent_manager: MultiAgentConversationManager
    ):
        """Test position dict contains all required fields."""

        response = await multi_agent_manager.create_conversation(
            user_id="test_user",
        )
        conversation_id = response.conversation_id

        async def mock_agent_events():
            yield ThinkingEvent(step=1, content="Test ")
            yield ToolStartEvent(
                step=1,
                tool_name="test_tool",
                friendly_name="Test Tool",
                tool_call_id="call_abc",
                arguments={"key": "value"},
            )
            yield ToolEndEvent(
                step=1,
                tool_name="test_tool",
                friendly_name="Test Tool",
                tool_call_id="call_abc",
                success=True,
                result_summary="OK",
                duration_seconds=0.1,
            )

        mock_specialist = Mock()
        mock_specialist.run_stream = Mock(return_value=mock_agent_events())

        mock_route_decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        with (
            patch.object(
                multi_agent_manager.handoff,
                "classify_and_route",
                new_callable=AsyncMock,
                return_value=mock_route_decision,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "should_request_clarification",
                return_value=False,
            ),
            patch.object(
                multi_agent_manager.handoff,
                "get_specialist",
                return_value=mock_specialist,
            ),
        ):
            tool_start_event = None
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Test",
                mode=OptimizationMode.ONLINE,
            ):
                if isinstance(event, ToolStartEvent):
                    tool_start_event = event
                    break

        assert tool_start_event is not None
        assert tool_start_event.tool_positions is not None

        pos = tool_start_event.tool_positions[0]

        # Check required fields
        assert "tool_call_id" in pos, "Missing tool_call_id"
        assert "position" in pos, "Missing position"
        assert "display" in pos, "Missing display"

        # Check types
        assert isinstance(pos["tool_call_id"], str)
        assert isinstance(pos["position"], int)
        assert isinstance(pos["display"], str)

        # Check values
        assert pos["tool_call_id"] == "call_abc"
        assert pos["position"] == 5  # After "Test "
        assert pos["display"] == "inline"
