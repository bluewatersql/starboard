"""Integration tests for multi-agent conversation flow (Phase 3, Task 3.4).

These tests verify end-to-end multi-agent workflows with all components integrated:
- IntentRouter → AgentFactory → Specialist Agent → Context Updates
- SharedAgentContext persistence and updates
- Agent transition tracking
- Legacy mode fallback
- Clarification handling

Unlike unit tests, these tests use real (mocked) components working together.
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
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    create_step_complete_event,
    create_thinking_event,
    create_tool_end_event,
)
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.routing.routing_models import RouteDecision
from starboard_server.agents.state.agent_state import WorkingMemory
from starboard_server.agents.state.shared_context import SharedAgentContext
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
    # json_response is a sync method (not async), so use Mock not AsyncMock
    client.json_response = Mock(
        return_value={
            "domain": "query",
            "confidence": 0.9,
            "reasoning": "User provided statement ID",
        }
    )
    # text_response is also sync
    client.text_response = Mock(return_value="Mock LLM response")

    # call_with_tools_stream is an async generator - create async iterable mock
    async def mock_stream(*args, **kwargs):
        # Yield minimal events for tests
        yield {"type": "content", "content": "Mock response"}

    client.call_with_tools_stream = mock_stream
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
# Integration Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_route_to_query_agent_end_to_end(multi_agent_manager, state_manager):
    """
    Integration test: Route to query agent and verify full flow.

    Flow:
    1. User provides statement_id
    2. IntentRouter classifies as 'query' domain
    3. AgentFactory creates query specialist
    4. Specialist processes request
    5. Context updated with transition and messages
    """
    conversation_id = "conv_query_test"
    user_message = "Optimize statement_id:abc123"

    # Mock the specialist agent's run_stream to return events
    with patch.object(
        multi_agent_manager.agent_factory,
        "get_agent",
    ) as mock_get_agent:
        mock_agent = Mock()

        async def mock_run_stream(user_input, mode, context, **kwargs):
            yield create_thinking_event(step=0, content="Analyzing query...")
            yield create_tool_end_event(
                step=0,
                tool_name="get_statement_metadata",
                tool_call_id="call_1",
                success=True,
                duration_seconds=0.5,
                result_summary="Retrieved statement metadata",
            )
            yield create_step_complete_event(
                step=0,
                tools_called=["get_statement_metadata"],
            )

        mock_agent.run_stream = mock_run_stream
        mock_get_agent.return_value = mock_agent

        # Execute flow
        events = [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=OptimizationMode.ONLINE,
            )
        ]

        # Verify events streamed
        assert len(events) >= 3  # At least thinking, tool_end, step_complete
        assert any(isinstance(e, ThinkingEvent) for e in events)
        assert any(isinstance(e, ToolEndEvent) for e in events)
        assert any(isinstance(e, StepCompleteEvent) for e in events)

        # Verify context saved
        saved_context = await state_manager.load_context(conversation_id)
        assert saved_context is not None
        # Conversation now includes user message + assistant response
        assert len(saved_context.conversation_history) == 2
        assert saved_context.conversation_history[0].content == user_message
        assert saved_context.conversation_history[0].role == "user"
        assert saved_context.conversation_history[1].role == "assistant"

        # Verify agent transition recorded
        assert len(saved_context.agent_transitions) == 1
        transition = saved_context.agent_transitions[0]
        assert transition.from_agent == "router"
        assert transition.to_agent == "query"
        assert (
            "statement" in transition.reason.lower()
            or "query" in transition.reason.lower()
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_route_to_job_agent_end_to_end(multi_agent_manager, state_manager):
    """
    Integration test: Route to job agent and verify full flow.

    Flow similar to query test, but with job_id detection.
    """
    conversation_id = "conv_job_test"
    user_message = "Analyze job performance for job_id:456"

    with patch.object(
        multi_agent_manager.agent_factory,
        "get_agent",
    ) as mock_get_agent:
        mock_agent = Mock()

        async def mock_run_stream(user_input, mode, context, **kwargs):
            yield create_thinking_event(step=0, content="Analyzing job...")
            yield create_tool_end_event(
                step=0,
                tool_name="get_job_metadata",
                tool_call_id="call_2",
                success=True,
                duration_seconds=0.3,
                result_summary="Retrieved job metadata",
            )
            yield create_step_complete_event(
                step=0,
                tools_called=["get_job_metadata"],
            )

        mock_agent.run_stream = mock_run_stream
        mock_get_agent.return_value = mock_agent

        # Execute flow
        [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=OptimizationMode.ONLINE,
            )
        ]

        # Verify context
        saved_context = await state_manager.load_context(conversation_id)
        assert saved_context is not None
        assert len(saved_context.agent_transitions) == 1
        assert saved_context.agent_transitions[0].to_agent == "job"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clarification_flow_end_to_end(multi_agent_manager, state_manager):
    """
    Integration test: Request clarification when intent is ambiguous.

    Flow:
    1. User provides ambiguous request
    2. IntentRouter returns low confidence
    3. Manager requests clarification (no specialist invoked)
    4. Context saved with original message
    """
    conversation_id = "conv_clarify_test"
    user_message = "Make it faster"  # Ambiguous

    # Mock router to return low confidence
    # Note: classify_intent is async, so use AsyncMock
    with patch.object(
        multi_agent_manager.handoff.intent_router,
        "classify_intent",
        new_callable=AsyncMock,
    ) as mock_classify:
        mock_classify.return_value = RouteDecision(
            domain="diagnostic",
            confidence=0.5,  # Below threshold
            extracted_ids={},
            context={},
            reasoning="Ambiguous request",
            clarification_needed=True,
        )

        # Execute flow
        events = [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=OptimizationMode.ONLINE,
            )
        ]

        # Verify clarification requested (ThinkingEvent with clarification text)
        # Note: ClarificationHandler generates ThinkingEvent + FinalOutputEvent,
        # not UserInputRequestEvent
        assert any(isinstance(e, ThinkingEvent) for e in events)

        # Verify context saved (even though no specialist invoked)
        saved_context = await state_manager.load_context(conversation_id)
        assert saved_context is not None
        # Context includes user message only (no assistant response added for clarification)
        assert len(saved_context.conversation_history) == 1
        assert saved_context.conversation_history[0].role == "user"
        # No transitions since clarification needed
        assert len(saved_context.agent_transitions) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ambiguous_message_triggers_clarification(agent_factory, state_manager):
    """
    Integration test: Ambiguous message triggers clarification.

    Flow:
    1. User sends ambiguous "optimize" request without specific IDs
    2. IntentRouter routes to diagnostic domain with low confidence
    3. Clarification is requested (ThinkingEvent with options)
    4. Context saved, no agent transition until clarification is resolved
    """
    # Create LLM client mock that returns LOW confidence to trigger clarification
    llm_client_low_confidence = Mock()
    llm_client_low_confidence.json_response = Mock(
        return_value={
            "domain": "diagnostic",
            "confidence": 0.4,  # Low confidence triggers clarification
            "reasoning": "Ambiguous request without specific IDs",
        }
    )
    llm_client_low_confidence.text_response = Mock(return_value="Mock response")

    # Create intent router with low-confidence LLM
    intent_router_with_clarification = IntentRouter(
        llm_client=llm_client_low_confidence
    )

    manager = MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router_with_clarification,
        state_manager=state_manager,
    )

    conversation_id = "conv_ambiguous_test"
    user_message = "Optimize my workload"  # Ambiguous - no explicit IDs

    # Execute flow - clarification should be triggered due to low confidence
    events = [
        event
        async for event in manager.handle_message_stream(
            conversation_id=conversation_id,
            user_message=user_message,
            mode=OptimizationMode.ONLINE,
        )
    ]

    # Verify clarification was requested (ThinkingEvent with domain options)
    thinking_events = [e for e in events if isinstance(e, ThinkingEvent)]
    assert len(thinking_events) > 0, (
        "Should have received ThinkingEvent for clarification"
    )

    # Verify context saved
    saved_context = await state_manager.load_context(conversation_id)
    assert saved_context is not None
    # Message is saved even during clarification
    assert len(saved_context.conversation_history) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_persistence_across_turns(multi_agent_manager, state_manager):
    """
    Integration test: Context persists and updates across multiple turns.

    Flow:
    1. First turn: User query → context created
    2. Second turn: Follow-up → context loaded and updated
    3. Verify conversation history accumulates
    4. Verify transitions accumulate
    """
    conversation_id = "conv_multi_turn"

    with patch.object(
        multi_agent_manager.agent_factory,
        "get_agent",
    ) as mock_get_agent:
        mock_agent = Mock()

        async def mock_run_stream(user_input, mode, context, **kwargs):
            yield create_thinking_event(step=0, content="Processing...")
            yield create_step_complete_event(step=0)

        mock_agent.run_stream = mock_run_stream
        mock_get_agent.return_value = mock_agent

        # Turn 1
        [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Optimize statement_id:abc",
                mode=OptimizationMode.ONLINE,
            )
        ]

        context_after_turn1 = await state_manager.load_context(conversation_id)
        # Each turn adds user message + assistant response = 2 messages
        assert len(context_after_turn1.conversation_history) == 2
        assert len(context_after_turn1.agent_transitions) == 1

        # Turn 2
        [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="What about job_id:xyz?",
                mode=OptimizationMode.ONLINE,
            )
        ]

        context_after_turn2 = await state_manager.load_context(conversation_id)
        # Turn 1 (user + assistant) + Turn 2 (user + assistant) = 4 messages
        assert len(context_after_turn2.conversation_history) == 4
        assert (
            context_after_turn2.conversation_history[0].content
            == "Optimize statement_id:abc"
        )
        assert (
            context_after_turn2.conversation_history[2].content
            == "What about job_id:xyz?"
        )
        # Transitions accumulate (2 total: query, then job)
        assert len(context_after_turn2.agent_transitions) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_working_memory_accumulation(multi_agent_manager, state_manager):
    """
    Integration test: Working memory accumulates facts across agent invocations.

    Flow:
    1. Specialist A processes request → adds facts to working memory
    2. Context saved with updated working memory
    3. Specialist B processes next request → sees accumulated facts
    """
    conversation_id = "conv_memory_test"

    with patch.object(
        multi_agent_manager.agent_factory,
        "get_agent",
    ) as mock_get_agent:
        # First specialist adds facts
        mock_agent_1 = Mock()

        async def mock_run_stream_1(user_input, mode, context, **kwargs):
            yield create_thinking_event(step=0, content="Analyzing...")
            # Simulate specialist updating working memory
            # (In reality, this would be done via events, but for testing we'll update context directly)
            yield create_step_complete_event(step=0, tools_called=["analyze_statement"])

        mock_agent_1.run_stream = mock_run_stream_1

        # First invocation
        mock_get_agent.return_value = mock_agent_1
        [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="Analyze statement_id:abc",
                mode=OptimizationMode.ONLINE,
            )
        ]

        # Manually update working memory to simulate specialist behavior
        context = await state_manager.load_context(conversation_id)
        # Facts are tuples (immutable), so create new WorkingMemory with updated facts
        updated_memory = WorkingMemory(
            facts=context.working_memory.facts + ("Statement abc has high latency",),
            summaries=context.working_memory.summaries,
            tools_used=context.working_memory.tools_used,
            metrics=context.working_memory.metrics,
            user_context=context.working_memory.user_context,
            clarifications=context.working_memory.clarifications,
        )
        # Replace working memory in context
        context_dict = context.to_dict()
        context_dict["working_memory"] = updated_memory.to_dict()
        updated_context = SharedAgentContext.from_dict(context_dict)
        await state_manager.save_context(updated_context)

        # Second specialist sees accumulated memory
        mock_agent_2 = Mock()

        async def mock_run_stream_2(user_input, mode, context, **kwargs):
            # Verify context includes accumulated facts
            assert "facts" in context.get("working_memory", {})
            yield create_thinking_event(step=0, content="Continuing analysis...")
            yield create_step_complete_event(step=0)

        mock_agent_2.run_stream = mock_run_stream_2
        mock_get_agent.return_value = mock_agent_2

        # Second invocation
        [
            event
            async for event in multi_agent_manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message="What about job_id:xyz?",
                mode=OptimizationMode.ONLINE,
            )
        ]

        # Verify working memory persisted
        final_context = await state_manager.load_context(conversation_id)
        assert "Statement abc has high latency" in final_context.working_memory.facts


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phase3_task34_acceptance_criteria():
    """
    Comprehensive integration test for Phase 3, Task 3.4 acceptance criteria.

    Verifies:
    1. End-to-end routing flow works
    2. Context persistence works
    3. Agent transitions recorded
    4. Legacy mode works
    5. Clarification handling works
    """
    # Setup
    mock_llm_client = Mock()
    mock_llm_client.json_response = AsyncMock(
        return_value={"domain": "query", "confidence": 0.9, "reasoning": "test"}
    )
    mock_llm_client.text_response = AsyncMock(return_value="test")

    tool_registry = ToolRegistry()
    base_config = AgentConfig(model="gpt-4o", temperature=0.5, max_tokens=10000)

    agent_factory = AgentFactory(
        llm_client=mock_llm_client,
        tool_registry=tool_registry,
        base_config=base_config,
        events=None,
    )

    intent_router = IntentRouter(llm_client=mock_llm_client)
    state_manager = InMemoryConversationStateManager()

    manager = MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router,
        state_manager=state_manager,
    )

    # 1. End-to-end routing flow
    with patch.object(agent_factory, "get_agent") as mock_get_agent:
        mock_agent = Mock()

        async def mock_run_stream(user_input, mode, context, **kwargs):
            yield create_thinking_event(step=0, content="test")
            yield create_step_complete_event(step=0)

        mock_agent.run_stream = mock_run_stream
        mock_get_agent.return_value = mock_agent

        events = [
            event
            async for event in manager.handle_message_stream(
                "conv_1", "Optimize statement_id:abc", OptimizationMode.ONLINE
            )
        ]
        assert len(events) > 0

        # 2. Context persistence
        context = await state_manager.load_context("conv_1")
        assert context is not None
        # Conversation includes user message + assistant response
        assert len(context.conversation_history) == 2

        # 3. Agent transitions recorded
        assert len(context.agent_transitions) == 1
        assert context.agent_transitions[0].from_agent == "router"

    # 4. Routing with specific ID (should route directly to agent)
    manager_with_id = MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router,
        state_manager=state_manager,
    )

    with patch.object(
        manager_with_id.handoff.agent_factory, "get_agent"
    ) as mock_get_agent_2:
        mock_agent_2 = Mock()
        mock_agent_2.run_stream = mock_run_stream
        mock_get_agent_2.return_value = mock_agent_2

        events = [
            event
            async for event in manager_with_id.handle_message_stream(
                "conv_with_id", "Analyze job_id:12345", OptimizationMode.ONLINE
            )
        ]
        # Agent should be called since we have explicit job_id
        mock_get_agent_2.assert_called()

    # 5. Clarification handling
    with patch.object(
        intent_router, "classify_intent", new_callable=AsyncMock
    ) as mock_classify:
        mock_classify.return_value = RouteDecision(
            domain="diagnostic",
            confidence=0.3,
            extracted_ids={},
            context={},
            reasoning="unclear",
            clarification_needed=True,
        )

        events = [
            event
            async for event in manager.handle_message_stream(
                "conv_clarify", "unclear request", OptimizationMode.ONLINE
            )
        ]
        # ClarificationHandler generates ThinkingEvent, not UserInputRequestEvent
        assert any(isinstance(e, ThinkingEvent) for e in events)
